"""Filter #15 — cooldown bypass race fix unit test.

The bug: in Gold Macro + Oil Macro live schedulers, `_traded_sweeps_macro["keys"].add(sweep_key)`
was placed AFTER `execute_signal()`. If execute_signal raised an exception (DB INSERT
failure, MT5 timeout, JSON serialization error), the sweep was never added to the
blacklist → next 3-min cron tick retried the same sweep.

Discovered: 2026-06-11 audit. Fixed: 2026-06-14.

This test proves the fix works by:
  1. Mocking execute_signal to raise an exception
  2. Building minimal sweep+engulfing candle fixtures
  3. Calling _run_alpha_sweep_core() once (live path, dry_run=False)
  4. Asserting _traded_sweeps_macro["keys"] still contains the sweep_key

Without the fix, the assertion fails (sweep_key not added) and the next
cron call would re-trigger the same sweep.

Test does NOT require PostgreSQL — all DB calls and execute_signal are
mocked at module level.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_minimal_h1_candles_with_asia_sweep(target_date: datetime) -> list[dict]:
    """Build 8 H1 Asia candles + scan-window candles to trigger a bullish sweep.

    Asia (00-08 UTC): wide range 2580-2610 (range=30 → max sl = 24 with risk_max_factor=0.8).
    Scan bar (08 UTC): wick down to 2576 (sweeps Asia low 2580 by 4pts > 2pt threshold)
                       and closes at 2607 (back above Asia low — bullish sweep confirmed).
    """
    candles = []
    base_ts = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=timezone.utc)

    # 8 Asia H1 bars 00-07 — 30-point range 2580-2610
    for i in range(8):
        ts = base_ts + timedelta(hours=i)
        candles.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "complete": True,
            "bid_open": 2590.0, "bid_high": 2609.0, "bid_low": 2581.0, "bid_close": 2600.0,
            "ask_open": 2591.0, "ask_high": 2610.0, "ask_low": 2582.0, "ask_close": 2601.0,
            "volume": 100,
        })

    # H1 bar at 08:00 UTC: bullish sweep — wicks down to 2576 (below Asia low 2580),
    # closes back above at 2606
    sweep_ts = base_ts + timedelta(hours=8)
    candles.append({
        "timestamp": sweep_ts.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "complete": True,
        "bid_open": 2600.0, "bid_high": 2608.0, "bid_low": 2575.0, "bid_close": 2606.0,
        "ask_open": 2601.0, "ask_high": 2609.0, "ask_low": 2576.0, "ask_close": 2607.0,
        "volume": 200,
    })
    return candles


def _make_daily_candles(target_date: datetime) -> list[dict]:
    """2 daily candles. Yesterday is bullish (body ≥ 40% of range, close > open)
    so daily_bias = bullish, allowing bullish sweep to fire."""
    yesterday_ts = (target_date - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000000000Z")
    today_ts = target_date.strftime("%Y-%m-%dT00:00:00.000000000Z")
    return [
        {  # yesterday — strong bullish: open 2580, close 2620 (40-pt body in 50-pt range)
            "timestamp": yesterday_ts,
            "complete": True,
            "bid_open": 2580.0, "bid_high": 2625.0, "bid_low": 2575.0, "bid_close": 2620.0,
            "ask_open": 2581.0, "ask_high": 2626.0, "ask_low": 2576.0, "ask_close": 2621.0,
            "volume": 5000,
        },
        {
            "timestamp": today_ts,
            "complete": True,
            "bid_open": 2606.0, "bid_high": 2625.0, "bid_low": 2594.0, "bid_close": 2620.0,
            "ask_open": 2607.0, "ask_high": 2626.0, "ask_low": 2595.0, "ask_close": 2621.0,
            "volume": 4000,
        },
    ]


def _make_engulfing_m3_candles(sweep_h1_ts: datetime) -> list[dict]:
    """M3 candles inside the engulfing window (45min after H1 sweep).

    Sweep wick is at ~2576 (low). For risk to fit `risk < asia_range × 0.8 = 24`,
    engulfing bar's entry should be near 2580-2590 (so risk = entry − 2574 ≈ 6-16).

    Pattern at sweep_ts + 6 min:
      - Prev bar: small bearish (open 2580, close 2578, body 2)
      - Curr bar: bullish engulfing (open 2577, close 2585, body 8)
                  body bottom 2577 ≤ prev body bottom 2578
                  body top 2585 ≥ prev body top 2580
    """
    candles = []
    # 5 M3 filler bars (skip_first_bar=True consumes idx 0+1, engulfing search starts at idx 2)
    for i in range(5):
        ts = sweep_h1_ts + timedelta(minutes=i * 3)
        candles.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "complete": True,
            "bid_open": 2580.0, "bid_high": 2581.0, "bid_low": 2579.0, "bid_close": 2580.0,
            "ask_open": 2581.0, "ask_high": 2582.0, "ask_low": 2580.0, "ask_close": 2581.0,
            "volume": 50,
        })
    # Bar 5: prev bar — bearish body 2580→2578
    candles.append({
        "timestamp": (sweep_h1_ts + timedelta(minutes=5 * 3)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "complete": True,
        "bid_open": 2580.0, "bid_high": 2581.0, "bid_low": 2577.0, "bid_close": 2578.0,
        "ask_open": 2581.0, "ask_high": 2582.0, "ask_low": 2578.0, "ask_close": 2579.0,
        "volume": 80,
    })
    # Bar 6: engulfing bullish — open below prev body bottom, close above prev body top
    candles.append({
        "timestamp": (sweep_h1_ts + timedelta(minutes=6 * 3)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "complete": True,
        "bid_open": 2577.0, "bid_high": 2587.0, "bid_low": 2576.0, "bid_close": 2585.0,
        "ask_open": 2578.0, "ask_high": 2588.0, "ask_low": 2577.0, "ask_close": 2586.0,
        "volume": 200,
    })
    return candles


# =============================================================================
# Gold Macro
# =============================================================================

class TestGoldMacroFilter15:
    """Filter #15: sweep_key must be in _traded_sweeps_macro["keys"]
    even when execute_signal raises."""

    def test_execute_signal_raises_sweep_still_blacklisted(self, monkeypatch):
        """The bug: execute_signal raises → sweep never blacklisted →
        next cron retries same sweep. The fix: pre-add to blacklist before
        execute_signal, so even on raise the sweep is consumed."""

        # Patch DB calls + execute_signal at scheduler module level BEFORE import,
        # so the module's `from ... import execute_signal` brings in our mock.
        # Approach: monkeypatch after import (the import is `from x import y`,
        # so we patch the name as it lives in the scheduler module's namespace).

        # Stub all DB calls used inside _run_alpha_sweep_core
        def _stub_execute(sql, params=None, fetch=False):
            sql_lower = (sql or "").lower()
            if fetch:
                if "count(*)" in sql_lower:
                    return [{"cnt": 0}]
                if "from gd_signals" in sql_lower:
                    return []  # No recent signal → no cooldown
                return []
            return None

        # Mock execute_signal to RAISE — simulating DB INSERT failure or
        # MT5 timeout mid-flight
        mock_execute_signal = MagicMock(side_effect=RuntimeError("mock execute_signal raised"))

        # Import scheduler module
        sys.path.insert(0, ROOT)
        # Reset to ensure fresh module state for our test
        for k in list(sys.modules.keys()):
            if k.startswith(("backend.scanner", "backend.config")):
                del sys.modules[k]
        from backend.scanner import scheduler as sched

        # Patch the names as they live in the scheduler module's namespace
        monkeypatch.setattr(sched, "execute", _stub_execute)
        monkeypatch.setattr(sched, "execute_signal", mock_execute_signal)
        # Stub journal helpers so they don't try to hit DB on raise path
        monkeypatch.setattr(sched, "_log_journal_safe", MagicMock())
        monkeypatch.setattr(sched, "_log_journal", MagicMock())
        monkeypatch.setattr(sched, "_persist_m3_candles", MagicMock())

        # Reset sweep blacklist
        target_date = datetime(2026, 6, 14, tzinfo=timezone.utc)
        sched._traded_sweeps_macro = {"date": target_date.date(), "keys": set()}

        # Build candle fixtures
        h1_candles = _make_minimal_h1_candles_with_asia_sweep(target_date)
        daily_candles = _make_daily_candles(target_date)
        sweep_h1_ts = datetime.fromisoformat(
            h1_candles[-1]["timestamp"].replace("Z", "+00:00").replace(".000000000", ".000000")
        )
        m3_candles = _make_engulfing_m3_candles(sweep_h1_ts)

        # Call core fn at a time AFTER the engulfing M3 bar is available
        now = sweep_h1_ts + timedelta(minutes=20)

        # Sanity: blacklist is empty before we call
        assert len(sched._traded_sweeps_macro["keys"]) == 0

        # Run core fn live path. This should:
        #   1. Detect bullish sweep
        #   2. Find engulfing pattern
        #   3. Pre-add sweep_key to blacklist (Filter #15 fix)
        #   4. Call execute_signal — which raises
        #   5. Catch the exception, log it, but NOT remove from blacklist
        sched._run_alpha_sweep_core(now, h1_candles, daily_candles, m3_candles, dry_run=False)

        # Filter #15 assertion: even though execute_signal raised, the sweep
        # was added to the blacklist BEFORE the call → next cron tick won't
        # retry the same sweep.
        assert len(sched._traded_sweeps_macro["keys"]) >= 1, (
            "Filter #15 BUG: execute_signal raised, but sweep_key was NOT added to "
            "_traded_sweeps_macro. The next 3-min cron tick will retry the same sweep "
            "(orphan-trade cascade pattern). Pre-add must happen BEFORE execute_signal."
        )

        # Confirm execute_signal was actually called (sanity check that the
        # test exercised the fix path, not a different early-return)
        assert mock_execute_signal.called, (
            "Test setup error: execute_signal was never called, so we didn't "
            "actually exercise the race path. Check candle fixtures."
        )


# =============================================================================
# Oil Macro
# =============================================================================

class TestOilMacroFilter15:
    """Same test for Oil Macro (backend-oil/scanner/scheduler.py)."""

    def test_execute_signal_raises_sweep_still_blacklisted(self, monkeypatch):
        # Stub DB
        def _stub_execute(sql, params=None, fetch=False):
            sql_lower = (sql or "").lower()
            if fetch:
                if "count(*)" in sql_lower:
                    return [{"cnt": 0}]
                if "from gd_signals" in sql_lower:
                    return []
                return []
            return None

        mock_execute_signal = MagicMock(side_effect=RuntimeError("mock execute_signal raised"))

        # Import Oil Macro scheduler. backend-oil uses a different sys.path setup —
        # need to add backend-oil/ to path before importing.
        sys.path.insert(0, os.path.join(ROOT, "backend-oil"))
        for k in list(sys.modules.keys()):
            if k.startswith(("scanner", "config", "strategies", "data", "execution",
                             "backend.scanner", "backend.config")):
                del sys.modules[k]
        # Re-add backend root last so `import scanner.scheduler` resolves to backend-oil's
        if ROOT in sys.path:
            sys.path.remove(ROOT)
        sys.path.append(ROOT)

        try:
            from scanner import scheduler as sched
        finally:
            # Restore path so other tests aren't affected by our re-ordering
            if os.path.join(ROOT, "backend-oil") in sys.path:
                sys.path.remove(os.path.join(ROOT, "backend-oil"))
            if ROOT not in sys.path:
                sys.path.insert(0, ROOT)

        monkeypatch.setattr(sched, "execute", _stub_execute)
        monkeypatch.setattr(sched, "execute_signal", mock_execute_signal)
        monkeypatch.setattr(sched, "_log_journal_safe", MagicMock())
        monkeypatch.setattr(sched, "_log_journal", MagicMock())

        target_date = datetime(2026, 6, 14, tzinfo=timezone.utc)
        sched._traded_sweeps_oil = {"date": target_date.date(), "keys": set()}

        # Oil candles (same numerical fixtures — sweep + engulfing)
        h1_candles = _make_minimal_h1_candles_with_asia_sweep(target_date)
        daily_candles = _make_daily_candles(target_date)
        sweep_h1_ts = datetime.fromisoformat(
            h1_candles[-1]["timestamp"].replace("Z", "+00:00").replace(".000000000", ".000000")
        )
        m3_candles = _make_engulfing_m3_candles(sweep_h1_ts)

        now = sweep_h1_ts + timedelta(minutes=20)

        assert len(sched._traded_sweeps_oil["keys"]) == 0

        sched._run_alpha_sweep_core(now, h1_candles, daily_candles, m3_candles, dry_run=False)

        assert len(sched._traded_sweeps_oil["keys"]) >= 1, (
            "Filter #15 BUG (Oil Macro): execute_signal raised but sweep_key was NOT added "
            "to _traded_sweeps_oil. Pre-add must happen BEFORE execute_signal."
        )
        assert mock_execute_signal.called, "Test setup error: execute_signal was never called."
