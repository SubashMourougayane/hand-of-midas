#!/usr/bin/env python3
"""Honest-leg library v2 — conditional / vol-state / post-move legs (bigger per-trade
moves => survive higher cost). All no-stop, real-return, both directions. Greedy
portfolio maximizing Sharpe at up to 5 tpd, reported at cost 0.30 AND 0.65.
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
    rows = []
    for d, g in m5.groupby("d", sort=True):
        us = g[(g["h"] >= 8) & (g["h"] < 17)]
        if len(us) < 10: continue
        c12 = us[us["h"] == 12]
        rows.append({"date": d, "dow": int(us.iloc[0]["dow"]),
                     "o8": float(us.iloc[0]["open"]), "c16": float(us.iloc[-1]["close"]),
                     "hi": float(us["high"].max()), "lo": float(us["low"].min()),
                     "c12": float(c12.iloc[-1]["close"]) if len(c12) else np.nan})
    s = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    s["year"] = s["date"].dt.year; s["month"] = s["date"].dt.month
    s["tdom"] = s.groupby([s["date"].dt.year, s["date"].dt.month]).cumcount() + 1
    dim = s.groupby([s["date"].dt.year, s["date"].dt.month])["date"].transform("count")
    s["tom"] = (dim - s["tdom"] <= 1) | (s["tdom"] <= 3)
    s["next_o8"] = s["o8"].shift(-1)
    s["ma200"] = s["c16"].rolling(200).mean().shift(1)
    s["sess_ret"] = np.log(s["c16"] / s["o8"])
    s["range"] = (s["hi"] - s["lo"]) / s["c16"]
    s["atr20"] = s["range"].rolling(20).mean().shift(1)          # vol state (lagged)
    s["prev_sess"] = s["sess_ret"].shift(1)                       # yesterday's session (known)
    s["prev_on"] = np.log(s["o8"] / s["c16"].shift(1))            # last overnight (known at open)
    return s.dropna(subset=["next_o8", "ma200", "atr20"]).reset_index(drop=True)


def sharpe(r):
    r = r[~np.isnan(r)]; return r.mean() / (r.std() + 1e-12) * np.sqrt(252) if len(r) else 0


def main():
    s = load(); px = s["c16"].values; o8 = s["o8"].values; yrs = s["year"].values
    up = (s["c16"] > s["ma200"]).values; dn = ~up
    strong = s["month"].isin([1, 2, 7, 8, 11, 12]).values
    tom = s["tom"].values
    hivol = (s["range"] > s["atr20"] * 1.3).values     # today high-vol (using lagged atr, but range is same-day -> use prev)
    hivol = (s["atr20"] > np.nanmedian(s["atr20"])).values  # vol REGIME (lagged, causal)
    ln = lambda a, b: np.log(a / b)
    span = (pd.to_datetime(s["date"].iloc[-1]) - pd.to_datetime(s["date"].iloc[0])).days / 365.25
    overnight = ln(s["next_o8"].values, s["c16"].values)
    session = s["sess_ret"].values
    morning = ln(s["c12"].values, s["o8"].values)
    C = 0.30
    def mk(sig, ret, base, c=C): return np.where(sig, ret, np.nan) - np.where(sig, c / base, 0)

    # post-move conditioning (mean-reversion / continuation), causal (prev day known)
    big_down = (s["prev_sess"].values < -0.008)     # yesterday fell >0.8%
    big_up = (s["prev_sess"].values > 0.008)
    gap_up = (s["prev_on"].values > 0.003)          # gapped up into today's open
    gap_dn = (s["prev_on"].values < -0.003)

    legs = {
        "L_on_strMo": mk(strong, overnight, px),
        "L_on_tom": mk(tom & up, overnight, px),
        "S_morn_dn": mk(dn, -morning, o8),
        # NEW conditional legs (bigger moves):
        "L_sess_postdown": mk(big_down, session, o8),       # bounce after big down day
        "S_sess_postup_dn": mk(big_up & dn, -session, o8),  # fade after big up in downtrend
        "L_on_hivol_str": mk(strong & hivol, overnight, px),
        "S_sess_gapup_dn": mk(gap_up & dn, -session, o8),   # gap-up fade in downtrend
        "L_sess_gapdn_up": mk(gap_dn & up, session, o8),    # gap-down recover in uptrend
        "S_morn_postup": mk(big_up, -morning, o8),
        "L_on_postdown": mk(big_down, overnight, px),
    }
    print("=== honest leg library v2 (conditional, cost 0.30) ===")
    scored = {}
    for nm, r in legs.items():
        rr = r[~np.isnan(r)]; yy = yrs[~np.isnan(r)]
        if len(rr) < 150: continue
        sh = sharpe(rr); osh = sharpe(rr[yy >= 2016]); ys = pd.Series(rr).groupby(pd.Series(yy)).sum()
        # cost 0.65 version
        base = px if nm.startswith("L_on") else o8
        r65 = np.where(~np.isnan(r), r + C/np.where(np.isnan(r),1,base if base is px else o8) - 0.65/(base if base is px else o8), np.nan)
        sh65 = sharpe(r65[~np.isnan(r65)])
        print(f"  {nm:<20} n={len(rr):>4d} tpd={len(rr)/(span*252):.2f} Sh={sh:>+5.2f} OOS={osh:>+5.2f} "
              f"Sh65={sh65:>+5.2f} posY={int((ys>0).sum())}/{len(ys)}")
        if sh > 0.3 and osh > 0.25:
            scored[nm] = r
    # greedy portfolio
    print("\n=== greedy portfolio (max Sharpe, <=5 tpd) ===")
    chosen = []; best = 0; rem = list(scored.keys())
    def comb(sel):
        M = np.vstack([scored[n] for n in sel]); arr = np.nansum(M, axis=0); cnt = np.sum(~np.isnan(M), axis=0)
        r = arr[cnt > 0]; yy = yrs[cnt > 0]
        tpd = np.sum([np.sum(~np.isnan(scored[n])) for n in sel])/(span*252)
        return r, yy, tpd
    while rem:
        c = None; cs = best
        for n in rem:
            r, yy, tpd = comb(chosen+[n])
            if tpd <= 5 and sharpe(r) > cs: cs = sharpe(r); c = n
        if c is None: break
        chosen.append(c); rem.remove(c); best = cs
        r, yy, tpd = comb(chosen); ys = pd.Series(r).groupby(pd.Series(yy)).sum()
        print(f"  +{c:<20} {len(chosen)}legs tpd={tpd:.2f} Sh={best:.2f} OOS={sharpe(r[yy>=2016]):.2f} "
              f"posY={int((ys>0).sum())}/{len(ys)} ret={(np.exp(r.sum())-1)*100:+.0f}%")


if __name__ == "__main__":
    main()
