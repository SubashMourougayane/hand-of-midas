#!/usr/bin/env python3
"""Intraday structure hunt — informed by B1: gold's US session is flat/choppy
gross (drift lives overnight). So intraday edge must be CONDITIONAL / REVERSION,
not directional. Three economically-motivated tests, all causal, intraday-only:

 A. OVERNIGHT GAP -> INTRADAY. Does the sign/size of the overnight move (Asian/
    London drift) predict the US session? Fade (US fades Asia) vs continue.
    Signal known at US open (overnight already happened). Exit US close.
 B. INTRADAY REVERSION. Price stretches k*ATR from session open by hour H ->
    fade back toward open. Exit at close or target. Choppy session supports it.
 C. OPENING DRIVE. First-hour (08-09 NY) direction -> rest-of-session continue/fade.

All returns net of COST round-trip. Per-year PF + Sharpe. No future peek:
every signal uses only bars closed before the entry bar.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
COST = 0.65
OPEN_HR, CLOSE_HR = 8, 17


def load():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    m5["ny_date"] = ny.dt.normalize(); m5["ny_hr"] = ny.dt.hour; m5["ny_min"] = ny.dt.minute
    return m5


def sessions(m5):
    """Per US-session record: open px, close px, first-hr close, hi/lo, prior close."""
    rows = []
    for d, g in m5.groupby("ny_date", sort=True):
        us = g[(g["ny_hr"] >= OPEN_HR) & (g["ny_hr"] < CLOSE_HR)]
        if len(us) < 20:
            continue
        h1 = us[us["ny_hr"] == OPEN_HR]
        rows.append({
            "date": d,
            "open_px": float(us.iloc[0]["open"]),
            "close_px": float(us.iloc[-1]["close"]),
            "h1_close": float(h1.iloc[-1]["close"]) if len(h1) else np.nan,
            "hi": float(us["high"].max()), "lo": float(us["low"].min()),
        })
    s = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    s["year"] = s["date"].dt.year
    s["prev_close"] = s["close_px"].shift(1)
    # overnight gap = this open vs prior US close (the overnight move, known at open)
    s["gap"] = np.log(s["open_px"] / s["prev_close"])
    # intraday return open->close
    s["intr"] = np.log(s["close_px"] / s["open_px"])
    # first-hour return
    s["h1"] = np.log(s["h1_close"] / s["open_px"])
    # rest-of-session (after hr1) return
    s["rest"] = np.log(s["close_px"] / s["h1_close"])
    # ATR proxy: 14-session rolling range, lagged
    s["atr"] = (s["hi"] - s["lo"]).rolling(14).mean().shift(1)
    return s.dropna(subset=["prev_close", "atr"]).reset_index(drop=True)


def pf(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    gl = -x[x < 0].sum(); return x[x > 0].sum() / gl if gl > 0 else float("inf")


def rep(name, r, years, cost_applied=True):
    r = np.asarray(r, float); m = ~np.isnan(r); r = r[m]; yy = np.asarray(years)[m]
    if len(r) == 0: print(f"  {name:<40s} ZERO"); return
    ys = pd.Series(r).groupby(pd.Series(yy)).sum(); pos = int((ys > 0).sum()); tot = len(ys)
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(252)
    print(f"  {name:<40s} n={len(r):>5d} net={r.sum():>+7.3f} PF={pf(r):>5.2f} "
          f"WR={(r>0).mean()*100:>4.1f}% posY={pos:>2d}/{tot:<2d} Sh={sh:>+5.2f}")


def main():
    s = sessions(load()); yrs = s["year"].values
    cr = COST / s["open_px"].values  # per-leg cost in return
    print("=== INTRADAY STRUCTURE (US session, cost $0.65 rt) ===")
    print(f"sessions {len(s)}  {s['date'].min().date()}->{s['date'].max().date()}\n")

    print("-- A. OVERNIGHT GAP -> INTRADAY (signal at open) --")
    gz = s["gap"] / s["gap"].rolling(60).std().shift(1)  # gap z-score, lagged std
    # continuation: trade intraday in gap direction
    dir_cont = np.sign(s["gap"].values)
    rep("continue gap (all)", dir_cont * s["intr"].values - cr, yrs)
    rep("fade gap (all)", -dir_cont * s["intr"].values - cr, yrs)
    for k in (0.5, 1.0, 1.5):
        big = (gz.abs() >= k).values
        rep(f"continue |gapz|>={k}", np.where(big, dir_cont * s["intr"].values - cr, np.nan), yrs)
        rep(f"fade     |gapz|>={k}", np.where(big, -dir_cont * s["intr"].values - cr, np.nan), yrs)

    print("\n-- B. OPENING DRIVE: first-hr dir -> rest of session --")
    d1 = np.sign(s["h1"].values)
    rep("continue h1 (rest)", d1 * s["rest"].values - cr, yrs)
    rep("fade h1 (rest)", -d1 * s["rest"].values - cr, yrs)
    h1z = s["h1"] / s["h1"].rolling(60).std().shift(1)
    for k in (0.5, 1.0, 1.5):
        big = (h1z.abs() >= k).values
        rep(f"continue |h1z|>={k}", np.where(big, d1 * s["rest"].values - cr, np.nan), yrs)
        rep(f"fade     |h1z|>={k}", np.where(big, -d1 * s["rest"].values - cr, np.nan), yrs)

    print("\n-- C. GAP x OPENING-DRIVE combos --")
    # gap up + h1 continues up -> continue; gap up + h1 fades -> ?
    same = (np.sign(s["gap"]) == np.sign(s["h1"])).values
    rep("gap&h1 agree -> continue rest", np.where(same, np.sign(s["h1"]).values * s["rest"].values - cr, np.nan), yrs)
    rep("gap&h1 disagree -> follow h1", np.where(~same, np.sign(s["h1"]).values * s["rest"].values - cr, np.nan), yrs)

    print("\n-- baseline drifts (no signal, gross) --")
    rep("intraday long (gross)", s["intr"].values, yrs)
    rep("rest-of-session long (gross)", s["rest"].values, yrs)


if __name__ == "__main__":
    main()
