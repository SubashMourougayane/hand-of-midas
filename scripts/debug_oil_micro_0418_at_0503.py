"""Check if dry_run picks up 04:18 SHORT at 05:03 cron tick (after 04:00 H1 closes)."""
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
d_df = pd.read_csv(os.path.join(ROOT, "data/raw/BCO_USD_D.csv"),
                   parse_dates=["timestamp"], index_col="timestamp")

def build_broker_view(now, m3_count=50, h1_count=24, d_count=2):
    cutoff = pd.Timestamp(now)
    m3_recent = m3_df[m3_df.index + pd.Timedelta(minutes=3) <= cutoff].tail(m3_count)
    h1_recent = h1_df[h1_df.index + pd.Timedelta(hours=1) <= cutoff].tail(h1_count)
    d_recent = d_df[d_df.index + pd.Timedelta(days=1) <= cutoff].tail(d_count)
    return h1_recent, d_recent, m3_recent


def df_to_dicts(df_subset):
    return [{
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "bid_open": float(r["bid_open"]), "bid_high": float(r["bid_high"]),
        "bid_low": float(r["bid_low"]), "bid_close": float(r["bid_close"]),
        "ask_open": float(r["ask_open"]), "ask_high": float(r["ask_high"]),
        "ask_low": float(r["ask_low"]), "ask_close": float(r["ask_close"]),
        "volume": int(r.get("volume", 0)), "complete": True,
    } for ts, r in df_subset.iterrows()]


# Check several ticks around when 04:00 H1 closes (at 05:00, first cron 05:03)
for tick_min in [0, 3, 6, 12, 21, 33, 45, 60, 75, 90]:
    target = datetime(2026, 6, 17, 5, tick_min, tzinfo=timezone.utc) if tick_min < 60 else datetime(2026, 6, 17, 5 + tick_min // 60, tick_min % 60, tzinfo=timezone.utc)
    h1, d, m3 = build_broker_view(target)

    scheduler_mod = importlib.import_module("scanner.scheduler")
    def mock_execute(query, *args, fetch=False, **kw):
        if not fetch:
            return None
        q = query.upper()
        if "SUM(PNL_USD)" in q:
            return [{"daily_pnl": 0}]
        if "COUNT(*)" in q:
            return [{"cnt": 0}]
        return []  # cooldown query returns empty list
    scheduler_mod.execute = mock_execute
    scheduler_mod.get_open_trades = lambda: []
    scheduler_mod._daily_state = {"date": None, "pnl": 0.0, "trades": 0}
    scheduler_mod._traded_sweeps = {"date": None, "keys": set()}
    scheduler_mod._startup_cooldown_until = None

    os.environ["OIL_MICRO_BIAS_MODE"] = "neutral"
    aw = scheduler_mod._get_active_windows(target)
    if not aw:
        print(f"  {target.strftime('%H:%M')} no active windows")
        continue
    sigs = scheduler_mod._run_micro_sweep_core(target, aw, df_to_dicts(h1), df_to_dicts(d), df_to_dicts(m3), dry_run=True)
    print(f"  {target.strftime('%H:%M')} active={[w['consol_start'] for w in aw]} h1_bars={len(h1)}({h1.index[-1]}) signals={len(sigs)} {[(s.get('time'), s.get('direction')) for s in sigs]}")
