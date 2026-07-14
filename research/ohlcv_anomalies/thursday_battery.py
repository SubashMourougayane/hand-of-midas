#!/usr/bin/env python3
"""Hostile battery on the GOLD THURSDAY EFFECT (Sharpe 1.70, 19/21yr gross).

Iron-clad audit (docs/EDGE_AUDIT_IRONCLAD.md):
 Gate 0  hostile: 5 DOW tested -> multiple-testing. Bootstrap the win.
 Gate 2  physical R / net-of-cost equity.
 Gate 3  causal: calendar known in advance (trivially). Entry Wed close, exit Thu close.
 Gate 4  per-year table + IS/OOS + per-regime (crisis vs calm) + kill condition.
 decompose: is it overnight (Wed->Thu open) or Thu intraday (open->close)?
 cost stress; delay; adjacent-day placebo (is Thursday special or is any day fine?).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

XAU_D1 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_D1_20060319_20260630.parquet"
M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
COST = 0.65


def load_d1():
    g = pd.read_parquet(XAU_D1)
    ts = pd.to_datetime(g["timestamp"])
    g["date"] = (ts.dt.tz_localize(None) if ts.dt.tz is not None else ts).dt.normalize()
    g = g[["date", "open", "high", "low", "close"]].sort_values("date").reset_index(drop=True)
    g["ret"] = np.log(g["close"] / g["close"].shift(1))
    g["year"] = g["date"].dt.year
    g["dow"] = g["date"].dt.dayofweek
    return g.dropna(subset=["ret"]).reset_index(drop=True)


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def stats(r):
    r = np.asarray(r, float); r = r[~np.isnan(r)]
    if len(r) == 0: return None
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(252)
    return dict(n=len(r), net=r.sum(), pf=pf(r), wr=(r > 0).mean(), sh=sh, mean=r.mean())


def rep(name, r, years):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    st = stats(r)
    if st is None: print(f"  {name:<28s} ZERO"); return
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    print(f"  {name:<28s} n={st['n']:>5d} net={st['net']:>+7.3f} PF={st['pf']:>5.2f} "
          f"WR={st['wr']*100:>4.1f}% posY={pos:>2d}/{tot:<2d} Sh={st['sh']:>+5.2f} "
          f"bp={st['mean']*1e4:>+6.1f}")
    return ys


def main():
    g = load_d1()
    yrs = g["year"].values
    cr = COST / g["close"].values
    print("=== THURSDAY EFFECT — HOSTILE BATTERY ===")
    print(f"days {len(g)}  {g['date'].min().date()}->{g['date'].max().date()}\n")

    thu = (g["dow"] == 3).values

    print("-- Gate 0: placebo — every DOW, net of cost (1 rt/wk) --")
    for d, nm in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"]):
        mask = (g["dow"] == d).values
        rep(f"long {nm} net", np.where(mask, g["ret"].values - cr, np.nan), yrs)

    print("\n-- Gate 2: Thursday net-of-cost per-year --")
    thu_ys = rep("Thu net", np.where(thu, g["ret"].values - cr, np.nan), yrs)

    print("\n-- Gate 4: IS/OOS split --")
    is_mask = g["year"] <= 2016
    rep("Thu IS (<=2016)", np.where(thu & is_mask.values, g["ret"].values - cr, np.nan), yrs)
    rep("Thu OOS (2017+)", np.where(thu & ~is_mask.values, g["ret"].values - cr, np.nan), yrs)

    print("\n-- Gate 0: BOOTSTRAP (is Sharpe 1.7 luck vs random day-picks?) --")
    thu_r = g["ret"].values[thu] - cr[thu]
    obs_sh = stats(thu_r)["sh"]
    # null: pick a random weekday label each week, same count
    allr = g["ret"].values - cr
    rng = np.random.default_rng(42)
    boot = []
    for _ in range(2000):
        samp = rng.choice(allr, size=len(thu_r), replace=False)
        boot.append(samp.mean() / (samp.std() + 1e-12) * np.sqrt(252))
    boot = np.array(boot)
    p = (boot >= obs_sh).mean()
    print(f"  Thu Sharpe={obs_sh:.2f}   random-day Sharpe mean={boot.mean():.2f} "
          f"95pct={np.percentile(boot,95):.2f}   P(random>=Thu)={p:.4f}")

    print("\n-- DECOMPOSE Thursday: overnight (Wed close->Thu open) vs Thu intraday --")
    # need Thu open. D1 open of the Thursday bar = Wed 17:00 NY ~ prior close. Use M5.
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    m5["ny_date"] = ny.dt.normalize(); m5["ny_hr"] = ny.dt.hour; m5["dow"] = ny.dt.dayofweek
    m5["year"] = ny.dt.year
    rows = []
    for d, gg in m5[(m5["ny_hr"] >= 8) & (m5["ny_hr"] < 17)].groupby("ny_date"):
        if len(gg) < 20: continue
        rows.append({"date": d, "dow": int(gg.iloc[0]["dow"]), "year": int(gg.iloc[0]["year"]),
                     "open": float(gg.iloc[0]["open"]), "close": float(gg.iloc[-1]["close"])})
    s = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    s["prev_close"] = s["close"].shift(1)
    s["overnight"] = np.log(s["open"] / s["prev_close"])   # into this session's open
    s["intraday"] = np.log(s["close"] / s["open"])
    thu_s = s["dow"] == 3
    rep("Thu overnight leg (gross)", s["overnight"].where(thu_s).values, s["year"].values)
    rep("Thu intraday leg (gross)", s["intraday"].where(thu_s).values, s["year"].values)
    # compare: Wed overnight, Wed intraday for context
    for d, nm in [(2, "Wed"), (1, "Tue"), (4, "Fri")]:
        m = s["dow"] == d
        rep(f"{nm} intraday (gross)", s["intraday"].where(m).values, s["year"].values)

    print("\n-- per-year Thursday net --")
    if thu_ys is not None:
        for y, v in thu_ys.items():
            print(f"    {int(y)}: {v:>+6.3f}")


if __name__ == "__main__":
    main()
