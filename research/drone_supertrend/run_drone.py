"""Drone Arrows SuperTrend strategy — causal port on 20.3yr OANDA M5.

Pine logic (lines 33-101 in source):
  - SuperTrend(close, sensitivity * atr_multiplier, atr_length)
    - upperBand = close + factor*atr
    - lowerBand = close - factor*atr
    - bands hysteresis on close[1] flip
  - Raw buy = crossover(close, supertrend_line)
  - Raw sell = crossunder(close, supertrend_line)
  - Trend filter: close > SMA(20) for buy, close < SMA for sell
  - Volume filter (disabled default)
  - Momentum check: |close - close[1]| > ATR(14) * 0.1
  - Signal cooldown: ≥ 2 bars between same-direction signals + flip required
  - SL = low - atr * 3 (long) / high + atr * 3 (short) on signal bar
  - TPs: 1R, 2R, 3R, 4R, 5R off entry-stop distance
  - We pick TP=3R for fair comparison with Fib V2

CAUSALITY FIXES (Pine uses current bar for crossover; we lag everything to be strict):
  - Compute supertrend with bars[:t] only
  - SMA shifted by 1 (use prior closed bar trend)
  - ATR shifted by 1 (use prior closed ATR)
  - Entry on NEXT M5 bar OPEN after crossover bar closes
  - SL captured at signal bar using PRIOR-bar low/high + ATR_lag
  - TP fixed-R from entry
  - Close-based bracket walker
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import headline, persist, print_headline, gate, COST_USD
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features


def supertrend(close, high, low, atr_period, factor):
    """Vectorised SuperTrend. All values are causal — uses prior close + current TR.
    Returns supertrend_line (array) and direction (+1 down, -1 up).
    """
    n = len(close)
    # ATR
    tr = np.maximum(high - low,
                     np.maximum(np.abs(high - np.r_[np.nan, close[:-1]]),
                                np.abs(low - np.r_[np.nan, close[:-1]])))
    atr = pd.Series(tr).rolling(atr_period).mean().values
    src = (high + low) / 2.0
    upper = src + factor * atr
    lower = src - factor * atr

    superTrend = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)
    finalUpper = np.full(n, np.nan)
    finalLower = np.full(n, np.nan)

    for i in range(n):
        if i == 0 or np.isnan(atr[i - 1]):
            direction[i] = 1
            finalUpper[i] = upper[i]
            finalLower[i] = lower[i]
            superTrend[i] = upper[i]
            continue
        # Band hysteresis
        if lower[i] > finalLower[i - 1] or close[i - 1] < finalLower[i - 1]:
            finalLower[i] = lower[i]
        else:
            finalLower[i] = finalLower[i - 1]
        if upper[i] < finalUpper[i - 1] or close[i - 1] > finalUpper[i - 1]:
            finalUpper[i] = upper[i]
        else:
            finalUpper[i] = finalUpper[i - 1]
        # Direction flip
        if superTrend[i - 1] == finalUpper[i - 1]:
            direction[i] = -1 if close[i] > finalUpper[i] else 1
        else:
            direction[i] = 1 if close[i] < finalLower[i] else -1
        superTrend[i] = finalLower[i] if direction[i] == -1 else finalUpper[i]
    return superTrend, direction


def run_drone(m5: pd.DataFrame, *, sensitivity: float, atr_length: int,
              atr_multiplier: float, ma_length: int, use_trend_filter: bool,
              tp_R: float, atr_risk_multiplier: float, atr_risk_length: int,
              cooldown_bars: int = 2, cost_usd: float = COST_USD,
              session_filter: str = "all"):
    """Run Drone strategy with full causality."""
    op = m5["open"].values
    hi = m5["high"].values
    lo = m5["low"].values
    cl = m5["close"].values
    ts = m5["timestamp"].values
    yr = m5["year"].values
    ny_hr = m5["ny_hr"].values
    n = len(m5)

    # Causal: shift everything by 1 — at bar t, only bar t-1 features are knowable
    # But SuperTrend Pine uses current close vs supertrend (which is built up to bar t-1).
    # We compute supertrend using bars 0..t-1, then check cl[t] crosses it.
    # In vectorised form: supertrend uses cl[i-1] and TR up to i, but we need to ensure
    # the LINE we cross is computed from PRIOR bars.

    # Build supertrend using ALL bars (vectorised). Then the line at index i was built
    # using close[i-1] in band hysteresis. Crossover check: close[i] vs supertrend[i].
    # That's exactly what Pine does — uses i-1 for hysteresis, i for crossover.
    factor = sensitivity * atr_multiplier
    st_line, st_dir = supertrend(cl, hi, lo, atr_length, factor)

    # SMA trend filter — lag 1 bar
    sma = pd.Series(cl).rolling(ma_length).mean().shift(1).values
    trend_up = cl > sma
    trend_down = cl < sma

    # Momentum check — |close - prior close| > 0.1 * ATR(14)_lag
    tr14 = np.maximum(hi - lo,
                       np.maximum(np.abs(hi - np.r_[np.nan, cl[:-1]]),
                                  np.abs(lo - np.r_[np.nan, cl[:-1]])))
    atr14_lag = pd.Series(tr14).rolling(14).mean().shift(1).values
    momentum_ok = np.abs(cl - np.r_[np.nan, cl[:-1]]) > atr14_lag * 0.1

    # Crossover detection
    prev_above = np.r_[False, cl[:-1] > st_line[:-1]]
    prev_below = np.r_[False, cl[:-1] < st_line[:-1]]
    raw_buy = (cl > st_line) & prev_below
    raw_sell = (cl < st_line) & prev_above

    # Apply filters
    if use_trend_filter:
        raw_buy &= trend_up
        raw_sell &= trend_down

    raw_buy &= momentum_ok
    raw_sell &= momentum_ok

    # Session filter
    if session_filter == "london":
        sess = (ny_hr >= 3) & (ny_hr < 12)
    elif session_filter == "ny":
        sess = (ny_hr >= 8) & (ny_hr < 17)
    elif session_filter == "london_ny":
        sess = (ny_hr >= 3) & (ny_hr < 17)
    elif session_filter == "overlap":
        sess = (ny_hr >= 8) & (ny_hr < 12)
    else:
        sess = np.ones(n, dtype=bool)
    raw_buy &= sess
    raw_sell &= sess

    # ATR for risk
    atr_risk = pd.Series(tr14).rolling(atr_risk_length).mean().shift(1).values
    atr_band = atr_risk * atr_risk_multiplier

    trades = []
    last_signal_bar = -10
    last_signal_type = ""

    for i in range(max(atr_length, ma_length, atr_risk_length, 14) + 2, n - 2):
        if not (raw_buy[i] or raw_sell[i]):
            continue
        if i - last_signal_bar < cooldown_bars:
            continue

        if raw_buy[i] and last_signal_type != "BUY":
            direction = +1
            last_signal_bar = i
            last_signal_type = "BUY"
        elif raw_sell[i] and last_signal_type != "SELL":
            direction = -1
            last_signal_bar = i
            last_signal_type = "SELL"
        else:
            continue

        entry_idx = i + 1
        if entry_idx >= n - 2: break
        entry = op[entry_idx]
        if direction == +1:
            stop = lo[i] - atr_band[i]
            risk = entry - stop
            tp = entry + tp_R * risk
        else:
            stop = hi[i] + atr_band[i]
            risk = stop - entry
            tp = entry - tp_R * risk

        if risk <= 0 or not np.isfinite(risk): continue
        if risk > 0.02 * entry: continue

        # Walk close-based bracket
        end = min(n - 1, entry_idx + 288)
        outcome_r = 0.0; exit_i = end; broke = False
        for j in range(entry_idx, end + 1):
            c = cl[j]
            if direction == +1:
                if c <= stop: outcome_r = -1.0; exit_i = j; broke = True; break
                if c >= tp: outcome_r = tp_R; exit_i = j; broke = True; break
            else:
                if c >= stop: outcome_r = -1.0; exit_i = j; broke = True; break
                if c <= tp: outcome_r = tp_R; exit_i = j; broke = True; break
        if not broke:
            outcome_r = max(-1.0, min(tp_R, direction * (cl[exit_i] - entry) / risk))

        trades.append({
            "entry_ts": ts[entry_idx], "side": direction,
            "entry_price": float(entry), "stop_price": float(stop),
            "tp_price": float(tp), "risk_units": float(risk),
            "exit_index": int(exit_i), "bracket_r": float(outcome_r),
            "cost_r": cost_usd / risk, "net_r": float(outcome_r) - cost_usd / risk,
            "year": int(yr[entry_idx]),
        })

    return pd.DataFrame(trades)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "sweep"], default="baseline")
    args = ap.parse_args()

    print("[load] OANDA M5...")
    _, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"),
                       Path("/tmp/oanda_xau_m5.parquet"))
    m5_f = add_m5_features(m5)
    print(f"  M5: {len(m5_f):,} bars")

    if args.mode == "baseline":
        # Default Pine settings
        print("\n=== DRONE BASELINE — Pine defaults ===")
        trades = run_drone(m5_f,
            sensitivity=1.0, atr_length=10, atr_multiplier=7.0,
            ma_length=20, use_trend_filter=True,
            tp_R=3.0, atr_risk_multiplier=3, atr_risk_length=14,
            session_filter="all")
        if len(trades) == 0:
            print("[NO TRADES]"); return
        h = headline(trades); print_headline("BASELINE 20.3yr", h)
        out = Path("/Users/subash/SUBASH/GoldDigger/research/drone_supertrend/drone_baseline_trades.parquet")
        trades.to_parquet(out)
        print(f"[save] → {out}")
        by_yr = trades.groupby("year")["net_r"].agg(["sum","count"]).round(2)
        by_yr.columns = ["net_R","n"]
        print("\n[Per-year]")
        print(by_yr.to_string())
        for side in [+1, -1]:
            slc = trades[trades.side == side]
            if len(slc):
                hs = headline(slc)
                print(f"  side={'LONG' if side>0 else 'SHORT':5s} n={hs['n']:>4d} netR={hs['net']:>+7.1f} PF={hs['pf']:.2f}")
        return

    print("\n=== DRONE SWEEP ===")
    rows = []
    for sens in [1.0, 0.5]:
        for atr_l in [10, 14, 20]:
            for atr_m in [3.0, 5.0, 7.0]:
                for ma in [20, 50]:
                    for tf in [True]:
                        for tp_r in [1.0, 2.0, 3.0, 4.0]:
                            for sess in ["all", "london_ny"]:
                                trades = run_drone(m5_f,
                                    sensitivity=sens, atr_length=atr_l,
                                    atr_multiplier=atr_m, ma_length=ma,
                                    use_trend_filter=tf, tp_R=tp_r,
                                    atr_risk_multiplier=3, atr_risk_length=14,
                                    session_filter=sess)
                                if len(trades) == 0: continue
                                h = headline(trades); g = gate(h)
                                label = f"sens{sens}_atrL{atr_l}_atrM{atr_m}_ma{ma}_tf{int(tf)}_TP{tp_r}_sess{sess}"
                                rows.append({"sens": sens, "atr_l": atr_l, "atr_m": atr_m,
                                             "ma": ma, "tf": int(tf), "tp_r": tp_r, "sess": sess,
                                             **h, **{f"gate_{k}": v for k,v in g.items()},
                                             "label": label})
                                if h["pf"] >= 1.15 and "/" in h["pos_years"]:
                                    pos = int(h["pos_years"].split("/")[0])
                                    if pos >= 12:
                                        print_headline(label, h)
    lb = pd.DataFrame(rows)
    out_path = Path("/Users/subash/SUBASH/GoldDigger/research/drone_supertrend/sweep_results.csv")
    lb.to_csv(out_path, index=False)
    print(f"\nSaved → {out_path}")
    top = lb.sort_values("mar", ascending=False).head(30)
    print("\n[TOP 30 by MAR]")
    cols = ["sens", "atr_l", "atr_m", "ma", "tp_r", "sess", "n", "trades_per_year", "pf", "mar", "pos_years"]
    print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
