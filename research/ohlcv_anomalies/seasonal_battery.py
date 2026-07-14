#!/usr/bin/env python3
"""Full hostile battery on the GOLD SEASONAL overlay (strong-months long).

The critical risk: MONTH SELECTION = data-mining (6/12 months picked in-sample).
Defenses:
 1. Per-month table (which months carry it; is it 1-2 or broad?).
 2. A-PRIORI documented gold seasonality {Jan,Feb,Aug,Sep,Nov,Dec} (festival/wedding
    demand + Jan effect) vs my in-sample-optimized set -> agreement = not curve-fit.
 3. OUT-OF-SAMPLE SELECTION: rank months on 2006-2015, trade the top-K on 2016-2026.
    This is the decisive anti-datamining test.
 4. Independent series cross-check: same seasonality on GLD (yfinance) 2005-2026?
 5. Bootstrap, delay+1, cost stress.
All causal (calendar known in advance). Position long during selected months, net cost.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

XAU_D1 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_D1_20060319_20260630.parquet"
COST = 0.65


def load_xau():
    g = pd.read_parquet(XAU_D1)
    ts = pd.to_datetime(g["timestamp"])
    g["date"] = (ts.dt.tz_localize(None) if ts.dt.tz is not None else ts).dt.normalize()
    g = g[["date", "close"]].sort_values("date").reset_index(drop=True)
    g["ret"] = g["close"].pct_change()
    g["year"] = g["date"].dt.year
    g["month"] = g["date"].dt.month
    return g.dropna().reset_index(drop=True)


def load_gld():
    yf = pd.read_parquet("/tmp/macro_yf.parquet"); yf.index = pd.to_datetime(yf.index)
    s = yf["GLD"].dropna().reset_index(); s.columns = ["date", "close"]
    s["date"] = pd.to_datetime(s["date"])
    s["ret"] = s["close"].pct_change(); s["year"] = s["date"].dt.year; s["month"] = s["date"].dt.month
    return s.dropna().reset_index(drop=True)


def month_ret(g):
    """total log return per (year,month) and mean daily by month."""
    return g.groupby("month")["ret"].agg(["mean", "count"])


def strat_daily(g, months, cost=COST):
    pos = g["month"].isin(months).values.astype(float)
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    cr = cost / g["close"].values
    return pos * g["ret"].values - turn * cr


def perf(name, dret, g, mask=None):
    d = np.asarray(dret, float)
    yy = g["year"].values
    if mask is not None:
        d = np.where(mask, d, np.nan)
    m = ~np.isnan(d); dd = d[m]; yym = yy[m]
    if len(dd) == 0: print(f"  {name:<32s} ZERO"); return
    sh = dd.mean() / (dd.std() + 1e-12) * np.sqrt(252)
    eq = np.cumprod(1 + dd); peak = np.maximum.accumulate(eq); mdd = ((eq - peak) / peak).min()
    ys = pd.Series(dd).groupby(pd.Series(yym)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    cagr = eq[-1] ** (252 / len(dd)) - 1
    print(f"  {name:<32s} Sh={sh:>+5.2f} CAGR={cagr*100:>+6.1f}% maxDD={mdd*100:>+6.1f}% "
          f"posY={pos:>2d}/{tot:<2d}")


def main():
    g = load_xau()
    print("=== GOLD SEASONAL — HOSTILE BATTERY ===")
    print(f"days {len(g)}  {g['date'].min().date()}->{g['date'].max().date()}\n")

    print("-- 1. per-month mean daily return (bp), full sample --")
    mr = month_ret(g)
    names = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    for mo in range(1, 13):
        # per-year positive consistency for this month
        ym = g[g["month"] == mo].groupby("year")["ret"].sum()
        pos = int((ym > 0).sum()); tot = len(ym)
        print(f"    {names[mo-1]}  mean={mr.loc[mo,'mean']*1e4:>+6.1f}bp  posYrs={pos:>2d}/{tot}")

    print("\n-- 2. a-priori documented vs optimized month sets --")
    apriori = [1, 2, 8, 9, 11, 12]     # documented gold seasonal (festival/Jan)
    optimized = [1, 2, 7, 8, 11, 12]   # my in-sample pick
    perf("a-priori {1,2,8,9,11,12}", strat_daily(g, apriori), g)
    perf("optimized {1,2,7,8,11,12}", strat_daily(g, optimized), g)
    perf("buy&hold", g["ret"].values, g)

    print("\n-- 3. OUT-OF-SAMPLE SELECTION (rank on <=2015, trade 2016+) --")
    train = g[g["year"] <= 2015]
    rank = train.groupby("month")["ret"].mean().sort_values(ascending=False)
    for K in (4, 6, 8):
        sel = sorted(rank.head(K).index.tolist())
        oos_mask = (g["year"] >= 2016).values
        perf(f"top{K} IS-selected {sel}", strat_daily(g, sel), g, mask=oos_mask)
    print(f"    (IS top-6 months = {sorted(rank.head(6).index.tolist())})")

    print("\n-- 4. INDEPENDENT SERIES cross-check: GLD (yfinance) --")
    try:
        gld = load_gld()
        print(f"    GLD {gld['date'].min().date()}->{gld['date'].max().date()}")
        perf("GLD a-priori {1,2,8,9,11,12}", strat_daily(gld, apriori), gld)
        perf("GLD optimized {1,2,7,8,11,12}", strat_daily(gld, optimized), gld)
        perf("GLD buy&hold", gld["ret"].values, gld)
        # GLD per-month agreement
        gmr = gld.groupby("month")["ret"].mean() * 1e4
        agree = [mo for mo in range(1, 13) if (mr.loc[mo, "mean"] > 0) == (gmr.loc[mo] > 0)]
        print(f"    month-sign agreement XAU vs GLD: {len(agree)}/12 months")
    except Exception as e:
        print("    GLD check failed:", e)

    print("\n-- 5. delay+1 & cost stress (optimized set) --")
    # delay: shift position start by 1 trading day
    pos = g["month"].isin(optimized).shift(1, fill_value=False).values.astype(float)
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    dret = pos * g["ret"].values - turn * (COST / g["close"].values)
    perf("optimized delay+1", dret, g)
    for c in (0.30, 0.65, 1.20):
        perf(f"optimized cost ${c}", strat_daily(g, optimized, cost=c), g)

    print("\n-- 6. bootstrap: seasonal Sharpe vs random 6-month sets --")
    obs = strat_daily(g, optimized); obs = obs[~np.isnan(obs)]
    obs_sh = obs.mean() / obs.std() * np.sqrt(252)
    rng = np.random.default_rng(3); boot = []
    for _ in range(3000):
        rs = rng.choice(range(1, 13), size=6, replace=False)
        d = strat_daily(g, list(rs)); d = d[~np.isnan(d)]
        boot.append(d.mean() / d.std() * np.sqrt(252))
    boot = np.array(boot)
    print(f"    optimized Sharpe={obs_sh:.2f}  random-6mo mean={boot.mean():.2f} "
          f"95pct={np.percentile(boot,95):.2f}  P(rand>=obs)={(boot>=obs_sh).mean():.4f}")


if __name__ == "__main__":
    main()
