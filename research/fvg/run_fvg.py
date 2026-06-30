"""FVG (Fair Value Gap) pattern family.

Definition: 3-bar imbalance.
- Bullish FVG: bar1.high < bar3.low  → gap between bars 1 high and 3 low (price moved up fast)
- Bearish FVG: bar1.low  > bar3.high → gap between bars 1 low  and 3 high

Trading variants:
1. FVG_RETEST: wait for price to retest the gap zone, enter in original direction
2. FVG_FADE:   when price enters the gap, fade it (counter-trend)
3. FVG_BREAK:  trade in direction of FVG as soon as bar3 closes (continuation)

Causal: all three bars must be CLOSED before signal. Detection on prior 3 bars, entry on bar N+1 open.

Run on M5 and M15. Different TP multipliers. Trend filter (prior M15 EMA20 vs EMA50).
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import pandas as pd
import numpy as np

from research.harness.causal_sim import load_data, simulate, print_headline, persist


def detect_fvgs(bars: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame with FVG flags + bounds, indexed to bar3 (the bar AFTER which FVG is confirmed)."""
    out = bars.copy()
    out["bar1_high"] = out["high"].shift(2)
    out["bar1_low"] = out["low"].shift(2)
    out["bar3_high"] = out["high"]
    out["bar3_low"] = out["low"]
    # Bullish FVG: bar1.high < bar3.low — gap between them is unfilled
    out["bull_fvg"] = out["bar1_high"] < out["bar3_low"]
    out["bear_fvg"] = out["bar1_low"] > out["bar3_high"]
    out["fvg_top"] = np.where(out["bull_fvg"], out["bar3_low"], np.where(out["bear_fvg"], out["bar1_low"], np.nan))
    out["fvg_bot"] = np.where(out["bull_fvg"], out["bar1_high"], np.where(out["bear_fvg"], out["bar3_high"], np.nan))
    return out


def run_m5_fvg_break() -> None:
    """Pattern: M5 FVG break continuation. Enter at bar N+1 open in FVG direction."""
    m1, m5, m15 = load_data()
    m5f = detect_fvgs(m5)
    print(f"M5 FVG counts — bullish: {m5f['bull_fvg'].sum()}  bearish: {m5f['bear_fvg'].sum()}")

    # Signal at bar N's close (= start of bar N+1) — entry at bar N+1 open
    # entry_index = current bar index + 1 in the m5 frame
    signals = []
    for i, row in m5f.iterrows():
        if not (row["bull_fvg"] or row["bear_fvg"]):
            continue
        side = 1 if row["bull_fvg"] else -1
        risk = float(row["atr14_lag"])
        if not np.isfinite(risk) or risk <= 0:
            continue
        signals.append({"entry_index": i + 1, "side": side, "risk_units": risk})
    sig = pd.DataFrame(signals)
    print(f"M5 FVG break signals: {len(sig)}")

    for tp in [1.0, 1.5, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        from research.harness.causal_sim import headline
        h = headline(t)
        print_headline(f"M5 FVG break TP={tp}R", h)
        persist("fvg", f"m5_break_tp{tp}", t,
                notes=f"M5 FVG break continuation, TP={tp}R, no filter")

    # Trend-filtered variant (long FVGs only when prior M15 EMA20>EMA50)
    sig2 = []
    for i, row in m5f.iterrows():
        if not (row["bull_fvg"] or row["bear_fvg"]):
            continue
        risk = float(row["atr14_lag"])
        if not np.isfinite(risk) or risk <= 0:
            continue
        uptrend = row["ema20_lag"] > row["ema50_lag"]
        dntrend = row["ema20_lag"] < row["ema50_lag"]
        if row["bull_fvg"] and uptrend:
            sig2.append({"entry_index": i + 1, "side": 1, "risk_units": risk})
        elif row["bear_fvg"] and dntrend:
            sig2.append({"entry_index": i + 1, "side": -1, "risk_units": risk})
    sig2 = pd.DataFrame(sig2)
    print(f"M5 FVG trend-aligned signals: {len(sig2)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig2, m5, tp_mult=tp)
        from research.harness.causal_sim import headline
        h = headline(t)
        print_headline(f"M5 FVG trend TP={tp}R", h)
        persist("fvg", f"m5_break_trend_tp{tp}", t,
                notes=f"M5 FVG break + trend filter, TP={tp}R")


def run_m5_fvg_retest() -> None:
    """Pattern: FVG forms, then price returns into the gap zone within N bars → trade in original direction.
    Causal: gap formed (3 closed bars). Price ENTERS gap on later bar. Enter on next bar after touch.
    """
    m1, m5, m15 = load_data()
    m5f = detect_fvgs(m5)
    print(f"M5 FVG retest scanning...")

    # Track active FVGs with expiry (e.g. 48 bars = 4h)
    fvg_active = []  # list of dicts with idx_formed, side, top, bot, expiry
    signals = []
    expiry_bars = 48
    high = m5f["high"].values
    low = m5f["low"].values
    bull = m5f["bull_fvg"].values
    bear = m5f["bear_fvg"].values
    top = m5f["fvg_top"].values
    bot = m5f["fvg_bot"].values
    atr_lag = m5f["atr14_lag"].values

    for i in range(len(m5f)):
        # Expire old FVGs
        fvg_active = [f for f in fvg_active if (i - f["idx"]) <= expiry_bars]
        # Check if price retested any active FVG on this bar
        for f in list(fvg_active):
            if f["touched"]:
                continue
            if f["side"] == 1:
                # bullish FVG retest: price low entered the zone [bot, top]
                if low[i] <= f["top"] and high[i] >= f["bot"]:
                    f["touched"] = True
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        signals.append({"entry_index": i + 1, "side": 1, "risk_units": float(risk)})
            else:
                if high[i] >= f["bot"] and low[i] <= f["top"]:
                    f["touched"] = True
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        signals.append({"entry_index": i + 1, "side": -1, "risk_units": float(risk)})
        # Register any NEW FVG forming on this bar (causal — uses bars i-2, i-1, i which are now all closed)
        if bull[i]:
            fvg_active.append({"idx": i, "side": 1, "top": top[i], "bot": bot[i], "touched": False})
        elif bear[i]:
            fvg_active.append({"idx": i, "side": -1, "top": top[i], "bot": bot[i], "touched": False})

    sig = pd.DataFrame(signals)
    print(f"M5 FVG retest signals: {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        from research.harness.causal_sim import headline
        h = headline(t)
        print_headline(f"M5 FVG retest TP={tp}R", h)
        persist("fvg", f"m5_retest_tp{tp}", t,
                notes=f"M5 FVG retest entry, expiry 48 bars, TP={tp}R")


def run_m15_fvg_retest() -> None:
    """Pattern: M15 FVG forms, then retest → trade. Bigger signals, less noise."""
    m1, m5, m15 = load_data()
    # Build M15 FVG (uses M15 OHLC, lagged)
    m15f = m15.copy()
    m15f["bar1_high"] = m15f["high_lag"].shift(2)
    m15f["bar1_low"] = m15f["low_lag"].shift(2)
    # Wait — high_lag is already shifted by 1. For 3-bar pattern we need bars at positions i-2, i-1, i
    # m15['high'] is bar i. m15['high'].shift(1) is bar i-1. m15['high'].shift(2) is bar i-2.
    m15f["b1h"] = m15["high"].shift(3)  # bar i-3 (oldest closed)
    m15f["b1l"] = m15["low"].shift(3)
    m15f["b3h"] = m15["high"].shift(1)  # bar i-1 (most recent closed)
    m15f["b3l"] = m15["low"].shift(1)
    m15f["bull_fvg"] = m15f["b1h"] < m15f["b3l"]
    m15f["bear_fvg"] = m15f["b1l"] > m15f["b3h"]
    m15f["fvg_top"] = np.where(m15f["bull_fvg"], m15f["b3l"], np.where(m15f["bear_fvg"], m15f["b1l"], np.nan))
    m15f["fvg_bot"] = np.where(m15f["bull_fvg"], m15f["b1h"], np.where(m15f["bear_fvg"], m15f["b3h"], np.nan))
    print(f"M15 FVG counts — bullish: {m15f['bull_fvg'].sum()}  bearish: {m15f['bear_fvg'].sum()}")

    # For retest: track active FVGs from M15 frame, check M5 bars for retest
    m5_idx_map = m5.reset_index().set_index("timestamp")["index"]
    fvg_list = []
    for _, row in m15f[m15f["bull_fvg"] | m15f["bear_fvg"]].iterrows():
        side = 1 if row["bull_fvg"] else -1
        ts = row["timestamp"]  # this M15 bar's open time
        if ts not in m5_idx_map.index:
            continue
        idx_m5 = int(m5_idx_map.loc[ts])
        fvg_list.append({
            "m5_idx": idx_m5, "side": side,
            "top": row["fvg_top"], "bot": row["fvg_bot"],
        })
    print(f"M15 FVGs mapped to M5: {len(fvg_list)}")

    # Now scan M5 bars looking for retest of each FVG, expiry 96 M5 bars (8h)
    signals = []
    high = m5["high"].values
    low = m5["low"].values
    atr_lag = m5["atr14_lag"].values
    expiry = 96
    for f in fvg_list:
        start = f["m5_idx"] + 1
        end = min(len(m5), start + expiry)
        for i in range(start, end):
            if f["side"] == 1:
                if low[i] <= f["top"] and high[i] >= f["bot"]:
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        signals.append({"entry_index": i + 1, "side": 1, "risk_units": float(risk)})
                    break
            else:
                if high[i] >= f["bot"] and low[i] <= f["top"]:
                    risk = atr_lag[i]
                    if np.isfinite(risk) and risk > 0:
                        signals.append({"entry_index": i + 1, "side": -1, "risk_units": float(risk)})
                    break

    sig = pd.DataFrame(signals)
    print(f"M15 FVG retest signals (on M5 grid): {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        from research.harness.causal_sim import headline
        h = headline(t)
        print_headline(f"M15 FVG retest TP={tp}R", h)
        persist("fvg", f"m15_retest_tp{tp}", t,
                notes=f"M15 FVG retest on M5 grid, expiry 96 bars, TP={tp}R")


if __name__ == "__main__":
    print("=" * 100)
    print("FVG FAMILY")
    print("=" * 100)
    run_m5_fvg_break()
    print()
    run_m5_fvg_retest()
    print()
    run_m15_fvg_retest()
