#!/usr/bin/env python3
"""Relative-value: GOLD/SILVER RATIO mean-reversion (and GDX lead-lag).

THESIS: gold & silver are both monetary/precious metals; their price RATIO (GSR)
is historically range-bound and mean-reverts (silver is higher-beta, overshoots).
When GSR is stretched high (silver cheap vs gold) -> expect reversion (short gold /
long silver, or just trade the leg expected to move). This is a genuine RV edge with
an economic anchor, market-neutral-ish, uncorrelated to outright gold drift.

Also test: does the GSR change predict GOLD's next move (positioning signal)?

CAUSAL: ratio z-score from prior closes; enter next open, hold H days. Daily.
Data: OANDA XAU + XAG (align on daily close). Cost applied per leg.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

XAU_D1 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_D1_20060319_20260630.parquet"
XAG_M5 = "/tmp/oanda_XAG_USD_M5.parquet"
COST_G = 0.65   # gold spread $/oz
COST_S = 0.03   # silver spread $/oz (~3c)


def load():
    g = pd.read_parquet(XAU_D1)
    ts = pd.to_datetime(g["timestamp"])
    g["date"] = (ts.dt.tz_localize(None) if ts.dt.tz is not None else ts).dt.normalize()
    g = g[["date", "close"]].rename(columns={"close": "g"})
    # silver daily from M5 (last bar per NY date)
    s = pd.read_parquet(XAG_M5)
    if s["timestamp"].dt.tz is None: s["timestamp"] = s["timestamp"].dt.tz_localize("UTC")
    sny = s["timestamp"].dt.tz_convert("America/New_York")
    s["date"] = sny.dt.normalize().dt.tz_localize(None)
    sd = s.groupby("date")["close"].last().rename("s").reset_index()
    df = g.merge(sd, on="date", how="inner").sort_values("date").reset_index(drop=True)
    df["year"] = df["date"].dt.year
    df["gsr"] = df["g"] / df["s"]
    df["g_ret"] = np.log(df["g"] / df["g"].shift(1))
    df["s_ret"] = np.log(df["s"] / df["s"].shift(1))
    return df.dropna().reset_index(drop=True)


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def rep(name, r, years):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    if len(r) == 0: print(f"  {name:<34s} ZERO"); return
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(252)
    oos = np.asarray(yy) >= 2021
    sh_o = r[oos].mean()/(r[oos].std()+1e-12)*np.sqrt(252) if oos.sum() > 20 else np.nan
    print(f"  {name:<34s} n={len(r):>5d} net={r.sum():>+7.3f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d} Sh={sh:>+5.2f} ShOOS={sh_o:>+5.2f}")


def main():
    df = load()
    print("=== GOLD/SILVER RATIO — RELATIVE VALUE ===")
    print(f"days {len(df)}  {df['date'].min().date()}->{df['date'].max().date()}")
    print(f"GSR range {df['gsr'].min():.1f}..{df['gsr'].max():.1f} (mean {df['gsr'].mean():.1f})\n")

    g_o = df["g_ret"].values; s_o = df["s_ret"].values; n = len(df)
    yrs = df["year"].values
    # forward H-day returns of each leg (approx: cumulative next-H daily rets)
    def fwd(series, h):
        s = pd.Series(series)
        return s.shift(-1).rolling(h).sum().shift(-(h-1)).values  # ret from t+1..t+h

    for W in (60, 120, 250):
        z = ((df["gsr"] - df["gsr"].rolling(W).mean()) / (df["gsr"].rolling(W).std() + 1e-12)).values
        print(f"-- GSR z-score W={W} --")
        for k in (1.0, 1.5, 2.0):
            for H in (5, 10, 20):
                # GSR high -> ratio should fall -> silver outperforms gold:
                #   spread trade: long silver, short gold. spread ret = s - g.
                sig = np.where(z >= k, 1.0, np.where(z <= -k, -1.0, 0.0))  # +1 = ratio high = long spread(S-G)
                sret = fwd(s_o, H) - fwd(g_o, H)
                cost = (COST_S / df["s"].values + COST_G / df["g"].values)
                r = np.where(sig != 0, sig * sret - cost, np.nan)
                # sample non-overlap
                idx = np.zeros(n, bool); idx[::H] = True
                rr = np.where(idx, r, np.nan)
                rep(f"W{W} |z|>={k} spread H{H}", rr, yrs)
        print()

    print("-- does GSR-z predict GOLD outright? (RV as gold-timing) --")
    z = ((df["gsr"] - df["gsr"].rolling(120).mean()) / (df["gsr"].rolling(120).std() + 1e-12)).values
    for H in (5, 10, 20):
        # GSR high (gold expensive vs silver) -> gold may fall -> short gold
        sig = np.where(z >= 1.5, -1.0, np.where(z <= -1.5, 1.0, 0.0))
        r = np.where(sig != 0, sig * fwd(g_o, H) - COST_G / df["g"].values, np.nan)
        idx = np.zeros(n, bool); idx[::H] = True
        rep(f"gold-timing |z|>=1.5 H{H}", np.where(idx, r, np.nan), yrs)


if __name__ == "__main__":
    main()
