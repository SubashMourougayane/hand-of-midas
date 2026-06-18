"""Find which date iteration in generate_signals produces the 04:18 SHORT signal."""
from __future__ import annotations
import os, sys, importlib

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

for k in list(sys.modules.keys()):
    if k.startswith(("scanner", "config", "backtest", "strategies",
                     "backend.execution", "backend.strategies", "backend.backtest",
                     "backend.data")):
        del sys.modules[k]

pkg_path = os.path.join(ROOT, "backend-oil-micro")
if pkg_path in sys.path:
    sys.path.remove(pkg_path)
sys.path.insert(0, pkg_path)
importlib.invalidate_caches()

# Patch generate_signals's traded_sweeps add to log when 04:18 signal is appended
import strategies.micro_alpha_sweep_oil as strat_mod
orig_signals_append_marker = []

# Monkey-patch by wrapping the function and tracing dates iterated
import datetime as dt
import pandas as pd

# Read full BT data
from backtest.engine import _get_cached_data
data = _get_cached_data()
oil_h1 = data["oil_h1"]
oil_m3 = data["oil_m3"]

# Manual replication of strategy outer loop, looking for what produces the 04:18 SHORT
from config import MICRO_ALPHA_SWEEP, ENGULFING_TOLERANCE
cfg = MICRO_ALPHA_SWEEP
target_engulfing = pd.Timestamp("2026-06-17 04:18:00", tz="UTC")

dates = sorted(set(oil_h1.index.date))
target_idx_in_m3 = oil_m3.index.get_loc(target_engulfing)

# What sweep_time produces this engulfing?
# Per metadata: sweep_time = 2026-06-17 04:00:00, start_hour = 22
# 22-2 window: consol = {22,23,0,1}, scan = {2,3,4,5,6,7}
# Sweep at 04:00 means iterating with date such that day_h1 includes bar at 04:00

for date in dates:
    if date < dt.date(2026, 6, 16) or date > dt.date(2026, 6, 17):
        continue
    day_h1 = oil_h1[oil_h1.index.date == date]
    print(f"\n=== Iterating date {date} ===")
    print(f"  day_h1: {len(day_h1)} bars, hours = {sorted([ts.hour for ts in day_h1.index])}")

    # Check window 22-2
    start_hour, end_hour = 22, 2
    consol_hours = {22, 23, 0, 1}
    scan_hours = {2, 3, 4, 5, 6, 7}
    consol = day_h1[day_h1.index.hour.isin(consol_hours)]
    print(f"  Window 22-2: consol_hours={consol_hours} → {len(consol)} consol bars")
    scan_bars = day_h1[day_h1.index.hour.isin(scan_hours)]
    print(f"  Window 22-2: scan_hours={scan_hours} → {len(scan_bars)} scan bars")
    if len(scan_bars) > 0:
        for ts, _ in scan_bars.iterrows():
            print(f"    scan bar: {ts}")
