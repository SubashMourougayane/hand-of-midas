"""ICT pattern family.

1. LIQUIDITY SWEEP + REVERSAL (asian high/low sweep at London open then reverse)
2. BOS (Break of Structure): swing-high break then continuation OR retracement
3. EQUAL HIGHS / EQUAL LOWS magnet — price has tagged a level multiple times, expect break + return
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd

from research.harness.causal_sim import load_data, simulate, headline, print_headline, persist


def asian_range_per_day(m5: pd.DataFrame) -> pd.DataFrame:
    """For each NY date, compute Asian (NY 19:00 prior → NY 02:00) high/low.
    Returns DataFrame indexed by ny_date with asian_high/asian_low + close_ts (when Asian closes).
    """
    df = m5.copy()
    # Asian "owner" date: shift hour by +5 so 19:00 prev day becomes 00:00 next day → groups together
    ny_ts = df["timestamp"].dt.tz_convert("America/New_York")
    df["asian_owner_date"] = (ny_ts + pd.Timedelta(hours=5)).dt.date.astype(str)
    df["asian_in"] = df["ny_hr"].isin([19, 20, 21, 22, 23, 0, 1])
    asian = df[df["asian_in"]].groupby("asian_owner_date").agg(
        asian_high=("high", "max"),
        asian_low=("low", "min"),
        asian_n=("high", "count"),
        asian_close_ts=("timestamp", "max"),
    )
    asian = asian[asian["asian_n"] >= 8].reset_index()
    return asian


def run_liquidity_sweep_reversal() -> None:
    """Pattern: At London/NY open (NY hr 3-9), if price sweeps Asian high/low and CLOSES back inside,
    enter counter-direction.
    Causal: Asian range = data from previous 8h. Sweep = single bar pierces level then closes back.
    """
    m1, m5, m15 = load_data()
    asian = asian_range_per_day(m5)
    print(f"Asian range days: {len(asian)}")

    # Join asian range to every M5 bar via ny_date
    m5 = m5.merge(asian, left_on="ny_date", right_on="asian_owner_date", how="left")
    # Filter to London/NY window
    m5["in_sweep_window"] = m5["ny_hr"].between(3, 10)

    # Sweep detection: bar high > asian_high AND bar close < asian_high (failed break)
    m5["sweep_high"] = m5["in_sweep_window"] & (m5["high"] > m5["asian_high"]) & (m5["close"] < m5["asian_high"])
    m5["sweep_low"]  = m5["in_sweep_window"] & (m5["low"]  < m5["asian_low"])  & (m5["close"] > m5["asian_low"])

    # Take only FIRST sweep per day
    m5["first_sweep_high"] = m5["sweep_high"] & ~m5.groupby("ny_date")["sweep_high"].cumsum().shift(1).fillna(0).astype(bool)
    m5["first_sweep_low"]  = m5["sweep_low"]  & ~m5.groupby("ny_date")["sweep_low"].cumsum().shift(1).fillna(0).astype(bool)

    # Side: sweep_high → SHORT (reversal), sweep_low → LONG
    sig = []
    for i in m5.index[m5["first_sweep_high"] | m5["first_sweep_low"]]:
        row = m5.iloc[i]
        risk = float(row["atr14_lag"])
        if not np.isfinite(risk) or risk <= 0: continue
        side = -1 if row["first_sweep_high"] else 1
        sig.append({"entry_index": i + 1, "side": side, "risk_units": risk})
    sig = pd.DataFrame(sig)
    print(f"Asian sweep reversal signals: {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        h = headline(t)
        print_headline(f"ICT Asian sweep reversal TP={tp}R", h)
        persist("ict", f"asian_sweep_reversal_tp{tp}", t,
                notes=f"Asian sweep + reversal (fade), London/NY window, TP={tp}R")


def run_bos_continuation() -> None:
    """Break of Structure: prior closed M15 bar breaks the most recent swing-high (last 10 bars).
    Trade continuation (long).
    """
    m1, m5, m15 = load_data()
    # Compute swing high/low: rolling max/min of last N (excluding current bar)
    N = 10
    m15c = m15.copy()
    m15c["sw_high"] = m15["high"].rolling(N).max().shift(1)
    m15c["sw_low"]  = m15["low"].rolling(N).min().shift(1)
    m15c["bos_up"]   = m15["close"].shift(1) > m15c["sw_high"]
    m15c["bos_down"] = m15["close"].shift(1) < m15c["sw_low"]
    m15c["atr14_lag"] = m15["atr14"].shift(1)
    print(f"BOS up: {m15c['bos_up'].sum()}, down: {m15c['bos_down'].sum()}")

    m5_idx_map = pd.Series(range(len(m5)), index=m5["timestamp"]).to_dict()
    sig = []
    for _, row in m15c[m15c["bos_up"] | m15c["bos_down"]].iterrows():
        ts = row["timestamp"]
        if ts not in m5_idx_map: continue
        idx = m5_idx_map[ts]
        risk = float(row["atr14_lag"])
        if not np.isfinite(risk) or risk <= 0: continue
        side = 1 if row["bos_up"] else -1
        sig.append({"entry_index": idx, "side": side, "risk_units": risk})
    sig = pd.DataFrame(sig)
    print(f"BOS continuation signals: {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        h = headline(t)
        print_headline(f"BOS continuation TP={tp}R", h)
        persist("ict", f"bos_continuation_tp{tp}", t,
                notes=f"M15 BOS continuation (10-bar swing), TP={tp}R")


def run_bos_fade() -> None:
    m1, m5, m15 = load_data()
    N = 10
    m15c = m15.copy()
    m15c["sw_high"] = m15["high"].rolling(N).max().shift(1)
    m15c["sw_low"]  = m15["low"].rolling(N).min().shift(1)
    m15c["bos_up"]   = m15["close"].shift(1) > m15c["sw_high"]
    m15c["bos_down"] = m15["close"].shift(1) < m15c["sw_low"]
    m15c["atr14_lag"] = m15["atr14"].shift(1)
    m5_idx_map = pd.Series(range(len(m5)), index=m5["timestamp"]).to_dict()
    sig = []
    for _, row in m15c[m15c["bos_up"] | m15c["bos_down"]].iterrows():
        ts = row["timestamp"]
        if ts not in m5_idx_map: continue
        idx = m5_idx_map[ts]
        risk = float(row["atr14_lag"])
        if not np.isfinite(risk) or risk <= 0: continue
        # FADE: opposite direction
        side = -1 if row["bos_up"] else 1
        sig.append({"entry_index": idx, "side": side, "risk_units": risk})
    sig = pd.DataFrame(sig)
    print(f"BOS fade signals: {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        h = headline(t)
        print_headline(f"BOS fade TP={tp}R", h)
        persist("ict", f"bos_fade_tp{tp}", t,
                notes=f"M15 BOS fade (10-bar swing), TP={tp}R")


def run_equal_highs_lows() -> None:
    """Equal highs: 2+ M15 bars within 0.5*ATR of each other on highs, then break → fade.
    """
    m1, m5, m15 = load_data()
    m15c = m15.copy()
    # Look for prior 10 bars: how many highs are within 0.5*ATR of the max?
    m15c["atr_lag"] = m15["atr14"].shift(1)
    N = 10
    eqh_count = []
    eql_count = []
    for i in range(len(m15c)):
        if i < N or not np.isfinite(m15c["atr_lag"].iloc[i]):
            eqh_count.append(0); eql_count.append(0); continue
        window_h = m15["high"].iloc[i-N:i]
        window_l = m15["low"].iloc[i-N:i]
        mx = window_h.max(); mn = window_l.min()
        threshold = 0.5 * m15c["atr_lag"].iloc[i]
        eqh_count.append((window_h >= mx - threshold).sum())
        eql_count.append((window_l <= mn + threshold).sum())
    m15c["eqh_count"] = eqh_count
    m15c["eql_count"] = eql_count
    # Trigger: current bar high makes new high AND there were 2+ equal highs in last 10 bars
    m15c["high_l1"] = m15["high"].shift(1)
    m15c["low_l1"]  = m15["low"].shift(1)
    m15c["high_max_prior"] = m15["high"].rolling(N).max().shift(1)
    m15c["low_min_prior"]  = m15["low"].rolling(N).min().shift(1)
    m15c["eqh_break"] = (m15c["high_l1"] > m15c["high_max_prior"]) & (m15c["eqh_count"] >= 2)
    m15c["eql_break"] = (m15c["low_l1"] < m15c["low_min_prior"]) & (m15c["eql_count"] >= 2)
    print(f"Equal highs break: {m15c['eqh_break'].sum()}, equal lows: {m15c['eql_break'].sum()}")

    m5_idx_map = pd.Series(range(len(m5)), index=m5["timestamp"]).to_dict()
    sig = []
    for _, row in m15c[m15c["eqh_break"] | m15c["eql_break"]].iterrows():
        ts = row["timestamp"]
        if ts not in m5_idx_map: continue
        idx = m5_idx_map[ts]
        risk = float(row["atr_lag"])
        if not np.isfinite(risk) or risk <= 0: continue
        # FADE the break (liquidity grab → reversal)
        side = -1 if row["eqh_break"] else 1
        sig.append({"entry_index": idx, "side": side, "risk_units": risk})
    sig = pd.DataFrame(sig)
    print(f"Equal H/L liquidity grab signals: {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        h = headline(t)
        print_headline(f"Equal H/L grab+fade TP={tp}R", h)
        persist("ict", f"eq_hl_grab_fade_tp{tp}", t,
                notes=f"Equal highs/lows liquidity grab + fade, TP={tp}R")


if __name__ == "__main__":
    print("=" * 100)
    print("ICT FAMILY")
    print("=" * 100)
    run_liquidity_sweep_reversal()
    print()
    run_bos_continuation()
    print()
    run_bos_fade()
    print()
    run_equal_highs_lows()
