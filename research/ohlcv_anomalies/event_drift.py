#!/usr/bin/env python3
"""Scheduled-event drift on gold. Economic basis: gold reacts to macro releases;
documented 'pre-event drift' (positioning ahead of scheduled data) and event-day
moves. Test what we can derive EXACTLY from the calendar:
  - NFP = first Friday of month (US jobs). Test NFP-day intraday + the day before.
  - CPI window ~ trading-day 8-10 of month (BLS releases ~mid-month). Rough.
  - FOMC weeks approximated by month-position not available exactly -> skip exact.

CAUSAL: event date known far in advance. Entry session open, exit session close
(intraday) or prior-close->open (overnight/pre-drift). Net of cost. Per-year + OOS.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
COST = 0.65


def load():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    m5["ny_date"] = ny.dt.normalize(); m5["ny_hr"] = ny.dt.hour
    m5["dow"] = ny.dt.dayofweek; m5["year"] = ny.dt.year
    rows = []
    for d, g in m5[(m5["ny_hr"] >= 8) & (m5["ny_hr"] < 17)].groupby("ny_date"):
        if len(g) < 20: continue
        # pre-8:30 (jobs release) vs post
        pre = g[g["ny_hr"] == 8]
        rows.append({"date": d, "dow": int(g.iloc[0]["dow"]), "year": int(g.iloc[0]["year"]),
                     "open": float(g.iloc[0]["open"]), "close": float(g.iloc[-1]["close"]),
                     "h830": float(pre.iloc[-1]["close"]) if len(pre) else np.nan})
    s = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    s["prev_close"] = s["close"].shift(1)
    s["overnight"] = np.log(s["open"] / s["prev_close"])
    s["intraday"] = np.log(s["close"] / s["open"])
    s["tdom"] = s.groupby([s["date"].dt.year, s["date"].dt.month]).cumcount() + 1
    # NFP = first Friday
    s["is_fri"] = s["dow"] == 4
    s["month"] = s["date"].dt.month
    first_fri_idx = s[s["is_fri"]].groupby([s["date"].dt.year, s["date"].dt.month]).head(1).index
    s["nfp"] = False; s.loc[first_fri_idx, "nfp"] = True
    s["pre_nfp"] = s["nfp"].shift(-1, fill_value=False)  # day before NFP
    return s


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def rep(name, r, years):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    if len(r) == 0: print(f"  {name:<30s} ZERO"); return
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(252)
    oos = np.asarray(yy) >= 2017
    sho = r[oos].mean()/(r[oos].std()+1e-12)*np.sqrt(252) if oos.sum() > 20 else np.nan
    print(f"  {name:<30s} n={len(r):>4d} net={r.sum():>+6.3f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d} Sh={sh:>+5.2f} ShOOS={sho:>+5.2f} bp={r.mean()*1e4:>+6.1f}")


def main():
    s = load()
    yrs = s["year"].values
    cr = COST / s["open"].values
    crn = COST / s["prev_close"].values
    print("=== SCHEDULED-EVENT DRIFT (gold) ===")
    print(f"sessions {len(s)}  NFP days {s['nfp'].sum()}\n")

    print("-- NFP day (first Friday) --")
    rep("NFP intraday net", np.where(s["nfp"].values, s["intraday"].values - cr, np.nan), yrs)
    rep("NFP overnight net", np.where(s["nfp"].values, s["overnight"].values - crn, np.nan), yrs)
    rep("NFP pre-830 (open->830)", np.where(s["nfp"].values, (np.log(s["h830"]/s["open"]) - cr).values, np.nan), yrs)
    rep("NFP post-830 (830->close)", np.where(s["nfp"].values, (np.log(s["close"]/s["h830"]) - cr).values, np.nan), yrs)

    print("\n-- day BEFORE NFP (pre-event drift) --")
    rep("pre-NFP intraday net", np.where(s["pre_nfp"].values, s["intraday"].values - cr, np.nan), yrs)
    rep("pre-NFP overnight net", np.where(s["pre_nfp"].values, s["overnight"].values - crn, np.nan), yrs)

    print("\n-- CPI window proxy (trading-day 8-10) --")
    cpi = ((s["tdom"] >= 8) & (s["tdom"] <= 10)).values
    rep("CPI-window intraday net", np.where(cpi, s["intraday"].values - cr, np.nan), yrs)
    rep("CPI-window overnight net", np.where(cpi, s["overnight"].values - crn, np.nan), yrs)

    print("\n-- non-NFP Fridays (is Friday effect just NFP?) --")
    nonfri = s["is_fri"].values & ~s["nfp"].values
    rep("non-NFP Fri intraday", np.where(nonfri, s["intraday"].values - cr, np.nan), yrs)


if __name__ == "__main__":
    main()
