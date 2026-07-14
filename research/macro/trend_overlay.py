#!/usr/bin/env python3
"""Time-series momentum (CTA trend) on gold + macro regime filters.

THESIS: gold has a persistent drift (real-rate/debasement premium). The classic
big-money systematic capture is TREND (time-series momentum) — low turnover so
cost-light, and it sidesteps the drift being un-timeable by mean-reversion.
Add macro regime (real-yield direction) as a filter/overlay.

All causal: momentum from prior closes; macro T-1; rebalance at close, hold.
Cost applied per position change. Report Sharpe/PF/DD vs buy&hold benchmark.
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
    g = g[["date", "close"]].sort_values("date").reset_index(drop=True)
    ry = pd.read_parquet("/tmp/fred_DFII10.parquet").rename(columns={"val": "ry"})
    ry["date"] = pd.to_datetime(ry["date"])
    g = g.merge(ry, on="date", how="left")
    g["ry"] = g["ry"].ffill()
    g["year"] = g["date"].dt.year
    g["ret"] = np.log(g["close"] / g["close"].shift(1))
    return g.dropna(subset=["ry", "ret"]).reset_index(drop=True)


def curve_stats(name, pos, ret, cost_r, years):
    """pos = target position (-1..1) held over next day; applied to next-day ret.
    Cost charged on |change in pos|. All arrays aligned; pos is causal (known today)."""
    pos = np.asarray(pos, float)
    ret = np.asarray(ret, float)
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    strat = pos * ret - turn * cost_r
    m = ~np.isnan(strat); strat = strat[m]; yy = np.asarray(years)[m]
    if len(strat) == 0: print(f"  {name:<34s} ZERO"); return None
    ys = pd.Series(strat).groupby(pd.Series(yy)).sum(); posy = int((ys > 0).sum()); tot = len(ys)
    sh = strat.mean() / (strat.std() + 1e-12) * np.sqrt(252)
    eq = strat.cumsum(); dd = float((eq - np.maximum.accumulate(eq)).min())
    gl = -strat[strat < 0].sum(); pf = strat[strat > 0].sum() / gl if gl > 0 else float("inf")
    trades = int((turn[m] > 0).sum())
    print(f"  {name:<34s} netLog={strat.sum():>+6.3f} PF={pf:>5.2f} Sh={sh:>+5.2f} "
          f"posY={posy:>2d}/{tot:<2d} DD={dd:>+6.3f} flips={trades:>4d}")
    return dict(net=strat.sum(), sharpe=sh, pf=pf, dd=dd, posy=posy, tot=tot)


def main():
    g = load()
    close = g["close"].values; ret = g["ret"].values; yrs = g["year"].values
    ry = g["ry"].values
    cost_r = COST / close  # per-flip cost in return terms (approx, one leg)
    # next-day return aligned to today's position
    nxt = np.concatenate([ret[1:], [np.nan]])
    print("=== GOLD TREND / TSMOM + MACRO REGIME ===")
    print(f"days {len(g)}  {g['date'].min().date()}->{g['date'].max().date()}\n")

    print("-- benchmark --")
    curve_stats("buy&hold (always long)", np.ones(len(g)), nxt, cost_r, yrs)

    print("\n-- TSMOM long/short (sign of N-day momentum) --")
    for N in (20, 50, 100, 200):
        mom = close / np.concatenate([[np.nan]*N, close[:-N]]) - 1.0
        pos = np.sign(mom)
        curve_stats(f"TSMOM {N}d L/S", pos, nxt, cost_r, yrs)

    print("\n-- TSMOM long-only (drift asset; flat instead of short) --")
    for N in (20, 50, 100, 200):
        mom = close / np.concatenate([[np.nan]*N, close[:-N]]) - 1.0
        pos = (mom > 0).astype(float)
        curve_stats(f"TSMOM {N}d long/flat", pos, nxt, cost_r, yrs)

    print("\n-- MA crossover (fast>slow = long) --")
    s = pd.Series(close)
    for f, sl in [(20, 100), (50, 200), (20, 50)]:
        ma_f = s.rolling(f).mean().values; ma_s = s.rolling(sl).mean().values
        pos = (ma_f > ma_s).astype(float)
        curve_stats(f"MA {f}/{sl} long/flat", pos, nxt, cost_r, yrs)
        curve_stats(f"MA {f}/{sl} L/S", np.where(ma_f > ma_s, 1.0, -1.0), nxt, cost_r, yrs)

    print("\n-- MACRO REGIME overlay: long only if real-yield falling (20d) --")
    dry20 = ry - np.concatenate([[np.nan]*20, ry[:-20]])
    ry_fall = (dry20 < 0)
    mom100 = close / np.concatenate([[np.nan]*100, close[:-100]]) - 1.0
    pos = ((mom100 > 0) & ry_fall).astype(float)
    curve_stats("trend100 & ry-falling", pos, nxt, cost_r, yrs)
    pos2 = np.where(mom100 > 0, np.where(ry_fall, 1.0, 0.5), 0.0)  # size up when macro agrees
    curve_stats("trend100 sized by ry", pos2, nxt, cost_r, yrs)
    # real-yield LEVEL regime: gold strongest when real yields low/negative
    curve_stats("long only if ry<1.0", (ry < 1.0).astype(float), nxt, cost_r, yrs)
    curve_stats("long only if ry<0.5", (ry < 0.5).astype(float), nxt, cost_r, yrs)
    curve_stats("trend100 & ry<1.0", ((mom100 > 0) & (ry < 1.0)).astype(float), nxt, cost_r, yrs)


if __name__ == "__main__":
    main()
