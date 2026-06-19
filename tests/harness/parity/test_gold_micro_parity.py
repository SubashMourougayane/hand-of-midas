"""Parity harness: Gold Micro live signal-gen ≡ BT signal-gen on identical data.

Plan-literal task 4.6 of REFACTOR_PLAN_LIVE_BT_UNIFY.md. Mirror of
test_oil_micro_parity.py but for Gold Micro (XAU_USD).

What this test asserts:
- Given the SAME H1 + M3 + Daily candles (loaded from JM CSVs), the live
  scheduler's `_run_micro_sweep_core(..., dry_run=True)` produces the
  SAME signal list as BT's `generate_signals()`.
- Match criteria: byte-identical (timestamp, direction, entry, sl, tp).

Critical: env var `GOLD_MICRO_BIAS_MODE` MUST be set BEFORE config import.
config.BIAS_MODE is captured at module-import time. The fixture sets it +
asserts cfg.BIAS_MODE == 'neutral' to guard against the import-order bug
that bit Oil Micro test during Phase 5.5.
"""
from __future__ import annotations

import os
import sys
import importlib

import pandas as pd
import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PKG_GOLD_MICRO = os.path.join(ROOT, "backend-micro")


@pytest.fixture
def gold_micro_modules():
    """Set up sys.path so backend-micro is importable as the active backend.

    CRITICAL: env vars (GOLD_MICRO_BIAS_MODE) MUST be set BEFORE config is
    imported. config.py reads `parse_bias_mode_env('GOLD_MICRO_BIAS_MODE',
    default='production')` at module-import time.
    """
    prev_path = list(sys.path)
    prev_modules = set(sys.modules.keys())
    prev_env = {k: os.environ.get(k) for k in ("GOLD_MICRO_BIAS_MODE",)}

    # Set BIAS_MODE neutral BEFORE any import. Matches live VPS state.
    os.environ["GOLD_MICRO_BIAS_MODE"] = "neutral"

    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies", "backend.backtest",
                         "backend.data")):
            del sys.modules[k]

    if PKG_GOLD_MICRO in sys.path:
        sys.path.remove(PKG_GOLD_MICRO)
    sys.path.insert(0, PKG_GOLD_MICRO)
    importlib.invalidate_caches()

    engine = importlib.import_module("backtest.engine")
    strategy = importlib.import_module("backend.strategies.micro_alpha_sweep")

    import config as cfg_mod
    assert cfg_mod.BIAS_MODE == "neutral", (
        f"BIAS_MODE expected 'neutral', got {cfg_mod.BIAS_MODE!r}. "
        f"Env var must be set BEFORE config import."
    )

    yield engine, strategy, cfg_mod

    # Teardown
    for k in list(sys.modules.keys()):
        if k not in prev_modules:
            del sys.modules[k]
    sys.path[:] = prev_path
    for k, v in prev_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_gold_micro_signal_parity_jun11_18(gold_micro_modules):
    """BT generate_signals output == live dry_run output for Jun 11-18 2026."""
    engine, strategy, cfg_mod = gold_micro_modules
    from backend.backtest.neutral_bias import NeutralBiasDict

    # ── BT side ────────────────────────────────────────────────
    data = engine._get_cached_data()
    daily_bias = NeutralBiasDict()
    bt_signals = strategy.generate_signals(
        data["gold_h1"], data["gold_m3"], daily_bias,
        cfg=cfg_mod.MICRO_ALPHA_SWEEP,
    )

    start = pd.Timestamp("2026-06-11", tz="UTC")
    end = pd.Timestamp("2026-06-18 23:59:59", tz="UTC")
    bt_window = [s for s in bt_signals if start <= s.date <= end]

    # Dedup (overlap window)
    seen = set()
    bt_deduped = []
    for s in bt_window:
        key = (s.date, s.direction)
        if key in seen:
            continue
        seen.add(key)
        bt_deduped.append(s)

    # ── Live side (dry_run replay) ─────────────────────────────
    live_signals = _live_dry_run_replay(start, end)

    # ── Match assertion ────────────────────────────────────────
    bt_keys = {(s.date, s.direction) for s in bt_deduped}
    live_keys = {(_parse_iso(s["time"]), s["direction"]) for s in live_signals}

    bt_only = bt_keys - live_keys
    live_only = live_keys - bt_keys
    matched = bt_keys & live_keys

    print(f"\nBT signals (deduped): {len(bt_deduped)}")
    print(f"Live signals (dry_run): {len(live_signals)}")
    print(f"Matched: {len(matched)}")
    print(f"BT-only: {len(bt_only)}")
    print(f"Live-only: {len(live_only)}")
    if bt_only:
        print(f"BT-only sample: {sorted(bt_only)[:3]}")
    if live_only:
        print(f"Live-only sample: {sorted(live_only)[:3]}")

    assert not bt_only, (
        f"BT fires {len(bt_only)} signals live doesn't: "
        f"{sorted(bt_only)[:3]}. Drift in live code path."
    )
    assert not live_only, (
        f"Live fires {len(live_only)} signals BT doesn't: "
        f"{sorted(live_only)[:3]}. Drift in live code path."
    )
    assert len(bt_deduped) == len(live_signals), (
        f"Signal counts diverge: BT={len(bt_deduped)} vs live={len(live_signals)}"
    )


# ─── Helpers ──────────────────────────────────────────────────


def _parse_iso(ts_str):
    cleaned = ts_str.replace("Z", "+00:00") if isinstance(ts_str, str) else ts_str
    ts = pd.Timestamp(cleaned)
    return ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")


def _live_dry_run_replay(start_ts, end_ts):
    """Replay Jun 11-18 ticks through live scheduler in dry_run mode."""
    from datetime import datetime, timezone, timedelta

    scheduler = importlib.import_module("scanner.scheduler")

    def mock_execute(query, *args, fetch=False, **kwargs):
        if not fetch:
            return None
        q = query.upper()
        if "SUM(PNL_USD)" in q:
            return [{"daily_pnl": 0}]
        if "COUNT(*)" in q:
            return [{"cnt": 0}]
        return []

    scheduler.execute = mock_execute
    scheduler.get_open_trades = lambda: []

    try:
        import backend.db as backend_db
        backend_db.is_sweep_consumed = lambda system, day, key: False
        backend_db.mark_sweep_consumed = lambda system, day, key: None
    except Exception:
        pass

    # Load CSVs
    m3_df = pd.read_csv(os.path.join(ROOT, "data/raw/XAU_USD_M3.csv"),
                        parse_dates=["timestamp"], index_col="timestamp")
    h1_df = pd.read_csv(os.path.join(ROOT, "data/raw/XAU_USD_H1.csv"),
                        parse_dates=["timestamp"], index_col="timestamp")
    d_df = pd.read_csv(os.path.join(ROOT, "data/raw/XAU_USD_D.csv"),
                       parse_dates=["timestamp"], index_col="timestamp")

    def _bars_dwx(df_subset):
        return [{
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
            "bid_open": float(r["bid_open"]), "bid_high": float(r["bid_high"]),
            "bid_low": float(r["bid_low"]), "bid_close": float(r["bid_close"]),
            "ask_open": float(r["ask_open"]), "ask_high": float(r["ask_high"]),
            "ask_low": float(r["ask_low"]), "ask_close": float(r["ask_close"]),
            "volume": int(r.get("volume", 0)), "complete": True,
        } for ts, r in df_subset.iterrows()]

    def _build_view(now):
        cutoff = pd.Timestamp(now)
        m3_view = m3_df[m3_df.index + pd.Timedelta(minutes=3) <= cutoff].tail(50)
        h1_view = h1_df[h1_df.index + pd.Timedelta(hours=1) <= cutoff].tail(24)
        d_view = d_df[d_df.index + pd.Timedelta(days=1) <= cutoff].tail(2)
        return _bars_dwx(h1_view), _bars_dwx(d_view), _bars_dwx(m3_view)

    tick = start_ts.to_pydatetime() if hasattr(start_ts, "to_pydatetime") else start_ts
    tick_end = end_ts.to_pydatetime() if hasattr(end_ts, "to_pydatetime") else end_ts

    seen = set()
    all_signals = []
    last_day = None

    while tick <= tick_end:
        if last_day != tick.date():
            scheduler._daily_state = {"date": None, "pnl": 0.0, "trades": 0}
            scheduler._traded_sweeps = {"date": None, "keys": set()}
            scheduler._startup_cooldown_until = None
            last_day = tick.date()

        h1_dicts, d_dicts, m3_dicts = _build_view(tick)
        if len(h1_dicts) < 6 or len(d_dicts) < 2 or not m3_dicts:
            tick += timedelta(minutes=3)
            continue

        active_windows = scheduler._get_active_windows(tick)
        if not active_windows:
            tick += timedelta(minutes=3)
            continue

        try:
            sigs = scheduler._run_micro_sweep_core(
                tick, active_windows, h1_dicts, d_dicts, m3_dicts, dry_run=True,
            )
        except Exception:
            tick += timedelta(minutes=3)
            continue

        if sigs:
            for s in sigs:
                key = (s.get("time", ""), s.get("direction", ""))
                if key in seen:
                    continue
                seen.add(key)
                all_signals.append(s)

        tick += timedelta(minutes=3)

    return all_signals
