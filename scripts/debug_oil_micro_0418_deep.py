"""Deep dive: why doesn't generate_signals fire 04:18 SHORT at 05:33 cron?"""
from __future__ import annotations
import os, sys, importlib
from datetime import datetime, timezone

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

import pandas as pd
m3_df = pd.read_csv(os.path.join(ROOT, "data/raw/BCO_USD_M3.csv"),
                    parse_dates=["timestamp"], index_col="timestamp")
h1_df = pd.read_csv(os.path.join(ROOT, "data/raw/BCO_USD_H1.csv"),
                    parse_dates=["timestamp"], index_col="timestamp")

target = datetime(2026, 6, 17, 5, 33, tzinfo=timezone.utc)
cutoff = pd.Timestamp(target)
h1_view = h1_df[h1_df.index + pd.Timedelta(hours=1) <= cutoff].tail(24)
m3_view = m3_df[m3_df.index + pd.Timedelta(minutes=3) <= cutoff].tail(50)
print(f"H1 view (24 bars): {h1_view.index[0]} → {h1_view.index[-1]}")
print(f"M3 view (50 bars): {m3_view.index[0]} → {m3_view.index[-1]}")

# 06-17 H1 bars in view
print(f"\n06-17 H1 bars in view: {[ts for ts in h1_view.index if ts.date() == __import__('datetime').date(2026, 6, 17)]}")

# Build adapter DataFrames
from backend.scanner.broker_to_dataframe import broker_bars_to_dataframe
def df_to_dicts(df_subset):
    return [{
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "bid_open": float(r["bid_open"]), "bid_high": float(r["bid_high"]),
        "bid_low": float(r["bid_low"]), "bid_close": float(r["bid_close"]),
        "ask_open": float(r["ask_open"]), "ask_high": float(r["ask_high"]),
        "ask_low": float(r["ask_low"]), "ask_close": float(r["ask_close"]),
        "volume": int(r.get("volume", 0)), "complete": True,
    } for ts, r in df_subset.iterrows()]

h1_dicts = df_to_dicts(h1_view)
m3_dicts = df_to_dicts(m3_view)
h1_real = broker_bars_to_dataframe(h1_dicts)
m3_real = broker_bars_to_dataframe(m3_dicts)

print(f"\nAdapter H1: {len(h1_real)} bars")
print(f"  Dates in H1: {sorted(set(h1_real.index.date))}")
print(f"  06-17 hours: {sorted([ts.hour for ts in h1_real.index if ts.date() == __import__('datetime').date(2026, 6, 17)])}")

# Call generate_signals
from strategies.micro_alpha_sweep_oil import generate_signals
from backend.backtest.neutral_bias import NeutralBiasDict
sigs = generate_signals(h1_real, m3_real, NeutralBiasDict())
print(f"\nSignals: {len(sigs)}")
for s in sigs:
    print(f"  {s.date}  {s.direction}  meta={s.metadata}")

# Now manually check: for window 22-2 on 2026-06-17, what does the strategy see?
print("\n=== Manual trace: window 22-2 on 06-17 ===")
from config import MICRO_ALPHA_SWEEP
cfg = MICRO_ALPHA_SWEEP
print(f"  cfg consol_hours={cfg['consol_hours']}, scan_after={cfg['scan_after_hours']}")
# window 22-2 means consol_start=22, consol_end=2 (22+4=26→2), scan_until=22+4+6=32→8
# consol_hours = {22, 23, 0, 1}
# scan_hours = {2, 3, 4, 5, 6, 7}
date = __import__('datetime').date(2026, 6, 17)
day_h1 = h1_real[h1_real.index.date == date]
print(f"  day_h1 (date == 06-17): {len(day_h1)} bars")
print(f"  hours: {sorted([ts.hour for ts in day_h1.index])}")

# strategy: consol = day_h1[day_h1.index.hour.isin(consol_hours)]
consol_hours = {22, 23, 0, 1}
consol = day_h1[day_h1.index.hour.isin(consol_hours)]
print(f"  consol (filtered to {consol_hours}): {len(consol)} bars  ← needs >= 2")
print(f"  ⚠️ HOURS 22,23,00,01 of 06-17 don't exist in 06-17 data — these belong to 06-16's UTC date!")
