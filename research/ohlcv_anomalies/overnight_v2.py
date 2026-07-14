#!/usr/bin/env python3
"""B1 v2 — monetize the overnight drift. B1 proved gold's gross return is
overnight-concentrated (+1.86 of +1.98 log B&H); intraday is flat (+0.58).
The only enemy is turnover cost (2 round-trips/day). Tests to reduce it:

 1. COST STRESS: $0.20 / 0.30 / 0.65 / 0.80 round-trip — where does it flip?
 2. REGIME (cost_r): only trade overnight when $cost / price < threshold
    (i.e. gold expensive enough that spread is small) — same lever as our edge.
 3. TREND FILTER: only hold overnight when above a slow MA (drift + trend).
 4. REDUCED TURNOVER: hold-through variants (skip re-entry) to cut cost.
 5. VOL-NORMALIZED SIZING placeholder (report gross Sharpe of overnight leg).

All causal: signal from the close bar (entry), exit next open. No future peek.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
OPEN_HR, CLOSE_HR = 8, 17


def load_sessions():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    m5["ny_date"] = ny.dt.normalize(); m5["ny_hr"] = ny.dt.hour; m5["dow"] = ny.dt.dayofweek
    rows = []
    for d, g in m5.groupby("ny_date", sort=True):
        o = g[g["ny_hr"] >= OPEN_HR]; c = g[g["ny_hr"] < CLOSE_HR]
        if len(o) == 0 or len(c) == 0: continue
        rows.append({"date": d, "dow": int(c.iloc[-1]["dow"]),
                     "open_px": float(o.iloc[0]["open"]), "close_px": float(c.iloc[-1]["close"])})
    s = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    s["year"] = s["date"].dt.year
    s["next_open_px"] = s["open_px"].shift(-1)
    s["gap_days"] = (s["date"].shift(-1) - s["date"]).dt.days
    # slow trend proxy: 50-session MA of close, LAGGED (known at close entry)
    s["ma50"] = s["close_px"].rolling(50).mean().shift(1)
    s["ma20"] = s["close_px"].rolling(20).mean().shift(1)
    return s.dropna(subset=["next_open_px"]).reset_index(drop=True)


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def stats(r, years):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    if len(r) == 0: return None
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    net = r.sum(); sharpe = r.mean() / (r.std() + 1e-12) * np.sqrt(252)
    eq = r.cumsum(); dd = float((eq - np.maximum.accumulate(eq)).min())
    return dict(n=len(r), net=net, pf=pf(r), wr=(r > 0).mean(), pos=pos, tot=tot,
                sharpe=sharpe, dd=dd, ys=ys)


def line(name, st):
    if st is None: print(f"  {name:<34s} ZERO"); return
    print(f"  {name:<34s} n={st['n']:>5d} netLog={st['net']:>+7.3f} PF={st['pf']:>5.2f} "
          f"WR={st['wr']*100:>4.1f}% posY={st['pos']:>2d}/{st['tot']:<2d} "
          f"Sh={st['sharpe']:>+5.2f} DD={st['dd']:>+6.3f}")


def overnight_r(s, cost, mask=None):
    r = np.log(s["next_open_px"] / s["close_px"]).values - cost / s["close_px"].values
    if mask is not None:
        r = np.where(mask.values, r, np.nan)
    return r


def main():
    s = load_sessions(); yrs = s["year"].values
    print("=== B1 v2 — MONETIZE OVERNIGHT DRIFT ===")
    print(f"sessions {len(s)}  {s['date'].min().date()}->{s['date'].max().date()}\n")

    print("-- 1. COST STRESS (overnight long, all days) --")
    for c in (0.20, 0.30, 0.45, 0.65, 0.80):
        line(f"cost ${c:.2f}", stats(overnight_r(s, c), yrs))
    gross = stats(overnight_r(s, 0.0), yrs)
    line("cost $0.00 (GROSS)", gross)

    print("\n-- 2. REGIME (cost_r = cost/price) filter @ $0.65 --")
    px = s["close_px"].values
    for thr in (0.0002, 0.0003, 0.0004, 0.0006):  # 0.65/price fractions
        mask = pd.Series((0.65 / px) <= thr)
        line(f"cost_r <= {thr:.4f} (px>=${0.65/thr:.0f})", stats(overnight_r(s, 0.65, mask), yrs))

    print("\n-- 3. TREND FILTER (overnight only if close>MA, $0.65) --")
    line("close>MA20", stats(overnight_r(s, 0.65, s["close_px"] > s["ma20"]), yrs))
    line("close>MA50", stats(overnight_r(s, 0.65, s["close_px"] > s["ma50"]), yrs))
    line("MA20>MA50 (uptrend)", stats(overnight_r(s, 0.65, s["ma20"] > s["ma50"]), yrs))

    print("\n-- 4. TREND x REGIME combo ($0.65) --")
    combo = (s["close_px"] > s["ma50"]) & (pd.Series((0.65 / px) <= 0.0004))
    line("close>MA50 & px>=$1625", stats(overnight_r(s, 0.65, combo), yrs))
    combo2 = (s["ma20"] > s["ma50"]) & (pd.Series((0.65 / px) <= 0.0004))
    line("MA20>MA50 & px>=$1625", stats(overnight_r(s, 0.65, combo2), yrs))

    print("\n-- 5. MODERN REGIME only (2020+, $0.65) --")
    m20 = s["year"] >= 2020
    line("2020+ all overnight", stats(overnight_r(s, 0.65, m20), yrs))
    line("2020+ & close>MA50", stats(overnight_r(s, 0.65, m20 & (s["close_px"] > s["ma50"])), yrs))

    print("\n-- per-year GROSS overnight (economic drift, no cost) --")
    for y, v in gross["ys"].items():
        print(f"    {int(y)}: {v:>+7.3f}")


if __name__ == "__main__":
    main()
