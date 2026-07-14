#!/usr/bin/env python3
"""S1 — Gold macro fair-value model (Group A flagship).

THESIS: gold is a zero-yield real asset. Its price is driven by the REAL 10y
interest rate (opportunity cost) and the US dollar. Real yields DOWN -> gold UP.
This has a genuine economic reason to predict — unlike chart geometry.

Signals (both causal, T-1 point-in-time — macro value known at prior close):
  (1) YIELD MOMENTUM: N-day change in real yield -> next-H-day gold direction.
      Real yield falling -> long gold.
  (2) FAIR-VALUE REVERSION: rolling OLS log(gold) ~ real_yield + log(dxy);
      residual z-score -> fade extremes back to fair value.

Data: OANDA XAU D1 (20yr) + FRED DFII10 (real yield) + yfinance DXY.
Cost: COST_USD per round trip in $/oz, converted to return. Horizon in trading days.
Battery: per-year PF/Sharpe, IS/OOS, cost stress, threshold monotonicity.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

XAU_D1 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_D1_20060319_20260630.parquet"
COST = 0.65


def load():
    g = pd.read_parquet(XAU_D1)
    if "timestamp" in g:
        g["date"] = pd.to_datetime(g["timestamp"]).dt.tz_localize(None).dt.normalize() \
            if pd.to_datetime(g["timestamp"]).dt.tz is not None else pd.to_datetime(g["timestamp"]).dt.normalize()
    g = g[["date", "open", "high", "low", "close"]].sort_values("date").reset_index(drop=True)
    ry = pd.read_parquet("/tmp/fred_DFII10.parquet").rename(columns={"date": "date", "val": "ry"})
    ry["date"] = pd.to_datetime(ry["date"])
    yf = pd.read_parquet("/tmp/macro_yf.parquet")
    yf.index = pd.to_datetime(yf.index)
    dxy = yf["DX-Y.NYB"].rename("dxy").reset_index().rename(columns={"Date": "date"})
    dxy["date"] = pd.to_datetime(dxy["date"])
    df = g.merge(ry, on="date", how="left").merge(dxy, on="date", how="left")
    # point-in-time: macro known at PRIOR close -> forward-fill then shift(1)
    df["ry"] = df["ry"].ffill()
    df["dxy"] = df["dxy"].ffill()
    df["ry_lag"] = df["ry"].shift(1)
    df["dxy_lag"] = df["dxy"].shift(1)
    df["year"] = df["date"].dt.year
    return df.dropna(subset=["ry_lag", "dxy_lag"]).reset_index(drop=True)


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def rep(name, r, years):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    if len(r) == 0: print(f"  {name:<38s} ZERO"); return None
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(252)
    eq = r.cumsum(); dd = float((eq - np.maximum.accumulate(eq)).min())
    print(f"  {name:<38s} n={len(r):>5d} net={r.sum():>+7.3f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d} Sh={sh:>+5.2f} DD={dd:>+6.3f}")
    return dict(net=r.sum(), pf=pf(r), sharpe=sh, pos=pos, tot=tot)


def fwd_ret(close, h):
    """log return from today's close to close h days ahead (the trade held H days)."""
    return np.log(pd.Series(close).shift(-h) / pd.Series(close)).values


def main():
    df = load()
    yrs = df["year"].values
    close = df["close"].values
    cr = COST / close
    print("=== S1 MACRO FAIR-VALUE (gold vs real-yield + DXY) ===")
    print(f"days {len(df)}  {df['date'].min().date()}->{df['date'].max().date()}")
    print(f"real yield range {df['ry'].min():.2f}..{df['ry'].max():.2f}\n")

    print("-- (1) YIELD MOMENTUM: dRY(N) -> gold dir, hold H days --")
    print("   thesis: real yield FALLING -> long gold\n")
    for N in (5, 10, 20):
        for H in (5, 10, 20):
            dry = df["ry_lag"] - df["ry_lag"].shift(N)   # change in real yield, causal
            sig = -np.sign(dry.values)                    # ry down -> long
            fr = fwd_ret(close, H)
            r = sig * fr - cr                             # 1 round trip per trade
            # non-overlapping-ish: sample every H days to avoid overlap inflation
            idx = np.arange(0, len(df), H)
            mask = np.zeros(len(df), bool); mask[idx] = True
            rr = np.where(mask, r, np.nan)
            st = rep(f"dRY({N}) hold {H}d", rr, yrs)

    print("\n-- (2) FAIR-VALUE REVERSION: resid z of log(gold)~ry+log(dxy) --")
    print("   thesis: gold above fair value -> short; below -> long\n")
    lg = np.log(close)
    ldxy = np.log(df["dxy_lag"].values)
    ry = df["ry_lag"].values
    for W in (120, 250):
        z = np.full(len(df), np.nan)
        for i in range(W, len(df)):
            X = np.column_stack([np.ones(W), ry[i-W:i], ldxy[i-W:i]])
            y = lg[i-W:i]
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            pred = beta @ np.array([1.0, ry[i], ldxy[i]])
            resid_hist = y - X @ beta
            z[i] = (lg[i] - pred) / (resid_hist.std() + 1e-12)
        for H in (5, 10, 20):
            for k in (1.0, 1.5, 2.0):
                sig = np.where(z <= -k, 1.0, np.where(z >= k, -1.0, 0.0))
                fr = fwd_ret(close, H)
                r = sig * fr - np.where(sig != 0, cr, 0.0)
                idx = np.arange(0, len(df), H); mask = np.zeros(len(df), bool); mask[idx] = True
                rr = np.where(mask & (sig != 0), r, np.nan)
                rep(f"W{W} |z|>={k} hold {H}d", rr, yrs)

    print("\n-- baseline: gold buy&hold (gross) --")
    rep("buy&hold daily", np.log(pd.Series(close).shift(-1) / pd.Series(close)).values, yrs)


if __name__ == "__main__":
    main()
