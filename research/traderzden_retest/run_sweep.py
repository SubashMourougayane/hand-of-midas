"""TraderzDen Retest Model — full causal grid sweep on XAUUSD.

Rule (literal PDF):
  1. HTF trend: close_lag > 20EMA_lag AND 20EMA_lag > 50EMA_lag (long).
     Mirror for short.
  2. LTF pullback to retest zone. Zone candidates:
       - 20EMA (HTF) lag
       - 50EMA (HTF) lag
       - last_swing_low_N (long) / last_swing_high_N (short)
  3. Bar touches zone (low <= zone <= high) within tol*ATR_lag.
  4. Confirmation candle closes:
       - close > prior_close  AND  close > open  (long)  (default)
       - engulfing: close > prior_open AND open < prior_close (long)
       - strong_body: |close-open| > body_min * (high-low) AND close > open
  5. Entry on NEXT M5 OPEN after confirmation candle.
  6. SL = swing low N bars (long) or swing high N bars (short).
  7. TP = tp_mult * R, 1R close-based bracket, 24h horizon.

Causality:
  - All HTF features lagged 1 bar.
  - Swing low/high computed from PRIOR M5 bars only (excluding current).
  - ATR lagged 1.
  - Entry strictly after confirmation candle closes (next bar open).

Grid:
  trend_tf:   H1, H4, D1
  pullback:   ema20, ema50, swing_low
  pullback_tol: 0.3, 0.5, 1.0  (× HTF ATR)
  confirm:    close, engulf, strong_body
  session:    all, london, ny, overlap
  swing_lookback: 10, 20
  tp_mult:    1, 2, 3, 4
  direction:  long, short

Phase-tiered run controlled by --phase flag.
"""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import (  # noqa: E402
    load_data, simulate, headline, persist, print_headline, gate
)


HTF_MAP = {"H1": "1h", "H4": "4h", "D1": "1d"}


def build_htf_features(m1: pd.DataFrame, tf: str) -> pd.DataFrame:
    rule = HTF_MAP[tf]
    htf = m1.set_index("timestamp").resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    htf["ema20"] = htf["close"].ewm(span=20, adjust=False).mean()
    htf["ema50"] = htf["close"].ewm(span=50, adjust=False).mean()
    tr = pd.concat([
        (htf["high"] - htf["low"]),
        (htf["high"] - htf["close"].shift(1)).abs(),
        (htf["low"] - htf["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    htf["atr14"] = tr.rolling(14).mean()
    for c in ["ema20", "ema50", "atr14", "close"]:
        htf[f"{c}_lag"] = htf[c].shift(1)
    htf = htf.dropna(subset=["ema20_lag", "ema50_lag", "atr14_lag"]).reset_index(drop=True)
    return htf


def attach_htf_to_m5(m5: pd.DataFrame, htf: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Merge LAST CLOSED HTF bar's lagged features onto each M5 bar."""
    rule_map = {"H1": "1h", "H4": "4h", "D1": "1d"}
    rule = rule_map[tf]
    floor = m5["timestamp"].dt.floor(rule)
    ctx = htf.set_index("timestamp")[["ema20_lag", "ema50_lag", "atr14_lag", "close_lag"]]
    ctx_aligned = ctx.reindex(floor).reset_index(drop=True)
    suffix = f"_{tf.lower()}"
    ctx_aligned.columns = [c.replace("_lag", f"{suffix}_lag") for c in ctx_aligned.columns]
    out = pd.concat([m5.reset_index(drop=True), ctx_aligned], axis=1)
    return out


def add_swings(m5: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Rolling swing low/high over PRIOR `lookback` M5 bars (excludes current)."""
    df = m5.copy()
    df[f"swing_low_{lookback}_lag"] = df["low"].shift(1).rolling(lookback).min()
    df[f"swing_high_{lookback}_lag"] = df["high"].shift(1).rolling(lookback).max()
    return df


def in_session(ny_hr: np.ndarray, session: str) -> np.ndarray:
    if session == "all":
        return np.ones_like(ny_hr, dtype=bool)
    if session == "london":
        return (ny_hr >= 3) & (ny_hr < 12)  # 08-17 UTC ≈ NY 03-12
    if session == "ny":
        return (ny_hr >= 8) & (ny_hr < 17)  # NY 08-17 ET
    if session == "overlap":
        return (ny_hr >= 8) & (ny_hr < 12)  # NY 08-12 ET = 13-17 UTC
    raise ValueError(session)


def gen_signals(
    df: pd.DataFrame,
    *,
    direction: str,
    trend_tf: str,
    pullback: str,
    pullback_tol: float,
    confirm: str,
    session: str,
    swing_lookback: int,
) -> pd.DataFrame:
    side = 1 if direction == "long" else -1
    suf = f"_{trend_tf.lower()}"
    ema20 = df[f"ema20{suf}_lag"].values
    ema50 = df[f"ema50{suf}_lag"].values
    atr_h = df[f"atr14{suf}_lag"].values
    cl_h = df[f"close{suf}_lag"].values

    op = df["open"].values
    hi = df["high"].values
    lo = df["low"].values
    cl = df["close"].values
    sw_lo = df[f"swing_low_{swing_lookback}_lag"].values
    sw_hi = df[f"swing_high_{swing_lookback}_lag"].values

    n = len(df)
    ts = df["timestamp"].values
    ny_hr = df["ny_hr"].values
    sess_mask = in_session(ny_hr, session)

    # Trend filter on PRIOR closed HTF bar
    if side > 0:
        trend = (cl_h > ema20) & (ema20 > ema50)
    else:
        trend = (cl_h < ema20) & (ema20 < ema50)

    # Pullback zone target
    if pullback == "ema20":
        zone = ema20
    elif pullback == "ema50":
        zone = ema50
    elif pullback == "swing_low" and side > 0:
        zone = sw_lo
    elif pullback == "swing_high" and side < 0:
        zone = sw_hi
    elif pullback == "swing_low":
        zone = sw_lo  # only valid for long
    elif pullback == "swing_high":
        zone = sw_hi
    else:
        raise ValueError(pullback)

    # Bar touches zone within tol * atr_h
    tol = pullback_tol * atr_h
    if side > 0:
        touch = (lo <= zone + tol) & (lo >= zone - tol) | ((lo <= zone) & (hi >= zone))
    else:
        touch = (hi >= zone - tol) & (hi <= zone + tol) | ((hi >= zone) & (lo <= zone))

    # Confirmation candle on bar t (after touch on bar t-1 to t)
    op_lag = np.r_[np.nan, op[:-1]]
    cl_lag = np.r_[np.nan, cl[:-1]]
    body = cl - op
    rng = (hi - lo).clip(min=1e-9)

    if confirm == "close":
        if side > 0:
            conf_bar = (cl > op) & (cl > cl_lag)
        else:
            conf_bar = (cl < op) & (cl < cl_lag)
    elif confirm == "engulf":
        if side > 0:
            conf_bar = (cl > op) & (cl > op_lag) & (op < cl_lag)
        else:
            conf_bar = (cl < op) & (cl < op_lag) & (op > cl_lag)
    elif confirm == "strong_body":
        if side > 0:
            conf_bar = (cl > op) & (body / rng > 0.6)
        else:
            conf_bar = (cl < op) & (-body / rng > 0.6)
    else:
        raise ValueError(confirm)

    # Touch must have happened on this bar or the previous bar
    touch_recent = touch | np.r_[False, touch[:-1]]

    base = trend & touch_recent & conf_bar & sess_mask
    base &= np.isfinite(zone) & np.isfinite(atr_h)

    sig_idx = np.flatnonzero(base)
    if len(sig_idx) == 0:
        return pd.DataFrame(columns=["entry_index", "side", "risk_units"])
    rows = []
    last_day = ""
    days = df["ny_date"].values
    for i in sig_idx:
        if i >= n - 2:
            continue
        # one trade per day per direction
        if days[i] == last_day:
            continue
        last_day = days[i]
        entry_idx = i + 1
        entry_price = op[entry_idx]
        if side > 0:
            stop = sw_lo[i] if pullback != "swing_low" else min(sw_lo[i], zone[i])
            stop = sw_lo[i]
            risk = entry_price - stop
        else:
            stop = sw_hi[i]
            risk = stop - entry_price
        if not np.isfinite(risk) or risk <= 0:
            continue
        # Sanity cap risk at 1% of price to avoid pathological stops
        if risk > 0.01 * entry_price:
            continue
        rows.append({"entry_index": int(entry_idx), "side": int(side),
                     "risk_units": float(risk)})
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["entry_index", "side", "risk_units"])


def prep_full_frame(m1: pd.DataFrame, m5: pd.DataFrame, trend_tfs: list[str],
                    swing_lookbacks: list[int]) -> pd.DataFrame:
    df = m5.copy()
    for tf in trend_tfs:
        htf = build_htf_features(m1, tf)
        df = attach_htf_to_m5(df, htf, tf)
    for lb in swing_lookbacks:
        df = add_swings(df, lb)
    return df


def run_grid(df: pd.DataFrame, grid_combos: list[dict], *, persist_family: str):
    leaderboard_rows = []
    for combo in grid_combos:
        tp_mults = combo.pop("tp_mults", [1.0, 2.0, 3.0, 4.0])
        try:
            sigs = gen_signals(df, **combo)
        except Exception as exc:
            print(f"  ERR {combo}: {exc}")
            continue
        if len(sigs) == 0:
            continue
        for tp in tp_mults:
            trades = simulate(sigs, df, tp_mult=tp)
            if len(trades) == 0:
                continue
            h = headline(trades)
            label = (
                f"{combo['direction']}_trend{combo['trend_tf']}_pb{combo['pullback']}"
                f"_tol{combo['pullback_tol']}_conf{combo['confirm']}"
                f"_sess{combo['session']}_sw{combo['swing_lookback']}_TP{tp}R"
            )
            g = gate(h)
            row = {
                **{k: v for k, v in combo.items() if k != "tp_mults"},
                "tp": tp, **h, **{f"gate_{k}": v for k, v in g.items()},
                "label": label,
            }
            leaderboard_rows.append(row)
            if g.get("ALL_PASS") or h["pf"] >= 1.3:
                print_headline(label, h)
                persist(persist_family, label, trades, notes="TraderzDen retest sweep")
    return pd.DataFrame(leaderboard_rows)


def phase1(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 1: H4 trend, 20EMA pullback, close-confirm, sweep session x direction."""
    print("\n=== Phase 1: H4 trend, 20EMA pb, close-confirm ===\n")
    combos = []
    for direction in ["long", "short"]:
        for session in ["all", "london", "ny", "overlap"]:
            combos.append({
                "direction": direction,
                "trend_tf": "H4",
                "pullback": "ema20",
                "pullback_tol": 0.5,
                "confirm": "close",
                "session": session,
                "swing_lookback": 20,
                "tp_mults": [1.0, 2.0, 3.0, 4.0],
            })
    return run_grid(df, combos, persist_family="traderzden_retest")


def phase2(df: pd.DataFrame, top_session: str, top_direction: str) -> pd.DataFrame:
    """Phase 2: lock best session+direction; sweep pullback target, tol, confirm, trend_tf, swing_lookback."""
    print(f"\n=== Phase 2: lock session={top_session} direction={top_direction}; full grid ===\n")
    combos = []
    for trend_tf in ["H1", "H4", "D1"]:
        for pullback in (["ema20", "ema50", "swing_low"] if top_direction == "long"
                         else ["ema20", "ema50", "swing_high"]):
            for tol in [0.3, 0.5, 1.0]:
                for confirm in ["close", "engulf", "strong_body"]:
                    for sw in [10, 20]:
                        combos.append({
                            "direction": top_direction,
                            "trend_tf": trend_tf,
                            "pullback": pullback,
                            "pullback_tol": tol,
                            "confirm": confirm,
                            "session": top_session,
                            "swing_lookback": sw,
                            "tp_mults": [1.0, 2.0, 3.0, 4.0],
                        })
    return run_grid(df, combos, persist_family="traderzden_retest")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["1", "2", "both"], default="both")
    args = ap.parse_args()

    print("[load] m1+m5 cached frames...")
    m1, m5, _ = load_data()
    print(f"  m5 rows: {len(m5):,}")

    print("[features] HTF context + swings...")
    df = prep_full_frame(m1, m5, trend_tfs=["H1", "H4", "D1"], swing_lookbacks=[10, 20])
    print(f"  feature rows: {len(df):,}")

    lb_p1 = pd.DataFrame()
    lb_p2 = pd.DataFrame()
    if args.phase in ("1", "both"):
        lb_p1 = phase1(df)
        if len(lb_p1):
            top = lb_p1.sort_values("mar", ascending=False).head(20)
            print("\n[Phase 1 — TOP 20 by MAR]\n")
            cols = ["direction", "trend_tf", "session", "tp", "n", "pf", "mar", "pos_years"]
            print(top[cols].to_string(index=False))
            best = lb_p1.sort_values("mar", ascending=False).iloc[0]
            top_session = best["session"]
            top_direction = best["direction"]
        else:
            print("Phase 1 returned no rows")
            top_session = "overlap"
            top_direction = "long"
    else:
        top_session = "overlap"
        top_direction = "long"

    if args.phase in ("2", "both"):
        lb_p2 = phase2(df, top_session, top_direction)
        if len(lb_p2):
            top = lb_p2.sort_values("mar", ascending=False).head(20)
            print("\n[Phase 2 — TOP 20 by MAR]\n")
            cols = ["direction", "trend_tf", "pullback", "pullback_tol", "confirm",
                    "session", "swing_lookback", "tp", "n", "pf", "mar", "pos_years"]
            print(top[cols].to_string(index=False))

    full = pd.concat([lb_p1, lb_p2], ignore_index=True) if len(lb_p1) or len(lb_p2) else pd.DataFrame()
    if len(full):
        out_path = Path("/Users/subash/SUBASH/GoldDigger/research/traderzden_retest/sweep_leaderboard.csv")
        full.to_csv(out_path, index=False)
        print(f"\nSaved sweep leaderboard → {out_path}")


if __name__ == "__main__":
    main()
