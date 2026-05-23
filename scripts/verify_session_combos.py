"""
Verify session combo results — uses EXACT same fill model + signal logic as production.
Tests 3 combos:
  A) Asia → London (08:00-10:30) [BASELINE - should match our backtest]
  A3) Asia → Mid London (11:00-15:00)
  F) Asia → NY session (13:00-20:00)

All use:
- Same Asia range (00:00-08:00 UTC)
- Same daily bias filter
- Same M3 engulfing confirmation
- Same fill_model.py (TP touch, SL gap-through, break-even at 50%)
- Same slippage model
- Same $5000/year fresh capital, 4% risk

Run: python scripts/verify_session_combos.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Tuple

from backend.execution.fill_model import execute_trade
from backend.config import slippage

np.random.seed(42)

# ─── Config ──────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
YEARLY_CAPITAL = 5000.0
RISK_PCT = 4.0
MAX_UNITS = 100
ASIA_MIN_RANGE = 5.0
SWEEP_THRESHOLD = 2.0
SL_BUFFER = 0.30
MIN_SL = 5.0
TP_MULTIPLIER = 2.0
MAX_BARS = 80
ENGULFING_WINDOW_HOURS = 2

# Session combos to test
COMBOS = {
    "A) Asia→London (08-10:30)": {"scan_start": 8, "scan_end": 10.5},
    "A3) Asia→Mid London (11-15)": {"scan_start": 11, "scan_end": 15},
    "F) Asia→NY (13-20)": {"scan_start": 13, "scan_end": 20},
}


@dataclass
class Signal:
    date: pd.Timestamp
    direction: str
    entry: float
    sl: float
    tp: float
    risk: float
    max_bars: int


def load_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load XAU_USD H1, M3, and Daily data."""
    print("Loading data...")

    h1 = pd.read_csv(os.path.join(DATA_DIR, "XAU_USD_H1.csv"), parse_dates=["timestamp"])
    h1 = h1.sort_values("timestamp").reset_index(drop=True)

    m3 = pd.read_csv(os.path.join(DATA_DIR, "XAU_USD_M3.csv"), parse_dates=["timestamp"])
    m3 = m3.sort_values("timestamp").reset_index(drop=True)
    m3.set_index("timestamp", inplace=True)

    daily = pd.read_csv(os.path.join(DATA_DIR, "XAU_USD_D.csv"), parse_dates=["timestamp"])
    daily = daily.sort_values("timestamp").reset_index(drop=True)

    print(f"  H1: {len(h1)} bars, M3: {len(m3)} bars, Daily: {len(daily)} bars")
    return h1, m3, daily


def get_daily_bias(daily: pd.DataFrame, date) -> str:
    """Get bias from previous day's candle."""
    prev_days = daily[daily["timestamp"].dt.date < date]
    if len(prev_days) == 0:
        return "neutral"
    prev = prev_days.iloc[-1]
    mid_close = (prev["bid_close"] + prev["ask_close"]) / 2 if "bid_close" in prev else prev["close"]
    mid_open = (prev["bid_open"] + prev["ask_open"]) / 2 if "bid_open" in prev else prev["open"]
    return "bullish" if mid_close > mid_open else "bearish"


def find_signals(h1: pd.DataFrame, m3: pd.DataFrame, daily: pd.DataFrame,
                 scan_start: float, scan_end: float) -> List[Signal]:
    """Generate Alpha-Sweep signals for a given scan window."""
    signals = []
    dates = sorted(h1["timestamp"].dt.date.unique())

    for date in dates:
        # Asia bars (00:00-08:00 UTC)
        asia_bars = h1[(h1["timestamp"].dt.date == date) & (h1["timestamp"].dt.hour >= 0) & (h1["timestamp"].dt.hour < 8)]
        if len(asia_bars) < 3:
            continue

        if "bid_high" in asia_bars.columns:
            asia_high = ((asia_bars["bid_high"] + asia_bars["ask_high"]) / 2).max()
            asia_low = ((asia_bars["bid_low"] + asia_bars["ask_low"]) / 2).min()
        else:
            asia_high = asia_bars["high"].max()
            asia_low = asia_bars["low"].min()

        asia_range = asia_high - asia_low
        if asia_range < ASIA_MIN_RANGE:
            continue

        # Scan window bars
        scan_bars = h1[(h1["timestamp"].dt.date == date) &
                       (h1["timestamp"].dt.hour + h1["timestamp"].dt.minute / 60 >= scan_start) &
                       (h1["timestamp"].dt.hour + h1["timestamp"].dt.minute / 60 < scan_end)]
        if len(scan_bars) == 0:
            continue

        # Detect sweep
        sweep_dir = None
        sweep_wick = 0.0
        for _, bar in scan_bars.iterrows():
            if "bid_high" in bar:
                mid_high = (bar["bid_high"] + bar["ask_high"]) / 2
                mid_low = (bar["bid_low"] + bar["ask_low"]) / 2
                mid_close = (bar["bid_close"] + bar["ask_close"]) / 2
            else:
                mid_high, mid_low, mid_close = bar["high"], bar["low"], bar["close"]

            if mid_high > asia_high + SWEEP_THRESHOLD and mid_close < asia_high:
                sweep_dir = "bearish"
                sweep_wick = mid_high
                sweep_time = bar["timestamp"]
                break
            elif mid_low < asia_low - SWEEP_THRESHOLD and mid_close > asia_low:
                sweep_dir = "bullish"
                sweep_wick = mid_low
                sweep_time = bar["timestamp"]
                break

        if sweep_dir is None:
            continue

        # Daily bias check
        bias = get_daily_bias(daily, date)
        if sweep_dir == "bullish" and bias != "bullish":
            continue
        if sweep_dir == "bearish" and bias != "bearish":
            continue

        # Find M3 engulfing
        window_start = sweep_time
        window_end = sweep_time + timedelta(hours=ENGULFING_WINDOW_HOURS)

        m3_window = m3[(m3.index > window_start) & (m3.index <= window_end)]
        if len(m3_window) < 3:
            continue

        signal_found = False
        for j in range(2, len(m3_window)):
            c = m3_window.iloc[j]
            prev = m3_window.iloc[j - 1]

            if "bid_open" in c:
                co = (c["bid_open"] + c["ask_open"]) / 2
                cc = (c["bid_close"] + c["ask_close"]) / 2
                po = (prev["bid_open"] + prev["ask_open"]) / 2
                pc = (prev["bid_close"] + prev["ask_close"]) / 2
                br = (c["bid_high"] + c["ask_high"]) / 2 - (c["bid_low"] + c["ask_low"]) / 2
            else:
                co, cc = c["open"], c["close"]
                po, pc = prev["open"], prev["close"]
                br = c["high"] - c["low"]

            ct, cb = max(co, cc), min(co, cc)
            pt, pb = max(po, pc), min(po, pc)

            if sweep_dir == "bullish" and not (cc > co and cb <= pb and ct >= pt):
                continue
            if sweep_dir == "bearish" and not (cc < co and cb <= pb and ct >= pt):
                continue

            # Engulfing confirmed — compute entry/SL/TP
            # Use ASK for longs, BID for shorts (matches production exactly)
            if "ask_close" in c:
                ask_close = c["ask_close"]
                bid_close = c["bid_close"]
            else:
                ask_close = cc + 0.25  # approximate half-spread
                bid_close = cc - 0.25

            if sweep_dir == "bullish":
                entry = ask_close + slippage(br)
                sl = sweep_wick - SL_BUFFER
                risk = entry - sl
                if risk < MIN_SL:
                    sl = entry - MIN_SL
                    risk = MIN_SL
                if risk < 0.30 or risk > asia_range * 0.8:
                    continue
                tp = entry + asia_range * TP_MULTIPLIER
                if tp - entry < risk * 0.8:
                    continue
                direction = "long"
            else:
                entry = bid_close - slippage(br)
                sl = sweep_wick + SL_BUFFER
                risk = sl - entry
                if risk < MIN_SL:
                    sl = entry + MIN_SL
                    risk = MIN_SL
                if risk < 0.30 or risk > asia_range * 0.8:
                    continue
                tp = entry - asia_range * TP_MULTIPLIER
                if entry - tp < risk * 0.8:
                    continue
                direction = "short"

            signals.append(Signal(
                date=m3_window.index[j],
                direction=direction,
                entry=entry,
                sl=sl,
                tp=tp,
                risk=risk,
                max_bars=MAX_BARS,
            ))
            signal_found = True
            break  # One signal per day

    return signals


def run_backtest(signals: List[Signal], m3: pd.DataFrame) -> dict:
    """Run backtest using production fill model."""
    if not signals:
        return {"trades": 0, "wr": 0, "pf": 0, "pnl": 0, "dd": 0, "lose_yrs": 0}

    trades = []
    equity = YEARLY_CAPITAL
    peak_equity = equity
    max_dd = 0
    current_year = signals[0].date.year
    yearly_pnl = {}

    for signal in signals:
        trade_year = signal.date.year
        if trade_year != current_year:
            yearly_pnl[current_year] = equity - YEARLY_CAPITAL
            equity = YEARLY_CAPITAL
            peak_equity = equity
            current_year = trade_year

        # Position sizing
        risk_dollar = equity * (RISK_PCT / 100)
        units = min(risk_dollar / signal.risk, MAX_UNITS)
        if units < 1:
            continue

        # Execute trade using production fill model
        try:
            bar_idx = m3.index.get_loc(signal.date)
        except KeyError:
            continue

        result = execute_trade(
            df=m3,
            bar_start=bar_idx,
            entry=signal.entry,
            sl=signal.sl,
            tp=signal.tp,
            direction=signal.direction,
            max_bars=signal.max_bars,
            strategy="alpha_sweep",
            use_break_even=True,
        )

        if result is None:
            continue

        pnl = result.pnl_per_unit * units
        equity += pnl

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        if dd > max_dd:
            max_dd = dd

        trades.append({"pnl": pnl, "year": trade_year})

    # Final year
    yearly_pnl[current_year] = equity - YEARLY_CAPITAL

    # Stats
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = len(trades) - wins
    total_pnl = sum(t["pnl"] for t in trades)
    avg_win = np.mean([t["pnl"] for t in trades if t["pnl"] > 0]) if wins > 0 else 0
    avg_loss = abs(np.mean([t["pnl"] for t in trades if t["pnl"] <= 0])) if losses > 0 else 1
    pf = (avg_win * wins) / (avg_loss * losses) if losses > 0 else 99
    wr = wins / len(trades) if trades else 0
    years = len(yearly_pnl)
    lose_yrs = sum(1 for v in yearly_pnl.values() if v < 0)
    pnl_per_yr = total_pnl / years if years > 0 else 0

    return {
        "trades": len(trades),
        "wr": wr,
        "pf": pf,
        "pnl": total_pnl,
        "pnl_per_yr": pnl_per_yr,
        "dd": max_dd,
        "lose_yrs": lose_yrs,
        "years": years,
    }


def main():
    h1, m3, daily = load_data()

    print("\n" + "=" * 90)
    print(f"{'SESSION COMBO':<35} {'TRADES':>7} {'WR':>7} {'PF':>7} {'$/yr':>10} {'DD':>7} {'Lose':>5}")
    print("=" * 90)

    for name, config in COMBOS.items():
        np.random.seed(42)  # Reset seed for each combo (deterministic slippage)
        signals = find_signals(h1, m3, daily, config["scan_start"], config["scan_end"])
        result = run_backtest(signals, m3)

        print(f"{name:<35} {result['trades']:>7} {result['wr']:>6.1%} {result['pf']:>7.2f} "
              f"{result['pnl_per_yr']:>+10,.0f} {result['dd']:>6.1%} {result['lose_yrs']:>3}/{result['years']}")

    print("=" * 90)
    print("\nNote: Uses EXACT same fill_model.py, slippage, and parameters as production.")
    print("If numbers differ significantly from claims, the claims are wrong.")


if __name__ == "__main__":
    main()
