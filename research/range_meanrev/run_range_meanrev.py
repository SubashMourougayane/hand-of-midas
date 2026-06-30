"""Three range/mean-reversion strategies on 20.3yr OANDA data.

Causality strict — ALL features lagged 1 bar.

Strategy 1: D1 ATR Percentile + Fib 0.5 BB-reversal
  Range detected when D1 ATR14 < percentile_p of last 60 D1 bars.
  Then enter fib 0.5 retrace (mean-reversion expectation, smaller TP).

Strategy 2: Bollinger Band Reversal at Fib 0.5
  M5 BB(20, 2.0). When close pierces lower BB AND retraces into fib 0.5 zone
  of H1 impulse → long. Mirror short.

Strategy 3: PDH/PDL Mean-Reversion when no D1 trend
  If D1 close < 3% from D1 EMA200 (no strong trend), trade prior-day-high
  rejection short / prior-day-low rejection long.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import math
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import headline, persist, print_headline, gate, COST_USD
from research.fib_retrace.run_fib import build_h1_features, detect_pivots, in_session
from research.fib_retrace.run_fib_v2 import build_pivot_events
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import resample_d1, add_d1_features, attach_d1_to_m5


# ============================================================
# Strategy 1: D1 ATR-percentile gated Fib 0.5 mean-reversion
# ============================================================


def build_d1_atr_percentile(d1: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Add D1 ATR percentile rank over rolling window. Lagged."""
    df = d1.copy()
    df["atr_pct_rank"] = df["atr14"].shift(1).rolling(window).rank(pct=True)
    return df


def gen_strat1_range_fib(m5, pivot_events, *, direction, atr_pct_max,
                          ext, sl_buf, max_hold_bars, session="all"):
    """Fib retrace with TIGHTER target (ext smaller, e.g. 0.5) when D1 ATR is low (range regime).
    Same V2 spec but fires only when d1_atr_pct_rank_lag < atr_pct_max."""
    side = 1 if direction == "long" else -1
    m5_ts = m5["timestamp"].values
    op = m5["open"].values; hi = m5["high"].values
    lo = m5["low"].values; cl = m5["close"].values
    cl_lag = np.r_[np.nan, cl[:-1]]; op_lag = np.r_[np.nan, op[:-1]]
    ny_hr = m5["ny_hr"].values
    sess_mask = in_session(ny_hr, session)
    atr_pct = m5["atr_pct_rank_d1"].values if "atr_pct_rank_d1" in m5.columns else None
    if atr_pct is None:
        raise SystemExit("ATR percentile column missing")
    range_mask = (atr_pct < atr_pct_max) & np.isfinite(atr_pct)

    if side > 0:
        bull_eng = (cl_lag < op_lag) & (cl > op) & (cl >= op_lag) & (op <= cl_lag)
        rng = hi - lo; lower_wick = np.minimum(op, cl) - lo
        with np.errstate(invalid='ignore'):
            pin = (rng > 0) & (lower_wick > 0.5 * rng)
        confirm_mask = bull_eng | pin
    else:
        bear_eng = (cl_lag > op_lag) & (cl < op) & (cl <= op_lag) & (op >= cl_lag)
        rng = hi - lo; upper_wick = hi - np.maximum(op, cl)
        with np.errstate(invalid='ignore'):
            pin = (rng > 0) & (upper_wick > 0.5 * rng)
        confirm_mask = bear_eng | pin

    sig_rows = []
    last_L = None; last_L_ts = None; last_H = None; last_H_ts = None
    for ev in pivot_events:
        if ev["type"] == "L": last_L = ev["price"]; last_L_ts = ev["confirm_ts"]
        else: last_H = ev["price"]; last_H_ts = ev["confirm_ts"]
        if side > 0:
            if last_L is None or last_H is None or last_H_ts <= last_L_ts: continue
            L = last_L; H = last_H; diff = H - L
            if diff <= 0: continue
            setup_ts = max(last_L_ts, last_H_ts)
            fib_382 = H - 0.382 * diff; fib_786 = H - 0.786 * diff; fib_100 = L
            tp = H + ext * diff; sl = L - sl_buf * diff
        else:
            if last_L is None or last_H is None or last_L_ts <= last_H_ts: continue
            L = last_L; H = last_H; diff = H - L
            if diff <= 0: continue
            setup_ts = max(last_L_ts, last_H_ts)
            fib_382 = L + 0.382 * diff; fib_786 = L + 0.786 * diff; fib_100 = H
            tp = L - ext * diff; sl = H + sl_buf * diff
        s_idx = np.searchsorted(m5_ts, setup_ts, side="right")
        if s_idx >= len(m5_ts): continue
        e_idx = min(len(m5_ts), s_idx + max_hold_bars)
        for k in range(s_idx, e_idx):
            if side > 0:
                if cl[k] < fib_100: break
                if cl[k] <= fib_382 and cl[k] >= fib_786 and sess_mask[k] and range_mask[k] and confirm_mask[k]:
                    en = k + 1
                    if en >= len(m5_ts) - 2: break
                    risk = op[en] - sl
                    if risk <= 0 or risk > 0.02 * op[en]: break
                    sig_rows.append({"entry_index": en, "side": 1, "risk_units": risk,
                                       "stop_price": sl, "tp_price_fixed": tp})
                    break
            else:
                if cl[k] > fib_100: break
                if cl[k] >= fib_382 and cl[k] <= fib_786 and sess_mask[k] and range_mask[k] and confirm_mask[k]:
                    en = k + 1
                    if en >= len(m5_ts) - 2: break
                    risk = sl - op[en]
                    if risk <= 0 or risk > 0.02 * op[en]: break
                    sig_rows.append({"entry_index": en, "side": -1, "risk_units": risk,
                                       "stop_price": sl, "tp_price_fixed": tp})
                    break
    return pd.DataFrame(sig_rows) if sig_rows else pd.DataFrame(
        columns=["entry_index", "side", "risk_units", "stop_price", "tp_price_fixed"])


def simulate_fixed_tp(m5, sigs, *, horizon_bars, cost_usd=COST_USD):
    op = m5["open"].values; cl = m5["close"].values
    ts = m5["timestamp"].values; yr = m5["year"].values
    n = len(m5)
    outs = []
    for sig in sigs.itertuples(index=False):
        i = int(sig.entry_index); side = int(sig.side)
        risk = float(sig.risk_units); stop = float(sig.stop_price); tp = float(sig.tp_price_fixed)
        entry = op[i]; end = min(n - 1, i + horizon_bars)
        outcome_r = 0.0; exit_i = end; broke = False
        max_r = abs(tp - entry) / risk
        for j in range(i, end + 1):
            c = cl[j]
            if side > 0:
                if c <= stop: outcome_r = -1.0; exit_i = j; broke=True; break
                if c >= tp:   outcome_r = (tp - entry) / risk; exit_i = j; broke=True; break
            else:
                if c >= stop: outcome_r = -1.0; exit_i = j; broke=True; break
                if c <= tp:   outcome_r = (entry - tp) / risk; exit_i = j; broke=True; break
        if not broke:
            outcome_r = max(-1.0, min(max_r, side * (cl[exit_i] - entry) / risk))
        outs.append({"entry_ts": ts[i], "side": side, "entry_price": entry,
                     "stop_price": stop, "tp_price": tp, "risk_units": risk,
                     "exit_index": exit_i, "bracket_r": outcome_r,
                     "cost_r": cost_usd / risk,
                     "net_r": outcome_r - cost_usd / risk, "year": yr[i]})
    return pd.DataFrame(outs)


# ============================================================
# Strategy 2: BB(20,2) reversal at fib 0.5
# ============================================================


def add_bollinger(m5, period=20, mult=2.0):
    df = m5.copy()
    df["bb_ma"] = df["close"].rolling(period).mean()
    df["bb_std"] = df["close"].rolling(period).std()
    df["bb_upper_lag"] = (df["bb_ma"] + mult * df["bb_std"]).shift(1)
    df["bb_lower_lag"] = (df["bb_ma"] - mult * df["bb_std"]).shift(1)
    df["bb_ma_lag"] = df["bb_ma"].shift(1)
    return df


def gen_strat2_bb_fib(m5, pivot_events, *, direction, sl_buf,
                       max_hold_bars, session="all"):
    """BB pierce + fib 0.5 retest mean-reversion.
    LONG: M5 low < BB_lower_lag AND price has entered fib 0.5 zone of last bullish impulse.
    SHORT mirror.
    """
    side = 1 if direction == "long" else -1
    m5_ts = m5["timestamp"].values
    op = m5["open"].values; hi = m5["high"].values
    lo = m5["low"].values; cl = m5["close"].values
    cl_lag = np.r_[np.nan, cl[:-1]]; op_lag = np.r_[np.nan, op[:-1]]
    bb_low = m5["bb_lower_lag"].values
    bb_up = m5["bb_upper_lag"].values
    bb_ma = m5["bb_ma_lag"].values
    ny_hr = m5["ny_hr"].values
    sess_mask = in_session(ny_hr, session)

    if side > 0:
        bull_eng = (cl_lag < op_lag) & (cl > op) & (cl >= op_lag) & (op <= cl_lag)
        rng = hi - lo; lower_wick = np.minimum(op, cl) - lo
        with np.errstate(invalid='ignore'):
            pin = (rng > 0) & (lower_wick > 0.5 * rng)
        confirm_mask = bull_eng | pin
        bb_pierce = (lo <= bb_low) & np.isfinite(bb_low)
    else:
        bear_eng = (cl_lag > op_lag) & (cl < op) & (cl <= op_lag) & (op >= cl_lag)
        rng = hi - lo; upper_wick = hi - np.maximum(op, cl)
        with np.errstate(invalid='ignore'):
            pin = (rng > 0) & (upper_wick > 0.5 * rng)
        confirm_mask = bear_eng | pin
        bb_pierce = (hi >= bb_up) & np.isfinite(bb_up)

    sig_rows = []
    last_L = None; last_L_ts = None; last_H = None; last_H_ts = None
    for ev in pivot_events:
        if ev["type"] == "L": last_L = ev["price"]; last_L_ts = ev["confirm_ts"]
        else: last_H = ev["price"]; last_H_ts = ev["confirm_ts"]
        if side > 0:
            if last_L is None or last_H is None or last_H_ts <= last_L_ts: continue
            L = last_L; H = last_H; diff = H - L
            if diff <= 0: continue
            setup_ts = max(last_L_ts, last_H_ts)
            fib_50 = H - 0.5 * diff
            fib_100 = L
            tp = bb_ma  # mean reversion target = bb middle (lagged) at trigger bar
            sl_price = L - sl_buf * diff
        else:
            if last_L is None or last_H is None or last_L_ts <= last_H_ts: continue
            L = last_L; H = last_H; diff = H - L
            if diff <= 0: continue
            setup_ts = max(last_L_ts, last_H_ts)
            fib_50 = L + 0.5 * diff
            fib_100 = H
            sl_price = H + sl_buf * diff
        s_idx = np.searchsorted(m5_ts, setup_ts, side="right")
        if s_idx >= len(m5_ts): continue
        e_idx = min(len(m5_ts), s_idx + max_hold_bars)
        for k in range(s_idx, e_idx):
            if side > 0:
                if cl[k] < fib_100: break
                if bb_pierce[k] and cl[k] <= fib_50 + 0.001 * diff and cl[k] >= fib_50 - 0.5 * diff \
                        and sess_mask[k] and confirm_mask[k] and np.isfinite(bb_ma[k]):
                    en = k + 1
                    if en >= len(m5_ts) - 2: break
                    risk = op[en] - sl_price
                    tp_p = bb_ma[k]  # target = BB middle
                    if risk <= 0 or risk > 0.02 * op[en]: break
                    if tp_p <= op[en]: break  # need positive RR for long
                    sig_rows.append({"entry_index": en, "side": 1, "risk_units": risk,
                                       "stop_price": sl_price, "tp_price_fixed": tp_p})
                    break
            else:
                if cl[k] > fib_100: break
                if bb_pierce[k] and cl[k] >= fib_50 - 0.001 * diff and cl[k] <= fib_50 + 0.5 * diff \
                        and sess_mask[k] and confirm_mask[k] and np.isfinite(bb_ma[k]):
                    en = k + 1
                    if en >= len(m5_ts) - 2: break
                    risk = sl_price - op[en]
                    tp_p = bb_ma[k]
                    if risk <= 0 or risk > 0.02 * op[en]: break
                    if tp_p >= op[en]: break
                    sig_rows.append({"entry_index": en, "side": -1, "risk_units": risk,
                                       "stop_price": sl_price, "tp_price_fixed": tp_p})
                    break
    return pd.DataFrame(sig_rows) if sig_rows else pd.DataFrame(
        columns=["entry_index", "side", "risk_units", "stop_price", "tp_price_fixed"])


# ============================================================
# Strategy 3: PDH/PDL mean-reversion when D1 close near EMA200
# ============================================================


def gen_strat3_pdh_pdl(m5, *, direction, near_pct, sl_atr_mult, tp_R,
                        session="all", max_hold_bars=288):
    """Trade PDH rejection (short) / PDL rejection (long) ONLY when
    |D1 close_lag - D1 ema200_lag| / D1 ema200_lag < near_pct.
    Entry on confirmation reversal candle in NY session."""
    side = 1 if direction == "long" else -1
    m5_ts = m5["timestamp"].values
    op = m5["open"].values; hi = m5["high"].values
    lo = m5["low"].values; cl = m5["close"].values
    cl_lag = np.r_[np.nan, cl[:-1]]; op_lag = np.r_[np.nan, op[:-1]]
    atr_m5 = m5["atr14_m5_lag"].values
    d1_dist = m5["d1_dist_pct_lag_d1"].values
    ny_hr = m5["ny_hr"].values
    sess_mask = in_session(ny_hr, session)

    near_mask = (np.abs(d1_dist) < near_pct) & np.isfinite(d1_dist)

    # Prior-day H/L per NY date
    df = m5.copy()
    df["ny_date"] = df["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    # Per ny_date high/low computed end-of-day, then shifted +1 day mapping
    daily_hl = df.groupby("ny_date").agg(day_high=("high","max"),
                                          day_low=("low","min")).reset_index()
    daily_hl["ny_date_dt"] = pd.to_datetime(daily_hl["ny_date"])
    daily_hl = daily_hl.sort_values("ny_date_dt").reset_index(drop=True)
    daily_hl["pdh"] = daily_hl["day_high"].shift(1)
    daily_hl["pdl"] = daily_hl["day_low"].shift(1)
    df = df.merge(daily_hl[["ny_date","pdh","pdl"]], on="ny_date", how="left")
    pdh = df["pdh"].values
    pdl = df["pdl"].values

    if side > 0:
        bull_eng = (cl_lag < op_lag) & (cl > op) & (cl >= op_lag) & (op <= cl_lag)
        rng = hi - lo; lower_wick = np.minimum(op, cl) - lo
        with np.errstate(invalid='ignore'):
            pin = (rng > 0) & (lower_wick > 0.5 * rng)
        confirm_mask = bull_eng | pin
        # Touch PDL: bar low <= pdl AND close > pdl (rejection from below)
        touch = (lo <= pdl) & (cl > pdl) & np.isfinite(pdl)
    else:
        bear_eng = (cl_lag > op_lag) & (cl < op) & (cl <= op_lag) & (op >= cl_lag)
        rng = hi - lo; upper_wick = hi - np.maximum(op, cl)
        with np.errstate(invalid='ignore'):
            pin = (rng > 0) & (upper_wick > 0.5 * rng)
        confirm_mask = bear_eng | pin
        touch = (hi >= pdh) & (cl < pdh) & np.isfinite(pdh)

    base = sess_mask & near_mask & touch & confirm_mask & np.isfinite(atr_m5)
    sig_rows = []
    last_day = ""
    days = df["ny_date"].values
    sig_idx = np.flatnonzero(base)
    for i in sig_idx:
        if i >= len(m5) - 2: continue
        if days[i] == last_day: continue
        en = i + 1
        atr_now = atr_m5[i]
        if side > 0:
            sl_price = lo[i] - sl_atr_mult * atr_now
            risk = op[en] - sl_price
        else:
            sl_price = hi[i] + sl_atr_mult * atr_now
            risk = sl_price - op[en]
        if not np.isfinite(risk) or risk <= 0: continue
        if risk > 0.02 * op[en]: continue
        tp_price = op[en] + tp_R * risk * side
        last_day = days[i]
        sig_rows.append({"entry_index": int(en), "side": int(side),
                         "risk_units": float(risk), "stop_price": float(sl_price),
                         "tp_price_fixed": float(tp_price)})
    return pd.DataFrame(sig_rows) if sig_rows else pd.DataFrame(
        columns=["entry_index", "side", "risk_units", "stop_price", "tp_price_fixed"])


# ============================================================
# Audit + reports
# ============================================================


def audit_block(label, m5, sigs, horizon_bars):
    print(f"\n=== {label} ===")
    print(f"signals: {len(sigs):,}")
    if len(sigs) == 0: return None
    trades = simulate_fixed_tp(m5, sigs, horizon_bars=horizon_bars)
    if len(trades) == 0: return None
    h = headline(trades); print_headline("BASELINE 20yr", h)
    for d in [1, 5, 10]:
        s = sigs.copy(); s["entry_index"] = s["entry_index"].astype(int) + d
        print_headline(f"+{d} delay", headline(simulate_fixed_tp(m5, s, horizon_bars=horizon_bars)))
    for extra in [0.10, 0.50]:
        print_headline(f"cost+${extra:.2f}",
            headline(simulate_fixed_tp(m5, sigs, horizon_bars=horizon_bars, cost_usd=0.30+extra)))
    cut = int(0.6 * len(m5))
    is_mask = sigs["entry_index"].astype(int) < cut
    print_headline("IS 60%", headline(simulate_fixed_tp(m5, sigs[is_mask], horizon_bars=horizon_bars)))
    print_headline("OOS 40%", headline(simulate_fixed_tp(m5, sigs[~is_mask], horizon_bars=horizon_bars)))
    rng = np.random.default_rng(42)
    if len(trades) > 5:
        nets = np.array([trades["net_r"].sample(n=len(trades), replace=True,
                          random_state=rng.integers(10**9)).sum() for _ in range(2000)])
        print(f"BOOTSTRAP n=2000: P(net<0)={(nets<0).mean()*100:.2f}% p05={np.percentile(nets,5):+.1f}R")
    by_yr = trades.groupby("year")["net_r"].agg(["sum","count"]).round(2)
    by_yr.columns = ["net_R","n"]
    print(by_yr.to_string())
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strat", choices=["1","2","3","all"], default="all")
    args = ap.parse_args()

    print("[load] OANDA H1+M5...")
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"),
                        Path("/tmp/oanda_xau_m5.parquet"))
    h1 = build_h1_features(h1)
    m5_f = add_m5_features(m5)
    d1 = resample_d1(m5_f)
    d1 = add_d1_features(d1)
    d1 = build_d1_atr_percentile(d1, window=60)
    # Merge d1 features incl atr_pct_rank
    d1["atr_pct_rank_lag"] = d1["atr_pct_rank"]
    floor = m5_f["timestamp"].dt.floor("1D")
    ctx = d1.set_index("timestamp")[["close_lag","ema200_lag","ema50_lag","atr14_lag","d1_dist_pct_lag","atr_pct_rank_lag"]]
    ctx_aligned = ctx.reindex(floor).reset_index(drop=True)
    ctx_aligned.columns = [f"{c}_d1" for c in ctx_aligned.columns]
    if "atr_pct_rank_lag_d1" in ctx_aligned.columns:
        m5_f["atr_pct_rank_d1"] = ctx_aligned["atr_pct_rank_lag_d1"].values
    m5_f["close_lag_d1"] = ctx_aligned["close_lag_d1"].values
    m5_f["ema200_lag_d1"] = ctx_aligned["ema200_lag_d1"].values
    m5_f["d1_dist_pct_lag_d1"] = ctx_aligned["d1_dist_pct_lag_d1"].values

    pivot_events = build_pivot_events(h1, 5)
    print(f"  H1 pivots: {len(pivot_events):,}")

    out_dir = Path("/Users/subash/SUBASH/GoldDigger/research/range_meanrev")

    if args.strat in ("1","all"):
        print("\n\n" + "="*80)
        print(">>> STRATEGY 1: D1 ATR low-percentile + Fib 0.5 mean-reversion <<<")
        # Sweep ATR pct max + ext small (mean-rev TP)
        for atr_max in [0.3, 0.5]:
            for ext_small in [0.27, 0.5]:
                for direction in ["long","short"]:
                    label = f"S1_{direction}_atrpct<{atr_max}_ext{ext_small}"
                    sigs = gen_strat1_range_fib(m5_f, pivot_events,
                        direction=direction, atr_pct_max=atr_max,
                        ext=ext_small, sl_buf=0.02, max_hold_bars=288)
                    trades = audit_block(label, m5_f, sigs, horizon_bars=576)
                    if trades is not None and len(trades) > 50:
                        trades.to_parquet(out_dir / f"{label}_trades.parquet")

    if args.strat in ("2","all"):
        print("\n\n" + "="*80)
        print(">>> STRATEGY 2: BB(20,2) pierce + Fib 0.5 mean-reversion <<<")
        m5_bb = add_bollinger(m5_f, period=20, mult=2.0)
        for direction in ["long","short"]:
            label = f"S2_{direction}_BB20_2"
            sigs = gen_strat2_bb_fib(m5_bb, pivot_events,
                direction=direction, sl_buf=0.02, max_hold_bars=288)
            trades = audit_block(label, m5_bb, sigs, horizon_bars=576)
            if trades is not None and len(trades) > 50:
                trades.to_parquet(out_dir / f"{label}_trades.parquet")

    if args.strat in ("3","all"):
        print("\n\n" + "="*80)
        print(">>> STRATEGY 3: PDH/PDL rejection when D1 near EMA200 <<<")
        for near in [0.02, 0.03, 0.05]:
            for sl_atr in [0.5, 1.0]:
                for tp_r in [1.5, 2.0, 3.0]:
                    for direction in ["long","short"]:
                        label = f"S3_{direction}_near{near}_sl{sl_atr}_TP{tp_r}"
                        sigs = gen_strat3_pdh_pdl(m5_f,
                            direction=direction, near_pct=near,
                            sl_atr_mult=sl_atr, tp_R=tp_r,
                            session="ny", max_hold_bars=288)
                        if len(sigs) < 30: continue
                        trades = audit_block(label, m5_f, sigs, horizon_bars=288)
                        if trades is not None and len(trades) > 50:
                            h = headline(trades)
                            if h["pf"] >= 1.2:
                                trades.to_parquet(out_dir / f"{label}_trades.parquet")


if __name__ == "__main__":
    main()
