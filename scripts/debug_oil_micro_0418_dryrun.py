"""Debug why dry_run misses Oil Micro 2026-06-17 04:18 SHORT.

Replays exact dry_run wrapper logic for the cron tick at 04:21 UTC
(first tick after 04:18 M3 bar closes).
"""
from __future__ import annotations
import os, sys, importlib
from datetime import datetime, timezone, timedelta

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

# Load CSVs same way wrapper does
m3_df = pd.read_csv(os.path.join(ROOT, "data/raw/BCO_USD_M3.csv"),
                    parse_dates=["timestamp"], index_col="timestamp")
h1_df = pd.read_csv(os.path.join(ROOT, "data/raw/BCO_USD_H1.csv"),
                    parse_dates=["timestamp"], index_col="timestamp")
d_df = pd.read_csv(os.path.join(ROOT, "data/raw/BCO_USD_D.csv"),
                   parse_dates=["timestamp"], index_col="timestamp")

# Replicate the wrapper's broker_view function
def build_broker_view(now: datetime, m3_count=50, h1_count=24, d_count=2):
    m3_cutoff = pd.Timestamp(now)
    m3_view = m3_df[m3_df.index + pd.Timedelta(minutes=3) <= m3_cutoff]
    m3_recent = m3_view.tail(m3_count)
    h1_view = h1_df[h1_df.index + pd.Timedelta(hours=1) <= m3_cutoff]
    h1_recent = h1_view.tail(h1_count)
    d_view = d_df[d_df.index + pd.Timedelta(days=1) <= m3_cutoff]
    d_recent = d_view.tail(d_count)
    return h1_recent, d_recent, m3_recent


# Try the cron tick AT 04:21 (right after 04:18 M3 closes)
target = datetime(2026, 6, 17, 4, 21, tzinfo=timezone.utc)
h1, d, m3 = build_broker_view(target)
print(f"At {target.isoformat()}:")
print(f"  H1 bars: {len(h1)}, range {h1.index[0]} → {h1.index[-1]}")
print(f"  Daily bars: {len(d)}, range {d.index[0]} → {d.index[-1]}")
print(f"  M3 bars: {len(m3)}, range {m3.index[0]} → {m3.index[-1]}")
print()

# Show the H1 bars that include sweep range candidates (likely 0-4 window)
print("Recent H1 bars near 04:18 (looking for sweep):")
for ts in h1.index[-12:]:
    row = h1.loc[ts]
    print(f"  {ts}  bid_h={row['bid_high']:.4f} bid_l={row['bid_low']:.4f} mid_h={(row['bid_high']+row['ask_high'])/2:.4f} mid_l={(row['bid_low']+row['ask_low'])/2:.4f}")

# Show M3 bars 04:00-04:21
print("\nM3 bars 04:00-04:21:")
m3_sample = m3[m3.index >= pd.Timestamp("2026-06-17 04:00", tz="UTC")]
for ts, row in m3_sample.iterrows():
    print(f"  {ts}  ask_h={row['ask_high']:.4f} ask_l={row['ask_low']:.4f}")

# Now run scheduler module's generate_signals with this view
print("\nCalling scheduler with this view...")

scheduler_mod = importlib.import_module("scanner.scheduler")

# Build candle dicts in DWX format
def df_to_dicts(df_subset):
    return [{
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "bid_open": float(r["bid_open"]),
        "bid_high": float(r["bid_high"]),
        "bid_low": float(r["bid_low"]),
        "bid_close": float(r["bid_close"]),
        "ask_open": float(r["ask_open"]),
        "ask_high": float(r["ask_high"]),
        "ask_low": float(r["ask_low"]),
        "ask_close": float(r["ask_close"]),
        "volume": int(r.get("volume", 0)),
        "complete": True,
    } for ts, r in df_subset.iterrows()]

h1_dicts = df_to_dicts(h1)
d_dicts = df_to_dicts(d)
m3_dicts = df_to_dicts(m3)

# Mock DB calls
def mock_execute(query, *args, fetch=False, **kwargs):
    if not fetch:
        return None
    q = query.upper()
    if "SUM(PNL_USD)" in q:
        return [{"daily_pnl": 0}]
    if "COUNT(*)" in q:
        return [{"cnt": 0}]
    return []

def mock_get_open_trades():
    return []

scheduler_mod.execute = mock_execute
scheduler_mod.get_open_trades = mock_get_open_trades

# Reset state
scheduler_mod._daily_state = {"date": None, "pnl": 0.0, "trades": 0}
scheduler_mod._traded_sweeps = {"date": None, "keys": set()}
scheduler_mod._startup_cooldown_until = None

# F28 neutral
os.environ["OIL_MICRO_BIAS_MODE"] = "neutral"

# Get active windows
active_windows = scheduler_mod._get_active_windows(target)
print(f"  active_windows: {active_windows}")

if active_windows:
    print(f"\nCalling _run_micro_sweep_core...")
    signals = scheduler_mod._run_micro_sweep_core(target, active_windows, h1_dicts, d_dicts, m3_dicts, dry_run=True)
    print(f"  signals returned: {signals}")

# Now call generate_signals directly to compare
from strategies.micro_alpha_sweep_oil import generate_signals
from backend.scanner.broker_to_dataframe import broker_bars_to_dataframe

h1_real_df = broker_bars_to_dataframe(h1_dicts)
m3_real_df = broker_bars_to_dataframe(m3_dicts)
print(f"\n  H1 DataFrame after adapter: {len(h1_real_df)} bars, range {h1_real_df.index[0]} → {h1_real_df.index[-1]}")
print(f"  M3 DataFrame after adapter: {len(m3_real_df)} bars, range {m3_real_df.index[0]} → {m3_real_df.index[-1]}")

# Build daily_bias dict
import sys as _sys
unique_dates = set(h1_real_df.index.date)
daily_bias = {d: "neutral" for d in unique_dates}
print(f"  unique dates in H1: {sorted(unique_dates)}")

bt_signals = generate_signals(h1_real_df, m3_real_df, daily_bias)
print(f"\n  generate_signals returned {len(bt_signals)} signals:")
for s in bt_signals:
    print(f"    {s.date}  {s.direction}  entry={s.entry:.4f} sl={s.sl:.4f}  meta_window={s.metadata.get('window')} sweep_time={s.metadata.get('sweep_time')}")
