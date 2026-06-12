"""TEST 16: Timezone Drift Bug (TDB) Regression Test.

Covers: MT5 server time → real UTC conversion in backend/execution/mt5_executor.py.

The Bug: MT5 EA writes bar timestamps in server local time (GMT+3 for JustMarkets),
but mt5_executor.py used to label them as UTC by appending "Z". This caused all 4
live trading systems (Gold Macro, Oil Macro, Gold Micro, Oil Micro) to filter
sessions 3 hours off from intended.

The Fix: _server_to_utc_iso() helper subtracts MT5_SERVER_OFFSET_HOURS to produce
real UTC timestamps that match backtest CSV format.

Runtime: <2 seconds total.
"""
import sys
import os
import re
import pytest
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# Test 1: Server-to-UTC ISO converter correctness
# ============================================================================

class TestServerToUTCConversion:
    """Verify _server_to_utc_iso() correctly converts GMT+3 → UTC."""

    def test_imports(self):
        """Helper function exists and is importable."""
        from backend.execution.mt5_executor import _server_to_utc_iso, MT5_SERVER_OFFSET_HOURS
        assert callable(_server_to_utc_iso)
        assert MT5_SERVER_OFFSET_HOURS == 3, "JustMarkets is GMT+3"

    def test_basic_conversion(self):
        """11 AM server time → 8 AM real UTC."""
        from backend.execution.mt5_executor import _server_to_utc_iso
        assert _server_to_utc_iso("2026.06.09 11:00:00") == "2026-06-09T08:00:00Z"

    def test_afternoon_conversion(self):
        """Trade fill timestamps from June 9 incident."""
        from backend.execution.mt5_executor import _server_to_utc_iso
        # Trade 1 fill: 18:42 server → 15:42 UTC
        assert _server_to_utc_iso("2026.06.09 18:42:00") == "2026-06-09T15:42:00Z"
        # Trade 2 fill: 18:24 server → 15:24 UTC
        assert _server_to_utc_iso("2026.06.09 18:24:00") == "2026-06-09T15:24:00Z"

    def test_midnight_wraparound(self):
        """Midnight server (00:00) crosses to previous day in UTC."""
        from backend.execution.mt5_executor import _server_to_utc_iso
        assert _server_to_utc_iso("2026.06.09 00:00:00") == "2026-06-08T21:00:00Z"

    def test_early_morning_wraparound(self):
        """2 AM server → 11 PM previous day UTC."""
        from backend.execution.mt5_executor import _server_to_utc_iso
        assert _server_to_utc_iso("2026.06.09 02:00:00") == "2026-06-08T23:00:00Z"

    def test_already_iso_passes_through(self):
        """If timestamp is already in ISO format, leave it alone (no '.' separator)."""
        from backend.execution.mt5_executor import _server_to_utc_iso
        # Already-ISO strings have '-' separators in date, not '.'
        assert _server_to_utc_iso("2026-06-09T08:00:00Z") == "2026-06-09T08:00:00Z"

    def test_malformed_input_fallback(self):
        """Malformed input shouldn't crash — falls back to legacy behavior."""
        from backend.execution.mt5_executor import _server_to_utc_iso
        # This is malformed but contains '.', should not raise
        result = _server_to_utc_iso("garbage.input.string")
        assert result is not None  # doesn't crash


# ============================================================================
# Test 2: _parse_mt5_time produces real UTC datetime
# ============================================================================

class TestParseMT5Time:
    """Verify _parse_mt5_time() returns real UTC datetimes."""

    def test_returns_real_utc(self):
        """Parsing 11:00 server time should give 08:00 UTC datetime."""
        from backend.execution.mt5_executor import _parse_mt5_time
        result = _parse_mt5_time("2026.06.09 11:00:00")
        assert result.hour == 8, f"Expected hour=8, got hour={result.hour}"
        assert result.tzinfo == timezone.utc

    def test_invalid_input_returns_now(self):
        """Invalid input falls back to datetime.now(utc) without crashing."""
        from backend.execution.mt5_executor import _parse_mt5_time
        result = _parse_mt5_time("not a valid timestamp")
        assert result.tzinfo == timezone.utc


# ============================================================================
# Test 3: Code-level check — old buggy line is gone
# ============================================================================

class TestNoLegacyBuggyCode:
    """Ensure the buggy line `t.replace(".", "-")...+ "Z"` is removed from get_candles."""

    def test_get_candles_uses_helper(self):
        """get_candles() must use _server_to_utc_iso(), not raw transformation."""
        path = os.path.join(PROJECT_ROOT, "backend/execution/mt5_executor.py")
        with open(path) as f:
            content = f.read()

        # The bug pattern should NOT appear in get_candles directly.
        # It can still appear in the fallback inside _server_to_utc_iso (legacy safety).
        # Find get_candles function body
        match = re.search(
            r'def get_candles\([^)]*\):.*?(?=\n(?:def |class |\Z))',
            content,
            re.DOTALL,
        )
        assert match, "Could not find get_candles function"
        body = match.group(0)

        # Old bug pattern: t.replace(".", "-").replace(" ", "T") + "Z"
        bug_pattern = r't\.replace\("\.", "-"\)\.replace\(" ", "T"\)\s*\+\s*"Z"'
        assert not re.search(bug_pattern, body), (
            "Buggy timestamp transformation still present in get_candles. "
            "Should use _server_to_utc_iso(t) instead."
        )

    def test_get_trade_details_uses_helper(self):
        """get_trade_details() must convert close_time via _server_to_utc_iso(),
        not the ad-hoc string-massage. Regression for the 2026-06-12 bug found
        via GD-MI-da28460d postmortem."""
        path = os.path.join(PROJECT_ROOT, "backend/execution/mt5_executor.py")
        with open(path) as f:
            content = f.read()

        match = re.search(
            r'def get_trade_details\([^)]*\):.*?(?=\n(?:def |class |\Z))',
            content,
            re.DOTALL,
        )
        assert match, "Could not find get_trade_details function"
        body = match.group(0)

        # Bug pattern: entry["close_time"].replace(".", "-")...
        bug_pattern = r'\["close_time"\]\.replace\("\.", "-"\)'
        assert not re.search(bug_pattern, body), (
            "Buggy timestamp transformation still present in get_trade_details. "
            "close_time must go through _server_to_utc_iso() to convert GMT+3 → UTC."
        )
        # Positive: must reference _server_to_utc_iso for close_time
        assert "_server_to_utc_iso(entry[\"close_time\"])" in body or \
               "_server_to_utc_iso(entry['close_time'])" in body, (
            "get_trade_details must call _server_to_utc_iso() on close_time."
        )

    def test_helper_function_exists(self):
        """_server_to_utc_iso must be defined in mt5_executor.py."""
        path = os.path.join(PROJECT_ROOT, "backend/execution/mt5_executor.py")
        with open(path) as f:
            content = f.read()
        assert "def _server_to_utc_iso" in content, "Helper function missing"
        assert "MT5_SERVER_OFFSET_HOURS" in content, "Offset constant missing"


# ============================================================================
# Test 4: Strategy filter alignment — Asia hours
# ============================================================================

class TestAsiaSessionAlignment:
    """After fix, ts.hour < 8 should select REAL UTC 0-7, not server 0-7."""

    def test_asia_hour_filter_real_utc(self):
        """Server 11:00 (= UTC 08:00) → ts.hour=8 → NOT in Asia (Asia is 0-7)."""
        from backend.execution.mt5_executor import _server_to_utc_iso

        ts_str = _server_to_utc_iso("2026.06.09 11:00:00")
        # Replicate scheduler.py _parse_ts
        cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
        ts = datetime.fromisoformat(cleaned)

        assert ts.hour == 8
        # Asia filter: 0 <= ts.hour < 8 → 8 is NOT Asia (correct)
        is_asia = 0 <= ts.hour < 8
        assert not is_asia, "Server 11:00 (UTC 08:00) should NOT be in Asia"

    def test_real_asia_bar_included(self):
        """Server 03:00 (= UTC 00:00 = real Tokyo open) → ts.hour=0 → IS Asia."""
        from backend.execution.mt5_executor import _server_to_utc_iso

        ts_str = _server_to_utc_iso("2026.06.09 03:00:00")
        cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
        ts = datetime.fromisoformat(cleaned)

        assert ts.hour == 0
        is_asia = 0 <= ts.hour < 8
        assert is_asia, "Server 03:00 (UTC 00:00 = real Tokyo open) should be in Asia"

    def test_pre_tdb_buggy_bars_excluded(self):
        """Server 00:00 (= UTC 21:00 prev day = NY close) → date is YESTERDAY, NOT today."""
        from backend.execution.mt5_executor import _server_to_utc_iso

        ts_str = _server_to_utc_iso("2026.06.09 00:00:00")
        cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
        ts = datetime.fromisoformat(cleaned)

        # Real UTC: 2026-06-08 21:00 (previous day's NY close)
        assert ts.hour == 21
        assert ts.date() == datetime(2026, 6, 8).date()

        # Asia filter: ts.date() == today AND 0 <= ts.hour < 8
        # If today is June 9: this bar's date is June 8, so it's correctly EXCLUDED
        today = datetime(2026, 6, 9).date()
        is_today = ts.date() == today
        assert not is_today, "Server 00:00 (real UTC 21:00 prev day) should NOT match today"


# ============================================================================
# Test 5: Scan window alignment — should cover real UTC 8-19
# ============================================================================

class TestScanWindowAlignment:
    """Live scan window should match backtest scan window."""

    def test_real_london_open_in_scan(self):
        """Server 11:00 (UTC 08:00 = real London Open) → ts.hour=8 → in scan window."""
        from backend.execution.mt5_executor import _server_to_utc_iso

        ts_str = _server_to_utc_iso("2026.06.09 11:00:00")
        cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
        ts = datetime.fromisoformat(cleaned)

        # Scan window: ts.hour >= 8 (cfg["scan_start"])
        assert ts.hour >= 8, "London Open should be in scan window"

    def test_late_ny_in_scan(self):
        """Server 22:00 (UTC 19:00 = late NY) → ts.hour=19 → in scan window (8-19)."""
        from backend.execution.mt5_executor import _server_to_utc_iso

        ts_str = _server_to_utc_iso("2026.06.09 22:00:00")
        cleaned = re.sub(r'(\.\d{6})\d+', r'\1', ts_str.replace("Z", "+00:00"))
        ts = datetime.fromisoformat(cleaned)

        assert ts.hour == 19


# ============================================================================
# Test 6: Configurable offset (other brokers)
# ============================================================================

class TestConfigurableOffset:
    """MT5_SERVER_OFFSET_HOURS should be overridable via env var."""

    def test_default_is_three(self):
        """Default offset is 3 (JustMarkets)."""
        from backend.execution.mt5_executor import MT5_SERVER_OFFSET_HOURS
        assert MT5_SERVER_OFFSET_HOURS == 3


# ============================================================================
# Test 7: get_trade_details() close_time conversion (TDB variant 2)
# ============================================================================

class TestGetTradeDetailsCloseTime:
    """Regression for the close_time bug found via GD-MI-da28460d postmortem
    on 2026-06-12. get_trade_details() returns the EA's GMT+3 server time
    converted to real UTC. Previously did ad-hoc string-massage and labelled
    GMT+3 as UTC — 3-hour error in DB exit_time. Fix: route through
    _server_to_utc_iso() (which already existed for bar timestamps).
    """

    def test_close_time_converted_to_utc(self, tmp_path, monkeypatch):
        """closed_orders.json entry like '2026.06.12 16:43:15' (server GMT+3)
        → get_trade_details returns '2026-06-12T13:43:15Z' (real UTC)."""
        import json as jsonlib
        fake_dir = tmp_path
        (fake_dir / "open_orders.json").write_text("{}")
        (fake_dir / "closed_orders.json").write_text(jsonlib.dumps([{
            "ticket": "2045156688",
            "symbol": "XAUUSD.ecn",
            "type": "BUY",
            "volume": 0.19,
            "open_price": 4204.09,
            "open_time": "2026.06.12 16:36:01",
            "close_price": 4184.63,
            "close_time": "2026.06.12 16:43:15",
            "profit": -369.74,
            "swap": 0.0,
            "commission": 0.0,
            "magic": 200000,
            "comment": "micro_alpha_sweep|GD-MI-da28460",
            "deal_reason": "SL",
        }]))

        from backend.execution import mt5_executor
        monkeypatch.setattr(mt5_executor, "DWX_DIR", str(fake_dir))

        details = mt5_executor.get_trade_details("2045156688")

        assert details is not None
        assert details["state"] == "CLOSED"
        # The fix: server GMT+3 16:43:15 → UTC 13:43:15
        assert details["close_time"] == "2026-06-12T13:43:15Z"
        assert details["close_price"] == 4184.63
        assert details["realized_pl"] == -369.74
        assert details["exit_reason"] == "SL"

    def test_close_time_iso_passthrough(self, tmp_path, monkeypatch):
        """If close_time is already in ISO form (no '.' separator), passthrough."""
        import json as jsonlib
        fake_dir = tmp_path
        (fake_dir / "open_orders.json").write_text("{}")
        (fake_dir / "closed_orders.json").write_text(jsonlib.dumps([{
            "ticket": "999",
            "symbol": "XAUUSD.ecn",
            "type": "BUY",
            "volume": 0.01,
            "open_price": 4200.0,
            "open_time": "2026-06-12T13:36:01Z",
            "close_price": 4201.0,
            "close_time": "2026-06-12T13:43:15Z",
            "profit": 0.01,
            "swap": 0.0,
            "commission": 0.0,
            "magic": 200000,
            "comment": "test",
            "deal_reason": "EXPERT",
        }]))

        from backend.execution import mt5_executor
        monkeypatch.setattr(mt5_executor, "DWX_DIR", str(fake_dir))

        details = mt5_executor.get_trade_details("999")
        assert details["close_time"] == "2026-06-12T13:43:15Z"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
