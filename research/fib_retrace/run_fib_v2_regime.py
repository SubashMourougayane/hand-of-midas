"""Fib V2 regime-aware variants on OANDA 20.3yr data.

Phase A: long-only V2 + D1 trend filter (close_lag > ema200_lag → bull regime ON).
Phase B: short variant (mirror) + D1 bear filter.
Phase C: sideways variant (range-bound: D1 |close - ema200| / atr < threshold).
Phase D: regime ensemble — fires whichever sub-strategy matches current regime.

Causality strict:
- D1 features ALL lagged (close, ema, atr from PRIOR closed daily bar).
- D1 bar floor mapping onto M5 timestamps uses PRIOR day's close, not today.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import (
    headline, persist, print_headline, gate, COST_USD
)
from research.fib_retrace.run_fib import build_h1_features, in_session
from research.fib_retrace.run_fib_v2 import (
    build_pivot_events, simulate_fixed_tp,
)
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features


def resample_d1(m5: pd.DataFrame) -> pd.DataFrame:
    """Daily OHLC from M5 with UTC date as session bin."""
    df = m5.set_index("timestamp").resample("1D", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna().reset_index()
    return df


def add_d1_features(d1: pd.DataFrame, ema_period: int = 200, atr_period: int = 14) -> pd.DataFrame:
    df = d1.copy()
    df["ema200"] = df["close"].ewm(span=ema_period, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(atr_period).mean()
    for c in ["ema200", "ema50", "atr14", "close"]:
        df[f"{c}_lag"] = df[c].shift(1)
    df["d1_dist_pct_lag"] = (df["close_lag"] - df["ema200_lag"]) / df["ema200_lag"]
    return df


def attach_d1_to_m5(m5: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    """Merge prior-D1 features onto each M5 bar via D1 floor."""
    floor = m5["timestamp"].dt.floor("1D")
    ctx = d1.set_index("timestamp")[["close_lag", "ema200_lag", "ema50_lag",
                                       "atr14_lag", "d1_dist_pct_lag"]]
    ctx_aligned = ctx.reindex(floor).reset_index(drop=True)
    ctx_aligned.columns = [f"{c}_d1" for c in ctx_aligned.columns]
    out = pd.concat([m5.reset_index(drop=True), ctx_aligned], axis=1)
    return out


def gen_signals_with_regime(
    m5: pd.DataFrame, pivot_events: list[dict], *,
    direction: str, session: str, max_hold_bars: int,
    ext_target_pct: float, sl_buffer_pct: float,
    regime: str = "any",  # any | bull | bear | sideways
    sideways_band_pct: float = 0.03,  # |close - ema200| / ema200 < 3%
):
    """Same as gen_signals_v2 but with D1 regime gate at each candidate confirmation bar."""
    side = 1 if direction == "long" else -1
    m5_ts = m5["timestamp"].values
    op = m5["open"].values; hi = m5["high"].values
    lo = m5["low"].values; cl = m5["close"].values
    cl_lag = np.r_[np.nan, cl[:-1]]
    op_lag = np.r_[np.nan, op[:-1]]
    ny_hr = m5["ny_hr"].values
    sess_mask = in_session(ny_hr, session)
    d1_close_lag = m5["close_lag_d1"].values
    d1_ema200_lag = m5["ema200_lag_d1"].values
    d1_dist_pct = m5["d1_dist_pct_lag_d1"].values

    d1_ema50_lag = m5["ema50_lag_d1"].values
    if regime == "bull":
        regime_mask = (d1_close_lag > d1_ema200_lag)
    elif regime == "bull_strong":
        regime_mask = (d1_close_lag > d1_ema200_lag) & (d1_ema50_lag > d1_ema200_lag)
    elif regime == "bear":
        regime_mask = (d1_close_lag < d1_ema200_lag)
    elif regime == "bear_strong":
        regime_mask = (d1_close_lag < d1_ema200_lag) & (d1_ema50_lag < d1_ema200_lag)
    elif regime == "sideways":
        regime_mask = np.abs(d1_dist_pct) < sideways_band_pct
    else:
        regime_mask = np.ones(len(m5), dtype=bool)
    regime_mask = regime_mask & np.isfinite(d1_close_lag) & np.isfinite(d1_ema200_lag)

    if side > 0:
        bull_eng = (cl_lag < op_lag) & (cl > op) & (cl >= op_lag) & (op <= cl_lag)
        rng = hi - lo
        lower_wick = np.minimum(op, cl) - lo
        with np.errstate(invalid='ignore'):
            pin = (rng > 0) & (lower_wick > 0.5 * rng)
        confirm_mask = bull_eng | pin
    else:
        bear_eng = (cl_lag > op_lag) & (cl < op) & (cl <= op_lag) & (op >= cl_lag)
        rng = hi - lo
        upper_wick = hi - np.maximum(op, cl)
        with np.errstate(invalid='ignore'):
            pin = (rng > 0) & (upper_wick > 0.5 * rng)
        confirm_mask = bear_eng | pin

    sig_rows = []
    last_L = None; last_L_ts = None; last_H = None; last_H_ts = None

    for ev in pivot_events:
        if ev["type"] == "L":
            last_L = ev["price"]; last_L_ts = ev["confirm_ts"]
        else:
            last_H = ev["price"]; last_H_ts = ev["confirm_ts"]
        if side > 0:
            if last_L is None or last_H is None: continue
            if last_H_ts <= last_L_ts: continue
            L = last_L; H = last_H
            diff = H - L
            if diff <= 0: continue
            setup_confirm_ts = max(last_L_ts, last_H_ts)
            fib_382 = H - 0.382 * diff
            fib_786 = H - 0.786 * diff
            fib_100 = L
            tp_price = H + ext_target_pct * diff
            sl_price = L - sl_buffer_pct * diff
        else:
            if last_L is None or last_H is None: continue
            if last_L_ts <= last_H_ts: continue
            L = last_L; H = last_H
            diff = H - L
            if diff <= 0: continue
            setup_confirm_ts = max(last_L_ts, last_H_ts)
            fib_382 = L + 0.382 * diff
            fib_786 = L + 0.786 * diff
            fib_100 = H
            tp_price = L - ext_target_pct * diff
            sl_price = H + sl_buffer_pct * diff

        start_idx = np.searchsorted(m5_ts, setup_confirm_ts, side="right")
        if start_idx >= len(m5_ts): continue
        end_idx = min(len(m5_ts), start_idx + max_hold_bars)
        for k in range(start_idx, end_idx):
            if side > 0:
                if cl[k] < fib_100: break
                if cl[k] <= fib_382 and cl[k] >= fib_786 and sess_mask[k] and regime_mask[k]:
                    if confirm_mask[k]:
                        entry_idx = k + 1
                        if entry_idx >= len(m5_ts) - 2: break
                        entry_price = op[entry_idx]
                        risk = entry_price - sl_price
                        if risk <= 0 or not np.isfinite(risk): break
                        if risk > 0.02 * entry_price: break
                        sig_rows.append({"entry_index": int(entry_idx), "side": 1,
                                          "risk_units": float(risk),
                                          "stop_price": float(sl_price),
                                          "tp_price_fixed": float(tp_price)})
                        break
            else:
                if cl[k] > fib_100: break
                if cl[k] >= fib_382 and cl[k] <= fib_786 and sess_mask[k] and regime_mask[k]:
                    if confirm_mask[k]:
                        entry_idx = k + 1
                        if entry_idx >= len(m5_ts) - 2: break
                        entry_price = op[entry_idx]
                        risk = sl_price - entry_price
                        if risk <= 0 or not np.isfinite(risk): break
                        if risk > 0.02 * entry_price: break
                        sig_rows.append({"entry_index": int(entry_idx), "side": -1,
                                          "risk_units": float(risk),
                                          "stop_price": float(sl_price),
                                          "tp_price_fixed": float(tp_price)})
                        break
    return pd.DataFrame(sig_rows) if sig_rows else pd.DataFrame(
        columns=["entry_index", "side", "risk_units", "stop_price", "tp_price_fixed"])


def regime_breakdown(trades: pd.DataFrame, label: str):
    regimes = [
        ("2007-2008", 2007, 2008),
        ("2009-2010", 2009, 2010),
        ("2011", 2011, 2011),
        ("2012-2015 (bear)", 2012, 2015),
        ("2016-2018 (base)", 2016, 2018),
        ("2019-2020", 2019, 2020),
        ("2021-2023", 2021, 2023),
        ("2024-2026", 2024, 2026),
    ]
    print(f"\n[Regime breakdown — {label}]")
    for name, y0, y1 in regimes:
        slc = trades[(trades.year >= y0) & (trades.year <= y1)]
        if len(slc):
            h = headline(slc)
            print(f"  {name:25s} n={len(slc):>5d} net={h['net']:+8.1f}R "
                  f"PF={h['pf']:>4.2f} pos={h['pos_years']}")


def run_variant(m5, pivot_events, *, label, direction, regime, ext, sl_buf,
                 max_hold_h, session="all", sideways_band_pct=0.03,
                 audit: bool = True):
    max_hold_bars = max_hold_h * 12
    print(f"\n=== {label}: dir={direction} regime={regime} ext={ext} ===")
    sigs = gen_signals_with_regime(m5, pivot_events,
                                    direction=direction, session=session,
                                    max_hold_bars=max_hold_bars,
                                    ext_target_pct=ext, sl_buffer_pct=sl_buf,
                                    regime=regime, sideways_band_pct=sideways_band_pct)
    print(f"  signals: {len(sigs):,}")
    if len(sigs) == 0:
        return None
    trades = simulate_fixed_tp(m5, sigs, horizon_bars=max_hold_bars * 2)
    h = headline(trades)
    print_headline("BASELINE 20yr", h)
    if audit:
        for d in [1, 5, 10]:
            s = sigs.copy(); s["entry_index"] = s["entry_index"].astype(int) + d
            print_headline(f"+{d} delay", headline(simulate_fixed_tp(m5, s, horizon_bars=max_hold_bars * 2)))
        for extra in [0.10, 0.50]:
            print_headline(f"cost+${extra:.2f}",
                headline(simulate_fixed_tp(m5, sigs, horizon_bars=max_hold_bars * 2,
                                            cost_usd=0.30 + extra)))
        cutoff = int(0.6 * len(m5))
        is_mask = sigs["entry_index"].astype(int) < cutoff
        print_headline("IS 60%", headline(simulate_fixed_tp(m5, sigs[is_mask], horizon_bars=max_hold_bars * 2)))
        print_headline("OOS 40%", headline(simulate_fixed_tp(m5, sigs[~is_mask], horizon_bars=max_hold_bars * 2)))
        rng = np.random.default_rng(42)
        nets = np.array([trades["net_r"].sample(n=len(trades), replace=True,
                          random_state=rng.integers(10**9)).sum() for _ in range(2000)])
        print(f"  BOOTSTRAP n=2000: P(net<0)={(nets<0).mean()*100:.2f}% p05={np.percentile(nets,5):+.1f}R")
    regime_breakdown(trades, label)
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["A", "B", "ensemble"], default="A")
    args = ap.parse_args()

    print("[load] OANDA H1+M5...")
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"),
                        Path("/tmp/oanda_xau_m5.parquet"))
    h1 = build_h1_features(h1)
    m5_f = add_m5_features(m5)
    d1 = resample_d1(m5_f)
    d1 = add_d1_features(d1)
    m5_f = attach_d1_to_m5(m5_f, d1)
    pivot_events = build_pivot_events(h1, 5)
    print(f"  H1 pivots: {len(pivot_events):,}")

    out_dir = Path("/Users/subash/SUBASH/GoldDigger/research/fib_retrace")

    if args.phase == "A":
        print("\n" + "="*80)
        print(">>> PHASE A: D1 bull filter on long V2 winner <<<\n")
        # Baseline (no regime filter) — already shown previously
        t_any = run_variant(m5_f, pivot_events,
            label="long_ANY_regime (baseline 20yr)", direction="long",
            regime="any", ext=1.618, sl_buf=0.02, max_hold_h=72)
        if t_any is not None:
            t_any.to_parquet(out_dir / "fib_v2_oanda_long_any_trades.parquet")

        # Bull-only filter
        t_bull = run_variant(m5_f, pivot_events,
            label="long_BULL_only (D1 close>EMA200)", direction="long",
            regime="bull", ext=1.618, sl_buf=0.02, max_hold_h=72)
        if t_bull is not None:
            t_bull.to_parquet(out_dir / "fib_v2_oanda_long_bull_trades.parquet")

    elif args.phase == "B":
        print("\n" + "="*80)
        print(">>> PHASE B: short variant + sideways variant <<<\n")
        # Short with bear filter
        t_short = run_variant(m5_f, pivot_events,
            label="short_BEAR_only (D1 close<EMA200)", direction="short",
            regime="bear", ext=1.618, sl_buf=0.02, max_hold_h=72)
        if t_short is not None:
            t_short.to_parquet(out_dir / "fib_v2_oanda_short_bear_trades.parquet")

        # Short any-regime (sanity)
        run_variant(m5_f, pivot_events,
            label="short_ANY", direction="short",
            regime="any", ext=1.618, sl_buf=0.02, max_hold_h=72, audit=False)

        # Sideways (range) variant — try both long and short with smaller TP
        run_variant(m5_f, pivot_events,
            label="long_SIDEWAYS (|dist|<3%, TP=0.5diff)", direction="long",
            regime="sideways", ext=0.5, sl_buf=0.02, max_hold_h=24, audit=False)
        run_variant(m5_f, pivot_events,
            label="short_SIDEWAYS (|dist|<3%, TP=0.5diff)", direction="short",
            regime="sideways", ext=0.5, sl_buf=0.02, max_hold_h=24, audit=False)

    elif args.phase == "ensemble":
        print("\n" + "="*80)
        print(">>> ENSEMBLE: STRONG-bull long + STRONG-bear short <<<\n")
        t_bull = run_variant(m5_f, pivot_events,
            label="long_BULL_STRONG", direction="long", regime="bull_strong",
            ext=1.618, sl_buf=0.02, max_hold_h=72, audit=True)
        t_short = run_variant(m5_f, pivot_events,
            label="short_BEAR_STRONG", direction="short", regime="bear_strong",
            ext=1.618, sl_buf=0.02, max_hold_h=72, audit=True)
        if t_bull is None or t_short is None:
            return
        merged = pd.concat([t_bull, t_short], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)
        print(f"\n[ensemble] combined trades: {len(merged):,}")
        h = headline(merged)
        print_headline("ENSEMBLE 20yr", h)
        regime_breakdown(merged, "ENSEMBLE")
        merged.to_parquet(out_dir / "fib_v2_oanda_ensemble_trades.parquet")
        print(f"\nsaved → {out_dir}/fib_v2_oanda_ensemble_trades.parquet")
        # Save individual
        t_bull.to_parquet(out_dir / "fib_v2_oanda_long_bull_strong_trades.parquet")
        t_short.to_parquet(out_dir / "fib_v2_oanda_short_bear_strong_trades.parquet")


if __name__ == "__main__":
    main()
