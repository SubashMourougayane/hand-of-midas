#!/usr/bin/env python3
"""Combined calendar-timing overlay on gold. Synthesis of the survivors:
Thursday (overnight-driven, OOS+), turn-of-month, January/strong-months, and the
overnight-drift concentration. Hypothesis: gold's drift lives in specific calendar
windows; being long ONLY those windows captures most of the return at a fraction of
the exposure -> higher Sharpe / lower DD than buy&hold, and it must survive OOS.

All calendar = known in advance (causal). Net of cost on position changes.
Benchmark = always-long buy&hold. Report Sharpe, MAR, OOS, and compounded $ curve.
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
    g["ret"] = np.log(g["close"] / g["close"].shift(1))
    g["year"] = g["date"].dt.year
    g["dow"] = g["date"].dt.dayofweek
    g["month"] = g["date"].dt.month
    g["tdom"] = g.groupby([g["date"].dt.year, g["date"].dt.month]).cumcount() + 1
    dim = g.groupby([g["date"].dt.year, g["date"].dt.month])["date"].transform("count")
    g["tdom_end"] = dim - g["tdom"] + 1
    ma = pd.Series(g["close"]).rolling(200).mean()
    g["uptrend"] = (g["close"] > ma).astype(float)
    return g.dropna(subset=["ret"]).reset_index(drop=True)


def curve(name, pos, ret, cost_r, years):
    pos = np.asarray(pos, float); ret = np.asarray(ret, float)
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    strat = pos * ret - turn * cost_r
    m = ~np.isnan(strat); strat = strat[m]; yy = np.asarray(years)[m]
    ys = pd.Series(strat).groupby(pd.Series(yy)).sum(); pos_y = int((ys > 0).sum()); tot = len(ys)
    sh = strat.mean() / (strat.std() + 1e-12) * np.sqrt(252)
    eq = strat.cumsum(); dd = float((eq - np.maximum.accumulate(eq)).min())
    mar = (strat.sum() / (len(strat) / 252)) / abs(dd) if dd != 0 else 0
    expo = (np.abs(pos[m]) > 0).mean()
    # OOS sharpe
    oos = yy >= 2017
    sh_oos = strat[oos].mean() / (strat[oos].std() + 1e-12) * np.sqrt(252) if oos.sum() > 30 else np.nan
    print(f"  {name:<30s} net={strat.sum():>+6.3f} Sh={sh:>+5.2f} ShOOS={sh_oos:>+5.2f} "
          f"MAR={mar:>+4.2f} DD={dd:>+6.3f} posY={pos_y:>2d}/{tot:<2d} expo={expo*100:>3.0f}%")
    return dict(sh=sh, mar=mar, ys=ys)


def main():
    g = load()
    ret = g["ret"].values; yrs = g["year"].values; cr = COST / g["close"].values
    nxt = np.concatenate([ret[1:], [np.nan]])  # position today earns tomorrow's ret
    print("=== CALENDAR-TIMING OVERLAY (gold daily) ===")
    print(f"days {len(g)}  {g['date'].min().date()}->{g['date'].max().date()}\n")

    print("-- benchmark --")
    curve("buy&hold (always long)", np.ones(len(g)), nxt, cr, yrs)

    thu = (g["dow"] == 3).values          # position held Wed->Thu (dow==3 is Thu ret)
    tom = ((g["tdom_end"] <= 2) | (g["tdom"] <= 3)).values
    strong_m = g["month"].isin([1, 2, 7, 8, 11, 12]).values
    up = g["uptrend"].values

    print("\n-- single calendar filters (long only when true) --")
    curve("long Thu only", thu.astype(float), nxt, cr, yrs)
    curve("long TOM only", tom.astype(float), nxt, cr, yrs)
    curve("long strong-months only", strong_m.astype(float), nxt, cr, yrs)

    print("\n-- UNION (long if ANY favorable window) --")
    u2 = (thu | tom).astype(float)
    curve("Thu | TOM", u2, nxt, cr, yrs)
    u3 = (thu | tom | strong_m).astype(float)
    curve("Thu | TOM | strongM", u3, nxt, cr, yrs)

    print("\n-- + TREND GATE (only take favorable day if uptrend) --")
    curve("(Thu|TOM) & uptrend", ((thu | tom) & (up > 0)).astype(float), nxt, cr, yrs)
    curve("(Thu|TOM|sM) & uptrend", ((thu | tom | strong_m) & (up > 0)).astype(float), nxt, cr, yrs)

    print("\n-- scaled: 1.0 favorable-day, 0.3 base long else (always some drift) --")
    base = np.where((thu | tom | strong_m), 1.0, 0.3)
    curve("scaled 1.0/0.3", base, nxt, cr, yrs)
    base_up = np.where(up > 0, np.where((thu | tom | strong_m), 1.0, 0.3), 0.0)
    curve("scaled 1.0/0.3 & uptrend", base_up, nxt, cr, yrs)


if __name__ == "__main__":
    main()
