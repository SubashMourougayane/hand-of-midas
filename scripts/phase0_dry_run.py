"""Phase 0 baseline parity — Plan-literal task 0.2.

For each Micro system: replay Jun 11-18 JM candles through the LIVE
scheduler's `_run_micro_sweep_core(dry_run=True)`. Capture every signal
that would have fired. Save to JSON.

NO LIVE OR BT CODE EDITS. Read-only on production code. No live VPS contact.

Strategy:
1. Load full JM CSVs (M3, H1, Daily for the instrument).
2. Walk Jun 11-18 in 3-min ticks (matches scheduler cron cadence).
3. At each tick, build candle-dict lists in DWX format that the
   scheduler expects — "current state of broker fetch at this minute":
     - H1: last 24 closed bars before tick
     - Daily: last 2 closed bars before tick
     - M3: last 50 closed bars before tick
4. Mock the 4 DB call sites (return empty: no positions, no recent
   signal, no trades-today, no MT5 open). Reset between days so each
   day fires fresh — matches what BT does.
5. Call `_run_micro_sweep_core(now, active_windows, h1, daily, m3, dry_run=True)`.
6. Collect signal dicts.
7. Write `scripts/output/baseline_live_signals_<system>.json`.

Output schema:
{
  "system": "gold-micro",
  "window": "2026-06-11 → 2026-06-18",
  "tick_count": <total 3-min ticks>,
  "signals": [
    {"time": "...", "direction": "...", "entry": ..., "sl": ..., "tp": ...,
     "risk": ..., "bias": ..., "tick_when_fired": "...",
     "consol_window": "0-4|2-6|...", "sweep_wick": ...}
  ]
}
"""
from __future__ import annotations
import os
import sys
import json
import importlib
from datetime import datetime, timezone, timedelta
from unittest import mock

import pandas as pd

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)


def df_row_to_dwx_dict(ts: pd.Timestamp, row: pd.Series) -> dict:
    """Build a candle dict in the DWX/broker format the scheduler expects."""
    return {
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "bid_open": float(row["bid_open"]),
        "bid_high": float(row["bid_high"]),
        "bid_low": float(row["bid_low"]),
        "bid_close": float(row["bid_close"]),
        "ask_open": float(row["ask_open"]),
        "ask_high": float(row["ask_high"]),
        "ask_low": float(row["ask_low"]),
        "ask_close": float(row["ask_close"]),
        "volume": int(row.get("volume", 0)),
        "complete": True,
    }


def load_csvs(instrument: str):
    """Load M3, H1, Daily for instrument."""
    m3 = pd.read_csv(os.path.join(ROOT, f"data/raw/{instrument}_M3.csv"),
                     parse_dates=["timestamp"], index_col="timestamp")
    h1 = pd.read_csv(os.path.join(ROOT, f"data/raw/{instrument}_H1.csv"),
                     parse_dates=["timestamp"], index_col="timestamp")
    d = pd.read_csv(os.path.join(ROOT, f"data/raw/{instrument}_D.csv"),
                    parse_dates=["timestamp"], index_col="timestamp")
    return m3, h1, d


def build_broker_view(now: datetime, m3_df, h1_df, d_df,
                     m3_count: int = 50, h1_count: int = 24, d_count: int = 2):
    """Build the candle-list view the scheduler sees at `now`.

    Mimics get_candles(): returns last N CLOSED bars before now.
    A bar is closed if its timestamp + bar_duration <= now.
    """
    # M3 bars closed before now
    m3_cutoff = pd.Timestamp(now)
    m3_view = m3_df[m3_df.index + pd.Timedelta(minutes=3) <= m3_cutoff]
    m3_recent = m3_view.tail(m3_count)
    m3_list = [df_row_to_dwx_dict(ts, row) for ts, row in m3_recent.iterrows()]

    h1_view = h1_df[h1_df.index + pd.Timedelta(hours=1) <= m3_cutoff]
    h1_recent = h1_view.tail(h1_count)
    h1_list = [df_row_to_dwx_dict(ts, row) for ts, row in h1_recent.iterrows()]

    d_view = d_df[d_df.index + pd.Timedelta(days=1) <= m3_cutoff]
    d_recent = d_view.tail(d_count)
    d_list = [df_row_to_dwx_dict(ts, row) for ts, row in d_recent.iterrows()]

    return h1_list, d_list, m3_list


def reset_module_state(scheduler_mod):
    """Reset in-memory dicts in the scheduler module so each day fires fresh."""
    if hasattr(scheduler_mod, "_daily_state"):
        scheduler_mod._daily_state = {"date": None, "pnl": 0.0, "trades": 0}
    if hasattr(scheduler_mod, "_traded_sweeps"):
        scheduler_mod._traded_sweeps = {"date": None, "keys": set()}
    if hasattr(scheduler_mod, "_startup_cooldown_until"):
        scheduler_mod._startup_cooldown_until = None


def replay_for(label: str, pkg_dir: str, instrument: str, output_name: str):
    """Replay Jun 11-18 ticks through the live scheduler in dry_run mode."""
    print(f"\n{'='*60}")
    print(f"=== Phase 0 dry_run replay — {label} ===")
    print(f"{'='*60}")

    # Module-clear pattern — make sure correct backend is active
    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies", "backend.backtest",
                         "backend.data")):
            del sys.modules[k]

    pkg_path = os.path.join(ROOT, pkg_dir)
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()

    scheduler_mod = importlib.import_module("scanner.scheduler")
    print(f"  imported: {scheduler_mod.__file__}")

    # Mock all DB calls in scheduler module to return empty/safe values.
    # The scheduler dry_run path doesn't write to DB but it DOES read for
    # state checks (trades_today, recent_signal cooldown, open_micro,
    # is_sweep_consumed). Mock these to return "fresh state" so each tick
    # fires as if no prior trades existed.
    def mock_execute(query, *args, fetch=False, **kwargs):
        # Return shapes the scheduler expects:
        if not fetch:
            return None
        q = query.upper()
        if "SUM(PNL_USD)" in q:
            return [{"daily_pnl": 0}]
        if "COUNT(*)" in q:
            return [{"cnt": 0}]
        if "TIMESTAMP, TAKEN, SKIP_REASON" in q.upper() or "skip_reason" in query.lower():
            return []  # no recent signal → no cooldown
        return []

    # Mock get_open_trades (MT5) and is_sweep_consumed (DB) — both return empty
    def mock_get_open_trades():
        return []

    def mock_is_sweep_consumed(system, day, key):
        return False

    def mock_mark_sweep_consumed(system, day, key):
        pass

    # Apply mocks
    scheduler_mod.execute = mock_execute
    scheduler_mod.get_open_trades = mock_get_open_trades

    # Patch backend.db imports the scheduler does inline
    try:
        import backend.db as backend_db
        backend_db.is_sweep_consumed = mock_is_sweep_consumed
        backend_db.mark_sweep_consumed = mock_mark_sweep_consumed
    except Exception:
        pass

    # Load CSVs
    print(f"  loading {instrument} CSVs...")
    m3_df, h1_df, d_df = load_csvs(instrument)
    print(f"  M3 bars: {len(m3_df)}, H1: {len(h1_df)}, Daily: {len(d_df)}")

    # Walk Jun 11-18 in 3-min ticks
    start = datetime(2026, 6, 11, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 18, 23, 57, tzinfo=timezone.utc)
    tick = start

    all_signals = []
    seen_signal_keys = set()  # dedup since each tick may re-fire the same already-found signal
    tick_count = 0
    last_day_seen = None

    while tick <= end:
        tick_count += 1

        # Reset state at midnight UTC (matches live scheduler behavior).
        if last_day_seen != tick.date():
            reset_module_state(scheduler_mod)
            last_day_seen = tick.date()

        # Build broker view
        h1_list, d_list, m3_list = build_broker_view(tick, m3_df, h1_df, d_df)

        # Skip if any feed is starved (matches early-return in real scheduler)
        if len(h1_list) < 6 or len(d_list) < 2 or not m3_list:
            tick += timedelta(minutes=3)
            continue

        # Get active windows for this tick
        active_windows = scheduler_mod._get_active_windows(tick)
        if not active_windows:
            tick += timedelta(minutes=3)
            continue

        # Call dry_run core
        try:
            signals = scheduler_mod._run_micro_sweep_core(
                tick, active_windows, h1_list, d_list, m3_list, dry_run=True,
            )
        except Exception as e:
            print(f"  [tick {tick.isoformat()}] error: {e}")
            tick += timedelta(minutes=3)
            continue

        if signals:
            for s in signals:
                # Dedup: same engulfing time + direction = same signal
                key = f"{s.get('time', '')}|{s.get('direction', '')}"
                if key in seen_signal_keys:
                    continue
                seen_signal_keys.add(key)
                s["tick_when_fired"] = tick.isoformat()
                all_signals.append(s)

        tick += timedelta(minutes=3)

    print(f"  ticks processed: {tick_count}")
    print(f"  unique signals: {len(all_signals)}")

    # Write output
    output = {
        "system": label,
        "package": pkg_dir,
        "instrument": instrument,
        "window": f"{start.isoformat()} → {end.isoformat()}",
        "tick_count": tick_count,
        "bias_mode": os.environ.get("BIAS_MODE", "default"),
        "signals": all_signals,
    }
    out_path = os.path.join(OUT_DIR, output_name)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  wrote: {out_path}")

    # Print summary
    if all_signals:
        print()
        print(f"  Signals (Jun 11-18, dry_run live replay):")
        for s in all_signals:
            print(f"    {s.get('time')} {s.get('direction')} entry={s.get('entry')} "
                  f"sl={s.get('sl')} tp={s.get('tp')} bias={s.get('bias')}")

    return all_signals


# Set per-system BIAS_MODE=neutral to match live VPS state.
# Configs read GOLD_MICRO_BIAS_MODE / OIL_MICRO_BIAS_MODE (per-system), NOT global BIAS_MODE.
os.environ["GOLD_MICRO_BIAS_MODE"] = "neutral"
os.environ["OIL_MICRO_BIAS_MODE"] = "neutral"

# Gold Micro
gold_signals = replay_for(
    "Gold Micro",
    "backend-micro",
    "XAU_USD",
    "baseline_live_signals_gold_micro.json",
)

# Oil Micro
oil_signals = replay_for(
    "Oil Micro",
    "backend-oil-micro",
    "BCO_USD",
    "baseline_live_signals_oil_micro.json",
)

print()
print("=" * 60)
print("Phase 0 dry_run replay complete.")
print(f"  Gold Micro live-signals: {len(gold_signals)}")
print(f"  Oil Micro live-signals : {len(oil_signals)}")
print("=" * 60)
