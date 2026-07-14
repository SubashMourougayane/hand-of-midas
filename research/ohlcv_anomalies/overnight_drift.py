#!/usr/bin/env python3
"""B1 — Overnight drift vs intraday asymmetry (Group B OHLCV anomaly).

THESIS (economic, stated first): gold's overnight session (US close -> next US
open) should carry a structural risk-premium / gap-accrual drift, while the US
intraday session is choppy/mean-reverting. If real, buy-at-close / sell-at-open
harvests the drift with low turnover.

CAUSAL: every trade uses only prices at or before its own entry timestamp. No
future peek. Entry at the session-close bar, exit at the next session-open bar.

Buckets (NY clock, DST-aware via tz_convert):
  intraday  = P(close_hr, day d)  ->  P(open_hr,  day d)      [long US session]
  overnight = P(close_hr, day d)  ->  P(open_hr,  day d+1)    [close -> next open]

Base test: per-year sum of net log-return for each bucket, after round-trip cost.
Compare overnight-long vs intraday-long vs buy&hold. Then filtered variants.

Cost: COST_USD round-trip spread, converted to return at the entry price.
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

M5 = "/Users/subash/SUBASH/GoldDigger/research-baseline/data/raw/oanda_XAU_USD_M5_20yr.parquet"
COST_USD = 0.65          # round-trip spread in $/oz (matches live cost audit)
OPEN_HR = 8              # NY US session open (COMEX floor ~08:20; use 08:00 grid)
CLOSE_HR = 17            # NY US session close / OANDA daily rollover


def load():
    m5 = pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    m5["ny"] = ny
    m5["ny_date"] = ny.dt.normalize()
    m5["ny_hr"] = ny.dt.hour
    m5["ny_min"] = ny.dt.minute
    m5["dow"] = ny.dt.dayofweek  # 0=Mon
    return m5


def session_marks(m5: pd.DataFrame) -> pd.DataFrame:
    """First bar at/after OPEN_HR and last bar at/before CLOSE_HR per NY date."""
    rows = []
    for d, g in m5.groupby("ny_date", sort=True):
        # open: first bar with ny_hr >= OPEN_HR
        o = g[g["ny_hr"] >= OPEN_HR]
        # close: last bar with ny_hr < CLOSE_HR (i.e. up to 16:55) -> the close print
        c = g[g["ny_hr"] < CLOSE_HR]
        if len(o) == 0 or len(c) == 0:
            continue
        obar = o.iloc[0]
        cbar = c.iloc[-1]
        rows.append({
            "date": d,
            "dow": int(cbar["dow"]),
            "open_px": float(obar["open"]),
            "open_ts": obar["ny"],
            "close_px": float(cbar["close"]),
            "close_ts": cbar["ny"],
        })
    s = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    s["year"] = s["date"].dt.year
    s["next_open_px"] = s["open_px"].shift(-1)
    s["next_dow"] = s["dow"].shift(-1)
    s["gap_days"] = (s["date"].shift(-1) - s["date"]).dt.days
    return s


def leg_returns(s: pd.DataFrame):
    """Net log-returns per leg, after round-trip cost at entry price."""
    # intraday: enter open_px, exit close_px, same day
    cost_intr = COST_USD / s["open_px"]
    r_intr = np.log(s["close_px"] / s["open_px"]) - cost_intr
    # overnight: enter close_px, exit next_open_px
    cost_on = COST_USD / s["close_px"]
    r_on = np.log(s["next_open_px"] / s["close_px"]) - cost_on
    return r_intr, r_on


def pf(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    gw = x[x > 0].sum()
    gl = -x[x < 0].sum()
    return gw / gl if gl > 0 else float("inf")


def summ(name, r, years):
    r = np.asarray(r, float)
    m = ~np.isnan(r)
    r = r[m]; yy = np.asarray(years)[m]
    if len(r) == 0:
        print(f"  {name:<28s} ZERO"); return
    ys = pd.Series(r).groupby(pd.Series(yy)).sum()
    pos = int((ys > 0).sum()); tot = int(len(ys))
    eq = r.cumsum(); peak = np.maximum.accumulate(eq); dd = float((eq - peak).min())
    net = r.sum()
    wr = (r > 0).mean()
    print(f"  {name:<28s} n={len(r):>5d} netLog={net:>+7.3f} "
          f"(~{(np.exp(net)-1)*100:>+6.1f}% simple) PF={pf(r):>5.2f} "
          f"WR={wr*100:>4.1f}% posYr={pos:>2d}/{tot:<2d} DD={dd:>+6.3f}")
    return ys


def main():
    m5 = load()
    s = session_marks(m5).dropna(subset=["next_open_px"]).reset_index(drop=True)
    r_intr, r_on = leg_returns(s)
    yrs = s["year"].values
    print(f"=== B1 OVERNIGHT DRIFT (gold, 20yr, cost ${COST_USD} rt) ===")
    print(f"sessions: {len(s)}  {s['date'].min().date()} -> {s['date'].max().date()}")
    print(f"open={OPEN_HR}:00 NY  close={CLOSE_HR}:00 NY\n")
    print("-- base legs (long each) --")
    summ("intraday long (o->c)", r_intr, yrs)
    on_ys = summ("overnight long (c->next o)", r_on, yrs)
    # buy & hold benchmark (log of total)
    bh = np.log(s["close_px"].iloc[-1] / s["open_px"].iloc[0])
    print(f"  {'buy&hold (open0->closeN)':<28s} netLog={bh:>+7.3f} (~{(np.exp(bh)-1)*100:>+.0f}% simple)")

    print("\n-- overnight FILTERS (causal, all long) --")
    # weekend-inclusive vs weekday-only overnight
    wd = s["gap_days"] == 1
    summ("overnight WEEKDAY-only", r_on.where(wd), yrs)
    summ("overnight FRI->MON only", r_on.where(s["gap_days"] >= 2), yrs)
    # by exit-day-of-week (next_dow)
    for d, nm in [(0, "->Mon"), (1, "->Tue"), (2, "->Wed"), (3, "->Thu"), (4, "->Fri")]:
        summ(f"overnight exit {nm}", r_on.where(s["next_dow"] == d), yrs)

    print("\n-- per-year overnight-long (net log) --")
    if on_ys is not None:
        for y, v in on_ys.items():
            print(f"    {int(y)}: {v:>+7.3f}")


if __name__ == "__main__":
    main()
