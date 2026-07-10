#!/usr/bin/env python3
"""Trade frequency — A+D + COBRAX combined: per day / month / year (avg + range)."""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research/cobrax")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
import cobrax as CB
from combined_pnl import capture_leg, cobrax_trades
from bt_engine.data.memory_provider import resample_m5_to
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD

def report(name, ts):
    ts = pd.DatetimeIndex(pd.to_datetime(ts)).tz_localize(None).sort_values()
    n = len(ts)
    span_days = (ts.max() - ts.min()).days
    span_yr = span_days / 365.25
    by_year = pd.Series(1, index=ts).groupby(ts.year).count()
    by_month = pd.Series(1, index=ts).resample("MS", level=0).count() if False else \
               pd.Series(1, index=ts).groupby([ts.year, ts.month]).count()
    active_days = pd.Series(1, index=ts).groupby(ts.normalize()).count()
    print(f"\n### {name} — {n} trades, {ts.min().date()} → {ts.max().date()} ({span_yr:.1f}yr) ###")
    print(f"  per YEAR : avg {n/span_yr:6.0f}   (range {by_year.min()}–{by_year.max()}, "
          f"full-year median {int(by_year[(by_year.index>ts.min().year)&(by_year.index<ts.max().year)].median())})")
    print(f"  per MONTH: avg {n/span_yr/12:6.1f}   (busiest month {by_month.max()}, quietest {by_month.min()})")
    print(f"  per CALENDAR day: avg {n/span_days:5.2f}")
    print(f"  per TRADING day (~252/yr): avg {n/span_yr/252:5.2f}   "
          f"(on days it trades: avg {active_days.mean():.1f}, max {active_days.max()})")
    print(f"  active days: {len(active_days)} of ~{int(span_yr*252)} trading days "
          f"({100*len(active_days)/(span_yr*252):.0f}% of days have ≥1 trade)")
    return ts

if __name__ == "__main__":
    print("loading M5 → M15 ...", flush=True)
    m5 = pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame = resample_m5_to(m5, "M15"); df_m5 = CB.load(CB.XAU_M5)

    print("A ...", flush=True); a = capture_leg(FibV2IntradayA, frame, 48)
    print("D ...", flush=True); d = capture_leg(FibV2IntradayD, frame, 96)
    print("COBRAX ...", flush=True); cob = cobrax_trades(df_m5, tp_r=3.0)

    ta = report("A leg (long)", [t["entry_ts"] for t in a])
    td = report("D leg (short)", [t["entry_ts"] for t in d])
    tc = report("COBRAX", [t["entry_ts"] for t in cob])
    all_ts = [t["entry_ts"] for t in a] + [t["entry_ts"] for t in d] + [t["entry_ts"] for t in cob]
    report("A + D + COBRAX (COMBINED)", all_ts)
