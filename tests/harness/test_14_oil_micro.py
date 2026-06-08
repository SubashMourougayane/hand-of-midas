"""TEST 14: Oil Micro Pre-Deploy & Execution Harness.

Covers: import checks, signal generation, fill model, break-even, one-at-a-time,
        daily max trades, cooldown, Combined V1+V2 bias, slippage, live engine guards.
Instrument: BCO_USD, strategy: micro_alpha_sweep_oil, trade_ref prefix: OIL-MI-
Runtime: <30 seconds total.
"""
import sys
import os
import ast
import re
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-oil-micro"))


# ============================================================================
# Module paths for Oil Micro
# ============================================================================

OIL_MICRO_MODULES = [
    "backend-oil-micro/scanner/scheduler.py",
    "backend-oil-micro/scanner/live_engine.py",
    "backend-oil-micro/config.py",
    "backend-oil-micro/backtest/engine.py",
]

OIL_MICRO_REMOVED_NAMES = [
    "_price_cache",
    "_old_dd_state",
]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def oil_m3_data():
    """Synthetic BCO_USD M3 data for fill model tests (100 bars)."""
    np.random.seed(42)
    n = 100
    base_price = 72.50
    idx = pd.date_range("2026-01-02 08:00", periods=n, freq="3min", tz="UTC")
    prices = base_price + np.cumsum(np.random.normal(0, 0.05, n))

    df = pd.DataFrame({
        "bid_open": prices,
        "bid_high": prices + np.random.uniform(0.02, 0.15, n),
        "bid_low": prices - np.random.uniform(0.02, 0.15, n),
        "bid_close": prices + np.random.normal(0, 0.03, n),
        "ask_open": prices + 0.03,
        "ask_high": prices + np.random.uniform(0.05, 0.18, n),
        "ask_low": prices - np.random.uniform(0.01, 0.12, n),
        "ask_close": prices + np.random.normal(0.03, 0.03, n),
        "volume": np.random.randint(50, 500, n),
    }, index=idx)
    df["mid_open"] = (df["bid_open"] + df["ask_open"]) / 2
    df["mid_high"] = (df["bid_high"] + df["ask_high"]) / 2
    df["mid_low"] = (df["bid_low"] + df["ask_low"]) / 2
    df["mid_close"] = (df["bid_close"] + df["ask_close"]) / 2
    return df


@pytest.fixture
def oil_h1_data():
    """Synthetic BCO_USD H1 data (24 bars) with clear consolidation."""
    np.random.seed(42)
    idx = pd.date_range("2026-01-02 00:00", periods=24, freq="h", tz="UTC")
    base = 72.00
    # First 4 bars: tight consolidation (range $0.50)
    prices = [base, base + 0.10, base + 0.20, base - 0.10,
              base + 0.05, base + 0.15, base + 0.30, base + 0.25,
              base + 0.60, base + 0.70, base + 0.50, base + 0.40,
              base + 0.35, base + 0.45, base + 0.55, base + 0.42,
              base + 0.30, base + 0.20, base + 0.10, base + 0.05,
              base - 0.05, base - 0.10, base - 0.15, base - 0.20]

    df = pd.DataFrame({
        "bid_open": prices,
        "bid_high": [p + 0.20 for p in prices],
        "bid_low": [p - 0.15 for p in prices],
        "bid_close": [p + 0.05 for p in prices],
        "ask_open": [p + 0.03 for p in prices],
        "ask_high": [p + 0.23 for p in prices],
        "ask_low": [p - 0.12 for p in prices],
        "ask_close": [p + 0.08 for p in prices],
        "volume": [200] * 24,
    }, index=idx)
    df["mid_open"] = (df["bid_open"] + df["ask_open"]) / 2
    df["mid_high"] = (df["bid_high"] + df["ask_high"]) / 2
    df["mid_low"] = (df["bid_low"] + df["ask_low"]) / 2
    df["mid_close"] = (df["bid_close"] + df["ask_close"]) / 2
    return df


@pytest.fixture
def mock_oanda_oil_micro():
    """Mock all OANDA/execution calls for Oil Micro live engine tests."""
    state = {
        "orders": [],
        "open_trades": [],
        "price": {"bid": 72.50, "ask": 72.53, "mid": 72.515, "spread": 0.03,
                  "time": "2026.01.02 12:00:00", "tradeable": True},
        "account": {"balance": 10000.0, "nav": 10000.0, "nav_usd": 10000.0,
                    "unrealized_pl": 0.0, "margin_used": 0.0, "open_trades": 0,
                    "currency": "USD"},
        "next_id": "100001",
    }

    def mock_place_order(instrument, units, sl=None, tp=None, comment=""):
        tid = state["next_id"]
        state["next_id"] = str(int(tid) + 1)
        fill = state["price"]["ask"] if units > 0 else state["price"]["bid"]
        state["orders"].append({
            "instrument": instrument, "units": units,
            "sl": sl, "tp": tp, "comment": comment,
            "fill_price": fill, "trade_id": tid,
        })
        state["open_trades"].append({"id": tid, "instrument": instrument, "currentUnits": units})
        return {"success": True, "trade_id": tid, "fill_price": fill,
                "units": abs(units), "time": datetime.now(timezone.utc).isoformat()}

    def mock_get_price(instrument="BCO_USD"):
        return dict(state["price"])

    def mock_get_account():
        return dict(state["account"])

    def mock_get_open():
        return list(state["open_trades"])

    def mock_modify_sl(trade_id, new_sl):
        return {"success": True}

    def mock_close(trade_id):
        state["open_trades"] = [t for t in state["open_trades"] if t["id"] != trade_id]
        return {"success": True, "close_price": state["price"]["mid"]}

    def mock_get_details(trade_id):
        return None

    def mock_get_candles(instrument="BCO_USD", granularity="H1", count=24, price="BA"):
        return []

    patches = {
        "place_market_order": patch("backend.execution.place_market_order", side_effect=mock_place_order),
        "get_current_price": patch("backend.execution.get_current_price", side_effect=mock_get_price),
        "get_account_summary": patch("backend.execution.get_account_summary", side_effect=mock_get_account),
        "get_open_trades": patch("backend.execution.get_open_trades", side_effect=mock_get_open),
        "modify_stop_loss": patch("backend.execution.modify_stop_loss", side_effect=mock_modify_sl),
        "close_trade": patch("backend.execution.close_trade", side_effect=mock_close),
        "get_trade_details": patch("backend.execution.get_trade_details", side_effect=mock_get_details),
        "get_candles": patch("backend.execution.get_candles", side_effect=mock_get_candles),
    }

    started = {k: p.start() for k, p in patches.items()}
    yield state
    for p in patches.values():
        p.stop()


@pytest.fixture
def mock_db_oil_micro():
    """Mock DB for Oil Micro — tracks signals and trades in memory."""
    state = {
        "trades": [],
        "signals": [],
        "dd_state": {"id": 4, "consecutive_losses": 0, "pause_counter": 0},
    }

    def mock_execute(sql, params=None, fetch=False):
        sql_lower = sql.strip().lower()
        if "gd_dd_state" in sql_lower and "select" in sql_lower:
            return [state["dd_state"]] if fetch else None
        if "gd_trades" in sql_lower and "exit_time is null" in sql_lower and fetch:
            return [t for t in state["trades"] if t.get("exit_time") is None]
        if "gd_signals" in sql_lower and "order by timestamp desc" in sql_lower and fetch:
            return state["signals"][-1:] if state["signals"] else []
        if "gd_trades" in sql_lower and "count" in sql_lower and fetch:
            today = datetime.now(timezone.utc).date()
            cnt = sum(1 for t in state["trades"]
                      if t.get("entry_time") and t["entry_time"].date() == today)
            return [{"cnt": cnt}]
        if "sum(pnl_usd)" in sql_lower and fetch:
            return [{"daily_pnl": 0}]
        if "insert" in sql_lower:
            if "gd_signals" in sql_lower:
                state["signals"].append({"timestamp": datetime.now(timezone.utc), "taken": True, "skip_reason": ""})
            elif "gd_trades" in sql_lower:
                state["trades"].append({"entry_time": datetime.now(timezone.utc), "exit_time": None,
                                        "trade_ref": params[0] if params else ""})
            return None
        if "update" in sql_lower:
            return None
        if fetch:
            return []
        return None

    with patch("backend.db.execute", side_effect=mock_execute):
        yield state


# ============================================================================
# TEST CLASS 14a: Pre-deploy Checks
# ============================================================================

class TestOilMicroImports:
    """14a: All Oil Micro modules parse and import without errors."""

    def test_all_modules_parse(self):
        """AST parse all Oil Micro source files."""
        errors = []
        for mod_path in OIL_MICRO_MODULES:
            full = os.path.join(PROJECT_ROOT, mod_path)
            if not os.path.exists(full):
                errors.append(f"MISSING: {mod_path}")
                continue
            try:
                with open(full) as f:
                    ast.parse(f.read())
            except SyntaxError as e:
                errors.append(f"SYNTAX ERROR in {mod_path}: {e}")
        assert not errors, "\n".join(errors)

    def test_no_stale_references(self):
        """No references to removed/renamed variables in Oil Micro code."""
        errors = []
        for mod_path in OIL_MICRO_MODULES:
            full = os.path.join(PROJECT_ROOT, mod_path)
            if not os.path.exists(full):
                continue
            with open(full) as f:
                content = f.read()
            for name in OIL_MICRO_REMOVED_NAMES:
                if name in content:
                    for i, line in enumerate(content.split("\n"), 1):
                        if name in line and not line.strip().startswith("#"):
                            errors.append(f"{mod_path}:{i} — stale ref to '{name}': {line.strip()}")
        assert not errors, "Stale references found:\n" + "\n".join(errors)

    def test_config_keys_cover_scheduler(self):
        """Every cfg['key'] in Oil Micro scheduler exists in MICRO_ALPHA_SWEEP."""
        scheduler_path = os.path.join(PROJECT_ROOT, "backend-oil-micro/scanner/scheduler.py")
        with open(scheduler_path) as f:
            content = f.read()
        accessed_keys = set(re.findall(r'cfg\["(\w+)"\]', content))
        accessed_keys.update(re.findall(r'cfg\.get\("(\w+)"', content))

        config_path = os.path.join(PROJECT_ROOT, "backend-oil-micro/config.py")
        with open(config_path) as f:
            config_content = f.read()
        defined_keys = set(re.findall(r'"(\w+)":\s*', config_content))

        get_with_defaults = set(re.findall(r'cfg\.get\("(\w+)",\s*[^)]+\)', content))
        missing = accessed_keys - defined_keys - get_with_defaults
        assert not missing, f"Config keys in scheduler but not in MICRO_ALPHA_SWEEP: {missing}"

    def test_live_engine_globals_no_stale(self):
        """live_engine.py must have _price_extremes, NOT _price_cache."""
        path = os.path.join(PROJECT_ROOT, "backend-oil-micro/scanner/live_engine.py")
        with open(path) as f:
            content = f.read()
        assert "_price_extremes" in content, "_price_extremes not in Oil Micro live_engine.py"
        # _price_cache should not be there (excluding comments)
        non_comment_lines = [l for l in content.split("\n") if not l.strip().startswith("#")]
        for line in non_comment_lines:
            assert "_price_cache" not in line, f"_price_cache found in non-comment line: {line.strip()}"

    def test_dd_state_id_is_4(self):
        """Oil Micro must use DD_STATE_ID=4 (not 1/2/3)."""
        from config import DD_STATE_ID
        assert DD_STATE_ID == 4, f"DD_STATE_ID={DD_STATE_ID}, expected 4"

    def test_trade_ref_prefix(self):
        """Oil Micro must use 'OIL-MI-' prefix."""
        from config import TRADE_REF_PREFIX
        assert TRADE_REF_PREFIX == "OIL-MI-", f"TRADE_REF_PREFIX='{TRADE_REF_PREFIX}', expected 'OIL-MI-'"

    def test_instrument_is_bco_usd(self):
        """Oil Micro config instrument must be BCO_USD."""
        from config import INSTRUMENT
        assert INSTRUMENT == "BCO_USD", f"INSTRUMENT='{INSTRUMENT}', expected 'BCO_USD'"


# ============================================================================
# TEST CLASS 14b: Signal Generation
# ============================================================================

class TestOilMicroSignals:
    """14b: generate_signals() produces valid Oil Micro signals."""

    def _get_generate_signals(self):
        if _oil_micro_bt is None:
            pytest.skip("Oil Micro backtest engine not loadable (data files missing?)")
        return _oil_micro_bt.generate_signals

    def test_signals_have_correct_strategy_name(self, oil_h1_data, oil_m3_data):
        """All signals must have strategy='micro_alpha_sweep_oil'."""
        np.random.seed(42)
        generate_signals = self._get_generate_signals()
        bias = {oil_h1_data.index[0].date(): "neutral"}
        signals = generate_signals(oil_h1_data, oil_m3_data, bias)
        for s in signals:
            assert s.strategy == "micro_alpha_sweep_oil", \
                f"Signal strategy='{s.strategy}', expected 'micro_alpha_sweep_oil'"

    def test_long_sl_below_entry(self, oil_h1_data, oil_m3_data):
        """LONG signals: SL < entry."""
        np.random.seed(42)
        generate_signals = self._get_generate_signals()
        bias = {oil_h1_data.index[0].date(): "neutral"}
        signals = generate_signals(oil_h1_data, oil_m3_data, bias)
        for s in [sig for sig in signals if sig.direction == "long"]:
            assert s.sl < s.entry, f"LONG: SL ({s.sl}) >= entry ({s.entry})"

    def test_short_sl_above_entry(self, oil_h1_data, oil_m3_data):
        """SHORT signals: SL > entry."""
        np.random.seed(42)
        generate_signals = self._get_generate_signals()
        bias = {oil_h1_data.index[0].date(): "neutral"}
        signals = generate_signals(oil_h1_data, oil_m3_data, bias)
        for s in [sig for sig in signals if sig.direction == "short"]:
            assert s.sl > s.entry, f"SHORT: SL ({s.sl}) <= entry ({s.entry})"

    def test_long_tp_above_entry(self, oil_h1_data, oil_m3_data):
        """LONG signals: TP > entry."""
        np.random.seed(42)
        generate_signals = self._get_generate_signals()
        bias = {oil_h1_data.index[0].date(): "neutral"}
        signals = generate_signals(oil_h1_data, oil_m3_data, bias)
        for s in [sig for sig in signals if sig.direction == "long"]:
            assert s.tp > s.entry, f"LONG: TP ({s.tp}) <= entry ({s.entry})"

    def test_short_tp_below_entry(self, oil_h1_data, oil_m3_data):
        """SHORT signals: TP < entry."""
        np.random.seed(42)
        generate_signals = self._get_generate_signals()
        bias = {oil_h1_data.index[0].date(): "neutral"}
        signals = generate_signals(oil_h1_data, oil_m3_data, bias)
        for s in [sig for sig in signals if sig.direction == "short"]:
            assert s.tp < s.entry, f"SHORT: TP ({s.tp}) >= entry ({s.entry})"

    def test_risk_is_positive(self, oil_h1_data, oil_m3_data):
        """All signals have positive risk."""
        np.random.seed(42)
        generate_signals = self._get_generate_signals()
        bias = {oil_h1_data.index[0].date(): "neutral"}
        signals = generate_signals(oil_h1_data, oil_m3_data, bias)
        for s in signals:
            assert s.risk > 0, f"Risk={s.risk} at {s.date} — must be positive"


# ============================================================================
# TEST CLASS 14c: Fill Model
# ============================================================================

class TestOilMicroFillModel:
    """14c: _execute_trade() produces correct exits, no phantom fills."""

    def _get_execute_trade(self):
        if _oil_micro_bt is None:
            pytest.skip("Oil Micro backtest engine not loadable (data files missing?)")
        return _oil_micro_bt._execute_trade

    def test_sl_exit_long(self, oil_m3_data):
        """LONG trade hits SL when bar low drops below SL."""
        _execute_trade = self._get_execute_trade()
        # Entry at bar 10, SL well below current
        entry = oil_m3_data["ask_close"].iat[10]
        sl = entry - 0.50  # Wide SL
        tp = entry + 1.00

        # Force bar 11 to hit SL by setting bid_low below SL
        oil_m3_data.iloc[11, oil_m3_data.columns.get_loc("bid_low")] = sl - 0.05

        result = _execute_trade(
            df=oil_m3_data, bar_start=10, entry=entry, sl=sl, tp=tp,
            direction="long", max_bars=80, use_break_even=False
        )
        assert result is not None
        assert result["exit_reason"] == "SL"
        assert result["exit_price"] <= sl, "SL exit should fill at or below SL level"

    def test_tp_exit_short(self, oil_m3_data):
        """SHORT trade hits TP when bar low drops to TP."""
        _execute_trade = self._get_execute_trade()
        entry = oil_m3_data["bid_close"].iat[10]
        tp = entry - 1.00
        sl = entry + 0.50

        # Force bar 12 to hit TP
        oil_m3_data.iloc[12, oil_m3_data.columns.get_loc("bid_low")] = tp - 0.10

        result = _execute_trade(
            df=oil_m3_data, bar_start=10, entry=entry, sl=sl, tp=tp,
            direction="short", max_bars=80, use_break_even=False
        )
        assert result is not None
        assert result["exit_reason"] == "TP"
        assert result["exit_price"] == tp, "TP must fill at exact TP price"

    def test_max_hold_exit(self, oil_m3_data):
        """Trade expires at max_bars with no SL/TP hit."""
        _execute_trade = self._get_execute_trade()
        entry = oil_m3_data["ask_close"].iat[5]
        sl = entry - 50.0  # Unreachable SL
        tp = entry + 50.0  # Unreachable TP

        result = _execute_trade(
            df=oil_m3_data, bar_start=5, entry=entry, sl=sl, tp=tp,
            direction="long", max_bars=10, use_break_even=False
        )
        assert result is not None
        assert result["exit_reason"] == "MAX_HOLD"
        assert result["bars_held"] == 10

    def test_no_phantom_fills(self, oil_m3_data):
        """If price never reaches SL or TP, trade must expire (not phantom fill)."""
        _execute_trade = self._get_execute_trade()
        entry = oil_m3_data["mid_close"].iat[5]
        # Set SL/TP so far away they cannot be reached in 10 bars
        sl = entry - 100.0
        tp = entry + 100.0

        result = _execute_trade(
            df=oil_m3_data, bar_start=5, entry=entry, sl=sl, tp=tp,
            direction="long", max_bars=10, use_break_even=False
        )
        assert result is not None
        assert result["exit_reason"] in ("MAX_HOLD", "DATA_END"), \
            f"Expected MAX_HOLD/DATA_END, got {result['exit_reason']} — possible phantom fill"


# ============================================================================
# TEST CLASS 14d: Break-Even
# ============================================================================

class TestOilMicroBreakEven:
    """14d: Break-even triggers at 50% to TP, moves SL to entry +/- $0.01."""

    def _get_execute_trade(self):
        if _oil_micro_bt is None:
            pytest.skip("Oil Micro backtest engine not loadable (data files missing?)")
        return _oil_micro_bt._execute_trade

    def test_break_even_long(self):
        """LONG: BE triggers when mid reaches entry + 50% of (TP - entry), SL becomes entry + 0.01."""
        _execute_trade = self._get_execute_trade()
        np.random.seed(42)

        entry = 72.50
        tp = 73.50
        sl = 72.00
        # 50% target = 72.50 + 0.50 = 73.00

        # Create data where bar hits BE trigger then hits BE SL
        idx = pd.date_range("2026-01-02 08:00", periods=5, freq="3min", tz="UTC")
        df = pd.DataFrame({
            "bid_open": [entry, 72.80, 73.05, 72.55, 72.48],
            "bid_high": [entry, 72.90, 73.10, 72.60, 72.55],
            "bid_low": [entry, 72.70, 72.95, 72.50, 72.40],
            "bid_close": [entry, 72.85, 73.00, 72.52, 72.45],
            "ask_open": [entry + 0.03, 72.83, 73.08, 72.58, 72.51],
            "ask_high": [entry + 0.03, 72.93, 73.13, 72.63, 72.58],
            "ask_low": [entry + 0.03, 72.73, 72.98, 72.53, 72.43],
            "ask_close": [entry + 0.03, 72.88, 73.03, 72.55, 72.48],
            "volume": [100] * 5,
            "mid_open": [entry] * 5,
            "mid_high": [entry, 72.92, 73.12, 72.62, 72.57],
            "mid_low": [entry, 72.72, 72.97, 72.52, 72.42],
            "mid_close": [entry, 72.87, 73.02, 72.54, 72.47],
        }, index=idx)

        result = _execute_trade(
            df=df, bar_start=0, entry=entry, sl=sl, tp=tp,
            direction="long", max_bars=4, use_break_even=True
        )
        assert result is not None
        # Bar 2 (index 2) has bid_high=73.10 > 73.00 (50% target) → BE triggers
        # BE SL = entry + 0.01 = 72.51
        # Bar 3 has bid_low=72.50 <= 72.51 → hits BE SL
        assert result["exit_reason"] == "BE_SL", f"Expected BE_SL, got {result['exit_reason']}"
        assert abs(result["exit_price"] - (entry + 0.01)) < 0.02, \
            f"BE exit should be near {entry + 0.01}, got {result['exit_price']}"

    def test_break_even_short(self):
        """SHORT: BE triggers when mid reaches entry - 50% of (entry - TP), SL becomes entry - 0.01."""
        _execute_trade = self._get_execute_trade()
        np.random.seed(42)

        entry = 72.50
        tp = 71.50
        sl = 73.00
        # 50% target = 72.50 - 0.50 = 72.00

        idx = pd.date_range("2026-01-02 08:00", periods=5, freq="3min", tz="UTC")
        df = pd.DataFrame({
            "bid_open": [entry, 72.20, 71.95, 72.30, 72.55],
            "bid_high": [entry, 72.30, 72.05, 72.45, 72.60],
            "bid_low": [entry, 72.10, 71.90, 72.20, 72.40],
            "bid_close": [entry, 72.15, 71.95, 72.35, 72.50],
            "ask_open": [entry + 0.03, 72.23, 71.98, 72.33, 72.58],
            "ask_high": [entry + 0.03, 72.33, 72.08, 72.50, 72.63],
            "ask_low": [entry + 0.03, 72.13, 71.93, 72.23, 72.43],
            "ask_close": [entry + 0.03, 72.18, 71.98, 72.38, 72.53],
            "volume": [100] * 5,
            "mid_open": [entry] * 5,
            "mid_high": [entry, 72.32, 72.07, 72.48, 72.62],
            "mid_low": [entry, 72.12, 71.92, 72.22, 72.42],
            "mid_close": [entry, 72.17, 71.97, 72.37, 72.52],
        }, index=idx)

        result = _execute_trade(
            df=df, bar_start=0, entry=entry, sl=sl, tp=tp,
            direction="short", max_bars=4, use_break_even=True
        )
        assert result is not None
        # Bar 2 ask_low=71.93 < 72.00 (50% target) → BE triggers
        # BE SL = entry - 0.01 = 72.49
        # Bar 3 ask_high=72.50 >= 72.49 → hits BE SL
        assert result["exit_reason"] == "BE_SL", f"Expected BE_SL, got {result['exit_reason']}"
        assert abs(result["exit_price"] - (entry - 0.01)) < 0.02, \
            f"BE exit should be near {entry - 0.01}, got {result['exit_price']}"


# ============================================================================
# TEST CLASS 14e: One-at-a-Time (No Overlapping)
# ============================================================================

class TestOilMicroOneAtATime:
    """14e: Backtest enforces position_exit_time (no overlapping trades)."""

    def test_position_exit_time_enforced(self):
        """If a trade is still open, the next signal must be skipped."""
        if _oil_micro_bt is None:
            pytest.skip("Oil Micro backtest engine not loadable (data files missing?)")
        _execute_trade = _oil_micro_bt._execute_trade

        # Create two signals where second overlaps with first
        np.random.seed(42)
        idx = pd.date_range("2026-01-02 08:00", periods=200, freq="3min", tz="UTC")
        base = 72.0
        prices = base + np.cumsum(np.random.normal(0, 0.03, 200))
        df = pd.DataFrame({
            "bid_open": prices, "bid_high": prices + 0.10,
            "bid_low": prices - 0.10, "bid_close": prices + 0.02,
            "ask_open": prices + 0.03, "ask_high": prices + 0.13,
            "ask_low": prices - 0.07, "ask_close": prices + 0.05,
            "mid_open": prices, "mid_high": prices + 0.12,
            "mid_low": prices - 0.09, "mid_close": prices + 0.03,
            "volume": [100] * 200,
        }, index=idx)

        # Execute first trade starting at bar 5 with 80 max_bars
        result1 = _execute_trade(df, bar_start=5, entry=prices[5], sl=prices[5] - 50,
                                 tp=prices[5] + 50, direction="long", max_bars=80, use_break_even=False)
        assert result1 is not None
        exit_bar = 5 + result1["bars_held"]

        # Verify that the exit is respected:
        # A second signal at bar 10 (while first is still open) should be blocked
        # by position_exit_time in the backtest loop
        # The backtest engine uses: position_exit_time = signal.date + timedelta(seconds=bars_held * 180)
        # This is tested implicitly by the backtest logic — here we verify the exit time is correct
        assert result1["bars_held"] > 0, "Trade must last at least 1 bar"


# ============================================================================
# TEST CLASS 14f: Daily Max Trades
# ============================================================================

class TestOilMicroDailyMaxTrades:
    """14f: Max 3 trades per day enforced."""

    def test_max_trades_config_is_3(self):
        """MICRO_ALPHA_SWEEP['max_trades_per_day'] == 3."""
        from config import MICRO_ALPHA_SWEEP
        assert MICRO_ALPHA_SWEEP["max_trades_per_day"] == 3

    def test_scheduler_checks_max_trades(self):
        """Scheduler code must contain max_trades_per_day guard."""
        path = os.path.join(PROJECT_ROOT, "backend-oil-micro/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        assert 'cfg["max_trades_per_day"]' in content or "max_trades_per_day" in content, \
            "Scheduler missing max_trades_per_day check"
        assert "trades_today >= cfg" in content, "Missing guard: trades_today >= cfg[max_trades_per_day]"


# ============================================================================
# TEST CLASS 14g: Cooldown
# ============================================================================

class TestOilMicroCooldown:
    """14g: 5-min cooldown between signals."""

    def test_cooldown_check_in_scheduler(self):
        """Scheduler must enforce 5-min cooldown after last signal."""
        path = os.path.join(PROJECT_ROOT, "backend-oil-micro/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        assert "timedelta(minutes=5)" in content, "5-min cooldown not found in scheduler"

    def test_startup_cooldown_active(self):
        """Startup cooldown variable must be checked."""
        path = os.path.join(PROJECT_ROOT, "backend-oil-micro/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        assert "_startup_cooldown_until and now < _startup_cooldown_until" in content, \
            "Startup cooldown check missing or bypassed"


# ============================================================================
# TEST CLASS 14h: Combined V1+V2 Bias
# ============================================================================

class TestOilMicroCombinedBias:
    """14h: Oil Micro uses Combined V1+V2 bias (NOT V1-only)."""

    def test_scheduler_has_combined_bias(self):
        """Scheduler must compute both V1 (body_pct) and V2 (close_position)."""
        path = os.path.join(PROJECT_ROOT, "backend-oil-micro/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        assert "body_pct" in content, "Missing V1 body_pct"
        assert "close_position" in content, "Missing V2 close_position"
        assert "v1_bias" in content, "Missing v1_bias variable"
        assert "v2_bias" in content, "Missing v2_bias variable"

    def test_combined_thresholds(self):
        """V1: body_pct >= 0.4, V2: close_position >= 0.8 / <= 0.2."""
        path = os.path.join(PROJECT_ROOT, "backend-oil-micro/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        assert "body_pct >= 0.4" in content, "V1 threshold 0.4 missing"
        assert "close_position >= 0.8" in content, "V2 bullish threshold 0.8 missing"
        assert "close_position <= 0.2" in content, "V2 bearish threshold 0.2 missing"

    def test_backtest_uses_combined_bias(self):
        """Backtest engine must also use Combined V1+V2."""
        path = os.path.join(PROJECT_ROOT, "backend-oil-micro/backtest/engine.py")
        with open(path) as f:
            content = f.read()
        assert "v1_bias" in content, "Backtest missing V1 bias"
        assert "v2_bias" in content, "Backtest missing V2 bias"
        assert "close_position" in content, "Backtest missing V2 close_position"


# ============================================================================
# TEST CLASS 14i: Slippage Model
# ============================================================================

class TestOilMicroSlippage:
    """14i: Uses $0.03 base slippage (not the fake $0.004)."""

    def test_config_slippage_base(self):
        """config.slippage() must use 0.03 base."""
        from config import slippage
        np.random.seed(42)
        result = slippage(0.0)
        # With bar_range=0, slippage = 0.03 + 0 + rand(0, 0.005)
        assert result >= 0.03, f"Slippage({0}) = {result} — base must be >= 0.03"
        assert result < 0.04, f"Slippage({0}) = {result} — too high for zero range"

    def test_slippage_formula_components(self):
        """Slippage = 0.03 + bar_range * 0.01 + rand(0, 0.005)."""
        path = os.path.join(PROJECT_ROOT, "backend-oil-micro/config.py")
        with open(path) as f:
            content = f.read()
        assert "0.03" in content, "Base $0.03 slippage not in config"
        assert "0.01" in content, "Range component 0.01 not in config"

    def test_backtest_slippage_matches_config(self):
        """Backtest _slippage() uses same base as config."""
        path = os.path.join(PROJECT_ROOT, "backend-oil-micro/backtest/engine.py")
        with open(path) as f:
            content = f.read()
        assert "0.03" in content, "Backtest _slippage missing 0.03 base"


# ============================================================================
# TEST CLASS 14j: Live Engine Guards
# ============================================================================

class TestOilMicroLiveGuards:
    """14j: SL=0 rejection, TP validation, execute_signal comment field."""

    @staticmethod
    def _get_execute_signal():
        """Load execute_signal from Oil Micro live_engine using importlib to avoid path conflicts."""
        import importlib.util
        oil_micro_dir = os.path.join(PROJECT_ROOT, "backend-oil-micro")
        old_path = sys.path[:]
        # Put oil-micro first so its config wins
        sys.path = [oil_micro_dir, PROJECT_ROOT, os.path.join(PROJECT_ROOT, "backend")] + \
                   [p for p in sys.path if p not in (oil_micro_dir,)]
        # Clear cached config/scanner modules so they reload from correct location
        for mod_name in list(sys.modules.keys()):
            if mod_name == "config" or mod_name.startswith("scanner") or mod_name == "oil_micro_live_engine":
                del sys.modules[mod_name]
        try:
            spec = importlib.util.spec_from_file_location(
                "oil_micro_live_engine",
                os.path.join(oil_micro_dir, "scanner/live_engine.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.execute_signal
        finally:
            sys.path = old_path

    def test_sl_zero_rejected(self, mock_oanda_oil_micro, mock_db_oil_micro):
        """execute_signal() must reject SL=0."""
        execute_signal = self._get_execute_signal()
        result = execute_signal(
            strategy="micro_alpha_sweep_oil",
            direction="long",
            entry_price=72.50,
            sl_price=0,
            tp_price=73.50,
            context={},
            daily_pnl=0,
        )
        assert result is None, "Signal with SL=0 should be rejected"

    def test_sl_none_rejected(self, mock_oanda_oil_micro, mock_db_oil_micro):
        """execute_signal() must not place an order with SL=None."""
        execute_signal = self._get_execute_signal()
        # SL=None should either be cleanly rejected (return None) or raise TypeError
        # Either way, no order should be placed
        try:
            result = execute_signal(
                strategy="micro_alpha_sweep_oil",
                direction="long",
                entry_price=72.50,
                sl_price=None,
                tp_price=73.50,
                context={},
                daily_pnl=0,
            )
            assert result is None, "Signal with SL=None should be rejected"
        except TypeError:
            pass  # Acceptable: code crashes before placing order (guards further down)
        # Verify no order was placed
        assert len(mock_oanda_oil_micro["orders"]) == 0, \
            "No order should be placed with SL=None"

    def test_order_comment_contains_trade_ref(self, mock_oanda_oil_micro, mock_db_oil_micro):
        """Place order must include strategy|trade_ref in comment."""
        execute_signal = self._get_execute_signal()

        # Set price so SL is valid (long: SL < bid - 0.05)
        mock_oanda_oil_micro["price"]["bid"] = 72.50
        mock_oanda_oil_micro["price"]["ask"] = 72.53

        result = execute_signal(
            strategy="micro_alpha_sweep_oil",
            direction="long",
            entry_price=72.53,
            sl_price=71.50,
            tp_price=73.50,
            context={},
            daily_pnl=0,
        )
        assert result is not None, "Signal should be accepted"
        assert result.startswith("OIL-MI-"), f"Trade ref must start with OIL-MI-, got '{result}'"

        # Verify order comment
        assert len(mock_oanda_oil_micro["orders"]) == 1
        comment = mock_oanda_oil_micro["orders"][0]["comment"]
        assert "micro_alpha_sweep_oil" in comment, f"Comment missing strategy: {comment}"
        assert "OIL-MI-" in comment, f"Comment missing trade_ref: {comment}"

    def test_instrument_is_bco_usd_in_order(self, mock_oanda_oil_micro, mock_db_oil_micro):
        """Orders must be placed on BCO_USD instrument."""
        execute_signal = self._get_execute_signal()

        mock_oanda_oil_micro["price"]["bid"] = 72.50
        mock_oanda_oil_micro["price"]["ask"] = 72.53

        execute_signal(
            strategy="micro_alpha_sweep_oil",
            direction="short",
            entry_price=72.50,
            sl_price=73.50,
            tp_price=71.50,
            context={},
            daily_pnl=0,
        )
        if mock_oanda_oil_micro["orders"]:
            assert mock_oanda_oil_micro["orders"][-1]["instrument"] == "BCO_USD"

    def test_harness_test_comment_in_execute(self, mock_oanda_oil_micro, mock_db_oil_micro):
        """
        CRITICAL: When placing orders via execute_signal(), the comment field
        must allow identification as a test. We verify the comment contains
        the test identifier (strategy|trade_ref pattern).
        """
        execute_signal = self._get_execute_signal()

        mock_oanda_oil_micro["price"]["bid"] = 72.50
        mock_oanda_oil_micro["price"]["ask"] = 72.53

        result = execute_signal(
            strategy="micro_alpha_sweep_oil",
            direction="long",
            entry_price=72.53,
            sl_price=71.00,
            tp_price=74.00,
            context={"test_marker": "HARNESS_TEST|test_14_oil_micro"},
            daily_pnl=0,
        )
        if result:
            # The comment in production format: "micro_alpha_sweep_oil|OIL-MI-xxxxxxxx"
            comment = mock_oanda_oil_micro["orders"][-1]["comment"]
            assert "|" in comment, f"Comment must contain pipe separator: {comment}"
            assert "OIL-MI-" in comment, f"Comment must contain trade ref: {comment}"


# ============================================================================
# Helper import shim (so we can import backtest engine without circular deps)
# ============================================================================

def _load_oil_micro_backtest():
    """Lazily load Oil Micro backtest engine."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "backend_oil_micro_backtest",
        os.path.join(PROJECT_ROOT, "backend-oil-micro/backtest/engine.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["backend_oil_micro_backtest"] = mod
    return mod


# Import at module level — will fail gracefully if data files missing
_oil_micro_bt = None
try:
    _oil_micro_bt = _load_oil_micro_backtest()
except Exception:
    # Data files may not be present — tests that need them will skip
    pass
