"""ORB causal — strict: ORB values only valid AFTER ORB window closes."""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd

from research.harness.causal_sim import load_data, simulate, headline, print_headline, persist


def compute_orb_daily(m5: pd.DataFrame, start_hr: int = 9, start_min: int = 30, duration_min: int = 30) -> pd.DataFrame:
    """ORB window = NY [start_hr:start_min, start_hr:start_min + duration_min].
    Returns per-day orb_high, orb_low, orb_close_ts.
    """
    end_min = (start_min + duration_min) % 60
    end_hr = start_hr + (start_min + duration_min) // 60
    win = m5[
        ((m5["ny_hr"] == start_hr) & (m5["ny_min"] >= start_min))
        | ((m5["ny_hr"] > start_hr) & (m5["ny_hr"] < end_hr))
        | ((m5["ny_hr"] == end_hr) & (m5["ny_min"] < end_min))
    ].copy()
    daily = win.groupby("ny_date").agg(
        orb_high=("high", "max"),
        orb_low=("low", "min"),
        orb_n=("high", "count"),
        orb_close_ts=("timestamp", "max"),
    )
    daily = daily[daily["orb_n"] >= duration_min // 5 - 1].reset_index()
    # ORB is "available" AFTER orb_close_ts (so add 5min = next M5 bar)
    daily["orb_available_from"] = daily["orb_close_ts"] + pd.Timedelta(minutes=5)
    return daily


def run_orb30_break_causal() -> None:
    """ORB30 break: after NY 10:00 (ORB30 just closed), if price breaks above ORB high → LONG.
    Strict causal: only trigger after NY hour >= 10.
    """
    m1, m5, m15 = load_data()
    orb = compute_orb_daily(m5, 9, 30, 30)
    print(f"ORB30 days: {len(orb)}")
    m5 = m5.merge(orb[["ny_date","orb_high","orb_low","orb_available_from"]], on="ny_date", how="left")

    # Trade window: NY 10:00 — 15:00 (only after ORB closes)
    m5["in_trade"] = (m5["timestamp"] >= m5["orb_available_from"]) & (m5["ny_hr"] < 16)
    m5["sig_long_break"]  = m5["in_trade"] & (m5["close"] > m5["orb_high"])
    m5["sig_short_break"] = m5["in_trade"] & (m5["close"] < m5["orb_low"])
    # First break per day
    m5["first_long"]  = m5["sig_long_break"]  & ~m5.groupby("ny_date")["sig_long_break"].cumsum().shift(1).fillna(0).astype(bool)
    m5["first_short"] = m5["sig_short_break"] & ~m5.groupby("ny_date")["sig_short_break"].cumsum().shift(1).fillna(0).astype(bool)

    sig = []
    for i in m5.index[m5["first_long"] | m5["first_short"]]:
        row = m5.iloc[i]
        risk = float(row["atr14_lag"])
        if not np.isfinite(risk) or risk <= 0: continue
        side = 1 if row["first_long"] else -1
        sig.append({"entry_index": i + 1, "side": side, "risk_units": risk})
    sig = pd.DataFrame(sig)
    print(f"ORB30 break signals: {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        h = headline(t)
        print_headline(f"ORB30 break TP={tp}R", h)
        persist("orb_causal", f"orb30_break_tp{tp}", t,
                notes=f"ORB30 (NY 9:30-10:00) break causal, NY 10-15 trade window, TP={tp}R")


def run_orb30_fade_causal() -> None:
    m1, m5, m15 = load_data()
    orb = compute_orb_daily(m5, 9, 30, 30)
    m5 = m5.merge(orb[["ny_date","orb_high","orb_low","orb_available_from"]], on="ny_date", how="left")
    m5["in_trade"] = (m5["timestamp"] >= m5["orb_available_from"]) & (m5["ny_hr"] < 16)
    m5["sig_long_break"]  = m5["in_trade"] & (m5["close"] > m5["orb_high"])
    m5["sig_short_break"] = m5["in_trade"] & (m5["close"] < m5["orb_low"])
    m5["first_long"]  = m5["sig_long_break"]  & ~m5.groupby("ny_date")["sig_long_break"].cumsum().shift(1).fillna(0).astype(bool)
    m5["first_short"] = m5["sig_short_break"] & ~m5.groupby("ny_date")["sig_short_break"].cumsum().shift(1).fillna(0).astype(bool)

    sig = []
    for i in m5.index[m5["first_long"] | m5["first_short"]]:
        row = m5.iloc[i]
        risk = float(row["atr14_lag"])
        if not np.isfinite(risk) or risk <= 0: continue
        side = -1 if row["first_long"] else 1   # FADE
        sig.append({"entry_index": i + 1, "side": side, "risk_units": risk})
    sig = pd.DataFrame(sig)
    print(f"ORB30 fade signals: {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        h = headline(t)
        print_headline(f"ORB30 fade TP={tp}R", h)
        persist("orb_causal", f"orb30_fade_tp{tp}", t,
                notes=f"ORB30 fade causal, TP={tp}R")


def run_orb60_break_causal() -> None:
    m1, m5, m15 = load_data()
    orb = compute_orb_daily(m5, 9, 30, 60)
    print(f"ORB60 days: {len(orb)}")
    m5 = m5.merge(orb[["ny_date","orb_high","orb_low","orb_available_from"]], on="ny_date", how="left")
    m5["in_trade"] = (m5["timestamp"] >= m5["orb_available_from"]) & (m5["ny_hr"] < 16)
    m5["sig_long_break"]  = m5["in_trade"] & (m5["close"] > m5["orb_high"])
    m5["sig_short_break"] = m5["in_trade"] & (m5["close"] < m5["orb_low"])
    m5["first_long"]  = m5["sig_long_break"]  & ~m5.groupby("ny_date")["sig_long_break"].cumsum().shift(1).fillna(0).astype(bool)
    m5["first_short"] = m5["sig_short_break"] & ~m5.groupby("ny_date")["sig_short_break"].cumsum().shift(1).fillna(0).astype(bool)
    sig = []
    for i in m5.index[m5["first_long"] | m5["first_short"]]:
        row = m5.iloc[i]
        risk = float(row["atr14_lag"])
        if not np.isfinite(risk) or risk <= 0: continue
        side = 1 if row["first_long"] else -1
        sig.append({"entry_index": i + 1, "side": side, "risk_units": risk})
    sig = pd.DataFrame(sig)
    print(f"ORB60 break signals: {len(sig)}")
    for tp in [1.0, 2.0, 3.0]:
        t = simulate(sig, m5, tp_mult=tp)
        h = headline(t)
        print_headline(f"ORB60 break TP={tp}R", h)
        persist("orb_causal", f"orb60_break_tp{tp}", t,
                notes=f"ORB60 break causal, TP={tp}R")


if __name__ == "__main__":
    print("=" * 100)
    print("ORB CAUSAL FAMILY")
    print("=" * 100)
    run_orb30_break_causal()
    print()
    run_orb30_fade_causal()
    print()
    run_orb60_break_causal()
