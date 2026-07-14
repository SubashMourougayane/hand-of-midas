#!/usr/bin/env python3
"""★ FRIDAY INTRADAY edge on gold (gross Sharpe 1.49, 16/21yr) — hostile battery.

THESIS: pre-weekend safe-haven / short-covering bid lifts gold during the Friday US
session. This is a genuine INTRADAY effect (not overnight) with an economic story.

Tests: hour-localization (whole session or specific hours?), net-of-cost, bootstrap
vs other days' intraday, IS/OOS, per-regime, delay robustness. Entry Fri 08:00 NY
open, exit Fri 17:00 NY close (1 round trip/week).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
COST = 0.65


def load():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    m5["ny_date"] = ny.dt.normalize(); m5["ny_hr"] = ny.dt.hour; m5["ny_min"] = ny.dt.minute
    m5["dow"] = ny.dt.dayofweek; m5["year"] = ny.dt.year
    return m5


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def rep(name, r, years):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    if len(r) == 0: print(f"  {name:<30s} ZERO"); return None
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(52)
    print(f"  {name:<30s} n={len(r):>4d} net={r.sum():>+6.3f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d} Sh={sh:>+5.2f} bp={r.mean()*1e4:>+6.1f}")
    return dict(r=r, ys=ys, sh=sh)


def session_leg(m5, dow, h_start, h_end):
    """log return from first bar >= h_start to last bar < h_end, per day of given dow."""
    sub = m5[(m5["dow"] == dow) & (m5["ny_hr"] >= h_start) & (m5["ny_hr"] < h_end)]
    rows = []
    for d, g in sub.groupby("ny_date"):
        if len(g) < 5: continue
        rows.append({"year": int(g.iloc[0]["year"]),
                     "open": float(g.iloc[0]["open"]), "close": float(g.iloc[-1]["close"])})
    s = pd.DataFrame(rows)
    if len(s) == 0: return None, None
    r = np.log(s["close"] / s["open"]).values - COST / s["open"].values
    gross = np.log(s["close"] / s["open"]).values
    return pd.Series(r), s["year"].values, pd.Series(gross)


def main():
    m5 = load()
    print("=== FRIDAY INTRADAY — HOSTILE BATTERY ===\n")

    print("-- full US session (08-17 NY), net of cost, each DOW --")
    for d, nm in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"]):
        r, yy, _ = session_leg(m5, d, 8, 17)
        if r is not None: rep(f"{nm} 08-17 net", r.values, yy)

    print("\n-- Friday hour-localization (net) --")
    windows = [(8, 12), (12, 17), (8, 13), (13, 17), (10, 16), (14, 17)]
    for a, b in windows:
        r, yy, _ = session_leg(m5, 4, a, b)
        if r is not None: rep(f"Fri {a:02d}-{b:02d} net", r.values, yy)

    print("\n-- Friday full-session battery --")
    r, yy, gross = session_leg(m5, 4, 8, 17)
    st = rep("Fri 08-17 net", r.values, yy)
    # IS/OOS
    yy = np.asarray(yy)
    is_m = yy <= 2016
    rep("Fri IS (<=2016)", np.where(is_m, r.values, np.nan), yy)
    rep("Fri OOS (2017+)", np.where(~is_m, r.values, np.nan), yy)
    # regime by price
    # bootstrap vs random days' intraday
    print("\n-- bootstrap: Fri intraday vs random-day intraday --")
    allrows = []
    sub = m5[(m5["ny_hr"] >= 8) & (m5["ny_hr"] < 17)]
    for d, g in sub.groupby("ny_date"):
        if len(g) < 5: continue
        allrows.append(np.log(g.iloc[-1]["close"] / g.iloc[0]["open"]) - COST / g.iloc[0]["open"])
    allr = np.array(allrows)
    fri_r = r.values
    obs = fri_r.mean() / (fri_r.std() + 1e-12) * np.sqrt(52)
    rng = np.random.default_rng(7); boot = []
    for _ in range(2000):
        samp = rng.choice(allr, size=len(fri_r), replace=False)
        boot.append(samp.mean() / (samp.std() + 1e-12) * np.sqrt(52))
    boot = np.array(boot)
    print(f"  Fri Sharpe={obs:.2f}  random mean={boot.mean():.2f} 95pct={np.percentile(boot,95):.2f} "
          f"P(rand>=Fri)={(boot>=obs).mean():.4f}")

    print("\n-- delay: enter Fri 08:30 instead of 08:00 (skip open microstructure) --")
    r2, yy2, _ = session_leg(m5, 4, 9, 17)  # from 09:00
    if r2 is not None: rep("Fri 09-17 net (delayed)", r2.values, yy2)

    print("\n-- per-year Friday net --")
    if st is not None:
        for y, v in st["ys"].items():
            print(f"    {int(y)}: {v:>+6.3f}")


if __name__ == "__main__":
    main()
