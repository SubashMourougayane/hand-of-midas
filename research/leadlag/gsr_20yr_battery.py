#!/usr/bin/env python3
"""GOLD/SILVER RATIO reversion — 20yr full battery (both D1, 2005-2026).
Validates the modern-sample lead (W250 |z|>=1.5 spread, Sharpe ~1.4 OOS ~1.7).

Hostile: full 20yr, per-year, IS(<=2015)/OOS(2016+), bootstrap vs random entry,
cost stress (silver spread 3-8c), delay+1, threshold monotonicity. Spread trade =
long silver / short gold (or reverse), equal $-notional legs, held H days.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

XAU_D1 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_D1_20060319_20260630.parquet"
XAG_D1 = "/tmp/oanda_XAG_USD_D1.parquet"


def load():
    g = pd.read_parquet(XAU_D1)
    gt = pd.to_datetime(g["timestamp"])
    g["date"] = (gt.dt.tz_localize(None) if gt.dt.tz is not None else gt).dt.normalize()
    g = g[["date", "close"]].rename(columns={"close": "g"})
    s = pd.read_parquet(XAG_D1)
    st = pd.to_datetime(s["timestamp"])
    s["date"] = (st.dt.tz_localize(None) if st.dt.tz is not None else st).dt.normalize()
    s = s[["date", "close"]].rename(columns={"close": "s"})
    df = g.merge(s, on="date", how="inner").sort_values("date").reset_index(drop=True)
    df["year"] = df["date"].dt.year
    df["gsr"] = df["g"] / df["s"]
    df["g_ret"] = np.log(df["g"] / df["g"].shift(1))
    df["s_ret"] = np.log(df["s"] / df["s"].shift(1))
    return df.dropna().reset_index(drop=True)


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def st_(r):
    r = np.asarray(r, float); r = r[~np.isnan(r)]
    if len(r) == 0: return None
    return dict(n=len(r), net=r.sum(), pf=pf(r), wr=(r > 0).mean(),
                sh=r.mean() / (r.std() + 1e-12) * np.sqrt(252))


def rep(name, r, years):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    s = st_(r)
    if s is None: print(f"  {name:<32s} ZERO"); return None
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    print(f"  {name:<32s} n={s['n']:>4d} net={s['net']:>+6.3f} PF={s['pf']:>5.2f} "
          f"WR={s['wr']*100:>4.1f}% posY={pos:>2d}/{tot:<2d} Sh={s['sh']:>+5.2f}")
    return ys


def spread_r(df, W, k, H, cost_s, cost_g, delay=0):
    z = ((df["gsr"] - df["gsr"].rolling(W).mean()) / (df["gsr"].rolling(W).std() + 1e-12)).values
    s_o = df["s_ret"].values; g_o = df["g_ret"].values; n = len(df)
    sp = pd.Series(s_o) - pd.Series(g_o)              # daily spread return (long S / short G)
    fwd = sp.shift(-1 - delay).rolling(H).sum().shift(-(H - 1)).values  # ret t+1+d .. t+H+d
    sig = np.where(z >= k, 1.0, np.where(z <= -k, -1.0, 0.0))          # z high -> ratio falls -> long spread
    cost = cost_s / df["s"].values + cost_g / df["g"].values
    r = np.where(sig != 0, sig * fwd - cost, np.nan)
    idx = np.zeros(n, bool); idx[::H] = True                          # non-overlap sampling
    return np.where(idx & (sig != 0), r, np.nan)


def main():
    df = load()
    yrs = df["year"].values
    print("=== GSR REVERSION — 20yr FULL BATTERY ===")
    print(f"days {len(df)}  {df['date'].min().date()}->{df['date'].max().date()}")
    print(f"GSR range {df['gsr'].min():.1f}..{df['gsr'].max():.1f} mean {df['gsr'].mean():.1f}\n")

    print("-- threshold monotonicity (W250, H5, cost s=3c g=65c) --")
    for k in (0.5, 1.0, 1.5, 2.0, 2.5):
        rep(f"W250 |z|>={k} H5", spread_r(df, 250, k, 5, 0.03, 0.65), yrs)

    print("\n-- horizon sweep (W250 |z|>=1.5) --")
    for H in (3, 5, 10, 20):
        rep(f"W250 |z|>=1.5 H{H}", spread_r(df, 250, 1.5, H, 0.03, 0.65), yrs)

    print("\n-- lookback sweep (|z|>=1.5 H5) --")
    for W in (120, 250, 500):
        rep(f"W{W} |z|>=1.5 H5", spread_r(df, W, 1.5, 5, 0.03, 0.65), yrs)

    print("\n-- IS/OOS (W250 |z|>=1.5 H5) --")
    r = spread_r(df, 250, 1.5, 5, 0.03, 0.65)
    rep("IS <=2015", np.where(yrs <= 2015, r, np.nan), yrs)
    rep("OOS 2016+", np.where(yrs >= 2016, r, np.nan), yrs)

    print("\n-- cost stress (silver spread, W250 |z|>=1.5 H5) --")
    for cs in (0.03, 0.05, 0.08, 0.12):
        rep(f"silver cost {cs*100:.0f}c", spread_r(df, 250, 1.5, 5, cs, 0.65), yrs)

    print("\n-- delay+1 robustness --")
    rep("W250 |z|>=1.5 H5 delay+1", spread_r(df, 250, 1.5, 5, 0.03, 0.65, delay=1), yrs)

    print("\n-- BOOTSTRAP (W250 |z|>=1.5 H5 vs random-entry spread) --")
    r = spread_r(df, 250, 1.5, 5, 0.03, 0.65)
    obs = st_(r); obs_sh = obs["sh"]; nsig = obs["n"]
    sp = (df["s_ret"] - df["g_ret"]).values
    fwd_all = pd.Series(sp).shift(-1).rolling(5).sum().shift(-4).values
    cost = 0.03 / df["s"].values + 0.65 / df["g"].values
    pool = fwd_all - cost
    pool = pool[~np.isnan(pool)]
    rng = np.random.default_rng(11); boot = []
    for _ in range(3000):
        samp = rng.choice(pool, size=nsig, replace=False)
        # random sign too
        sg = rng.choice([-1, 1], size=nsig)
        v = sg * samp
        boot.append(v.mean() / (v.std() + 1e-12) * np.sqrt(252))
    boot = np.array(boot)
    print(f"  obs Sharpe={obs_sh:.2f}  random |Sharpe| 95pct={np.percentile(np.abs(boot),95):.2f}  "
          f"P(|rand|>=obs)={(np.abs(boot)>=obs_sh).mean():.4f}")

    print("\n-- per-year (W250 |z|>=1.5 H5) --")
    ys = rep("final", r, yrs)


if __name__ == "__main__":
    main()
