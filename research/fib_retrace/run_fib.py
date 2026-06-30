"""Fib retracement strategy — H1 swing impulse + M5 entry.

Rules (literal port):
  1. H1 swing detection via pivot(left=N, right=N). Confirmed at pivot_idx + N.
  2. Pair consecutive opposite pivots (high→low = bearish impulse; low→high = bullish).
  3. Filter: impulse_magnitude / ATR_h1_at_pivot >= impulse_atr_min.
  4. Fib levels of impulse: 0.236, 0.382, 0.5, 0.618, 0.786.
  5. After impulse confirmed, monitor M5 bars within max_wait_h hours.
  6. Entry trigger (BEARISH continuation = short):
       - M5 bar high reaches fib level (touch within tol·atr_m5)
       - M5 bar closes BELOW open AND below prior close (rejection)
  7. Entry on NEXT M5 OPEN after confirmation bar.
  8. SL = swing high (impulse origin) + atr_pad * ATR_m5_lag
     OR fib_0 extreme.
  9. TP = TP_R * risk.

Causality strict:
  - H1 features lagged 1 H1 bar (closed bars only).
  - Pivot at H1 idx i confirmed at H1 idx i+right_N; usable from H1[i+right_N+1] onward.
  - M5 retest must occur strictly AFTER pivot confirmation H1 bar close ts.
  - All ATRs lagged.

Sweep grid: pivot_lb, fib_level, impulse_atr_min, max_wait_h, tol_atr, session, TP_R, direction.
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
    return (m1.set_index("timestamp")
            .resample(rule, label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"})
            .dropna().reset_index())


def build_h1_features(h1: pd.DataFrame) -> pd.DataFrame:
    tr = pd.concat([
        (h1["high"] - h1["low"]),
        (h1["high"] - h1["close"].shift(1)).abs(),
        (h1["low"] - h1["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    h1["atr14"] = tr.rolling(14).mean()
    h1["atr14_lag"] = h1["atr14"].shift(1)
    return h1


def detect_pivots(highs: np.ndarray, lows: np.ndarray, lb: int) -> tuple[np.ndarray, np.ndarray]:
    """Return pivot_high_idx, pivot_low_idx arrays where each idx is the pivot bar.
    Confirmation lands at idx + lb. We treat these as 'confirmed at' boundary later."""
    n = len(highs)
    ph = np.zeros(n, dtype=bool)
    pl = np.zeros(n, dtype=bool)
    for i in range(lb, n - lb):
        win_h = highs[i - lb:i + lb + 1]
        win_l = lows[i - lb:i + lb + 1]
        if highs[i] == win_h.max() and (win_h == highs[i]).sum() == 1:
            ph[i] = True
        if lows[i] == win_l.min() and (win_l == lows[i]).sum() == 1:
            pl[i] = True
    return ph, pl


def build_impulses(h1: pd.DataFrame, pivot_lb: int, impulse_atr_min: float):
    """Returns DataFrame of impulses:
        confirm_ts (H1 confirm bar close), origin_ts, origin_price (start of impulse),
        end_ts, end_price, side: +1 bullish / -1 bearish, atr_at_end.
    """
    highs = h1["high"].values
    lows = h1["low"].values
    ts = h1["timestamp"].values
    atr_lag = h1["atr14_lag"].values
    ph, pl = detect_pivots(highs, lows, pivot_lb)

    # Sequence: collect events (idx, type, price)
    pivots = []
    for i in range(len(h1)):
        if ph[i]:
            pivots.append({"idx": i, "type": "H", "price": float(highs[i])})
        if pl[i]:
            pivots.append({"idx": i, "type": "L", "price": float(lows[i])})
    pivots = sorted(pivots, key=lambda x: (x["idx"], x["type"]))
    impulses = []
    for k in range(1, len(pivots)):
        a = pivots[k - 1]
        b = pivots[k]
        if a["type"] == b["type"]:
            continue
        # bullish: L→H ; bearish: H→L
        if a["type"] == "L" and b["type"] == "H":
            side = 1
            origin_price = a["price"]; end_price = b["price"]
            magnitude = end_price - origin_price
        else:
            side = -1
            origin_price = a["price"]; end_price = b["price"]
            magnitude = origin_price - end_price
        if magnitude <= 0:
            continue
        atr_now = atr_lag[b["idx"]]
        if not np.isfinite(atr_now) or atr_now <= 0:
            continue
        if magnitude / atr_now < impulse_atr_min:
            continue
        confirm_idx = b["idx"] + pivot_lb
        if confirm_idx >= len(h1):
            continue
        confirm_ts = ts[confirm_idx]
        impulses.append({
            "confirm_ts": confirm_ts,
            "origin_ts": ts[a["idx"]], "origin_price": origin_price,
            "end_ts": ts[b["idx"]], "end_price": end_price,
            "side": side, "magnitude": magnitude, "atr_at_end": float(atr_now),
        })
    return pd.DataFrame(impulses)


def add_m5_swings_and_atr(m5: pd.DataFrame, swing_lb: int = 20, atr_period: int = 14) -> pd.DataFrame:
    df = m5.copy()
    df[f"swing_high_{swing_lb}_lag"] = df["high"].shift(1).rolling(swing_lb).max()
    df[f"swing_low_{swing_lb}_lag"] = df["low"].shift(1).rolling(swing_lb).min()
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14_m5"] = tr.rolling(atr_period).mean()
    df["atr14_m5_lag"] = df["atr14_m5"].shift(1)
    return df


def in_session(ny_hr: np.ndarray, session: str) -> np.ndarray:
    if session == "all": return np.ones_like(ny_hr, dtype=bool)
    if session == "london": return (ny_hr >= 3) & (ny_hr < 12)
    if session == "ny": return (ny_hr >= 8) & (ny_hr < 17)
    if session == "overlap": return (ny_hr >= 8) & (ny_hr < 12)
    if session == "london_ny": return (ny_hr >= 3) & (ny_hr < 17)
    raise ValueError(session)


def gen_signals(
    m5: pd.DataFrame, impulses: pd.DataFrame, *,
    direction: str, fib_level: float, tol_atr: float, max_wait_h: float,
    session: str, atr_pad: float,
):
    side = 1 if direction == "long" else -1
    imp_dir = impulses[impulses["side"] == side].reset_index(drop=True)
    if len(imp_dir) == 0:
        return pd.DataFrame()
    # For LONG: bullish impulse L→H. Retrace DOWN to fib. Entry long.
    # For SHORT: bearish impulse H→L. Retrace UP to fib. Entry short.
    m5_ts = m5["timestamp"].values
    op = m5["open"].values
    hi = m5["high"].values
    lo = m5["low"].values
    cl = m5["close"].values
    cl_lag = np.r_[np.nan, cl[:-1]]
    op_lag = np.r_[np.nan, op[:-1]]
    atr_m5 = m5["atr14_m5_lag"].values
    sw_lo = m5["swing_low_20_lag"].values
    sw_hi = m5["swing_high_20_lag"].values
    ny_hr = m5["ny_hr"].values
    sess = in_session(ny_hr, session)
    wait_ns = int(max_wait_h * 3600 * 1e9)

    sig_rows = []
    # Pre-compute candle-direction masks vectorised
    if side > 0:
        confirm_mask_global = (cl > op) & (cl > cl_lag)
    else:
        confirm_mask_global = (cl < op) & (cl < cl_lag)

    for imp in imp_dir.itertuples(index=False):
        confirm_ts = imp.confirm_ts
        origin = imp.origin_price; end = imp.end_price
        if side > 0:
            fib_price = end - fib_level * (end - origin)
            sl_extreme = origin
        else:
            fib_price = end + fib_level * (origin - end)
            sl_extreme = origin
        start_idx = np.searchsorted(m5_ts, confirm_ts, side="right")
        if start_idx >= len(m5_ts): continue
        deadline = confirm_ts + np.timedelta64(wait_ns, "ns")
        end_idx = np.searchsorted(m5_ts, deadline, side="right")
        if end_idx <= start_idx: continue

        # Vectorised window
        win_lo = lo[start_idx:end_idx]
        win_hi = hi[start_idx:end_idx]
        win_atr = atr_m5[start_idx:end_idx]
        win_sess = sess[start_idx:end_idx]
        win_conf = confirm_mask_global[start_idx:end_idx]
        atr_valid = np.isfinite(win_atr) & (win_atr > 0)
        tol = tol_atr * win_atr
        if side > 0:
            touch = (win_lo <= fib_price + tol) & (win_hi >= fib_price - tol)
        else:
            touch = (win_hi >= fib_price - tol) & (win_lo <= fib_price + tol)
        full = touch & win_conf & win_sess & atr_valid
        hits = np.flatnonzero(full)
        if len(hits) == 0:
            continue
        k = start_idx + int(hits[0])
        entry_idx = k + 1
        if entry_idx >= len(m5) - 2:
            continue
        entry_price = op[entry_idx]
        atr_now = atr_m5[k]
        if side > 0:
            stop = sl_extreme - atr_pad * atr_now
            risk = entry_price - stop
        else:
            stop = sl_extreme + atr_pad * atr_now
            risk = stop - entry_price
        if not np.isfinite(risk) or risk <= 0:
            continue
        if risk > 0.02 * entry_price:
            continue
        sig_rows.append({
            "entry_index": int(entry_idx), "side": int(side),
            "risk_units": float(risk), "stop_price": float(stop),
            "fib_price": float(fib_price), "impulse_confirm_ts": confirm_ts,
        })
    return pd.DataFrame(sig_rows) if sig_rows else pd.DataFrame(
        columns=["entry_index", "side", "risk_units", "stop_price"])


def simulate_with_stop(m5: pd.DataFrame, sigs: pd.DataFrame, *, tp_mult: float,
                       horizon_bars: int = 288, cost_usd: float = COST_USD) -> pd.DataFrame:
    op = m5["open"].values; cl = m5["close"].values; ts = m5["timestamp"].values
    yr = m5["year"].values
    n = len(m5)
    outs = []
    for sig in sigs.itertuples(index=False):
        i = int(sig.entry_index)
        side = int(sig.side)
        risk = float(sig.risk_units)
        stop = float(sig.stop_price)
        entry = op[i]
        tp = entry + tp_mult * risk * side
        end = min(n - 1, i + horizon_bars)
        outcome_r = 0.0; exit_i = end; broke = False
        for j in range(i, end + 1):
            c = cl[j]
            if side > 0:
                if c <= stop: outcome_r = -1.0; exit_i = j; broke=True; break
                if c >= tp:   outcome_r = tp_mult; exit_i = j; broke=True; break
            else:
                if c >= stop: outcome_r = -1.0; exit_i = j; broke=True; break
                if c <= tp:   outcome_r = tp_mult; exit_i = j; broke=True; break
        if not broke:
            outcome_r = max(-1.0, min(tp_mult, side * (cl[exit_i] - entry) / risk))
        outs.append({"entry_ts": ts[i], "side": side, "entry_price": entry,
                     "stop_price": stop, "tp_price": tp, "risk_units": risk,
                     "exit_index": exit_i, "bracket_r": outcome_r,
                     "cost_r": cost_usd / risk,
                     "net_r": outcome_r - cost_usd / risk,
                     "year": yr[i]})
    return pd.DataFrame(outs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["1", "2"], default="1")
    args = ap.parse_args()

    print("[load] m1/m5...")
    m1, m5, _ = load_data()
    print("[build] H1 frame + features...")
    h1 = resample(m1, "1h")
    h1 = build_h1_features(h1)
    print(f"  H1 bars: {len(h1):,}")
    print("[build] M5 swings + ATR...")
    m5_f = add_m5_swings_and_atr(m5)

    all_rows = []

    if args.phase == "1":
        print("\n=== Phase 1: coarse sweep ===\n")
        for pivot_lb in [3, 5]:
            print(f"  building impulses pivot_lb={pivot_lb}...")
            for impulse_atr_min in [1.0, 2.0]:
                impulses = build_impulses(h1, pivot_lb, impulse_atr_min)
                if len(impulses) == 0: continue
                for direction in ["long", "short"]:
                    for fib in [0.5, 0.618]:
                        for tol in [0.2]:
                            for wait in [24, 72]:
                                for sess_name in ["all", "london_ny"]:
                                    for atr_pad in [0.5]:
                                        sigs = gen_signals(m5_f, impulses,
                                            direction=direction, fib_level=fib,
                                            tol_atr=tol, max_wait_h=wait,
                                            session=sess_name, atr_pad=atr_pad)
                                        if len(sigs) == 0: continue
                                        for tp in [2.0, 3.0, 4.0]:
                                            trades = simulate_with_stop(m5_f, sigs, tp_mult=tp)
                                            if len(trades) == 0: continue
                                            h = headline(trades); g = gate(h)
                                            label = f"{direction}_lb{pivot_lb}_imp{impulse_atr_min}_fib{fib}_tol{tol}_wait{wait}h_sess{sess_name}_pad{atr_pad}_TP{tp}R"
                                            all_rows.append({
                                                "direction": direction, "pivot_lb": pivot_lb,
                                                "impulse_atr": impulse_atr_min, "fib": fib,
                                                "tol": tol, "wait_h": wait, "session": sess_name,
                                                "atr_pad": atr_pad, "tp": tp, **h,
                                                **{f"gate_{k}": v for k, v in g.items()},
                                                "label": label,
                                            })
                                            if h["pf"] >= 1.3 and "/" in h["pos_years"]:
                                                pos = int(h["pos_years"].split("/")[0])
                                                if pos >= 6:
                                                    print_headline(label, h)
                                                    persist("fib_retrace", label, trades, notes="Fib phase1")

    else:
        print("\n=== Phase 2: deep grid ===\n")
        for pivot_lb in [3, 5, 8]:
            for impulse_atr_min in [1.0, 1.5, 2.0, 3.0]:
                impulses = build_impulses(h1, pivot_lb, impulse_atr_min)
                if len(impulses) == 0: continue
                for direction in ["long", "short"]:
                    for fib in [0.382, 0.5, 0.618, 0.786]:
                        for tol in [0.1, 0.3, 0.5]:
                            for wait in [12, 24, 48, 72]:
                                for sess_name in ["all", "london", "ny", "london_ny", "overlap"]:
                                    for atr_pad in [0.3, 0.5, 1.0]:
                                        sigs = gen_signals(m5_f, impulses,
                                            direction=direction, fib_level=fib,
                                            tol_atr=tol, max_wait_h=wait,
                                            session=sess_name, atr_pad=atr_pad)
                                        if len(sigs) == 0: continue
                                        for tp in [2.0, 3.0, 4.0]:
                                            trades = simulate_with_stop(m5_f, sigs, tp_mult=tp)
                                            if len(trades) == 0: continue
                                            h = headline(trades); g = gate(h)
                                            label = f"{direction}_lb{pivot_lb}_imp{impulse_atr_min}_fib{fib}_tol{tol}_wait{wait}h_sess{sess_name}_pad{atr_pad}_TP{tp}R"
                                            all_rows.append({
                                                "direction": direction, "pivot_lb": pivot_lb,
                                                "impulse_atr": impulse_atr_min, "fib": fib,
                                                "tol": tol, "wait_h": wait, "session": sess_name,
                                                "atr_pad": atr_pad, "tp": tp, **h,
                                                **{f"gate_{k}": v for k, v in g.items()},
                                                "label": label,
                                            })
                                            if h["pf"] >= 1.5 and "/" in h["pos_years"]:
                                                pos = int(h["pos_years"].split("/")[0])
                                                if pos >= 7:
                                                    print_headline(label, h)
                                                    persist("fib_retrace", label, trades, notes="Fib phase2")

    if not all_rows:
        print("\n[NO ROWS]"); return
    lb = pd.DataFrame(all_rows)
    out_path = Path(f"/Users/subash/SUBASH/GoldDigger/research/fib_retrace/sweep_p{args.phase}.csv")
    lb.to_csv(out_path, index=False)
    print(f"\nSaved → {out_path}")
    top = lb.sort_values("mar", ascending=False).head(20)
    print("\n[TOP 20 by MAR]\n")
    cols = ["direction", "pivot_lb", "impulse_atr", "fib", "tol", "wait_h", "session",
            "atr_pad", "tp", "n", "trades_per_year", "pf", "mar", "pos_years"]
    print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
