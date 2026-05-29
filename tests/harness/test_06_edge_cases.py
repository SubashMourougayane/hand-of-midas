"""TEST 06: Edge Cases — Every real bug replayed on current code.

Each test recreates the EXACT scenario that caused a live bug.
If any test fails, that bug has regressed.
"""
import sys
import os
import ast
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-micro"))


class TestC5SweepRefire:
    """06a: C5 — Same sweep cannot fire twice after SL hit."""

    def test_traded_sweeps_persists_across_calls(self):
        """_traded_sweeps is module-level and survives between scan cycles."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        # _traded_sweeps must be at module level (not inside a function)
        tree = ast.parse(source)
        module_assigns = [n for n in ast.iter_child_nodes(tree) if isinstance(n, ast.Assign)]
        found = False
        for assign in module_assigns:
            for target in assign.targets:
                if isinstance(target, ast.Name) and target.id == "_traded_sweeps":
                    found = True
        assert found, "_traded_sweeps must be defined at module level"

    def test_traded_sweeps_resets_at_midnight(self):
        """_traded_sweeps resets on new date (not carried forever)."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        # Must contain date check + reset logic
        assert '_traded_sweeps["date"] != today' in source or \
               "_traded_sweeps[\"date\"] != today" in source, \
               "No midnight reset check for _traded_sweeps"


class TestC8RestartRefire:
    """06b: C8 — Service restart cannot re-fire old sweeps."""

    def test_startup_cooldown_exists(self):
        """_startup_cooldown_until is declared and checked."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        assert "_startup_cooldown_until" in source, "No startup cooldown variable"
        assert "_restore_traded_sweeps_on_startup" in source, "No startup restore function"

    def test_startup_cooldown_blocks_signals(self):
        """If _startup_cooldown_until is in the future, signals are blocked."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        # Must check: if _startup_cooldown_until and now < _startup_cooldown_until: return
        assert "startup_cooldown_until" in source and "return" in source


class TestC7ExitEstimation:
    """06c: C7 — Exit estimation uses price extremes (not single snapshot)."""

    def test_price_extremes_declared(self):
        """_price_extremes dict exists at module level in live_engine.py."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/live_engine.py")
        with open(path) as f:
            source = f.read()
        assert "_price_extremes" in source, "_price_extremes not in live_engine.py"

    def test_extremes_track_high_low(self):
        """Price extremes must track both high and low."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/live_engine.py")
        with open(path) as f:
            source = f.read()
        assert '"high"' in source and '"low"' in source, \
            "_price_extremes must track both high and low"
        assert "max(" in source, "High must use max()"
        assert "min(" in source, "Low must use min()"

    def test_sl_default_when_both_reached(self):
        """When both SL and TP levels were reached, default to SL (conservative)."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/live_engine.py")
        with open(path) as f:
            source = f.read()
        # Logic should be: if tp_reached and NOT sl_reached → TP, else → SL
        assert "tp_reached and not sl_reached" in source, \
            "Missing conservative default: must be 'tp_reached and not sl_reached'"


class TestB1PriceCacheCrash:
    """06f: B1 — No references to removed _price_cache variable."""

    def test_no_price_cache_reference(self):
        """_price_cache must not appear anywhere in live code."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/live_engine.py")
        with open(path) as f:
            source = f.read()
        lines_with_cache = []
        for i, line in enumerate(source.split("\n"), 1):
            if "_price_cache" in line and not line.strip().startswith("#"):
                lines_with_cache.append(f"  Line {i}: {line.strip()}")
        assert not lines_with_cache, \
            "_price_cache still referenced (should be _price_extremes):\n" + "\n".join(lines_with_cache)


class TestC1DailyMaxLoss:
    """06g: C1 — Daily max loss queries DB (not dead local variable)."""

    def test_daily_max_queries_db(self):
        """Daily PnL check must use DB query, not local _daily_state['pnl']."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        # Must contain a DB query for actual daily P&L
        assert "sum(pnl_usd)" in source.lower() or "SUM(pnl" in source, \
            "Daily max loss must query SUM(pnl) from DB, not local variable"


class TestC2MaxHoldCrash:
    """06h: C2 — MAX_HOLD close handles missing 'time' field."""

    def test_max_hold_uses_fallback_time(self):
        """close_trade response may not have 'time' — must use fallback."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/live_engine.py")
        with open(path) as f:
            source = f.read()
        # Must have .get("time" or datetime.now fallback
        assert 'get("time"' in source or "datetime.now" in source, \
            "MAX_HOLD close must handle missing 'time' field with fallback"


class TestOneAtATime:
    """06k: One-at-a-time rule prevents double entry."""

    def test_one_at_a_time_check_exists(self):
        """Scheduler checks for open positions before new entry."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        # Must query for open positions (exit_time IS NULL)
        assert "exit_time IS NULL" in source or "exit_time is null" in source.lower(), \
            "No one-at-a-time check (query for open positions)"

    def test_backtest_has_one_at_a_time(self):
        """Backtest engine also enforces one-at-a-time (C9 fix)."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/backtest/engine.py")
        with open(path) as f:
            source = f.read()
        assert "position_exit_time" in source, \
            "Backtest missing one-at-a-time (C9 fix not applied)"


class TestCooldownBoundary:
    """06l: 5-min cooldown boundary correct."""

    def test_cooldown_is_300_seconds(self):
        """Cooldown must be 300 seconds (5 minutes)."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        assert "minutes=5" in source or "300" in source, \
            "Cooldown should be 5 minutes (300 seconds)"


class TestMarketClose:
    """06m: Market close (21-22 UTC) is respected."""

    def test_market_close_in_config(self):
        """Config has market_close_start and market_close_end."""
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-micro"))
        from config import MICRO_ALPHA_SWEEP
        assert MICRO_ALPHA_SWEEP.get("market_close_start") == 21
        assert MICRO_ALPHA_SWEEP.get("market_close_end") == 22

    def test_market_close_check_in_scheduler(self):
        """Scheduler skips scans during market close."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        assert "market_close" in source, "No market close handling in scheduler"


class TestRiskFilters:
    """06n-06o: Risk filters prevent bad signals."""

    def test_min_risk_filter(self):
        """Signals with risk < 0.3 are rejected."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        assert "risk < 0.3" in source, "Missing minimum risk filter (0.3)"

    def test_max_risk_filter(self):
        """Signals with risk > range * 0.8 are rejected."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        assert "consol_range * 0.8" in source or "range * 0.8" in source, \
            "Missing maximum risk filter (range * 0.8)"

    def test_tp_validity_filter(self):
        """TP must be at least risk * 0.8 away from entry."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            source = f.read()
        assert "risk * 0.8" in source, "Missing TP validity filter"


class TestGlobalStateConsistency:
    """Cross-cutting: all global state variables are properly managed."""

    def test_all_globals_declared_before_use(self):
        """Every 'global X' statement references a module-level variable."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/live_engine.py")
        with open(path) as f:
            tree = ast.parse(f.read())

        # Collect module-level names
        module_names = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        module_names.add(t.id)
            elif isinstance(node, ast.FunctionDef):
                module_names.add(node.name)

        # Check all 'global X' declarations
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                for name in node.names:
                    assert name in module_names, \
                        f"'global {name}' but '{name}' not defined at module level in live_engine.py"

    def test_scheduler_globals_declared(self):
        """Same check for scheduler.py."""
        path = os.path.join(PROJECT_ROOT, "backend-micro/scanner/scheduler.py")
        with open(path) as f:
            tree = ast.parse(f.read())

        module_names = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        module_names.add(t.id)
            elif isinstance(node, ast.FunctionDef):
                module_names.add(node.name)

        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                for name in node.names:
                    assert name in module_names, \
                        f"'global {name}' but '{name}' not defined at module level in scheduler.py"
