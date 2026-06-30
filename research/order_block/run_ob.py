"""Order Block (OB) pattern family.

Definition:
- Bullish OB: last bearish candle BEFORE a strong upward impulse (≥1.5 ATR rise in next 3 bars).
  Mitigation = price returns to this OB zone (high/low of bearish candle) → buy on retest.
- Bearish OB mirror.

Causal: detect OB only AFTER impulse confirms (so we know it was last opposite candle before impulse).
Then track future bars for retest.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd

from research.harness.causal_sim import load_data, simulate, headline, print_headline, persist


def detect_ob_on_m15() -> list[dict]:
    """Detect OBs on M15. Return list with m15_idx_ob, side, top, bot, impulse_ts."""
    m1, m5, m15 = load_data()
    obs = []
    closes = m15["close"].values
    opens = m15["open"].values
    highs = m15["high"].values
    lows = m15["low"].values
    atr = m15["atr14"].values
    n = len(m15)

    for i in range(20, n - 3):
        # Check if bars i+1..i+3 form a strong UP impulse: cumulative move >= 1.5 ATR
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        move_up = closes[i+3] - opens[i+1]
        if move_up >= 1.5 * atr[i]:
            # Bar i must be bearish (closed < opened)
            if closes[i] < opens[i]:
                obs.append({
                    "m15_idx_ob": i,  # bar index of the OB itself
                    "side": 1,
                    "top": float(highs[i]),
                    "bot": float(lows[i]),
                    "confirmed_idx": i + 3,  # OB is "confirmed" after this impulse bar closes
                    "ob_ts": m15["timestamp"].iloc[i],
                })
        move_dn = opens[i+1] - closes[i+3]
        if move_dn >= 1.5 * atr[i]:
            if closes[i] > opens[i]:
                obs.append({
                    "m15_idx_ob": i,
                    "side": -1,
                    "top": float(highs[i]),
                    "bot": float(lows[i]),
                    "confirmed_idx": i + 3,
                    "ob_ts": m15["timestamp"].iloc[i],
                })
    return obs


def run_ob_retest() -> None:
    m1, m5, m15 = load_data()
    obs = detect_ob_on_m15()
    print(f"M15 OBs detected: {len(obs)}")

    # Map confirmed timestamp to M5 grid
    m5_ts_to_idx = pd.Series(range(len(m5)), index=m5["timestamp"]).to_dict()

    # For each OB, scan M5 bars from confirmed_ts forward for retest (price enters [bot, top])
    expiry_bars_m5 = 96 * 2  # 16h
    signals = []
    high = m5["high"].values
    low = m5["low"].values
    atr_lag = m5["atr14_lag"].values

    for ob in obs:
        confirmed_ts = m15["timestamp"].iloc[ob["confirmed_idx"]]
        # find first M5 bar at or after this ts
        # use searchsorted
        start = m5["timestamp"].searchsorted(confirmed_ts, side="right")
        end = min(len(m5), start + expiry_bars_m5)
        for i in range(start, end):
            if ob["side"] == 1:
                if low[i] <= ob["top"] and high[i] >= ob["bot"]:
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        signals.append({"entry_index": i + 1, "side": 1, "risk_units": float(risk)})
                    break
            else:
                if high[i] >= ob["bot"] and low[i] <= ob["top"]:
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        signals.append({"entry_index": i + 1, "side": -1, "risk_units": float(risk)})
                    break

    sig = pd.DataFrame(signals)
    print(f"OB retest signals: {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        h = headline(t)
        print_headline(f"OB retest TP={tp}R", h)
        persist("order_block", f"m15_retest_tp{tp}", t,
                notes=f"M15 OB (1.5 ATR impulse), retest on M5, expiry 192 bars, TP={tp}R")

    # Trend-filtered variant
    sig2 = []
    for ob in obs:
        confirmed_ts = m15["timestamp"].iloc[ob["confirmed_idx"]]
        start = m5["timestamp"].searchsorted(confirmed_ts, side="right")
        end = min(len(m5), start + expiry_bars_m5)
        for i in range(start, end):
            if ob["side"] == 1:
                if low[i] <= ob["top"] and high[i] >= ob["bot"]:
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        # require prior M15 EMA20 > EMA50 (uptrend)
                        ema20 = m5["ema20_lag"].iloc[i]
                        ema50 = m5["ema50_lag"].iloc[i]
                        if ema20 > ema50:
                            sig2.append({"entry_index": i + 1, "side": 1, "risk_units": float(risk)})
                    break
            else:
                if high[i] >= ob["bot"] and low[i] <= ob["top"]:
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        ema20 = m5["ema20_lag"].iloc[i]
                        ema50 = m5["ema50_lag"].iloc[i]
                        if ema20 < ema50:
                            sig2.append({"entry_index": i + 1, "side": -1, "risk_units": float(risk)})
                    break
    s2 = pd.DataFrame(sig2)
    print(f"OB retest + trend signals: {len(s2)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(s2, m5, tp_mult=tp)
        h = headline(t)
        print_headline(f"OB retest+trend TP={tp}R", h)
        persist("order_block", f"m15_retest_trend_tp{tp}", t,
                notes=f"M15 OB + trend filter, TP={tp}R")


if __name__ == "__main__":
    print("=" * 100)
    print("ORDER BLOCK FAMILY")
    print("=" * 100)
    run_ob_retest()
