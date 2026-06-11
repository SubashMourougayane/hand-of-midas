"""SignalRecord extraction from BT and Live signal-gen paths.

The two paths produce different output shapes (BT yields Signal dataclass
instances, Live's dry_run mode yields plain dicts). This module normalizes
both into list[SignalRecord] so the diff layer can compare them.

The extractor functions are kept in plain Python (no test/pytest deps) so
they can be imported and exercised standalone.
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pandas as pd


@dataclass
class SignalRecord:
    """Normalized signal description (one record per detected signal)."""
    system: str
    timestamp: datetime          # UTC, exact bar timestamp
    direction: str               # "long" | "short"
    taken: bool
    skip_reason: str             # "" if taken
    entry_price: float | None
    sl_price: float | None
    tp_price: float | None
    sweep_wick: float | None
    sweep_dir: str | None        # "bullish" | "bearish" (the engine's view)
    bias: str                    # "bullish" | "bearish" | "neutral"
    range_high: float | None
    range_low: float | None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat() if self.timestamp else None
        return d

    def comparison_key(self) -> tuple:
        """Bucket key for diffing: (timestamp_floored_to_minute, direction)."""
        if self.timestamp is None:
            return ("nullts", self.direction)
        floored = self.timestamp.replace(second=0, microsecond=0)
        return (floored, self.direction)


# ---------------------------------------------------------------------------
# Backtest path
# ---------------------------------------------------------------------------

def extract_backtest_signals(
    system_key: str,
    backtest_module_path: str,
    backtest_fn_name: str,
    h1_df: pd.DataFrame,
    m3_df: pd.DataFrame,
    daily_bias: dict,
) -> list[SignalRecord]:
    """Run BT signal-gen and convert its Signal dataclass list to SignalRecords.

    Two backtest module shapes exist in this repo:

    1. Shared backend/strategies/micro_alpha_sweep.py — used by Gold Micro.
       Reads ALPHA_SWEEP from backend/config.py (gold-tuned values).

    2. Per-system backend-<X>/backtest/engine.py — used by Oil Micro
       (and Macro systems too in Phase 4). Reads MICRO_ALPHA_SWEEP /
       ALPHA_SWEEP from backend-<X>/config.py (system-tuned values).

    To resolve the second shape, we must put the system's directory on
    sys.path BEFORE importing — otherwise `from config import ...` inside
    the engine resolves to the wrong system. _import_live_module_with_path
    handles the same problem for the live side; we reuse it here.

    Signature (both shapes):
        generate_signals(h1_df, m3_df, daily_bias) -> list[Signal]

    Signal dataclass (backend/strategies/base.py):
        date, entry, sl, tp, direction, risk, strategy, max_bars, timeframe, metadata
    """
    # System-local backtest engines need their parent dir on sys.path so
    # `from config import ...` resolves to the right system's config.
    # Shared modules (backend.strategies.*) are unaffected by this.
    if not backtest_module_path.startswith("backend."):
        _import_live_module_with_path(system_key, backtest_module_path)
    module = importlib.import_module(backtest_module_path)
    fn = getattr(module, backtest_fn_name)
    raw_signals = fn(h1_df, m3_df, daily_bias)

    records: list[SignalRecord] = []
    for s in raw_signals:
        ts = s.date
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        meta = s.metadata or {}
        # The backtest path doesn't expose bias on the Signal directly. It's
        # encoded by the FACT that the signal exists (bias filter passed).
        # We re-derive bias from daily_bias for the signal's date so the
        # SignalRecord has a meaningful field.
        bias = daily_bias.get(ts.date(), "neutral")

        records.append(SignalRecord(
            system=system_key,
            timestamp=ts.astimezone(timezone.utc),
            direction=s.direction,         # "long" | "short"
            taken=True,                     # BT only reports taken signals
            skip_reason="",
            entry_price=float(s.entry),
            sl_price=float(s.sl),
            tp_price=float(s.tp),
            sweep_wick=float(meta.get("sweep_wick")) if meta.get("sweep_wick") is not None else None,
            sweep_dir=meta.get("sweep_dir"),
            bias=bias,
            range_high=float(meta.get("range_high")) if meta.get("range_high") is not None else None,
            range_low=float(meta.get("range_low")) if meta.get("range_low") is not None else None,
        ))
    return records


# ---------------------------------------------------------------------------
# Live path (replay)
# ---------------------------------------------------------------------------

# These helpers are duplicated from tests/harness/test_12_replay.py
# (build_candle_dicts, build_daily_candle_dicts) because importing from
# test_12 would couple the parity harness to test ordering. The shapes are
# verified to match the live wrappers' expectations.

def _build_candle_dicts(df: pd.DataFrame, start_idx: int, count: int) -> list[dict]:
    candles = []
    end_idx = min(start_idx + count, len(df))
    for i in range(start_idx, end_idx):
        row = df.iloc[i]
        candles.append({
            "timestamp": df.index[i].strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "bid_open": row["bid_open"], "bid_high": row["bid_high"],
            "bid_low": row["bid_low"], "bid_close": row["bid_close"],
            "ask_open": row["ask_open"], "ask_high": row["ask_high"],
            "ask_low": row["ask_low"], "ask_close": row["ask_close"],
            "volume": row.get("volume", 100),
            "complete": True,
        })
    return candles


def _build_daily_candle_dicts(df: pd.DataFrame, target_date) -> list[dict]:
    before = df[df.index.date < target_date]
    if len(before) < 2:
        return []
    last_two = before.iloc[-2:]
    candles = []
    for i in range(len(last_two)):
        row = last_two.iloc[i]
        candles.append({
            "timestamp": last_two.index[i].strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "bid_open": row["bid_open"], "bid_high": row["bid_high"],
            "bid_low": row["bid_low"], "bid_close": row["bid_close"],
            "ask_open": row["ask_open"], "ask_high": row["ask_high"],
            "ask_low": row["ask_low"], "ask_close": row["ask_close"],
            "volume": row.get("volume", 100),
            "complete": True,
        })
    return candles


def _import_live_module_with_path(system_key: str, live_module_path: str):
    """Import the live scheduler module after putting the right system's
    directory on sys.path so its sibling `config` resolves correctly.

    This mirrors the trick used by backend-micro/main.py and test_12_replay,
    but is more aggressive: when other tests have already loaded a different
    system's scheduler, sys.modules['scanner.scheduler'] may point at the
    wrong file. We must also REMOVE other systems' dirs from sys.path so
    Python's import-from-disk path resolves to OUR system, not theirs.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    sys_dir_map = {
        "gold_micro": os.path.join(project_root, "backend-micro"),
        "oil_micro":  os.path.join(project_root, "backend-oil-micro"),
        "gold_macro": os.path.join(project_root, "backend"),
        "oil_macro":  os.path.join(project_root, "backend-oil"),
    }
    sys_dir = sys_dir_map[system_key]

    # Remove sibling system dirs so our scheduler.py wins resolution.
    other_dirs = [d for k, d in sys_dir_map.items() if k != system_key]
    sys.path[:] = [p for p in sys.path if p not in other_dirs]

    # Put OUR dir first (move-to-front; insert if absent).
    if sys_dir in sys.path:
        sys.path.remove(sys_dir)
    sys.path.insert(0, sys_dir)

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Force a clean import. sys.modules cache may hold the OTHER system's
    # scheduler / config under the same import name. Drop them so the next
    # import resolves from disk under our (now-prioritized) sys.path.
    for mod_name in list(sys.modules.keys()):
        if mod_name == "config" or mod_name == "scanner" or mod_name.startswith("scanner."):
            del sys.modules[mod_name]

    return importlib.import_module(live_module_path)


def extract_live_signals(
    system_key: str,
    live_module_path: str,
    live_core_fn_name: str,
    h1_df: pd.DataFrame,
    m3_df: pd.DataFrame,
    d_df: pd.DataFrame,
    daily_bias: dict,
    date_range_start,
    date_range_end,
) -> list[SignalRecord]:
    """Replay live signal-gen across [date_range_start, date_range_end].

    Walks each M3 bar and calls live_core_fn(dry_run=True). Returns the
    flattened list of dry_run signal dicts converted to SignalRecord.

    The replay loop mirrors tests/harness/test_12_replay.py:replay_day()
    so any drift in this function's behavior would also show up there.

    h1_df, m3_df, d_df should be FULL history; date_range bounds limit which
    bars get evaluated. This matches live production where the scheduler
    always has plenty of H1 backfill available — even on the first day of
    the parity window.
    """
    sched = _import_live_module_with_path(system_key, live_module_path)
    core_fn = getattr(sched, live_core_fn_name)

    records: list[SignalRecord] = []
    last_signal_time: datetime | None = None

    # Iterate dates in window. m3_df is FULL history, so we filter explicitly.
    dates = sorted(set(
        d.date()
        for d in m3_df.index
        if date_range_start <= d.date() <= date_range_end
    ))

    for target_date in dates:
        # Reset module-level state per day (matches scheduler midnight reset)
        sched._traded_sweeps = {"date": target_date, "keys": set()}
        sched._startup_cooldown_until = None
        sched._daily_state = {"date": target_date, "pnl": 0.0, "trades": 0}

        day_start = pd.Timestamp(target_date, tz="UTC")
        day_end = day_start + timedelta(days=1)
        day_m3 = m3_df[(m3_df.index >= day_start) & (m3_df.index < day_end)]

        daily_candles = _build_daily_candle_dicts(d_df, target_date)
        if len(daily_candles) < 2:
            continue

        for m3_idx in range(0, len(day_m3)):
            bar_ts = day_m3.index[m3_idx]
            now = bar_ts.to_pydatetime() if hasattr(bar_ts, "to_pydatetime") else bar_ts
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)

            # Skip market close (matches live scheduler)
            if 21 <= now.hour < 22:
                continue

            h1_before = h1_df[h1_df.index < bar_ts].tail(24)
            if len(h1_before) < 6:
                continue
            h1_candles = _build_candle_dicts(h1_before, 0, len(h1_before))

            m3_before = m3_df[m3_df.index <= bar_ts].tail(50)
            m3_candles = _build_candle_dicts(m3_before, 0, len(m3_before))

            active_windows = sched._get_active_windows(now)
            if not active_windows:
                continue

            # Mock DB calls — no real DB during replay.
            #
            # CRITICAL: order matters. The scheduler emits two distinct COUNT
            # queries; both contain "COUNT" so we MUST disambiguate by other
            # tokens in the SQL. The order below is fail-fast: most specific
            # branch first.
            #
            # Query 1: "SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref
            #           LIKE 'GD-MI-%' AND entry_time::date = %s"
            #   → trades-today count. Driven by signals_today (per-day local).
            #
            # Query 2: "SELECT COUNT(*) as cnt FROM gd_trades WHERE trade_ref
            #           LIKE 'GD-MI-%' AND exit_time IS NULL"
            #   → open-position count. Always 0 during dry replay (no broker).
            #
            # An earlier version of this mock returned len(records) for ALL
            # COUNT queries, which made the scheduler think there was 1 open
            # position after the first signal. That collapsed the rest of the
            # window to 0 signals. Don't do that.
            signals_today = sum(1 for r in records
                                if r.timestamp.date() == target_date)

            def mock_execute(sql, params=None, fetch=False):
                # Open-position check: ALWAYS 0 in dry replay.
                if "exit_time IS NULL" in sql:
                    return [{"cnt": 0}]
                # Trades-today count (max_trades_per_day gate).
                if "entry_time::date" in sql and "COUNT" in sql:
                    return [{"cnt": signals_today}]
                # Daily P&L (DD daily-loss gate).
                if "SUM(pnl_usd)" in sql:
                    return [{"daily_pnl": 0}]
                # Recent signal cooldown.
                if "gd_signals" in sql and "ORDER BY" in sql:
                    if last_signal_time:
                        return [{"timestamp": last_signal_time, "taken": True, "skip_reason": ""}]
                    return []
                return []

            with patch.object(sched, "execute", side_effect=mock_execute):
                try:
                    raw = core_fn(
                        now=now,
                        active_windows=active_windows,
                        h1_candles=h1_candles,
                        daily_candles=daily_candles,
                        m3_candles=m3_candles,
                        dry_run=True,
                    )
                except Exception as e:
                    # Don't swallow; surface as a synthetic record so the
                    # diagnosis hint can flag it.
                    records.append(SignalRecord(
                        system=system_key,
                        timestamp=now,
                        direction="error",
                        taken=False,
                        skip_reason=f"live_replay_crashed: {e}",
                        entry_price=None, sl_price=None, tp_price=None,
                        sweep_wick=None, sweep_dir=None,
                        bias=daily_bias.get(target_date, "neutral"),
                        range_high=None, range_low=None,
                    ))
                    continue

            for sig in raw or []:
                # Apply 5-min cooldown (the live scheduler does this via DB; we
                # simulate it here so replay matches live polling cadence).
                ts_str = sig.get("time")
                ts = pd.Timestamp(ts_str)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                ts_dt = ts.to_pydatetime()
                if last_signal_time and (ts_dt - last_signal_time).total_seconds() < 300:
                    continue
                last_signal_time = ts_dt

                records.append(SignalRecord(
                    system=system_key,
                    timestamp=ts_dt.astimezone(timezone.utc),
                    direction=sig["direction"],
                    taken=True,
                    skip_reason="",
                    entry_price=float(sig["entry"]),
                    sl_price=float(sig["sl"]),
                    tp_price=float(sig["tp"]),
                    sweep_wick=float(sig["sweep_wick"]) if sig.get("sweep_wick") is not None else None,
                    sweep_dir=None,  # not exposed in dry_run dict; bias maps it
                    bias=sig.get("bias", "neutral"),
                    range_high=float(sig["range_high"]) if sig.get("range_high") is not None else None,
                    range_low=float(sig["range_low"]) if sig.get("range_low") is not None else None,
                ))
    return records
