"""H4 FVG → M15 FVG nested retrace strategy (TraderzDen reel quantised).

Rules:
1. Detect H4 FVG (3-bar array). Available from H4_bar(t+1).close_ts onward.
2. Wait for price to retrace into H4 FVG range.
3. Inside H4 retrace window, detect M15 FVG matching H4 direction.
4. Place limit order at M15 FVG (upper for long, lower for short).
5. Limit fill check on M5 grid: long fills if M5.low <= M15_FVG_upper.
6. SL = M15 swing low/high last N bars (prior).
7. TP = 3R close-based bracket.

Causality strict:
- H4 FVG (bars i-1, i, i+1) confirmed at i+1 close. Available from i+2.
- M15 FVG same.
- Retrace check: M5 bar high/low touches H4 FVG range AFTER FVG confirmed.
- Limit fill: M5 bar OPEN >= FVG upper THEN M5 bar LOW <= FVG upper → fill at FVG upper.
  If M5 OPEN < FVG upper (gapped through) → fill at M5 OPEN (worse for long).
- SL/TP causal: SL from prior 20 M5 swing lows.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import (  # noqa
    load_data, headline, persist, print_headline, gate, COST_USD
)


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = m1.set_index("timestamp").resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    return out


def detect_fvgs(htf: pd.DataFrame, side: int) -> pd.DataFrame:
    """Return DataFrame[fvg_start_ts, fvg_end_ts (confirm), upper, lower, side].
    side=+1 bullish; side=-1 bearish.
    Confirm bar = bar at index i+1 (where i+1.low > i-1.high for bullish).
    """
    n = len(htf)
    out = []
    h = htf["high"].values
    l = htf["low"].values
    ts = htf["timestamp"].values
    # Index t in [1, n-2]; FVG defined by bars (t-1, t, t+1)
    for t in range(1, n - 1):
        if side > 0 and l[t + 1] > h[t - 1]:
            out.append({
                "created_ts": ts[t - 1],         # original t-1 bar
                "confirm_ts": ts[t + 1],          # confirmed at t+1
                "upper": float(l[t + 1]),
                "lower": float(h[t - 1]),
                "side": 1,
            })
        elif side < 0 and h[t + 1] < l[t - 1]:
            out.append({
                "created_ts": ts[t - 1],
                "confirm_ts": ts[t + 1],
                "upper": float(l[t - 1]),
                "lower": float(h[t + 1]),
                "side": -1,
            })
    return pd.DataFrame(out)


def detect_all_fvgs(htf: pd.DataFrame) -> pd.DataFrame:
    bull = detect_fvgs(htf, +1)
    bear = detect_fvgs(htf, -1)
    return pd.concat([bull, bear], ignore_index=True).sort_values("confirm_ts").reset_index(drop=True)


def add_swings(m5: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    df = m5.copy()
    df[f"swing_low_{lookback}_lag"] = df["low"].shift(1).rolling(lookback).min()
    df[f"swing_high_{lookback}_lag"] = df["high"].shift(1).rolling(lookback).max()
    return df


def in_session(ny_hr: np.ndarray, session: str) -> np.ndarray:
    if session == "all": return np.ones_like(ny_hr, dtype=bool)
    if session == "london": return (ny_hr >= 3) & (ny_hr < 12)
    if session == "ny": return (ny_hr >= 8) & (ny_hr < 17)
    if session == "overlap": return (ny_hr >= 8) & (ny_hr < 12)
    raise ValueError(session)


def simulate_with_limit_fills(
    m5: pd.DataFrame, sigs: pd.DataFrame, *, tp_mult: float, horizon_bars: int = 288,
    cost_usd: float = COST_USD,
) -> pd.DataFrame:
    """Each sig has: signal_index, limit_price, side, stop_price.
    Look forward for fill: M5 bar where low <= limit_price (long) within max_wait bars.
    Fill price = limit_price (if open > limit) or open (gapped through).
    Then walk 1R bracket close-based until tp/sl/timeout.
    """
    op = m5["open"].values
    hi = m5["high"].values
    lo = m5["low"].values
    cl = m5["close"].values
    ts = m5["timestamp"].values
    yr = m5["year"].values
    n = len(m5)
    outs = []
    MAX_WAIT = 96  # 8h to find limit fill

    for sig in sigs.itertuples(index=False):
        i0 = int(sig.signal_index)
        side = int(sig.side)
        limit = float(sig.limit_price)
        stop = float(sig.stop_price)
        # Find first bar within [i0+1, i0+MAX_WAIT] where price touches limit
        fill_idx = -1
        for k in range(i0 + 1, min(n - 1, i0 + 1 + MAX_WAIT)):
            if side > 0 and lo[k] <= limit:
                fill_idx = k; break
            if side < 0 and hi[k] >= limit:
                fill_idx = k; break
        if fill_idx < 0:
            continue
        # Determine entry price
        if side > 0:
            entry = limit if op[fill_idx] >= limit else op[fill_idx]
        else:
            entry = limit if op[fill_idx] <= limit else op[fill_idx]
        risk = entry - stop if side > 0 else stop - entry
        if risk <= 0 or not np.isfinite(risk):
            continue
        # Cap risk at 1% price
        if risk > 0.01 * entry:
            continue
        tp = entry + tp_mult * risk * side
        end = min(n - 1, fill_idx + horizon_bars)
        outcome_r = 0.0
        exit_i = end
        for j in range(fill_idx, end + 1):
            c = cl[j]
            if side > 0:
                if c <= stop: outcome_r = -1.0; exit_i = j; break
                if c >= tp:   outcome_r = tp_mult; exit_i = j; break
            else:
                if c >= stop: outcome_r = -1.0; exit_i = j; break
                if c <= tp:   outcome_r = tp_mult; exit_i = j; break
        else:
            outcome_r = max(-1.0, min(tp_mult, side * (cl[exit_i] - entry) / risk))
        outs.append({
            "entry_ts": ts[fill_idx], "side": side, "entry_price": entry,
            "stop_price": stop, "tp_price": tp, "risk_units": risk,
            "exit_index": exit_i, "bracket_r": outcome_r,
            "cost_r": cost_usd / risk, "net_r": outcome_r - cost_usd / risk,
            "year": yr[fill_idx],
        })
    return pd.DataFrame(outs)


def gen_signals(
    m5: pd.DataFrame, h4_fvgs: pd.DataFrame, m15_fvgs: pd.DataFrame,
    *, direction: str, fvg_max_age_h: float, session: str,
    swing_lookback: int, require_m15_inside_h4: bool = True,
) -> pd.DataFrame:
    """For each M5 bar, check if it is retracing into an active H4 FVG
    that matches direction, and find an active M15 FVG inside that.
    Emit ONE signal per H4 FVG (first valid setup)."""
    side = +1 if direction == "long" else -1
    ny_hr = m5["ny_hr"].values
    sess_mask = in_session(ny_hr, session)
    op = m5["open"].values
    hi = m5["high"].values
    lo = m5["low"].values
    ts = m5["timestamp"].values
    sw_lo = m5[f"swing_low_{swing_lookback}_lag"].values
    sw_hi = m5[f"swing_high_{swing_lookback}_lag"].values

    h4_filt = h4_fvgs[h4_fvgs["side"] == side].copy().reset_index(drop=True)
    m15_filt = m15_fvgs[m15_fvgs["side"] == side].copy().reset_index(drop=True)

    h4_confirm = h4_filt["confirm_ts"].values
    h4_upper = h4_filt["upper"].values
    h4_lower = h4_filt["lower"].values
    m15_confirm = m15_filt["confirm_ts"].values
    m15_upper = m15_filt["upper"].values
    m15_lower = m15_filt["lower"].values

    age_ns = int(fvg_max_age_h * 3600 * 1e9)
    rows = []
    used_h4 = set()

    for i in range(swing_lookback + 1, len(m5)):
        if not sess_mask[i]:
            continue
        t = ts[i]
        # Active H4 FVGs: confirm_ts <= t and (t - confirm_ts) <= age
        # Use searchsorted bounds
        max_h4_idx = np.searchsorted(h4_confirm, t, side="right") - 1
        if max_h4_idx < 0:
            continue
        # Find FVG with retrace touch this bar — iterate backwards over recent FVGs
        chosen_h4 = -1
        for k in range(max_h4_idx, max(-1, max_h4_idx - 200), -1):
            age = int(t.astype("int64")) - int(h4_confirm[k].astype("int64"))
            if age > age_ns:
                break  # older FVGs all out
            if h4_confirm[k] in used_h4:
                continue
            # Retrace touch on this M5 bar?
            if side > 0:
                if lo[i] <= h4_upper[k] and hi[i] >= h4_lower[k]:
                    chosen_h4 = k
                    break
            else:
                if hi[i] >= h4_lower[k] and lo[i] <= h4_upper[k]:
                    chosen_h4 = k
                    break
        if chosen_h4 < 0:
            continue

        # Inside H4 retrace, find latest M15 FVG that is:
        #   (a) confirmed <= t
        #   (b) overlaps H4 FVG range (if require_m15_inside_h4)
        h4_lo, h4_hi = h4_lower[chosen_h4], h4_upper[chosen_h4]
        max_m15_idx = np.searchsorted(m15_confirm, t, side="right") - 1
        if max_m15_idx < 0:
            continue
        chosen_m15 = -1
        for j in range(max_m15_idx, max(-1, max_m15_idx - 500), -1):
            age = int(t.astype("int64")) - int(m15_confirm[j].astype("int64"))
            if age > age_ns:
                break
            mu, ml = m15_upper[j], m15_lower[j]
            if require_m15_inside_h4:
                overlap = not (ml > h4_hi or mu < h4_lo)
                if not overlap:
                    continue
            chosen_m15 = j
            break
        if chosen_m15 < 0:
            continue

        # Limit price
        if side > 0:
            limit = m15_upper[chosen_m15]
            # Need price currently ABOVE limit so retrace fills it
            if op[i] < limit:
                continue
            stop = sw_lo[i]
            if not np.isfinite(stop) or stop >= limit:
                continue
        else:
            limit = m15_lower[chosen_m15]
            if op[i] > limit:
                continue
            stop = sw_hi[i]
            if not np.isfinite(stop) or stop <= limit:
                continue

        used_h4.add(h4_confirm[chosen_h4])
        rows.append({
            "signal_index": i, "side": side,
            "limit_price": float(limit), "stop_price": float(stop),
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["signal_index", "side", "limit_price", "stop_price"])


def prep(m1: pd.DataFrame, m5: pd.DataFrame, swing_lookback: int):
    h4 = resample(m1, "4h")
    m15 = resample(m1, "15min")
    h4_fvgs = detect_all_fvgs(h4)
    m15_fvgs = detect_all_fvgs(m15)
    m5 = add_swings(m5, lookback=swing_lookback)
    return h4_fvgs, m15_fvgs, m5


def run_combo(m5, h4_fvgs, m15_fvgs, *, combo, persist_family):
    sigs = gen_signals(m5, h4_fvgs, m15_fvgs, **{k: v for k, v in combo.items()
                                                  if k not in ("tp_mults",)})
    if len(sigs) == 0:
        return []
    rows = []
    for tp in combo["tp_mults"]:
        trades = simulate_with_limit_fills(m5, sigs, tp_mult=tp)
        if len(trades) == 0:
            continue
        h = headline(trades); g = gate(h)
        label = (
            f"{combo['direction']}_age{combo['fvg_max_age_h']}h"
            f"_sess{combo['session']}_sw{combo['swing_lookback']}"
            f"_inside{int(combo['require_m15_inside_h4'])}_TP{tp}R"
        )
        rows.append({**{k: v for k, v in combo.items() if k != "tp_mults"},
                     "tp": tp, **h, **{f"gate_{k}": v for k, v in g.items()},
                     "label": label})
        if h["pf"] >= 1.3 and "/" in h["pos_years"]:
            pos = int(h["pos_years"].split("/")[0])
            if pos >= 6:
                print_headline(label, h)
                persist(persist_family, label, trades, notes="FVG nested H4→M15")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["1", "2", "both"], default="1")
    args = ap.parse_args()

    print("[load] m1/m5 cached...")
    m1, m5, _ = load_data()
    # Pre-build all swing variants we might need
    print("[build] FVGs + swings...")
    h4 = resample(m1, "4h")
    m15 = resample(m1, "15min")
    h4_fvgs = detect_all_fvgs(h4)
    m15_fvgs = detect_all_fvgs(m15)
    print(f"  H4 FVGs: {len(h4_fvgs):,}   M15 FVGs: {len(m15_fvgs):,}")

    all_rows = []

    if args.phase in ("1", "both"):
        print("\n=== Phase 1: coarse sweep ===\n")
        for direction in ["long", "short"]:
            for session in ["all", "london", "ny", "overlap"]:
                for fvg_age in [12, 24, 72]:
                    for sw in [20]:
                        m5_with_sw = add_swings(m5, lookback=sw)
                        combo = dict(direction=direction, fvg_max_age_h=fvg_age,
                                     session=session, swing_lookback=sw,
                                     require_m15_inside_h4=True,
                                     tp_mults=[1.0, 2.0, 3.0, 4.0])
                        all_rows.extend(run_combo(m5_with_sw, h4_fvgs, m15_fvgs,
                                                   combo=combo,
                                                   persist_family="fvg_nested"))

    if args.phase in ("2", "both"):
        print("\n=== Phase 2: deep grid ===\n")
        for direction in ["long", "short"]:
            for session in ["all", "london", "overlap"]:
                for fvg_age in [4, 8, 12, 24, 48, 72]:
                    for sw in [10, 20, 30, 50]:
                        for inside in [True, False]:
                            m5_with_sw = add_swings(m5, lookback=sw)
                            combo = dict(direction=direction, fvg_max_age_h=fvg_age,
                                         session=session, swing_lookback=sw,
                                         require_m15_inside_h4=inside,
                                         tp_mults=[2.0, 3.0, 4.0])
                            all_rows.extend(run_combo(m5_with_sw, h4_fvgs, m15_fvgs,
                                                       combo=combo,
                                                       persist_family="fvg_nested"))

    if not all_rows:
        print("\nNO ROWS produced.")
        return
    lb = pd.DataFrame(all_rows)
    out_path = Path("/Users/subash/SUBASH/GoldDigger/research/fvg_nested/sweep_leaderboard.csv")
    lb.to_csv(out_path, index=False)
    print(f"\nSaved → {out_path}")
    top = lb.sort_values("mar", ascending=False).head(20)
    print("\n[TOP 20 by MAR]\n")
    cols = ["direction", "fvg_max_age_h", "session", "swing_lookback",
            "require_m15_inside_h4", "tp", "n", "trades_per_year", "pf", "mar", "pos_years"]
    print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
