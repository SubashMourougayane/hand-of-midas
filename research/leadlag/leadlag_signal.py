#!/usr/bin/env python3
"""S3 — Cross-asset intraday lead-lag: does silver (XAG) lead gold (XAU)?

THESIS: gold & silver are both precious/real-rate assets and co-move, but liquidity
& flow differ. If silver (or the dollar) makes a sharp move first, gold may follow
within minutes — a genuine economic driver for an intraday signal (unlike ORB chart
geometry). Signal: leader's M5 return > kσ -> take gold same (co-move) direction for
the next H bars; exit fixed horizon.

CAUSAL: leader return measured on the SAME closed M5 bar; gold entry at NEXT bar open,
exit H bars later. No future peek. Cost applied. First check the raw lead-lag
correlation (does silver_ret[t] predict gold_ret[t+1]?) before trading it.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

XAU = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
XAG = "/tmp/oanda_XAG_USD_M5.parquet"
EUR = "/tmp/oanda_EUR_USD_M5.parquet"
COST = 0.65


def load():
    g = pd.read_parquet(XAU)[["timestamp", "open", "close"]].rename(columns={"open": "g_o", "close": "g_c"})
    s = pd.read_parquet(XAG)[["timestamp", "close"]].rename(columns={"close": "s_c"})
    for d in (g, s):
        if d["timestamp"].dt.tz is None:
            d["timestamp"] = d["timestamp"].dt.tz_localize("UTC")
    df = g.merge(s, on="timestamp", how="inner").sort_values("timestamp").reset_index(drop=True)
    try:
        e = pd.read_parquet(EUR)[["timestamp", "close"]].rename(columns={"close": "e_c"})
        if e["timestamp"].dt.tz is None: e["timestamp"] = e["timestamp"].dt.tz_localize("UTC")
        df = df.merge(e, on="timestamp", how="left")
    except Exception:
        df["e_c"] = np.nan
    ny = df["timestamp"].dt.tz_convert("America/New_York")
    df["ny_hr"] = ny.dt.hour; df["year"] = ny.dt.year
    df["g_ret"] = np.log(df["g_c"] / df["g_c"].shift(1))
    df["s_ret"] = np.log(df["s_c"] / df["s_c"].shift(1))
    df["e_ret"] = np.log(df["e_c"] / df["e_c"].shift(1))
    # gold forward returns (entry next open -> close H bars ahead)
    return df.dropna(subset=["g_ret", "s_ret"]).reset_index(drop=True)


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def rep(name, r, years):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    if len(r) == 0: print(f"  {name:<40s} ZERO"); return
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    print(f"  {name:<40s} n={len(r):>6d} net={r.sum():>+8.3f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d}")


def main():
    df = load()
    print("=== S3 SILVER->GOLD LEAD-LAG (M5) ===")
    print(f"aligned bars {len(df)}  {df['timestamp'].min().date()}->{df['timestamp'].max().date()}\n")

    # 0. Raw predictive correlation: does leader_ret[t] predict gold_ret[t+1]?
    print("-- predictive corr leader_ret[t] vs gold_ret[t+1] (lag-1) --")
    g_next = df["g_ret"].shift(-1)
    for nm, col in [("silver", "s_ret"), ("EUR(=inv USD)", "e_ret")]:
        c = df[col]
        v = pd.concat([c, g_next], axis=1).dropna()
        if len(v) > 100:
            corr = np.corrcoef(v.iloc[:, 0], v.iloc[:, 1])[0, 1]
            # contemporaneous for reference
            v0 = pd.concat([c, df["g_ret"]], axis=1).dropna()
            corr0 = np.corrcoef(v0.iloc[:, 0], v0.iloc[:, 1])[0, 1]
            print(f"  {nm:<14s} contemp corr={corr0:>+.3f}   lag1(predictive) corr={corr:>+.3f}")

    # 1. Trade: silver spike > kσ -> gold same direction, hold H bars, entry next open
    print("\n-- TRADE: silver spike -> gold co-move (entry next open) --")
    sstd = df["s_ret"].rolling(120).std().shift(1)
    sz = df["s_ret"] / sstd
    g_o = df["g_o"].values; g_c = df["g_c"].values; n = len(df)
    for k in (2.0, 3.0, 4.0):
        for H in (1, 3, 6):
            sig = np.where(sz.values >= k, 1.0, np.where(sz.values <= -k, -1.0, 0.0))
            # entry next open (i+1), exit close at i+H
            r = np.full(n, np.nan)
            for i in np.where(sig != 0)[0]:
                ei = i + 1; xi = i + H
                if xi >= n: continue
                ent = g_o[ei]
                fr = np.log(g_c[xi] / ent) * sig[i]
                r[i] = fr - COST / ent
            rep(f"silver |z|>={k} hold{H}", r, df["year"].values)

    # 2. EUR (dollar) spike -> gold co-move (gold up when USD down => EUR up)
    if df["e_ret"].notna().sum() > 1000:
        print("\n-- TRADE: EUR spike -> gold co-move --")
        estd = df["e_ret"].rolling(120).std().shift(1); ez = df["e_ret"] / estd
        for k in (2.0, 3.0, 4.0):
            for H in (1, 3, 6):
                sig = np.where(ez.values >= k, 1.0, np.where(ez.values <= -k, -1.0, 0.0))
                r = np.full(n, np.nan)
                for i in np.where(sig != 0)[0]:
                    ei = i + 1; xi = i + H
                    if xi >= n: continue
                    ent = g_o[ei]; r[i] = np.log(g_c[xi] / ent) * sig[i] - COST / ent
                rep(f"EUR |z|>={k} hold{H}", r, df["year"].values)


if __name__ == "__main__":
    main()
