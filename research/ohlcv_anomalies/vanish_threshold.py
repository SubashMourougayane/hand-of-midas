#!/usr/bin/env python3
"""A+D edge VANISH THRESHOLD. The edge is gated by cost_r = spread / stop_distance.
Filter kills a trade when cost_r > 0.12  <=>  stop_distance < $0.30/0.12 = $2.50.

A+D stop distance is set by the M15 fib swing ~ tracks gold's M15 volatility (ATR).
Compute per-year: gold price, M15 ATR ($), implied typical stop, cost_r, and how far
the CURRENT regime is from the 0.12 cliff. Answers: at what gold price+vol does the
edge switch off, and how much runway is left.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
SPREAD = 0.30
COST_R_MAX = 0.12
STOP_CLIFF = SPREAD / COST_R_MAX   # $2.50


def load_m15():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")
    m15 = m5.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    m15 = m15.reset_index()
    tr = pd.concat([
        m15["high"] - m15["low"],
        (m15["high"] - m15["close"].shift(1)).abs(),
        (m15["low"] - m15["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    m15["atr14"] = tr.rolling(14).mean()
    m15["year"] = m15["timestamp"].dt.year
    return m15.dropna().reset_index(drop=True)


def main():
    m15 = load_m15()
    print("=== A+D EDGE VANISH THRESHOLD ===")
    print(f"spread ${SPREAD}/oz | cost_r cliff {COST_R_MAX} | => stop cliff ${STOP_CLIFF:.2f}\n")
    print("A+D stop ~ fib swing ~ k * M15_ATR. Test k in {1.0, 1.5, 2.0}.\n")

    print(f"{'year':>5}{'gold$':>8}{'M15ATR$':>9}{'%vol':>7}  cost_r @ stop=k*ATR   frac trades kept(<0.12)")
    print(f"{'':>29}{'k1.0':>7}{'k1.5':>7}{'k2.0':>7}")
    for yr, g in m15.groupby("year"):
        price = g["close"].mean(); atr = g["atr14"].median()
        pctvol = atr / price * 100
        crs = {}
        for k in (1.0, 1.5, 2.0):
            stop = k * g["atr14"].values
            cr = SPREAD / np.maximum(stop, 1e-9)
            crs[k] = (np.median(cr), (cr <= COST_R_MAX).mean())
        print(f"{yr:>5}{price:>8.0f}{atr:>9.2f}{pctvol:>6.2f}%  "
              f"{crs[1.0][0]:>6.3f} {crs[1.5][0]:>6.3f} {crs[2.0][0]:>6.3f}   "
              f"{crs[1.0][1]*100:>4.0f}% {crs[1.5][1]*100:>4.0f}% {crs[2.0][1]*100:>4.0f}%")

    # threshold in price terms: assume %vol persists at recent level.
    recent = m15[m15["year"] >= 2024]
    rv = (recent["atr14"] / recent["close"]).median()   # recent %vol per M15 bar
    print(f"\n-- runway (assume M15 %vol holds at recent {rv*100:.3f}%, stop=1.5*ATR) --")
    print(f"   stop$ = 1.5 * price * {rv*100:.3f}%  ;  edge OFF when stop < ${STOP_CLIFF:.2f}")
    cliff_price = STOP_CLIFF / (1.5 * rv)
    cur_price = recent["close"].iloc[-1]
    cur_stop = 1.5 * cur_price * rv
    cur_cr = SPREAD / cur_stop
    print(f"   current gold ${cur_price:.0f} -> stop ~${cur_stop:.2f} -> cost_r ~{cur_cr:.3f}")
    print(f"   edge switches OFF only if gold falls below ~${cliff_price:.0f} AT THIS VOL")
    print(f"   => runway: gold can fall {(1-cliff_price/cur_price)*100:.0f}% before cost_r hits 0.12")

    print("\n-- OR if volatility dies at current price ($%.0f) --" % cur_price)
    cliff_vol = STOP_CLIFF / (1.5 * cur_price)
    print(f"   edge OFF if M15 %vol drops below {cliff_vol*100:.3f}% (now {rv*100:.3f}%)")
    print(f"   => vol can fall {(1-cliff_vol/rv)*100:.0f}% before edge cuts off")


if __name__ == "__main__":
    main()
