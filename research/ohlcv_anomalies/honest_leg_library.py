#!/usr/bin/env python3
"""Honest-leg library: test MANY no-stop, real-return legs (overnight, session,
hour-slices, calendar), both directions, honest execution. Then greedily build the
best UNCORRELATED portfolio at 1-5 trades/day. No stop => no execution artifact.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"


def load():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    m5["d"] = ny.dt.normalize(); m5["h"] = ny.dt.hour; m5["dow"] = ny.dt.dayofweek
    # price at key NY hours per day
    rows = []
    for d, g in m5.groupby("d", sort=True):
        gh = {h: g[g["h"] == h] for h in (8, 10, 12, 14, 16)}
        def px(h, which):
            x = gh[h]
            if len(x) == 0: return np.nan
            return float(x.iloc[0]["open"]) if which == "o" else float(x.iloc[-1]["close"])
        us = g[(g["h"] >= 8) & (g["h"] < 17)]
        if len(us) < 10: continue
        rows.append({"date": d, "dow": int(us.iloc[0]["dow"]),
                     "o8": float(us.iloc[0]["open"]), "c16": float(us.iloc[-1]["close"]),
                     "c10": px(10, "c"), "c12": px(12, "c"), "c14": px(14, "c")})
    s = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    s["year"] = s["date"].dt.year; s["month"] = s["date"].dt.month
    s["tdom"] = s.groupby([s["date"].dt.year, s["date"].dt.month]).cumcount() + 1
    dim = s.groupby([s["date"].dt.year, s["date"].dt.month])["date"].transform("count")
    s["tdom_end"] = dim - s["tdom"] + 1
    s["next_o8"] = s["o8"].shift(-1)
    s["ma200"] = s["c16"].rolling(200).mean().shift(1)
    return s.dropna(subset=["next_o8", "ma200"]).reset_index(drop=True)


def sharpe(r):
    r = r[~np.isnan(r)]
    return r.mean() / (r.std() + 1e-12) * np.sqrt(252) if len(r) else 0


def main():
    s = load(); px = s["c16"].values; yrs = s["year"].values
    up = (s["c16"] > s["ma200"]).values; dn = ~up
    strong = s["month"].isin([1, 2, 7, 8, 11, 12]).values
    tom = ((s["tdom_end"] <= 2) | (s["tdom"] <= 3)).values
    C = 0.30
    ln = lambda a, b: np.log(a / b)
    span = (pd.to_datetime(s["date"].iloc[-1]) - pd.to_datetime(s["date"].iloc[0])).days / 365.25

    overnight = ln(s["next_o8"].values, s["c16"].values)
    session = ln(s["c16"].values, s["o8"].values)
    morning = ln(s["c12"].values, s["o8"].values)      # 8->12
    afternoon = ln(s["c16"].values, s["c12"].values)   # 12->16
    thu = (s["dow"] == 3).values

    # leg library: (name, per-day return array with NaN where inactive)
    def mk(sig, ret, base): return np.where(sig, ret, np.nan) - np.where(sig, C / base, 0)
    legs = {
        "L_overnight_strMo": mk(strong, overnight, px),
        "L_overnight_up": mk(up, overnight, px),
        "L_overnight_thu": mk(thu, overnight, px),
        "L_overnight_tom": mk(tom, overnight, px),
        "S_session_dn": mk(dn, -session, s["o8"].values),
        "L_session_up": mk(up, session, s["o8"].values),
        "S_afternoon_dn": mk(dn, -afternoon, s["c12"].values),
        "L_morning_up": mk(up, morning, s["o8"].values),
        "S_morning_dn": mk(dn, -morning, s["o8"].values),
        "L_afternoon_up": mk(up, afternoon, s["c12"].values),
    }
    print("=== honest leg library (no stop, real return, cost $0.30) ===")
    scored = {}
    for nm, r in legs.items():
        rr = r[~np.isnan(r)]; yy = yrs[~np.isnan(r)]
        if len(rr) < 200: continue
        oos = yy >= 2016
        sh = sharpe(rr); osh = sharpe(rr[oos])
        ys = pd.Series(rr).groupby(pd.Series(yy)).sum()
        tpd = len(rr) / (span * 252)
        print(f"  {nm:<22} n={len(rr):>4d} tpd={tpd:.2f} Sh={sh:>+5.2f} OOS={osh:>+5.2f} "
              f"posY={int((ys>0).sum())}/{len(ys)} sum={rr.sum():+.2f}")
        if sh > 0.3 and osh > 0.2:
            scored[nm] = r

    # greedy uncorrelated portfolio: maximize combined Sharpe
    print("\n=== greedy best portfolio (honest legs, maximize Sharpe) ===")
    chosen = []
    names = list(scored.keys())
    def combined(sel):
        M = np.vstack([scored[n] for n in sel])
        arr = np.nansum(M, axis=0); cnt = np.sum(~np.isnan(M), axis=0)
        r = arr[cnt > 0]; yy = yrs[cnt > 0]
        tpd = np.sum([np.sum(~np.isnan(scored[n])) for n in sel]) / (span * 252)
        return r, yy, tpd
    best_sh = 0
    remaining = names[:]
    while remaining:
        cand = None; cand_sh = best_sh
        for n in remaining:
            r, yy, tpd = combined(chosen + [n])
            sh = sharpe(r)
            if sh > cand_sh and tpd <= 5:
                cand_sh = sh; cand = n
        if cand is None: break
        chosen.append(cand); remaining.remove(cand); best_sh = cand_sh
        r, yy, tpd = combined(chosen)
        oos = yy >= 2016; ys = pd.Series(r).groupby(pd.Series(yy)).sum()
        print(f"  + {cand:<22} -> {len(chosen)} legs, tpd={tpd:.2f} Sh={best_sh:.2f} "
              f"OOS={sharpe(r[oos]):.2f} posY={int((ys>0).sum())}/{len(ys)} ret={(np.exp(r.sum())-1)*100:+.0f}%")


if __name__ == "__main__":
    main()
