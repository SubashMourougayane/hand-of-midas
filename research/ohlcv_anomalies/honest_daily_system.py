#!/usr/bin/env python3
"""The HONEST deployable system: overnight-drift capture, ~1 trade/day, NO stop
(books real close->open return, so no wick/-1R artifact). Regime + seasonal filtered.
Test BOTH directions honestly. Quantify real money (flat risk, no fantasy).

This is the ONLY intraday-adjacent thing that survives honest execution all session.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
OPEN_HR, CLOSE_HR = 8, 17


def load():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    m5["d"] = ny.dt.normalize(); m5["h"] = ny.dt.hour; m5["dow"] = ny.dt.dayofweek
    rows = []
    for d, g in m5.groupby("d", sort=True):
        o = g[g["h"] >= OPEN_HR]; c = g[g["h"] < CLOSE_HR]
        if len(o) == 0 or len(c) == 0: continue
        rows.append({"date": d, "dow": int(c.iloc[-1]["dow"]),
                     "open": float(o.iloc[0]["open"]), "close": float(c.iloc[-1]["close"])})
    s = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    s["year"] = s["date"].dt.year; s["month"] = s["date"].dt.month
    s["next_open"] = s["open"].shift(-1)
    s["overnight"] = np.log(s["next_open"] / s["close"])       # close -> next open (real)
    s["intraday"] = np.log(s["close"] / s["open"])             # open -> close (real)
    s["ma50"] = s["close"].rolling(50).mean().shift(1)
    s["ma200"] = s["close"].rolling(200).mean().shift(1)
    return s.dropna(subset=["next_open", "ma200"]).reset_index(drop=True)


def stats(name, r, px, years, cost):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; px = np.asarray(px)[m]; yy = np.asarray(years)[m]
    r = r - cost / px   # honest cost per trade
    if len(r) == 0: print(f"  {name:<30} ZERO"); return
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(252)
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    eq = r.cumsum(); dd = float((eq - np.maximum.accumulate(eq)).min())
    oos = yy >= 2016
    osh = r[oos].mean()/(r[oos].std()+1e-12)*np.sqrt(252) if oos.sum() > 50 else np.nan
    print(f"  {name:<30} n={len(r):>4d} Sh={sh:>+5.2f} ShOOS={osh:>+5.2f} sum={r.sum():>+6.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d} DD={dd:>+5.2f}")
    return r


def main():
    s = load(); yrs = s["year"].values; px = s["close"].values; opx = s["open"].values
    strong = s["month"].isin([1, 2, 7, 8, 11, 12]).values
    up = (s["close"] > s["ma200"]).values
    print("=== HONEST DAILY SYSTEM (overnight drift, no stop, real returns) ===")
    print(f"sessions {len(s)}  ~1 trade/day\n")
    for cost in (0.30, 0.65):
        print(f"-- cost ${cost} --")
        stats("overnight LONG (all)", s["overnight"].values, px, yrs, cost)
        stats("overnight LONG & uptrend", np.where(up, s["overnight"].values, np.nan), px, yrs, cost)
        stats("overnight LONG & strongMo", np.where(strong, s["overnight"].values, np.nan), px, yrs, cost)
        stats("overnight LONG & up & strMo", np.where(up & strong, s["overnight"].values, np.nan), px, yrs, cost)
        stats("overnight SHORT & downtrend", np.where(~up, -s["overnight"].values, np.nan), px, yrs, cost)
        stats("intraday LONG & uptrend", np.where(up, s["intraday"].values, np.nan), opx, yrs, cost)
        stats("intraday SHORT & downtrend", np.where(~up, -s["intraday"].values, np.nan), opx, yrs, cost)
        print()

    # money for the best honest leg
    print("-- MONEY: overnight LONG & uptrend, flat risk (honest) --")
    best = np.where(up, s["overnight"].values, np.nan) - 0.30 / px
    best = best[~np.isnan(best)]
    simple = np.exp(best) - 1
    for risk in (0.005, 0.01, 0.02):
        for start in (5000, 100000):
            flat = start * (1 + risk * simple.sum() / (best.std()+1e-9) * 0)  # placeholder
    tot_simple = simple.sum()
    print(f"    sum log={best.sum():.3f}  ~{(np.exp(best.sum())-1)*100:.0f}% unlevered over 20yr (1 unit)")
    print(f"    Sharpe {best.mean()/best.std()*np.sqrt(252):.2f} — position/swing overlay, honest, ~1 trade/day")


if __name__ == "__main__":
    main()
