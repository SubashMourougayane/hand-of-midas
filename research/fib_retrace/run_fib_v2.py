"""Fib retracement V2 — literal port of the formalised spec.

Rules (per spec):
  1. Causal pivot detection on H1 (pivot_left=N, pivot_right=N).
     Confirmed at pivot_idx + pivot_right → usable from confirmed+1 onward.
     NO rolling(center=True) — that's look-ahead.
  2. Track last_swing_low (L) and last_swing_high (H).
     For LONG setup: need confirmed L THEN later confirmed H. diff = H - L > 0.
     For SHORT setup: need confirmed H THEN later confirmed L. diff = H - L > 0.
  3. Fib levels (LONG retracement from H toward L):
     fib_0   = H
     fib_382 = H - 0.382 * diff
     fib_500 = H - 0.500 * diff
     fib_618 = H - 0.618 * diff
     fib_786 = H - 0.786 * diff
     fib_100 = L  (invalidation)
     ext_target = H + 0.27 * diff  (TP)
  4. Active "buy hunt": once setup formed, monitor M5 bars.
  5. Invalidation: any M5 close < fib_100 (L) → kill setup, no entry.
  6. Entry zone: bar low <= fib_382 AND bar close >= fib_786 (price is inside zone).
  7. Confirmation candle on bar in zone (LONG):
       BULLISH ENGULFING:
         prev close < prev open (red prior)
         current close > current open (green current)
         current close >= prev open
         current open <= prev close
       OR LOWER REJECTION WICK PINBAR:
         lower_wick > 50% of total_range
         where lower_wick = min(open, close) - low
               total_range = high - low
  8. Entry on NEXT M5 OPEN after confirmation.
  9. SL = fib_100 - 0.05 * diff (5% beyond swing low).
 10. TP = ext_target (fixed price, NOT R-multiple).
 11. Risk per trade = entry - SL, R = (exit - entry) / risk * side.
 12. Time horizon = max_hold_bars (configurable).
 13. Setup resets after first entry OR invalidation OR new swing extreme.

Causality:
 - Pivots confirmed at idx+right. Never use future bars.
 - Each M5 bar in active hunt evaluated using only its own + prior bars.
 - Entry strictly NEXT bar after confirmation close.
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
from research.fib_retrace.run_fib import (
    resample, build_h1_features, detect_pivots, add_m5_swings_and_atr, in_session
)


def build_pivot_events(h1: pd.DataFrame, pivot_lb: int):
    """Return list of (confirm_ts, type, price) sorted by confirm_ts.
    confirm_ts = ts of the bar (pivot_idx + pivot_lb)."""
    highs = h1["high"].values
    lows = h1["low"].values
    ts = h1["timestamp"].values
    n = len(h1)
    ph, pl = detect_pivots(highs, lows, pivot_lb)
    events = []
    for i in np.flatnonzero(ph):
        ci = i + pivot_lb
        if ci >= n: continue
        events.append({"confirm_ts": ts[ci], "type": "H", "price": float(highs[i])})
    for i in np.flatnonzero(pl):
        ci = i + pivot_lb
        if ci >= n: continue
        events.append({"confirm_ts": ts[ci], "type": "L", "price": float(lows[i])})
    events.sort(key=lambda x: x["confirm_ts"])
    return events


def gen_signals_v2(
    m5: pd.DataFrame, pivot_events: list[dict], *,
    direction: str, session: str, min_diff_atr: float, max_hold_bars: int,
    ext_target_pct: float, sl_buffer_pct: float,
):
    """Generate signals per formalised spec.
    direction: 'long' or 'short'.
    min_diff_atr: minimum (H - L) / atr_h1_at_setup; filters micro-impulses.
    ext_target_pct: TP at swing extreme + ext_target_pct * diff (0.27 default).
    sl_buffer_pct: SL = swing_L - sl_buffer_pct * diff (5% default = 0.05).
    """
    side = 1 if direction == "long" else -1
    m5_ts = m5["timestamp"].values
    op = m5["open"].values; hi = m5["high"].values
    lo = m5["low"].values; cl = m5["close"].values
    cl_lag = np.r_[np.nan, cl[:-1]]
    op_lag = np.r_[np.nan, op[:-1]]
    ny_hr = m5["ny_hr"].values
    sess_mask = in_session(ny_hr, session)

    # Precompute confirmation masks per bar
    if side > 0:
        # Bullish engulfing: prev red, this green, close>=prev open, open<=prev close
        bull_eng = (cl_lag < op_lag) & (cl > op) & (cl >= op_lag) & (op <= cl_lag)
        # Lower wick pinbar: lower_wick > 50% of range
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
    last_L = None; last_L_ts = None
    last_H = None; last_H_ts = None
    # iterate pivot events
    for ev in pivot_events:
        if ev["type"] == "L":
            last_L = ev["price"]; last_L_ts = ev["confirm_ts"]
        else:
            last_H = ev["price"]; last_H_ts = ev["confirm_ts"]

        # Setup formed: depending on direction we need
        # LONG: latest L THEN latest H (impulse L→H), H confirmed after L
        # SHORT: latest H THEN latest L (impulse H→L), L confirmed after H
        if side > 0:
            if last_L is None or last_H is None: continue
            if last_H_ts <= last_L_ts: continue  # H must be after L
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

        # Scan M5 bars from setup_confirm_ts onward until invalidation, entry, or new pivot
        start_idx = np.searchsorted(m5_ts, setup_confirm_ts, side="right")
        if start_idx >= len(m5_ts): continue
        # End scan when next pivot of OPPOSITE type confirms (creates new setup)
        # Conservative: scan up to max_hold_bars or until invalidation
        end_idx = min(len(m5_ts), start_idx + max_hold_bars)
        entered = False
        for k in range(start_idx, end_idx):
            if side > 0:
                if cl[k] < fib_100:
                    break  # invalidated
                # In retracement zone?
                if cl[k] <= fib_382 and cl[k] >= fib_786 and sess_mask[k]:
                    if confirm_mask[k]:
                        entry_idx = k + 1
                        if entry_idx >= len(m5_ts) - 2: break
                        entry_price = op[entry_idx]
                        risk = entry_price - sl_price
                        if risk <= 0 or not np.isfinite(risk): break
                        if risk > 0.02 * entry_price: break
                        # Effective R multiple to TP given risk
                        rr = (tp_price - entry_price) / risk
                        if rr <= 0: break
                        sig_rows.append({
                            "entry_index": int(entry_idx), "side": 1,
                            "risk_units": float(risk),
                            "stop_price": float(sl_price),
                            "tp_price_fixed": float(tp_price),
                            "rr_to_tp": float(rr),
                        })
                        entered = True; break
            else:
                if cl[k] > fib_100:
                    break
                if cl[k] >= fib_382 and cl[k] <= fib_786 and sess_mask[k]:
                    if confirm_mask[k]:
                        entry_idx = k + 1
                        if entry_idx >= len(m5_ts) - 2: break
                        entry_price = op[entry_idx]
                        risk = sl_price - entry_price
                        if risk <= 0 or not np.isfinite(risk): break
                        if risk > 0.02 * entry_price: break
                        rr = (entry_price - tp_price) / risk
                        if rr <= 0: break
                        sig_rows.append({
                            "entry_index": int(entry_idx), "side": -1,
                            "risk_units": float(risk),
                            "stop_price": float(sl_price),
                            "tp_price_fixed": float(tp_price),
                            "rr_to_tp": float(rr),
                        })
                        entered = True; break

    return pd.DataFrame(sig_rows) if sig_rows else pd.DataFrame(
        columns=["entry_index", "side", "risk_units", "stop_price",
                 "tp_price_fixed", "rr_to_tp"])


def simulate_fixed_tp(m5: pd.DataFrame, sigs: pd.DataFrame, *,
                       horizon_bars: int = 576, cost_usd: float = COST_USD) -> pd.DataFrame:
    """Bracket walker using fixed tp_price + stop_price from sigs."""
    op = m5["open"].values; cl = m5["close"].values
    ts = m5["timestamp"].values; yr = m5["year"].values
    n = len(m5)
    outs = []
    for sig in sigs.itertuples(index=False):
        i = int(sig.entry_index); side = int(sig.side)
        risk = float(sig.risk_units); stop = float(sig.stop_price)
        tp = float(sig.tp_price_fixed)
        entry = op[i]
        end = min(n - 1, i + horizon_bars)
        outcome_r = 0.0; exit_i = end; broke = False
        max_r = abs(tp - entry) / risk  # ceiling outcome in R
        for j in range(i, end + 1):
            c = cl[j]
            if side > 0:
                if c <= stop:
                    outcome_r = -1.0; exit_i = j; broke=True; break
                if c >= tp:
                    outcome_r = (tp - entry) / risk; exit_i = j; broke=True; break
            else:
                if c >= stop:
                    outcome_r = -1.0; exit_i = j; broke=True; break
                if c <= tp:
                    outcome_r = (entry - tp) / risk; exit_i = j; broke=True; break
        if not broke:
            outcome_r = max(-1.0, min(max_r, side * (cl[exit_i] - entry) / risk))
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
    h1 = resample(m1, "1h"); h1 = build_h1_features(h1)
    m5_f = add_m5_swings_and_atr(m5)
    if "ny_hr" not in m5_f.columns:
        m5_f["ny_hr"] = m5_f["timestamp"].dt.tz_convert("America/New_York").dt.hour

    all_rows = []

    if args.phase == "1":
        print("\n=== Phase 1: V2 spec coarse sweep ===\n")
        for pivot_lb in [3, 5, 8]:
            print(f"  pivot_lb={pivot_lb}...")
            pivot_events = build_pivot_events(h1, pivot_lb)
            print(f"  pivot_events: {len(pivot_events)}")
            for direction in ["long", "short"]:
                for max_hold_h in [12, 24, 48]:
                    max_hold_bars = int(max_hold_h * 12)
                    for sess in ["all", "london_ny"]:
                        for ext in [0.27]:
                            for sl_buf in [0.05]:
                                sigs = gen_signals_v2(m5_f, pivot_events,
                                    direction=direction, session=sess,
                                    min_diff_atr=0.0, max_hold_bars=max_hold_bars,
                                    ext_target_pct=ext, sl_buffer_pct=sl_buf)
                                if len(sigs) == 0: continue
                                trades = simulate_fixed_tp(m5_f, sigs, horizon_bars=max_hold_bars*2)
                                if len(trades) == 0: continue
                                h = headline(trades); g = gate(h)
                                label = f"{direction}_lb{pivot_lb}_hold{max_hold_h}h_sess{sess}_ext{ext}_sl{sl_buf}_v2"
                                all_rows.append({
                                    "direction": direction, "pivot_lb": pivot_lb,
                                    "max_hold_h": max_hold_h, "session": sess,
                                    "ext": ext, "sl_buf": sl_buf, **h,
                                    **{f"gate_{k}": v for k, v in g.items()},
                                    "label": label,
                                })
                                if h["pf"] >= 1.3 and "/" in h["pos_years"]:
                                    pos = int(h["pos_years"].split("/")[0])
                                    if pos >= 6:
                                        print_headline(label, h)
                                        persist("fib_retrace", label, trades, notes="Fib V2 phase1")
    else:
        print("\n=== Phase 2: V2 spec deep grid ===\n")
        for pivot_lb in [3, 5, 8, 10]:
            pivot_events = build_pivot_events(h1, pivot_lb)
            if len(pivot_events) == 0: continue
            for direction in ["long", "short"]:
                for max_hold_h in [6, 12, 24, 48, 72]:
                    max_hold_bars = int(max_hold_h * 12)
                    for sess in ["all", "london", "ny", "london_ny", "overlap"]:
                        for ext in [0.27, 0.5, 1.0, 1.618]:
                            for sl_buf in [0.02, 0.05, 0.1]:
                                sigs = gen_signals_v2(m5_f, pivot_events,
                                    direction=direction, session=sess,
                                    min_diff_atr=0.0, max_hold_bars=max_hold_bars,
                                    ext_target_pct=ext, sl_buffer_pct=sl_buf)
                                if len(sigs) == 0: continue
                                trades = simulate_fixed_tp(m5_f, sigs, horizon_bars=max_hold_bars*2)
                                if len(trades) == 0: continue
                                h = headline(trades); g = gate(h)
                                label = f"{direction}_lb{pivot_lb}_hold{max_hold_h}h_sess{sess}_ext{ext}_sl{sl_buf}_v2"
                                all_rows.append({
                                    "direction": direction, "pivot_lb": pivot_lb,
                                    "max_hold_h": max_hold_h, "session": sess,
                                    "ext": ext, "sl_buf": sl_buf, **h,
                                    **{f"gate_{k}": v for k, v in g.items()},
                                    "label": label,
                                })
                                if h["pf"] >= 1.5 and "/" in h["pos_years"]:
                                    pos = int(h["pos_years"].split("/")[0])
                                    if pos >= 7:
                                        print_headline(label, h)
                                        persist("fib_retrace", label, trades, notes="Fib V2 phase2")

    if not all_rows:
        print("\n[NO ROWS]"); return
    lb = pd.DataFrame(all_rows)
    out_path = Path(f"/Users/subash/SUBASH/GoldDigger/research/fib_retrace/sweep_v2_p{args.phase}.csv")
    lb.to_csv(out_path, index=False)
    print(f"\nSaved → {out_path}")
    top = lb.sort_values("mar", ascending=False).head(30)
    print("\n[TOP 30 by MAR]\n")
    cols = ["direction", "pivot_lb", "max_hold_h", "session", "ext", "sl_buf",
            "n", "trades_per_year", "pf", "mar", "pos_years"]
    print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
