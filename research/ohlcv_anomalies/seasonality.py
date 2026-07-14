#!/usr/bin/env python3
"""Calendar / seasonality anomalies on gold (daily). Documented real effects with
liquidity/flow causes (not chart geometry): turn-of-month (fund flows), day-of-week,
month-of-year (seasonal demand), options/futures-expiry week (COMEX), and the
turn-of-month overnight interaction.

CAUSAL: calendar is known in advance (no data leak by definition). Cost applied per
round trip. Report per-year consistency (the anti-datamining check) + Sharpe.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

XAU_D1 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_D1_20060319_20260630.parquet"
COST = 0.65


def load():
    g = pd.read_parquet(XAU_D1)
    ts = pd.to_datetime(g["timestamp"])
    g["date"] = (ts.dt.tz_localize(None) if ts.dt.tz is not None else ts).dt.normalize()
    g = g[["date", "open", "close"]].sort_values("date").reset_index(drop=True)
    g["ret"] = np.log(g["close"] / g["close"].shift(1))  # today's daily return
    g["year"] = g["date"].dt.year
    g["dow"] = g["date"].dt.dayofweek
    g["dom"] = g["date"].dt.day
    g["month"] = g["date"].dt.month
    # trading-day-of-month index
    g["tdom"] = g.groupby([g["date"].dt.year, g["date"].dt.month]).cumcount() + 1
    g["days_in_m"] = g.groupby([g["date"].dt.year, g["date"].dt.month])["date"].transform("count")
    g["tdom_from_end"] = g["days_in_m"] - g["tdom"] + 1
    return g.dropna(subset=["ret"]).reset_index(drop=True)


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def rep(name, r, years, cost=True):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    if len(r) == 0: print(f"  {name:<30s} ZERO"); return
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(252)
    print(f"  {name:<30s} n={len(r):>5d} net={r.sum():>+7.3f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d} Sh={sh:>+5.2f} "
          f"avgbp={r.mean()*1e4:>+6.1f}")


def main():
    g = load()
    yrs = g["year"].values
    cr = COST / g["close"].values
    print("=== GOLD CALENDAR / SEASONALITY (daily, long each bucket) ===")
    print(f"days {len(g)}  {g['date'].min().date()}->{g['date'].max().date()}\n")

    print("-- day-of-week (long that day, gross to see raw drift) --")
    for d, nm in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"]):
        rep(f"{nm} (gross)", g["ret"].where(g["dow"] == d).values, yrs)

    print("\n-- month-of-year (long that month, gross) --")
    for mo in range(1, 13):
        rep(f"month {mo:>2d} (gross)", g["ret"].where(g["month"] == mo).values, yrs)

    print("\n-- turn-of-month (trading-day-of-month windows, gross) --")
    rep("TDOM 1-3 (start)", g["ret"].where(g["tdom"] <= 3).values, yrs)
    rep("TDOM last3 (end)", g["ret"].where(g["tdom_from_end"] <= 3).values, yrs)
    rep("TOM (last2+first3)", g["ret"].where((g["tdom_from_end"] <= 2) | (g["tdom"] <= 3)).values, yrs)
    rep("mid-month (8-18)", g["ret"].where((g["tdom"] >= 8) & (g["tdom"] <= 18)).values, yrs)

    print("\n-- TRADEABLE strategies (net of cost) --")
    # long only during TOM window, flat else
    tom = ((g["tdom_from_end"] <= 2) | (g["tdom"] <= 3)).values
    r = np.where(tom, g["ret"].values, np.nan) - np.where(tom, cr / 5, 0)  # amortized cost over ~5 day hold
    rep("long TOM window", r, yrs)
    # long strong months (historically Jan, Aug, Sep, Nov, Dec seasonal)
    for months in [(1, 8, 9), (1, 2, 8, 9, 11, 12)]:
        mask = g["month"].isin(months).values
        rr = np.where(mask, g["ret"].values, np.nan)
        rep(f"long months {months}", rr, yrs)


if __name__ == "__main__":
    main()
