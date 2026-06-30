"""Fully-vectorised Fib retracement strategy sweep.

Approach: per impulse, walk forward window with numpy. Build all signals in one shot.
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
    resample, build_h1_features, build_impulses, add_m5_swings_and_atr, in_session
)


def gen_signals_fast(
    m5: pd.DataFrame, impulses: pd.DataFrame, *,
    direction: str, fib_level: float, tol_atr: float, max_wait_h: float,
    session: str, atr_pad: float,
) -> pd.DataFrame:
    side = 1 if direction == "long" else -1
    imp_dir = impulses[impulses["side"] == side].reset_index(drop=True)
    if len(imp_dir) == 0:
        return pd.DataFrame()
    m5_ts = m5["timestamp"].values
    op = m5["open"].values; hi = m5["high"].values
    lo = m5["low"].values; cl = m5["close"].values
    cl_lag = np.r_[np.nan, cl[:-1]]
    op_lag = np.r_[np.nan, op[:-1]]
    atr_m5 = m5["atr14_m5_lag"].values
    ny_hr = m5["ny_hr"].values
    sess_mask = in_session(ny_hr, session)
    if side > 0:
        confirm_mask = (cl > op) & (cl > cl_lag)
    else:
        confirm_mask = (cl < op) & (cl < cl_lag)

    confirm_ts = imp_dir["confirm_ts"].values
    origin = imp_dir["origin_price"].values
    end_p = imp_dir["end_price"].values
    n_imp = len(imp_dir)
    wait_ns = int(max_wait_h * 3600 * 1e9)

    # Window starts per impulse
    start_idx = np.searchsorted(m5_ts, confirm_ts, side="right")
    deadline = confirm_ts + np.timedelta64(wait_ns, "ns")
    end_idx = np.searchsorted(m5_ts, deadline, side="right")
    end_idx = np.minimum(end_idx, len(m5_ts))

    if side > 0:
        fib_prices = end_p - fib_level * (end_p - origin)
        sl_extreme = origin
    else:
        fib_prices = end_p + fib_level * (origin - end_p)
        sl_extreme = origin

    sig_rows = []
    for i in range(n_imp):
        s = int(start_idx[i]); e = int(end_idx[i])
        if e <= s or s >= len(m5_ts) - 2:
            continue
        fib_p = float(fib_prices[i])
        win_lo = lo[s:e]; win_hi = hi[s:e]
        win_atr = atr_m5[s:e]
        win_sess = sess_mask[s:e]
        win_conf = confirm_mask[s:e]
        valid = np.isfinite(win_atr) & (win_atr > 0)
        tol = tol_atr * win_atr
        if side > 0:
            touch = (win_lo <= fib_p + tol) & (win_hi >= fib_p - tol)
        else:
            touch = (win_hi >= fib_p - tol) & (win_lo <= fib_p + tol)
        full = touch & win_conf & win_sess & valid
        hits = np.flatnonzero(full)
        if len(hits) == 0:
            continue
        k = s + int(hits[0])
        entry_idx = k + 1
        if entry_idx >= len(m5_ts) - 2:
            continue
        entry_price = op[entry_idx]
        atr_now = atr_m5[k]
        if not np.isfinite(atr_now) or atr_now <= 0:
            continue
        sl_ext = float(sl_extreme[i])
        if side > 0:
            stop = sl_ext - atr_pad * atr_now
            risk = entry_price - stop
        else:
            stop = sl_ext + atr_pad * atr_now
            risk = stop - entry_price
        if not np.isfinite(risk) or risk <= 0:
            continue
        if risk > 0.02 * entry_price:
            continue
        sig_rows.append({
            "entry_index": int(entry_idx), "side": int(side),
            "risk_units": float(risk), "stop_price": float(stop),
        })
    return pd.DataFrame(sig_rows) if sig_rows else pd.DataFrame(
        columns=["entry_index", "side", "risk_units", "stop_price"])


def simulate_fib(m5: pd.DataFrame, sigs: pd.DataFrame, *, tp_mult: float,
                 horizon_bars: int = 288, cost_usd: float = COST_USD) -> pd.DataFrame:
    """Bracket walker with stop_price from sigs (NOT default risk-units stop)."""
    op = m5["open"].values; cl = m5["close"].values
    ts = m5["timestamp"].values; yr = m5["year"].values
    n = len(m5)
    outs = []
    for sig in sigs.itertuples(index=False):
        i = int(sig.entry_index); side = int(sig.side)
        risk = float(sig.risk_units); stop = float(sig.stop_price)
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
    h1 = resample(m1, "1h"); h1 = build_h1_features(h1)
    m5_f = add_m5_swings_and_atr(m5)
    if "ny_hr" not in m5_f.columns:
        m5_f["ny_hr"] = m5_f["timestamp"].dt.tz_convert("America/New_York").dt.hour

    all_rows = []

    if args.phase == "1":
        print("\n=== Phase 1: coarse sweep ===\n")
        grid = []
        for pivot_lb in [3, 5]:
            for impulse_atr_min in [1.0, 2.0]:
                grid.append((pivot_lb, impulse_atr_min))
        for pivot_lb, impulse_atr_min in grid:
            print(f"  building impulses lb={pivot_lb} imp_atr={impulse_atr_min}...")
            impulses = build_impulses(h1, pivot_lb, impulse_atr_min)
            print(f"  impulses: {len(impulses)}")
            if len(impulses) == 0: continue
            for direction in ["long", "short"]:
                for fib in [0.382, 0.5, 0.618, 0.786]:
                    for tol in [0.2]:
                        for wait in [24, 72]:
                            for sess_name in ["all", "london_ny"]:
                                for atr_pad in [0.5]:
                                    sigs = gen_signals_fast(m5_f, impulses,
                                        direction=direction, fib_level=fib,
                                        tol_atr=tol, max_wait_h=wait,
                                        session=sess_name, atr_pad=atr_pad)
                                    if len(sigs) == 0: continue
                                    for tp in [2.0, 3.0, 4.0]:
                                        trades = simulate_fib(m5_f, sigs, tp_mult=tp)
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
                                                persist("fib_retrace", label, trades,
                                                        notes="Fib phase1")

    else:
        print("\n=== Phase 2: deep grid ===\n")
        for pivot_lb in [3, 5, 8]:
            for impulse_atr_min in [1.0, 1.5, 2.0, 3.0]:
                print(f"  building impulses lb={pivot_lb} imp_atr={impulse_atr_min}...")
                impulses = build_impulses(h1, pivot_lb, impulse_atr_min)
                if len(impulses) == 0: continue
                for direction in ["long", "short"]:
                    for fib in [0.382, 0.5, 0.618, 0.786]:
                        for tol in [0.1, 0.3, 0.5]:
                            for wait in [12, 24, 48, 72]:
                                for sess_name in ["all", "london", "ny", "london_ny", "overlap"]:
                                    for atr_pad in [0.3, 0.5, 1.0]:
                                        sigs = gen_signals_fast(m5_f, impulses,
                                            direction=direction, fib_level=fib,
                                            tol_atr=tol, max_wait_h=wait,
                                            session=sess_name, atr_pad=atr_pad)
                                        if len(sigs) == 0: continue
                                        for tp in [2.0, 3.0, 4.0]:
                                            trades = simulate_fib(m5_f, sigs, tp_mult=tp)
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
                                                    persist("fib_retrace", label, trades,
                                                            notes="Fib phase2")

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
