"""Tiger NY-evening sweep strategy — causal port on 20.3yr OANDA M5.

Strategy mechanics (literal from spec, with causality bugs FIXED):

  STEP 1. Window: 20:00 – 22:00 EST (NY evening session)
  STEP 2. Anchor at 19:55 EST: most recent 15M swing high/low CONFIRMED before 19:55.
          Swing = pivot left=2 right=2, confirmed at idx+2 close (NOT center-rolling).
  STEP 3. During 20:00–22:00: monitor M5 bars (proxy for 1M).
  STEP 4. Sweep: bar high > anchor_high (bearish setup) OR bar low < anchor_low (bullish).
  STEP 5. MSS (Market Structure Shift): bar CLOSE past prior 5-bar minor swing.
          - Bearish setup: M5 close < prior 5-bar minor swing low (using shift(1).rolling(5).min())
          - Bullish setup: M5 close > prior 5-bar minor swing high
  STEP 6. FVG + OB overlap:
          - FVG = 3-bar array confirmed at bar t (so we need bar t close before declaring FVG)
            Bearish FVG: high[t] < low[t-2]
            Bullish FVG: low[t] > high[t-2]
          - OB = last opposite-close candle before MSS displacement
            Bearish OB = last UP-close candle before bearish MSS
            Bullish OB = last DOWN-close candle before bullish MSS
          - Entry zone = intersection of FVG and OB, otherwise use whichever is valid
  STEP 7. LIMIT ORDER at entry edge.
          - SL = sweep extreme wick ± 0.50 USD buffer
          - TP = 1:2 RR (entry ± 2 * risk)
          - Fill = NEXT M5 bar that touches the limit price after limit is placed

CAUSALITY RULES (strict, NO shortcuts):
  - 15M swing detection: pivot[i] confirmed at i+2 bar close. Only usable from i+3.
  - 19:55 anchor: only swings whose CONFIRM_TS < 19:55 EST are valid.
  - 1M (M5 proxy) minor swing: shift(1).rolling(5) — never include current bar.
  - FVG bar t: declared only at bar t close, usable from t+1.
  - OB declared at MSS bar; can be SEARCHED BACKWARDS through closed bars only.
  - Entry = NEXT bar OPEN after limit fill condition met (or fill price = limit if open beyond limit).
  - Exit walked close-based using SL/TP bracket on subsequent M5 closes.
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
from research.fib_retrace.run_fib import detect_pivots
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features


def resample_m15(m5: pd.DataFrame) -> pd.DataFrame:
    df = m5.set_index("timestamp").resample("15min", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna().reset_index()
    return df


def detect_pivots_with_confirm(m15: pd.DataFrame, left: int = 2, right: int = 2) -> pd.DataFrame:
    """Return DataFrame[confirm_ts, type ('H'|'L'), price]. Confirm at idx+right."""
    highs = m15["high"].values
    lows = m15["low"].values
    ts = m15["timestamp"].values
    ph, pl = detect_pivots(highs, lows, right)  # uses left=right=N
    rows = []
    n = len(m15)
    for i in np.flatnonzero(ph):
        ci = i + right
        if ci >= n: continue
        rows.append({"confirm_ts": ts[ci], "type": "H", "price": float(highs[i])})
    for i in np.flatnonzero(pl):
        ci = i + right
        if ci >= n: continue
        rows.append({"confirm_ts": ts[ci], "type": "L", "price": float(lows[i])})
    df = pd.DataFrame(rows).sort_values("confirm_ts").reset_index(drop=True)
    return df


def run_tiger(m5: pd.DataFrame, m15_pivots: pd.DataFrame, *,
              window_start_et=(20, 0), window_end_et=(22, 0),
              anchor_time_et=(19, 55),
              minor_swing_lookback=5,
              sl_buffer_usd=0.50, rr=2.0,
              max_hold_bars=120,  # 10 hours on M5
              cost_usd=COST_USD):
    """Run Tiger strategy. Returns trades DataFrame."""
    # All times in UTC; convert anchor to UTC per-bar (handle DST)
    m5_et = m5["timestamp"].dt.tz_convert("America/New_York")
    m5_et_date = m5_et.dt.date
    m5_et_time = m5_et.dt.time
    m5_et_hr = m5_et.dt.hour
    m5_et_min = m5_et.dt.minute

    in_window = ((m5_et_hr > window_start_et[0]) |
                 ((m5_et_hr == window_start_et[0]) & (m5_et_min >= window_start_et[1]))) & \
                ((m5_et_hr < window_end_et[0]) |
                 ((m5_et_hr == window_end_et[0]) & (m5_et_min < window_end_et[1])))

    op = m5["open"].values; hi = m5["high"].values
    lo = m5["low"].values; cl = m5["close"].values
    ts = m5["timestamp"].values
    n = len(m5)

    # Prior 5-bar minor swing low/high (shift(1).rolling(5)) — strict causal
    minor_low = m5["low"].shift(1).rolling(minor_swing_lookback).min().values
    minor_high = m5["high"].shift(1).rolling(minor_swing_lookback).max().values

    # Group by NY date
    m5_with_date = pd.DataFrame({
        "idx": np.arange(n), "et_date": m5_et_date.values,
        "et_hr": m5_et_hr.values, "et_min": m5_et_min.values,
        "in_window": in_window.values,
    })

    # M15 pivot lookup
    piv_ts = m15_pivots["confirm_ts"].values
    piv_type = m15_pivots["type"].values
    piv_price = m15_pivots["price"].values

    trades = []

    # Iterate per NY date
    for date_val, day_df in m5_with_date.groupby("et_date"):
        # Find anchor cutoff time = ts where ET = 19:55 on this date
        anchor_mask = day_df["in_window"].values
        if not anchor_mask.any():
            continue
        # First in-window M5 bar
        win_bars = day_df[day_df["in_window"]]
        first_win_idx = int(win_bars.iloc[0]["idx"])
        last_win_idx = int(win_bars.iloc[-1]["idx"])
        anchor_ts_utc = ts[first_win_idx]  # 20:00 EST mapped to UTC

        # CAUSAL FIX: Pivot confirm_ts is the left-label of confirmation bar.
        # That bar CLOSES at confirm_ts + 15min. To be knowable at 19:55 EST,
        # bar_close <= 19:55 → confirm_ts <= 19:40 → confirm_ts <= anchor_ts - 20min.
        # We use -30min for extra strict (require bar closed by 19:30).
        causal_cutoff = anchor_ts_utc - np.timedelta64(30, "m")
        valid_piv = piv_ts < causal_cutoff
        if not valid_piv.any():
            continue
        idx_valid = np.flatnonzero(valid_piv)
        # Latest H
        latest_h_idx = -1
        latest_l_idx = -1
        for i in idx_valid[::-1]:
            if piv_type[i] == "H" and latest_h_idx < 0:
                latest_h_idx = i
            if piv_type[i] == "L" and latest_l_idx < 0:
                latest_l_idx = i
            if latest_h_idx >= 0 and latest_l_idx >= 0:
                break
        if latest_h_idx < 0 or latest_l_idx < 0:
            continue
        anchor_high = piv_price[latest_h_idx]
        anchor_low = piv_price[latest_l_idx]
        if not np.isfinite(anchor_high) or not np.isfinite(anchor_low):
            continue
        if anchor_high <= anchor_low:
            continue

        # State per day
        swept_high = False
        swept_low = False
        sweep_extreme = np.nan
        mss_formed = False
        mss_idx = -1
        direction = 0
        execution_zone = None  # tuple (top, bottom)
        entered = False

        for k in range(first_win_idx, min(last_win_idx + 1, n - 2)):
            if entered: break
            c_hi = hi[k]; c_lo = lo[k]; c_cl = cl[k]; c_op = op[k]

            # Detect sweep
            if not swept_high and not swept_low:
                if c_hi > anchor_high:
                    swept_high = True
                    direction = -1  # bearish setup expected
                    sweep_extreme = c_hi
                    continue
                if c_lo < anchor_low:
                    swept_low = True
                    direction = +1
                    sweep_extreme = c_lo
                    continue
            else:
                # Update sweep extreme until MSS forms
                if not mss_formed:
                    if direction == -1 and c_hi > sweep_extreme:
                        sweep_extreme = c_hi
                    elif direction == +1 and c_lo < sweep_extreme:
                        sweep_extreme = c_lo

            # MSS detection
            if (swept_high or swept_low) and not mss_formed:
                if direction == -1:
                    swing_low_now = minor_low[k]
                    if np.isfinite(swing_low_now) and c_cl < swing_low_now:
                        mss_formed = True
                        mss_idx = k
                elif direction == +1:
                    swing_high_now = minor_high[k]
                    if np.isfinite(swing_high_now) and c_cl > swing_high_now:
                        mss_formed = True
                        mss_idx = k

            # Compute execution_zone AFTER MSS
            if mss_formed and execution_zone is None:
                # FVG check (3-bar array using bars [mss-2, mss-1, mss])
                # Bearish FVG: high[mss] < low[mss-2]
                # Bullish FVG: low[mss] > high[mss-2]
                fvg_top = np.nan; fvg_bot = np.nan; has_fvg = False
                if mss_idx >= 2:
                    if direction == -1 and hi[mss_idx] < lo[mss_idx - 2]:
                        has_fvg = True
                        fvg_top = lo[mss_idx - 2]
                        fvg_bot = hi[mss_idx]
                    elif direction == +1 and lo[mss_idx] > hi[mss_idx - 2]:
                        has_fvg = True
                        fvg_top = lo[mss_idx]
                        fvg_bot = hi[mss_idx - 2]

                # OB: search backward from mss-1 for last opposite-close candle
                ob_top = np.nan; ob_bot = np.nan; has_ob = False
                for j in range(mss_idx - 1, max(-1, mss_idx - 30), -1):
                    if j < 0: break
                    if direction == -1:
                        # Bearish OB = last UP candle (close > open) before MSS
                        if cl[j] > op[j]:
                            ob_top = hi[j]; ob_bot = lo[j]; has_ob = True; break
                    else:
                        if cl[j] < op[j]:
                            ob_top = hi[j]; ob_bot = lo[j]; has_ob = True; break

                # Build execution zone
                if has_fvg and has_ob:
                    overlap_top = min(fvg_top, ob_top)
                    overlap_bot = max(fvg_bot, ob_bot)
                    if overlap_top > overlap_bot:
                        execution_zone = (overlap_top, overlap_bot)
                if execution_zone is None and has_fvg:
                    execution_zone = (fvg_top, fvg_bot)
                if execution_zone is None and has_ob:
                    execution_zone = (ob_top, ob_bot)
                if execution_zone is None:
                    entered = True  # abort day; no valid zone → no trade
                    continue

                # Place limit at PROXIMAL edge (closer to current price).
                # Bearish: price below zone rallying up → limit at BOTTOM of zone (fills first).
                # Bullish: price above zone dipping down → limit at TOP of zone.
                if direction == -1:
                    limit_price = execution_zone[1]  # bottom (proximal for bearish)
                    sl_price = sweep_extreme + sl_buffer_usd
                    risk = sl_price - limit_price
                    if risk <= 0 or not np.isfinite(risk):
                        entered = True; continue
                    if risk > 0.02 * limit_price:
                        entered = True; continue
                    tp_price = limit_price - rr * risk
                else:
                    limit_price = execution_zone[0]  # top (proximal for bullish)
                    sl_price = sweep_extreme - sl_buffer_usd
                    risk = limit_price - sl_price
                    if risk <= 0 or not np.isfinite(risk):
                        entered = True; continue
                    if risk > 0.02 * limit_price:
                        entered = True; continue
                    tp_price = limit_price + rr * risk

                # Track limit waiting from k+1 onwards
                fill_idx = -1
                for f in range(k + 1, min(n, k + 1 + max_hold_bars)):
                    if direction == -1 and hi[f] >= limit_price:
                        fill_idx = f; break
                    if direction == +1 and lo[f] <= limit_price:
                        fill_idx = f; break
                if fill_idx < 0:
                    entered = True  # no fill within window — day done
                    continue
                # Re-check fill is still inside the same day window
                fill_et = pd.Timestamp(ts[fill_idx]).tz_localize("UTC").tz_convert("America/New_York")
                if fill_et.date() != date_val:
                    # Fill crossed into next day — reject as setup expired
                    entered = True
                    continue
                # Entry price = limit (we hit limit precisely; intrabar fills are causal)
                # Account for gap: if open at fill bar is already past limit, fill at open (worse)
                if direction == -1 and op[fill_idx] > limit_price:
                    entry_price = op[fill_idx]
                    # Recompute risk after gap-fill
                    risk = sl_price - entry_price
                    if risk <= 0: continue
                    tp_price = entry_price - rr * risk
                elif direction == +1 and op[fill_idx] < limit_price:
                    entry_price = op[fill_idx]
                    risk = entry_price - sl_price
                    if risk <= 0: continue
                    tp_price = entry_price + rr * risk
                else:
                    entry_price = limit_price

                # Walk bracket forward from fill_idx using close-based stops
                end = min(n - 1, fill_idx + max_hold_bars)
                outcome_r = 0.0; exit_i = end; broke = False
                for j in range(fill_idx, end + 1):
                    c = cl[j]
                    if direction == +1:
                        if c <= sl_price: outcome_r = -1.0; exit_i = j; broke=True; break
                        if c >= tp_price: outcome_r = rr; exit_i = j; broke=True; break
                    else:
                        if c >= sl_price: outcome_r = -1.0; exit_i = j; broke=True; break
                        if c <= tp_price: outcome_r = rr; exit_i = j; broke=True; break
                if not broke:
                    outcome_r = max(-1.0, min(rr, direction * (cl[exit_i] - entry_price) / risk))

                trades.append({
                    "entry_ts": ts[fill_idx], "side": int(direction),
                    "entry_price": float(entry_price), "stop_price": float(sl_price),
                    "tp_price": float(tp_price), "risk_units": float(risk),
                    "exit_index": int(exit_i), "bracket_r": float(outcome_r),
                    "cost_r": cost_usd / risk,
                    "net_r": float(outcome_r) - cost_usd / risk,
                    "year": pd.Timestamp(ts[fill_idx]).year,
                    "sweep_extreme": float(sweep_extreme),
                    "anchor_high": float(anchor_high),
                    "anchor_low": float(anchor_low),
                    "fvg_used": bool(has_fvg),
                    "ob_used": bool(has_ob),
                })
                entered = True

    return pd.DataFrame(trades)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "sweep"], default="baseline")
    args = ap.parse_args()

    print("[load] OANDA M5...")
    _, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"),
                       Path("/tmp/oanda_xau_m5.parquet"))
    m5_f = add_m5_features(m5)
    print(f"  M5: {len(m5_f):,} bars range {m5_f.timestamp.min()} → {m5_f.timestamp.max()}")

    print("[build] M15 + pivots (left=2 right=2)...")
    m15 = resample_m15(m5_f)
    m15_pivots = detect_pivots_with_confirm(m15, left=2, right=2)
    print(f"  M15: {len(m15):,} bars   pivots: {len(m15_pivots):,}")

    if args.mode == "baseline":
        print("\n=== TIGER BASELINE — 19:55 EST anchor, 20:00-22:00 EST window, M5 proxy ===")
        trades = run_tiger(m5_f, m15_pivots,
                            window_start_et=(20, 0), window_end_et=(22, 0),
                            anchor_time_et=(19, 55),
                            minor_swing_lookback=5,
                            sl_buffer_usd=0.50, rr=2.0,
                            max_hold_bars=120)
        if len(trades) == 0:
            print("[NO TRADES]"); return
        h = headline(trades)
        print_headline("BASELINE 20.3yr", h)
        out = Path("/Users/subash/SUBASH/GoldDigger/research/tiger_sweep/tiger_baseline_trades.parquet")
        trades.to_parquet(out)
        print(f"[save] → {out}")

        # Per-year breakdown
        by_yr = trades.groupby("year")["net_r"].agg(["sum","count"]).round(2)
        by_yr.columns = ["net_R","n"]
        print("\n[Per-year]")
        print(by_yr.to_string())

        # Per side
        print("\n[Per side]")
        for side in [+1, -1]:
            slc = trades[trades.side == side]
            if len(slc):
                hs = headline(slc)
                print(f"  side={'LONG' if side>0 else 'SHORT':5s} n={hs['n']:>4d} netR={hs['net']:>+7.1f} PF={hs['pf']:.2f}")

        # FVG/OB usage
        print(f"\n[Entry-zone usage]")
        print(f"  has_FVG: {trades.fvg_used.sum()} / {len(trades)}")
        print(f"  has_OB:  {trades.ob_used.sum()} / {len(trades)}")
        print(f"  both:    {((trades.fvg_used) & (trades.ob_used)).sum()}")
        return

    if args.mode == "sweep":
        print("\n=== Tiger param sweep ===")
        rows = []
        for win_start_h in [19, 20]:
            for win_end_h in [22, 23]:
                if win_end_h <= win_start_h: continue
                for anchor_min in [(19, 55), (19, 45)]:
                    for minor_lb in [3, 5, 10]:
                        for sl_buf in [0.20, 0.50, 1.00]:
                            for rr in [1.5, 2.0, 3.0]:
                                trades = run_tiger(m5_f, m15_pivots,
                                    window_start_et=(win_start_h, 0),
                                    window_end_et=(win_end_h, 0),
                                    anchor_time_et=anchor_min,
                                    minor_swing_lookback=minor_lb,
                                    sl_buffer_usd=sl_buf, rr=rr,
                                    max_hold_bars=120)
                                if len(trades) == 0: continue
                                h = headline(trades); g = gate(h)
                                label = f"w{win_start_h}-{win_end_h}_anc{anchor_min[0]}:{anchor_min[1]}_ml{minor_lb}_sl{sl_buf}_RR{rr}"
                                rows.append({"win_start": win_start_h, "win_end": win_end_h,
                                              "anchor": f"{anchor_min[0]}:{anchor_min[1]}",
                                              "minor_lb": minor_lb, "sl_buf": sl_buf, "rr": rr,
                                              **h, **{f"gate_{k}": v for k,v in g.items()},
                                              "label": label})
                                if h["pf"] >= 1.2:
                                    print_headline(label, h)
        lb = pd.DataFrame(rows)
        out_path = Path("/Users/subash/SUBASH/GoldDigger/research/tiger_sweep/sweep_results.csv")
        lb.to_csv(out_path, index=False)
        print(f"\nSaved → {out_path}")
        top = lb.sort_values("mar", ascending=False).head(30)
        print("\n[TOP 30 by MAR]")
        cols = ["win_start","win_end","anchor","minor_lb","sl_buf","rr","n","trades_per_year","pf","mar","pos_years"]
        print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
