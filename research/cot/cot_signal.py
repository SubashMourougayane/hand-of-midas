#!/usr/bin/env python3
"""S2 — COT positioning signal on gold.

THESIS: speculative (noncommercial) net-long at a percentile EXTREME = crowded ->
contrarian reversal; commercials (producers/hedgers, "smart money") are the other
side. Alternatively spec positioning momentum = trend confirmation. Test both.

POINT-IN-TIME (critical): COT reports Tuesday positions, RELEASED Friday 3:30pm ET.
So a Tuesday-dated report is only tradeable from the NEXT Monday. We lag the signal
by 1 full week (shift the weekly series, then trade the following week's gold).

Data: CFTC legacy GOLD (COMEX) weekly + OANDA XAU D1. Weekly rebalance, hold H weeks.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

XAU_D1 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_D1_20060319_20260630.parquet"
COST = 0.65


def load():
    c = pd.read_parquet("/tmp/cot_gold_raw.parquet")
    c["date"] = pd.to_datetime(c["report_date_as_yyyy_mm_dd"]).dt.normalize()
    for col in ["noncomm_positions_long_all", "noncomm_positions_short_all",
                "comm_positions_long_all", "comm_positions_short_all", "open_interest_all"]:
        c[col] = pd.to_numeric(c[col], errors="coerce")
    c = c.sort_values("date").reset_index(drop=True)
    c["nc_net"] = c["noncomm_positions_long_all"] - c["noncomm_positions_short_all"]
    c["nc_net_pct_oi"] = c["nc_net"] / c["open_interest_all"]
    # POINT-IN-TIME: shift weekly so the value is only known the FOLLOWING week
    c["nc_net_pct_oi_known"] = c["nc_net_pct_oi"].shift(1)
    c["release_date"] = c["date"] + pd.Timedelta(days=3)  # Tue report -> Fri release
    # tradeable from the Monday after release
    c["tradeable_from"] = c["release_date"] + pd.Timedelta(days=3)
    c = c[c["date"] >= "2006-01-01"].reset_index(drop=True)
    # z-score / percentile of the KNOWN value over trailing 3yr (156 wk)
    s = c["nc_net_pct_oi_known"]
    c["z"] = (s - s.rolling(156, min_periods=52).mean()) / (s.rolling(156, min_periods=52).std() + 1e-12)
    c["pct"] = s.rolling(156, min_periods=52).apply(lambda w: (w.iloc[-1] > w[:-1]).mean() if len(w) > 1 else np.nan)
    c["dz"] = c["nc_net_pct_oi_known"] - c["nc_net_pct_oi_known"].shift(4)  # 4wk change

    g = pd.read_parquet(XAU_D1)
    ts = pd.to_datetime(g["timestamp"])
    g["date"] = (ts.dt.tz_localize(None) if ts.dt.tz is not None else ts).dt.normalize()
    g = g[["date", "close"]].sort_values("date").reset_index(drop=True)
    return c, g


def gold_fwd(g, from_date, weeks):
    """gold log return from first trading day >= from_date, held `weeks` weeks."""
    gi = g[g["date"] >= from_date]
    if len(gi) == 0: return np.nan
    p0 = gi["close"].iloc[0]
    tgt = from_date + pd.Timedelta(weeks=weeks)
    gj = g[g["date"] >= tgt]
    if len(gj) == 0: return np.nan
    return np.log(gj["close"].iloc[0] / p0), p0


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def rep(name, rows):
    if not rows: print(f"  {name:<34s} ZERO"); return
    df = pd.DataFrame(rows, columns=["year", "r"])
    r = df["r"].values
    ys = df.groupby("year")["r"].sum(); pos = int((ys > 0).sum()); tot = len(ys)
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(52)
    print(f"  {name:<34s} n={len(r):>4d} net={r.sum():>+6.3f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d} Sh={sh:>+5.2f}")


def run(c, g, side_fn, hold, name):
    rows = []
    for _, row in c.iterrows():
        sig = side_fn(row)
        if sig == 0 or pd.isna(sig): continue
        res = gold_fwd(g, row["tradeable_from"], hold)
        if res is np.nan or (isinstance(res, float) and np.isnan(res)): continue
        fr, p0 = res
        rows.append((row["tradeable_from"].year, sig * fr - COST / p0))
    rep(f"{name} hold{hold}w", rows)


def main():
    c, g = load()
    print("=== S2 COT POSITIONING (gold, Fri-release lag) ===")
    print(f"weeks {len(c)}  {c['date'].min().date()}->{c['date'].max().date()}\n")

    print("-- CONTRARIAN: fade spec extremes (z) --")
    for k in (1.0, 1.5, 2.0):
        for h in (1, 2, 4):
            run(c, g, lambda r, k=k: -1.0 if r["z"] >= k else (1.0 if r["z"] <= -k else 0.0), h, f"fade |z|>={k}")

    print("\n-- FOLLOW: trade with spec positioning change (momentum) --")
    for h in (1, 2, 4):
        run(c, g, lambda r: np.sign(r["dz"]) if not pd.isna(r["dz"]) else 0.0, h, "follow dz")

    print("\n-- CONTRARIAN by percentile extreme --")
    for h in (1, 2, 4):
        run(c, g, lambda r: -1.0 if r["pct"] >= 0.9 else (1.0 if r["pct"] <= 0.1 else 0.0), h, "fade pct 10/90")

    print("\n-- benchmark: always long gold, weekly --")
    run(c, g, lambda r: 1.0, 1, "buy&hold")


if __name__ == "__main__":
    main()
