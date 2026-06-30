"""H4→M15 FVG nested retrace — VECTORISED edition.

Avoids Python-per-bar loops by:
  1. For each H4 FVG, compute the M5 index range where price first retraces in.
  2. For each H4 retrace event, pick the most-recent M15 FVG (causal) inside that range.
  3. Compute one signal per H4 FVG.

This caps work to O(num_fvgs) which is ~1500 H4 + ~20000 M15 — fast.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import (
    load_data, headline, persist, print_headline, gate, COST_USD
)


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    return (
        m1.set_index("timestamp")
        .resample(rule, label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )


def detect_fvgs(htf: pd.DataFrame) -> pd.DataFrame:
    h = htf["high"].values
    l = htf["low"].values
    ts = htf["timestamp"].values
    n = len(htf)
    if n < 3:
        return pd.DataFrame(columns=["confirm_ts", "upper", "lower", "side"])
    t_idx = np.arange(1, n - 1)
    bull = l[t_idx + 1] > h[t_idx - 1]
    bear = h[t_idx + 1] < l[t_idx - 1]
    rows = []
    for k in np.flatnonzero(bull):
        i = t_idx[k]
        rows.append({"confirm_ts": ts[i + 1], "upper": float(l[i + 1]),
                     "lower": float(h[i - 1]), "side": 1})
    for k in np.flatnonzero(bear):
        i = t_idx[k]
        rows.append({"confirm_ts": ts[i + 1], "upper": float(l[i - 1]),
                     "lower": float(h[i + 1]), "side": -1})
    df = pd.DataFrame(rows).sort_values("confirm_ts").reset_index(drop=True)
    return df


def add_swings(m5: pd.DataFrame, lookback: int) -> pd.DataFrame:
    df = m5.copy()
    df[f"swing_low_{lookback}_lag"] = df["low"].shift(1).rolling(lookback).min()
    df[f"swing_high_{lookback}_lag"] = df["high"].shift(1).rolling(lookback).max()
    return df


def in_session_mask(ny_hr: np.ndarray, session: str) -> np.ndarray:
    if session == "all": return np.ones_like(ny_hr, dtype=bool)
    if session == "london": return (ny_hr >= 3) & (ny_hr < 12)
    if session == "ny": return (ny_hr >= 8) & (ny_hr < 17)
    if session == "overlap": return (ny_hr >= 8) & (ny_hr < 12)
    raise ValueError(session)


def find_retrace_idx_per_fvg(
    m5_ts: np.ndarray, m5_high: np.ndarray, m5_low: np.ndarray, m5_open: np.ndarray,
    fvg_confirm: np.ndarray, fvg_upper: np.ndarray, fvg_lower: np.ndarray,
    fvg_side: np.ndarray, age_ns: int, sess_mask: np.ndarray,
) -> np.ndarray:
    """For each FVG, find earliest M5 idx where retrace-touch happens within age."""
    n_fvg = len(fvg_confirm)
    retrace_idx = np.full(n_fvg, -1, dtype=np.int64)
    # M5 starts indexed by confirm_ts: searchsorted right
    start_idx = np.searchsorted(m5_ts, fvg_confirm, side="right")
    for f in range(n_fvg):
        s = start_idx[f]
        deadline = fvg_confirm[f] + np.timedelta64(age_ns, "ns")
        end_idx = np.searchsorted(m5_ts, deadline, side="right")
        if s >= len(m5_ts):
            continue
        end_idx = min(end_idx, len(m5_ts))
        u = fvg_upper[f]
        l = fvg_lower[f]
        side = fvg_side[f]
        # vectorise within window
        if end_idx <= s:
            continue
        win_lo = m5_low[s:end_idx]
        win_hi = m5_high[s:end_idx]
        win_op = m5_open[s:end_idx]
        win_sess = sess_mask[s:end_idx]
        if side > 0:
            # touch = low <= upper AND high >= lower AND open > upper (need price ABOVE retrace zone)
            touch = (win_lo <= u) & (win_hi >= l) & (win_op > u) & win_sess
        else:
            touch = (win_hi >= l) & (win_lo <= u) & (win_op < l) & win_sess
        hits = np.flatnonzero(touch)
        if len(hits) == 0:
            continue
        retrace_idx[f] = s + int(hits[0])
    return retrace_idx


def attach_m15_fvgs(
    m5_ts: np.ndarray, m5_idx_arr: np.ndarray,
    h4_lo_arr: np.ndarray, h4_hi_arr: np.ndarray, h4_side_arr: np.ndarray,
    m15_confirm: np.ndarray, m15_upper: np.ndarray, m15_lower: np.ndarray,
    m15_side: np.ndarray, age_ns: int, require_inside: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """For each H4 retrace event, find latest M15 FVG (same side) confirmed before
    retrace ts, age <= age_ns, optionally overlapping H4 FVG range.

    Returns: (m15_limit_arr, valid_mask)
    """
    n = len(m5_idx_arr)
    limits = np.full(n, np.nan)
    valid = np.zeros(n, dtype=bool)
    # sort m15 by confirm_ts (already done)
    for f in range(n):
        i = m5_idx_arr[f]
        if i < 0:
            continue
        t = m5_ts[i]
        deadline_lo = t - np.timedelta64(age_ns, "ns")
        side = h4_side_arr[f]
        # Bound search
        hi_idx = np.searchsorted(m15_confirm, t, side="right")
        lo_idx = np.searchsorted(m15_confirm, deadline_lo, side="left")
        if hi_idx <= lo_idx:
            continue
        # Walk backwards through M15 FVGs in [lo_idx, hi_idx) with matching side
        h4_lo = h4_lo_arr[f]; h4_hi = h4_hi_arr[f]
        found_limit = np.nan
        for k in range(hi_idx - 1, lo_idx - 1, -1):
            if m15_side[k] != side:
                continue
            mu = m15_upper[k]; ml = m15_lower[k]
            if require_inside:
                # overlap
                if ml > h4_hi or mu < h4_lo:
                    continue
            if side > 0:
                found_limit = mu
            else:
                found_limit = ml
            break
        if np.isfinite(found_limit):
            limits[f] = found_limit
            valid[f] = True
    return limits, valid


def simulate_with_limit(
    m5_arr: dict, sigs: pd.DataFrame, *, tp_mult: float,
    horizon_bars: int = 288, cost_usd: float = COST_USD,
    max_wait: int = 96,
) -> pd.DataFrame:
    op = m5_arr["open"]; hi = m5_arr["high"]; lo = m5_arr["low"]
    cl = m5_arr["close"]; ts = m5_arr["ts"]; yr = m5_arr["year"]
    n = len(op)
    outs = []
    for sig in sigs.itertuples(index=False):
        i0 = int(sig.signal_index)
        side = int(sig.side)
        limit = float(sig.limit_price)
        stop = float(sig.stop_price)
        end_w = min(n - 1, i0 + 1 + max_wait)
        fill_idx = -1
        for k in range(i0 + 1, end_w):
            if side > 0 and lo[k] <= limit:
                fill_idx = k; break
            if side < 0 and hi[k] >= limit:
                fill_idx = k; break
        if fill_idx < 0:
            continue
        if side > 0:
            entry = limit if op[fill_idx] >= limit else op[fill_idx]
        else:
            entry = limit if op[fill_idx] <= limit else op[fill_idx]
        risk = entry - stop if side > 0 else stop - entry
        if risk <= 0 or not np.isfinite(risk):
            continue
        if risk > 0.01 * entry:
            continue
        tp = entry + tp_mult * risk * side
        end = min(n - 1, fill_idx + horizon_bars)
        outcome_r = 0.0
        exit_i = end
        broke = False
        for j in range(fill_idx, end + 1):
            c = cl[j]
            if side > 0:
                if c <= stop: outcome_r = -1.0; exit_i = j; broke=True; break
                if c >= tp:   outcome_r = tp_mult; exit_i = j; broke=True; break
            else:
                if c >= stop: outcome_r = -1.0; exit_i = j; broke=True; break
                if c <= tp:   outcome_r = tp_mult; exit_i = j; broke=True; break
        if not broke:
            outcome_r = max(-1.0, min(tp_mult, side * (cl[exit_i] - entry) / risk))
        outs.append({"entry_ts": ts[fill_idx], "side": side, "entry_price": entry,
                     "stop_price": stop, "tp_price": tp, "risk_units": risk,
                     "exit_index": exit_i, "bracket_r": outcome_r,
                     "cost_r": cost_usd / risk,
                     "net_r": outcome_r - cost_usd / risk,
                     "year": yr[fill_idx]})
    return pd.DataFrame(outs)


def gen_signals_fast(
    m5: pd.DataFrame, h4_fvgs: pd.DataFrame, m15_fvgs: pd.DataFrame,
    *, direction: str, fvg_max_age_h: float, session: str,
    swing_lookback: int, require_m15_inside_h4: bool,
):
    side = +1 if direction == "long" else -1
    h4_filt = h4_fvgs[h4_fvgs["side"] == side].reset_index(drop=True)
    if len(h4_filt) == 0:
        return pd.DataFrame()

    m5 = add_swings(m5, swing_lookback)
    sess_mask = in_session_mask(m5["ny_hr"].values, session)
    age_ns = int(fvg_max_age_h * 3600 * 1e9)

    m5_ts = m5["timestamp"].values
    m5_open = m5["open"].values
    m5_high = m5["high"].values
    m5_low = m5["low"].values
    sw_lo = m5[f"swing_low_{swing_lookback}_lag"].values
    sw_hi = m5[f"swing_high_{swing_lookback}_lag"].values

    h4_confirm = h4_filt["confirm_ts"].values
    h4_upper = h4_filt["upper"].values
    h4_lower = h4_filt["lower"].values
    h4_side = h4_filt["side"].values

    retrace_idx = find_retrace_idx_per_fvg(
        m5_ts, m5_high, m5_low, m5_open,
        h4_confirm, h4_upper, h4_lower, h4_side,
        age_ns, sess_mask,
    )
    keep = retrace_idx >= 0
    if not keep.any():
        return pd.DataFrame()
    m5_idx_arr = retrace_idx[keep]
    h4_lo_arr = h4_lower[keep]
    h4_hi_arr = h4_upper[keep]
    h4_side_arr = h4_side[keep]

    m15_all = m15_fvgs.sort_values("confirm_ts").reset_index(drop=True)
    m15_confirm = m15_all["confirm_ts"].values
    m15_upper = m15_all["upper"].values
    m15_lower = m15_all["lower"].values
    m15_side = m15_all["side"].values

    limits, valid = attach_m15_fvgs(
        m5_ts, m5_idx_arr, h4_lo_arr, h4_hi_arr, h4_side_arr,
        m15_confirm, m15_upper, m15_lower, m15_side,
        age_ns, require_m15_inside_h4,
    )
    if not valid.any():
        return pd.DataFrame()
    m5_idx_arr = m5_idx_arr[valid]
    limits = limits[valid]

    rows = []
    for k in range(len(m5_idx_arr)):
        i = int(m5_idx_arr[k])
        limit = float(limits[k])
        if side > 0:
            if m5_open[i] < limit:
                continue
            stop = sw_lo[i]
            if not np.isfinite(stop) or stop >= limit:
                continue
        else:
            if m5_open[i] > limit:
                continue
            stop = sw_hi[i]
            if not np.isfinite(stop) or stop <= limit:
                continue
        rows.append({"signal_index": i, "side": side,
                     "limit_price": limit, "stop_price": float(stop)})
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["signal_index", "side", "limit_price", "stop_price"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["1", "2"], default="1")
    args = ap.parse_args()

    print("[load] frames...")
    m1, m5, _ = load_data()
    print(f"  m5 rows: {len(m5):,}")
    print("[build] FVGs...")
    h4_fvgs = detect_fvgs(resample(m1, "4h"))
    m15_fvgs = detect_fvgs(resample(m1, "15min"))
    print(f"  H4 FVGs: {len(h4_fvgs):,}   M15 FVGs: {len(m15_fvgs):,}")

    m5_arr = {
        "open": m5["open"].values,
        "high": m5["high"].values,
        "low": m5["low"].values,
        "close": m5["close"].values,
        "ts": m5["timestamp"].values,
        "year": m5["year"].values,
    }

    all_rows = []

    if args.phase == "1":
        print("\n=== Phase 1: coarse sweep ===\n")
        for direction in ["long", "short"]:
            for session in ["all", "london", "ny", "overlap"]:
                for fvg_age in [12, 24, 72]:
                    sigs = gen_signals_fast(
                        m5, h4_fvgs, m15_fvgs,
                        direction=direction, fvg_max_age_h=fvg_age,
                        session=session, swing_lookback=20,
                        require_m15_inside_h4=True,
                    )
                    if len(sigs) == 0:
                        continue
                    for tp in [1.0, 2.0, 3.0, 4.0]:
                        trades = simulate_with_limit(m5_arr, sigs, tp_mult=tp)
                        if len(trades) == 0:
                            continue
                        h = headline(trades); g = gate(h)
                        label = f"{direction}_age{fvg_age}h_sess{session}_sw20_inside1_TP{tp}R"
                        all_rows.append({
                            "direction": direction, "fvg_max_age_h": fvg_age,
                            "session": session, "swing_lookback": 20,
                            "require_m15_inside_h4": True, "tp": tp, **h,
                            **{f"gate_{k}": v for k, v in g.items()}, "label": label,
                        })
                        if h["pf"] >= 1.3:
                            print_headline(label, h)
                            persist("fvg_nested", label, trades, notes="FVG nested phase1")

    elif args.phase == "2":
        print("\n=== Phase 2: deep grid ===\n")
        # Tier 2 focuses on best direction/session/sw + flips for ablations
        for direction in ["long", "short"]:
            for session in ["all", "london", "overlap"]:
                for fvg_age in [4, 8, 12, 24, 48, 72]:
                    for sw in [10, 20, 30]:
                        for inside in [True, False]:
                            sigs = gen_signals_fast(
                                m5, h4_fvgs, m15_fvgs,
                                direction=direction, fvg_max_age_h=fvg_age,
                                session=session, swing_lookback=sw,
                                require_m15_inside_h4=inside,
                            )
                            if len(sigs) == 0:
                                continue
                            for tp in [2.0, 3.0, 4.0]:
                                trades = simulate_with_limit(m5_arr, sigs, tp_mult=tp)
                                if len(trades) == 0:
                                    continue
                                h = headline(trades); g = gate(h)
                                label = f"{direction}_age{fvg_age}h_sess{session}_sw{sw}_inside{int(inside)}_TP{tp}R"
                                all_rows.append({
                                    "direction": direction, "fvg_max_age_h": fvg_age,
                                    "session": session, "swing_lookback": sw,
                                    "require_m15_inside_h4": inside, "tp": tp, **h,
                                    **{f"gate_{k}": v for k, v in g.items()}, "label": label,
                                })
                                if h["pf"] >= 1.3 and "/" in h["pos_years"]:
                                    pos = int(h["pos_years"].split("/")[0])
                                    if pos >= 6:
                                        print_headline(label, h)
                                        persist("fvg_nested", label, trades, notes="FVG nested phase2")

    if not all_rows:
        print("\n[NO ROWS]")
        return
    lb = pd.DataFrame(all_rows)
    out_path = Path(f"/Users/subash/SUBASH/GoldDigger/research/fvg_nested/sweep_p{args.phase}.csv")
    lb.to_csv(out_path, index=False)
    print(f"\nSaved → {out_path}")
    top = lb.sort_values("mar", ascending=False).head(20)
    print("\n[TOP 20 by MAR]\n")
    cols = ["direction", "fvg_max_age_h", "session", "swing_lookback",
            "require_m15_inside_h4", "tp", "n", "trades_per_year", "pf", "mar", "pos_years"]
    print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
