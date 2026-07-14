#!/usr/bin/env python3
"""Overnight-drift edge v3 — re-examined at REALISTIC ECN cost + regime gating.

User instinct: $0.65 retail spread + full-20yr-sample may be TOO strict and burying
a real edge. Gold's drift is overnight-concentrated (proven). At tight ECN cost and
in the modern (expensive-gold) regime, overnight capture is positive. Quantify it
properly and build the biggest HONEST deployable version (levered, vol-targeted).

Causality kept STRICT (enter US close, exit next open, no peek). Only COST and
REGIME assumptions are relaxed to match real execution.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
OPEN_HR, CLOSE_HR = 8, 17


def load_sessions():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
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
    s["year"] = s["date"].dt.year; s["month"] = s["date"].dt.month
    s["next_open"] = s["open_px"].shift(-1)
    s["on_ret"] = np.log(s["next_open"] / s["close_px"])   # overnight simple-ish log
    s["ma50"] = s["close_px"].rolling(50).mean().shift(1)
    return s.dropna(subset=["next_open"]).reset_index(drop=True)


def perf(name, dret, years, start=5000.0):
    d = np.asarray(dret, float); m = ~np.isnan(d); d = d[m]; yy = np.asarray(years)[m]
    if len(d) == 0: print(f"  {name:<34s} ZERO"); return
    sh = d.mean() / (d.std() + 1e-12) * np.sqrt(252)
    eq = start * np.cumprod(1 + d); peak = np.maximum.accumulate(eq); mdd = ((eq - peak)/peak).min()
    ys = pd.Series(d).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    cagr = (eq[-1]/start) ** (252/len(d)) - 1
    mar = cagr/abs(mdd) if mdd else 0
    print(f"  {name:<34s} Sh={sh:>+5.2f} CAGR={cagr*100:>+6.1f}% mDD={mdd*100:>+6.1f}% "
          f"MAR={mar:>+4.2f} posY={pos:>2d}/{tot:<2d} ${start:,.0f}->${eq[-1]:,.0f}")


def on_simple(s, cost):
    """overnight simple return net of cost (round trip at close price)."""
    return (np.exp(s["on_ret"].values) - 1.0) - cost / s["close_px"].values


def main():
    s = load_sessions(); yrs = s["year"].values
    print("=== OVERNIGHT-DRIFT EDGE v3 (cost + regime calibrated) ===")
    print(f"sessions {len(s)}  {s['date'].min().date()}->{s['date'].max().date()}\n")

    print("-- 1. cost sensitivity, ALL days, full sample --")
    for c in (0.15, 0.30, 0.45, 0.65):
        perf(f"overnight all, cost ${c:.2f}", on_simple(s, c), yrs)

    print("\n-- 2. regime gate: only when gold 'expensive' (cost_r small), cost $0.30 --")
    px = s["close_px"].values
    for pxmin in (0, 1500, 2000):
        mask = px >= pxmin
        perf(f"cost$0.30 px>=${pxmin}", np.where(mask, on_simple(s, 0.30), np.nan), yrs)

    print("\n-- 3. trend gate (close>MA50) + cost $0.30 --")
    up = (s["close_px"] > s["ma50"]).values
    perf("cost$0.30 & uptrend", np.where(up, on_simple(s, 0.30), np.nan), yrs)
    perf("cost$0.30 & uptrend & px>=1500", np.where(up & (px >= 1500), on_simple(s, 0.30), np.nan), yrs)

    print("\n-- 4. seasonal gate (strong months) + overnight, cost $0.30 --")
    strong = s["month"].isin([1, 2, 7, 8, 11, 12]).values
    perf("cost$0.30 & strongMonths", np.where(strong, on_simple(s, 0.30), np.nan), yrs)
    perf("cost$0.30 & strong & uptrend", np.where(strong & up, on_simple(s, 0.30), np.nan), yrs)

    print("\n-- 5. LEVERED best overlay (vol-targeted), cost $0.30 --")
    base = on_simple(s, 0.30)
    vol = pd.Series(base).rolling(30).std().shift(1).values
    sig = (up).astype(float)  # long overnight when uptrend
    for tgt_daily in (0.010, 0.015, 0.020):
        lev = np.clip(tgt_daily / (vol + 1e-9), 0, 5.0)
        dret = sig * lev * base
        perf(f"uptrend lev vol-tgt {tgt_daily*100:.1f}%/d", dret, yrs)

    print("\n-- 6. MODERN REGIME ONLY (2019+), levered overnight+uptrend --")
    mod = s["year"] >= 2019
    perf("2019+ overnight&uptrend $0.30", np.where(mod & up, on_simple(s, 0.30), np.nan), yrs)
    base_m = np.where(mod, base, np.nan)
    lev = np.clip(0.015 / (vol + 1e-9), 0, 5.0)
    perf("2019+ levered 1.5%/d", np.where(mod & up, sig*lev*base, np.nan), yrs)


if __name__ == "__main__":
    main()
