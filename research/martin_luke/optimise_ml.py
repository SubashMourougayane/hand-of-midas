"""Optimise Martin Luke long-side: try filter combos to push WR up + keep PF up.

Levers:
- Tighter trend filter (ema9>ema21>ema50 + price > ema9 + slope check)
- ADR filter (only trade if prior daily range > threshold)
- Inside-day filter (range contraction)
- VWAP filter (entry above anchor VWAP from prior breakout)
- Time-of-day filter (NY morning only / power hour only / avoid lunch)
- Day-of-week
- Volume filter (today's volume so far > prior day same time)
- Stop tightness (max risk % cap)
- Re-entry on failed first break
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd
from itertools import product

from research.harness.causal_sim import load_data
from research.martin_luke.run_ml_xau import build_daily, simulate_ml, headline


def generate_signals(m5: pd.DataFrame, daily: pd.DataFrame, *,
                     require_uptrend: bool = True,
                     require_inside_day: bool = False,
                     adr_min_pct: float | None = None,
                     ema_slope_up: bool = False,
                     above_ema9_daily: bool = False,
                     ny_window: tuple[int, int] = (9, 16),
                     volume_strong: bool = False,
                     max_stop_pct: float = 0.05) -> list[dict]:
    """Generate PDH-break long signals with optional extra filters (all causal, lagged)."""
    # Vectorised daily features
    d = daily.copy().reset_index(drop=True)
    d["ny_date_str"] = d["ny_date"].astype(str)
    d["prior_dh"] = d["high"].shift(1)
    d["prior_dl"] = d["low"].shift(1)
    d["prior_ema9"] = d["ema9"].shift(1)
    d["prior_ema21"] = d["ema21"].shift(1)
    d["prior_ema50"] = d["ema50"].shift(1)
    d["prior_close"] = d["close"].shift(1)
    d["prior_adr"] = d["adr20"].shift(1)
    d["inside_lag"] = ((d["high"].shift(1) < d["high"].shift(2)) & (d["low"].shift(1) > d["low"].shift(2)))
    d["uptrend_lag"] = ((d["prior_ema9"] > d["prior_ema21"]) & (d["prior_ema21"] > d["prior_ema50"]))
    d["above_ema9_lag"] = d["prior_close"] > d["prior_ema9"]
    d["slope_up_lag"] = d["prior_ema9"] > d["ema9"].shift(2)
    d_keep = d[["ny_date_str", "prior_dh", "prior_dl", "prior_ema9", "prior_ema21",
                "prior_ema50", "prior_close", "prior_adr",
                "inside_lag", "uptrend_lag", "above_ema9_lag", "slope_up_lag"]]
    m5 = m5.copy()
    m5["ny_date_str"] = m5["ny_date"].astype(str)
    m5 = m5.merge(d_keep, on="ny_date_str", how="left")
    m5["pdh"] = m5["prior_dh"]
    m5["pdl"] = m5["prior_dl"]
    m5["inside"] = m5["inside_lag"].fillna(False).astype(bool)
    m5["uptrend"] = m5["uptrend_lag"].fillna(False).astype(bool)
    m5["above_ema9"] = m5["above_ema9_lag"].fillna(False).astype(bool)
    m5["slope_up"] = m5["slope_up_lag"].fillna(False).astype(bool)

    m5["in_window"] = (m5["ny_hr"] >= ny_window[0]) & (m5["ny_hr"] < ny_window[1])
    m5["sig"] = m5["in_window"] & (m5["close"] > m5["pdh"])
    if require_uptrend:
        m5["sig"] = m5["sig"] & m5["uptrend"]
    if require_inside_day:
        m5["sig"] = m5["sig"] & m5["inside"]
    if ema_slope_up:
        m5["sig"] = m5["sig"] & m5["slope_up"]
    if above_ema9_daily:
        m5["sig"] = m5["sig"] & m5["above_ema9"]
    if adr_min_pct is not None:
        m5["sig"] = m5["sig"] & (m5["prior_adr"] >= adr_min_pct)
    m5["first"] = m5["sig"] & ~m5.groupby("ny_date")["sig"].cumsum().shift(1).fillna(0).astype(bool)

    m5["lod_so_far"] = m5.groupby("ny_date")["low"].cummin()
    signals = []
    for i in m5.index[m5["first"]]:
        row = m5.iloc[i]
        if i + 1 >= len(m5): continue
        entry_open = float(m5["open"].iloc[i + 1])
        lod = float(row["lod_so_far"])
        risk_std = entry_open - lod
        risk_pct = risk_std / entry_open
        if risk_pct > max_stop_pct:
            # aggressive: 5min entry candle low
            risk_alt = entry_open - float(row["low"])
            if risk_alt < risk_std and risk_alt > 0:
                risk_units = risk_alt
            else:
                risk_units = entry_open * max_stop_pct
        else:
            risk_units = risk_std
        # cap
        risk_units = min(risk_units, entry_open * max_stop_pct)
        if risk_units <= 0: continue
        signals.append({"entry_index": i + 1, "side": 1, "risk_units": float(risk_units)})
    return signals


def print_h(label, h):
    if h.get("n", 0) == 0: print(f"  {label:<70s} ZERO"); return
    print(f"  {label:<70s} n={h['n']:>4d} /yr={h['trades_per_year']:>4.0f} "
          f"net={h['net']:>+7.1f}R /yr={h['yr_r']:>+6.1f} WR={h['wr']*100:>5.1f}% "
          f"PF={h['pf']:>5.2f} DD={h['dd']:>+6.1f} MAR={h['mar']:>+5.2f} pos={h['pos_years']}")


def run():
    print("="*128)
    print("MARTIN LUKE LONG OPTIMISATION SWEEP")
    print("="*128)
    m1, m5, m15 = load_data()
    daily = build_daily(m1)
    print(f"daily ADR median: {daily['adr20'].median()*100:.2f}%  q25: {daily['adr20'].quantile(0.25)*100:.2f}%  q75: {daily['adr20'].quantile(0.75)*100:.2f}%")

    # Baseline
    base_sigs = generate_signals(m5, daily, require_uptrend=True)
    base_t = simulate_ml(base_sigs, m5, daily, tp_mult=3.0)
    print()
    print_h("BASELINE (PDH+uptrend+TP3R)", headline(base_t))

    print()
    print("="*128)
    print("SINGLE-FILTER ADDITIONS (one extra filter at a time)")
    print("="*128)
    single_filters = [
        ("+ ADR > 1.5%",         {"adr_min_pct": 0.015}),
        ("+ ADR > 2.0%",         {"adr_min_pct": 0.020}),
        ("+ ADR > 2.5%",         {"adr_min_pct": 0.025}),
        ("+ slope_up",           {"ema_slope_up": True}),
        ("+ above_ema9_daily",   {"above_ema9_daily": True}),
        ("+ inside-day",         {"require_inside_day": True}),
        ("+ NY morning 9-12",    {"ny_window": (9, 12)}),
        ("+ NY power 14-16",     {"ny_window": (14, 16)}),
        ("+ avoid lunch (10-14)",{"ny_window": (10, 14)}),
        ("+ tight stop 3%",      {"max_stop_pct": 0.03}),
        ("+ tight stop 2%",      {"max_stop_pct": 0.02}),
        ("+ slope+aboveEMA9",    {"ema_slope_up": True, "above_ema9_daily": True}),
    ]
    for label, params in single_filters:
        sigs = generate_signals(m5, daily, require_uptrend=True, **params)
        if len(sigs) < 30: continue
        for tp in [2.0, 3.0]:
            t = simulate_ml(sigs, m5, daily, tp_mult=tp)
            print_h(f"{label} TP={tp}R", headline(t))

    print()
    print("="*128)
    print("BEST COMBINATIONS (multi-filter)")
    print("="*128)
    combos = [
        {"adr_min_pct": 0.015, "ema_slope_up": True},
        {"adr_min_pct": 0.015, "above_ema9_daily": True},
        {"adr_min_pct": 0.015, "ema_slope_up": True, "above_ema9_daily": True},
        {"adr_min_pct": 0.020, "ema_slope_up": True, "above_ema9_daily": True},
        {"adr_min_pct": 0.015, "ema_slope_up": True, "above_ema9_daily": True, "ny_window": (9, 14)},
        {"adr_min_pct": 0.015, "ema_slope_up": True, "above_ema9_daily": True, "max_stop_pct": 0.03},
        {"adr_min_pct": 0.020, "ema_slope_up": True, "above_ema9_daily": True, "max_stop_pct": 0.03},
        {"adr_min_pct": 0.015, "ema_slope_up": True, "above_ema9_daily": True, "require_inside_day": True},
    ]
    for params in combos:
        sigs = generate_signals(m5, daily, require_uptrend=True, **params)
        if len(sigs) < 30: continue
        label = "+".join([f"{k}={v}" for k, v in params.items()])
        for tp in [1.5, 2.0, 3.0]:
            t = simulate_ml(sigs, m5, daily, tp_mult=tp)
            print_h(f"{label} TP={tp}R", headline(t))


if __name__ == "__main__":
    run()
