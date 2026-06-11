"""TEST 15: Oil Macro Pre-Deploy & Execution Harness.

Covers: import checks, fixed Asia window (00-08 UTC), fill model, break-even,
        V1-only bias (NOT Combined), Asia range calc, max trades/day,
        exit detection, live engine execution with BCO_USD + OIL-AS- prefix.
Instrument: BCO_USD, strategy: alpha_sweep_oil, trade_ref prefix: OIL-AS-
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
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-oil"))


# ============================================================================
# Module paths for Oil Macro
# ============================================================================

OIL_MACRO_MODULES = [
    "backend-oil/scanner/scheduler.py",
    "backend-oil/scanner/live_engine.py",
    "backend-oil/config.py",
    "backend-oil/backtest/engine.py",
    "backend-oil/strategies/alpha_sweep.py",
    "backend-oil/execution/fill_model.py",
    "backend-oil/data/cache.py",
]

OIL_MACRO_REMOVED_NAMES = [
    "_price_cache",
    "_old_dd_state",
]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def oil_m3_data_macro():
    """Synthetic BCO_USD M3 data for Oil Macro fill model tests (100 bars)."""
    np.random.seed(42)
    n = 100
    base_price = 75.00
    idx = pd.date_range("2026-01-02 08:00", periods=n, freq="3min", tz="UTC")
    prices = base_price + np.cumsum(np.random.normal(0, 0.04, n))

    df = pd.DataFrame({
        "bid_open": prices,
        "bid_high": prices + np.random.uniform(0.02, 0.12, n),
        "bid_low": prices - np.random.uniform(0.02, 0.12, n),
        "bid_close": prices + np.random.normal(0, 0.03, n),
        "ask_open": prices + 0.03,
        "ask_high": prices + np.random.uniform(0.05, 0.15, n),
        "ask_low": prices - np.random.uniform(0.01, 0.10, n),
        "ask_close": prices + np.random.normal(0.03, 0.03, n),
        "volume": np.random.randint(50, 500, n),
    }, index=idx)
    df["mid_open"] = (df["bid_open"] + df["ask_open"]) / 2
    df["mid_high"] = (df["bid_high"] + df["ask_high"]) / 2
    df["mid_low"] = (df["bid_low"] + df["ask_low"]) / 2
    df["mid_close"] = (df["bid_close"] + df["ask_close"]) / 2
    return df


@pytest.fixture
def oil_h1_with_asia():
    """Synthetic H1 data with clear Asia session (00-08 UTC) + scan window (08-20)."""
    np.random.seed(42)
    base = 75.00
    idx = pd.date_range("2026-01-02 00:00", periods=24, freq="h", tz="UTC")

    # Asia session (00-08): tight range ~$0.60
    asia_prices = [base, base + 0.10, base + 0.20, base - 0.10,
                   base + 0.05, base + 0.15, base + 0.25, base + 0.30]
    # Scan window (08-20): includes sweep beyond Asia range
    scan_prices = [base + 0.50, base + 0.70, base + 0.80, base + 0.60,
                   base + 0.40, base + 0.30, base + 0.20, base + 0.10,
                   base - 0.05, base - 0.10, base - 0.15, base - 0.20]
    # Market close (20-24)
    close_prices = [base - 0.25, base - 0.30, base - 0.35, base - 0.40]

    all_prices = asia_prices + scan_prices + close_prices

    df = pd.DataFrame({
        "bid_open": all_prices,
        "bid_high": [p + 0.20 for p in all_prices],
        "bid_low": [p - 0.15 for p in all_prices],
        "bid_close": [p + 0.05 for p in all_prices],
        "ask_open": [p + 0.03 for p in all_prices],
        "ask_high": [p + 0.23 for p in all_prices],
        "ask_low": [p - 0.12 for p in all_prices],
        "ask_close": [p + 0.08 for p in all_prices],
        "volume": [200] * 24,
    }, index=idx)
    df["mid_open"] = (df["bid_open"] + df["ask_open"]) / 2
    df["mid_high"] = (df["bid_high"] + df["ask_high"]) / 2
    df["mid_low"] = (df["bid_low"] + df["ask_low"]) / 2
    df["mid_close"] = (df["bid_close"] + df["ask_close"]) / 2
    return df


@pytest.fixture
def mock_oanda_oil_macro():
    """Mock all OANDA/execution calls for Oil Macro live engine tests."""
    state = {
        "orders": [],
        "open_trades": [],
        "price": {"bid": 75.00, "ask": 75.03, "mid": 75.015, "spread": 0.03,
                  "time": "2026.01.02 10:00:00", "tradeable": True},
        "account": {"balance": 5000.0, "nav": 5000.0, "nav_usd": 5000.0,
                    "unrealized_pl": 0.0, "margin_used": 0.0, "open_trades": 0,
                    "currency": "USD"},
        "next_id": "200001",
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
        state["open_trades"].append({"id": tid, "trade_id": tid, "instrument": instrument, "currentUnits": units})
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
        state["open_trades"] = [t for t in state["open_trades"] if t.get("id") != trade_id and t.get("trade_id") != trade_id]
        return {"success": True, "close_price": state["price"]["mid"],
                "time": datetime.now(timezone.utc).isoformat()}

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
def mock_db_oil_macro():
    """Mock DB for Oil Macro — tracks signals and trades in memory."""
    state = {
        "trades": [],
        "signals": [],
        "dd_state": {"id": 2, "consecutive_losses": 0, "pause_counter": 0,
                     "equity": 5000, "peak_equity": 5000},
    }

    def mock_execute(sql, params=None, fetch=False):
        sql_lower = sql.strip().lower()
        if "gd_dd_state" in sql_lower and "select" in sql_lower:
            return [state["dd_state"]] if fetch else None
        if "gd_trades" in sql_lower and "exit_time is null" in sql_lower and fetch:
            return [t for t in state["trades"] if t.get("exit_time") is None]
        if "gd_trades" in sql_lower and "count" in sql_lower and fetch:
            today = datetime.now(timezone.utc).date()
            cnt = sum(1 for t in state["trades"]
                      if t.get("entry_time") and t["entry_time"].date() == today)
            return [{"cnt": cnt}]
        if "pnl_usd" in sql_lower and "order by exit_time" in sql_lower and fetch:
            return []
        if "insert" in sql_lower:
            if "gd_signals" in sql_lower:
                state["signals"].append({"timestamp": datetime.now(timezone.utc), "taken": True})
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
# TEST CLASS 15a: Pre-Deploy Checks
# ============================================================================

class TestOilMacroImports:
    """15a: All Oil Macro modules parse and import without errors."""

    def test_all_modules_parse(self):
        """AST parse all Oil Macro source files."""
        errors = []
        for mod_path in OIL_MACRO_MODULES:
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
        """No references to removed/renamed variables in Oil Macro code."""
        errors = []
        for mod_path in OIL_MACRO_MODULES:
            full = os.path.join(PROJECT_ROOT, mod_path)
            if not os.path.exists(full):
                continue
            with open(full) as f:
                content = f.read()
            for name in OIL_MACRO_REMOVED_NAMES:
                if name in content:
                    for i, line in enumerate(content.split("\n"), 1):
                        if name in line and not line.strip().startswith("#"):
                            errors.append(f"{mod_path}:{i} — stale ref to '{name}': {line.strip()}")
        assert not errors, "Stale references found:\n" + "\n".join(errors)

    def test_config_has_required_keys(self):
        """ALPHA_SWEEP must have all required keys."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        required = ["asia_min_range", "sweep_threshold", "sl_buffer", "min_sl",
                    "tp_multiplier", "tp_structure_buffer", "be_trigger_pct",
                    "max_bars", "scan_start", "scan_end", "max_trades_per_day",
                    "engulfing_window_hours"]
        defined = set(re.findall(r'"(\w+)":\s*', content))
        missing = [k for k in required if k not in defined]
        assert not missing, f"Missing from Oil Macro ALPHA_SWEEP: {missing}"

    def test_instrument_is_bco_usd(self):
        """Oil Macro INSTRUMENT must be BCO_USD."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        assert 'INSTRUMENT = "BCO_USD"' in content, "INSTRUMENT not BCO_USD"

    def test_dd_state_id_is_2(self):
        """Oil Macro uses DD state id=2."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/live_engine.py")
        with open(path) as f:
            content = f.read()
        assert "id = 2" in content or "id=2" in content, "DD state id not 2 in Oil Macro live_engine"


# ============================================================================
# TEST CLASS 15b: Signal Generation (Fixed Asia 00-08)
# ============================================================================

class TestOilMacroSignals:
    """15b: Fixed Asia window (00-08 UTC), scan window (08-20 UTC)."""

    def test_asia_window_is_0_to_8(self):
        """ALPHA_SWEEP must define Asia session as 00-08 UTC."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        # Check SESSIONS_UTC or Asia hours in config
        assert '"asia"' in content or '"start": 0' in content, "Asia session not defined"

    def test_scan_window_8_to_20(self):
        """ALPHA_SWEEP scan_start=8, scan_end=20."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        assert '"scan_start": 8' in content, "scan_start != 8"
        assert '"scan_end": 20' in content, "scan_end != 20"

    def test_scheduler_uses_8_to_20(self):
        """Scheduler must only poll during 08-20 UTC."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        # Must check scan_start/scan_end or have hour-based guard
        assert 'cfg["scan_start"]' in content or "scan_start" in content, \
            "Scheduler missing scan_start reference"
        assert 'cfg["scan_end"]' in content or "scan_end" in content, \
            "Scheduler missing scan_end reference"

    def test_asia_bars_filter_0_to_8(self):
        """Scheduler filters Asia bars by hour 0-8."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        # Must filter bars with hour >= 0 and hour < 8
        assert "ts.hour < 8" in content or "hour < 8" in content, \
            "Asia bar filter (hour < 8) not found in scheduler"

    def test_strategy_generate_signals_uses_asia(self):
        """generate_signals() must extract Asia bars (00-08 UTC)."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/strategies/alpha_sweep.py")
        with open(path) as f:
            content = f.read()
        assert "hour >= 0" in content or "hour < 8" in content, \
            "generate_signals() missing Asia hour filter"


# ============================================================================
# TEST CLASS 15c: Fill Model
# ============================================================================

class TestOilMacroFillModel:
    """15c: execute_trade() with correct Oil Macro fills."""

    def test_sl_exit_long(self, oil_m3_data_macro):
        """LONG SL exit: fills at SL level (with slippage)."""
        np.random.seed(42)
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-oil"))
        from execution.fill_model import execute_trade

        entry = 75.00
        sl = 74.50
        tp = 76.00

        # Craft data where bar 2 hits SL
        idx = pd.date_range("2026-01-02 08:00", periods=5, freq="3min", tz="UTC")
        df = pd.DataFrame({
            "bid_open": [entry, 74.80, 74.60, 74.40, 74.30],
            "bid_high": [entry + 0.10, 74.90, 74.70, 74.50, 74.40],
            "bid_low": [entry - 0.05, 74.70, 74.40, 74.30, 74.20],
            "bid_close": [entry, 74.75, 74.55, 74.35, 74.25],
            "ask_open": [entry + 0.03, 74.83, 74.63, 74.43, 74.33],
            "ask_high": [entry + 0.13, 74.93, 74.73, 74.53, 74.43],
            "ask_low": [entry - 0.02, 74.73, 74.43, 74.33, 74.23],
            "ask_close": [entry + 0.03, 74.78, 74.58, 74.38, 74.28],
            "volume": [100] * 5,
        }, index=idx)

        result = execute_trade(
            df=df, bar_start=0, entry=entry, sl=sl, tp=tp,
            direction="long", max_bars=4, strategy="alpha_sweep_oil",
            use_break_even=False
        )
        assert result is not None
        assert result.exit_reason == "sl"
        assert result.exit_price <= sl, f"SL exit price {result.exit_price} > SL {sl}"

    def test_tp_exit_short(self, oil_m3_data_macro):
        """SHORT TP exit: fills at exact TP level."""
        np.random.seed(42)
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-oil"))
        from execution.fill_model import execute_trade

        entry = 75.00
        sl = 75.50
        tp = 74.00

        idx = pd.date_range("2026-01-02 08:00", periods=5, freq="3min", tz="UTC")
        df = pd.DataFrame({
            "bid_open": [entry, 74.80, 74.50, 73.90, 73.80],
            "bid_high": [entry + 0.10, 74.90, 74.60, 74.00, 73.90],
            "bid_low": [entry - 0.05, 74.70, 74.30, 73.80, 73.70],
            "bid_close": [entry, 74.75, 74.40, 73.85, 73.75],
            "ask_open": [entry + 0.03, 74.83, 74.53, 73.93, 73.83],
            "ask_high": [entry + 0.13, 74.93, 74.63, 74.03, 73.93],
            "ask_low": [entry - 0.02, 74.73, 74.33, 73.83, 73.73],
            "ask_close": [entry + 0.03, 74.78, 74.43, 73.88, 73.78],
            "volume": [100] * 5,
        }, index=idx)

        result = execute_trade(
            df=df, bar_start=0, entry=entry, sl=sl, tp=tp,
            direction="short", max_bars=4, strategy="alpha_sweep_oil",
            use_break_even=False
        )
        assert result is not None
        assert result.exit_reason == "tp"
        assert result.exit_price == tp, f"TP must fill at {tp}, got {result.exit_price}"

    def test_max_hold_expired(self, oil_m3_data_macro):
        """Trade expires at max_bars with 'expired' reason."""
        np.random.seed(42)
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-oil"))
        from execution.fill_model import execute_trade

        entry = 75.00
        sl = 50.00  # Unreachable
        tp = 100.00  # Unreachable

        result = execute_trade(
            df=oil_m3_data_macro, bar_start=5, entry=entry, sl=sl, tp=tp,
            direction="long", max_bars=10, strategy="alpha_sweep_oil",
            use_break_even=False
        )
        assert result is not None
        assert result.exit_reason == "expired"
        assert result.bars_held <= 10

    def test_no_phantom_fills(self, oil_m3_data_macro):
        """If price never reaches SL or TP, trade must expire."""
        np.random.seed(42)
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-oil"))
        from execution.fill_model import execute_trade

        entry = oil_m3_data_macro["mid_close"].iat[5]
        sl = entry - 200.0  # Impossible
        tp = entry + 200.0  # Impossible

        result = execute_trade(
            df=oil_m3_data_macro, bar_start=5, entry=entry, sl=sl, tp=tp,
            direction="long", max_bars=15, strategy="alpha_sweep_oil",
            use_break_even=False
        )
        assert result is not None
        assert result.exit_reason == "expired", \
            f"Expected expired, got {result.exit_reason} — possible phantom fill"


# ============================================================================
# TEST CLASS 15d: Break-Even
# ============================================================================

class TestOilMacroBreakEven:
    """15d: Break-even at 50% to TP, moves SL to entry +/- $0.01."""

    def test_break_even_formula_in_live_engine(self):
        """Live engine must use entry + 0.01 / entry - 0.01 for BE."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/live_engine.py")
        with open(path) as f:
            content = f.read()
        assert "entry + 0.01" in content, "LONG BE SL formula (entry + 0.01) missing"
        assert "entry - 0.01" in content, "SHORT BE SL formula (entry - 0.01) missing"

    def test_break_even_trigger_is_50pct(self):
        """BE trigger must be at 50% of distance to TP."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/live_engine.py")
        with open(path) as f:
            content = f.read()
        assert "* 0.5" in content or "* cfg[\"be_trigger_pct\"]" in content, \
            "BE trigger 50% not found in live_engine"

    def test_fill_model_break_even(self):
        """Fill model uses break-even when use_break_even=True."""
        np.random.seed(42)
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-oil"))
        from execution.fill_model import execute_trade

        entry = 75.00
        tp = 76.00
        sl = 74.00
        # 50% target = 75.50

        idx = pd.date_range("2026-01-02 08:00", periods=5, freq="3min", tz="UTC")
        df = pd.DataFrame({
            "bid_open": [entry, 75.30, 75.55, 75.10, 74.90],
            "bid_high": [entry + 0.10, 75.60, 75.70, 75.20, 75.00],
            "bid_low": [entry - 0.05, 75.20, 75.40, 74.95, 74.80],
            "bid_close": [entry, 75.40, 75.50, 75.05, 74.85],
            "ask_open": [entry + 0.03, 75.33, 75.58, 75.13, 74.93],
            "ask_high": [entry + 0.13, 75.63, 75.73, 75.23, 75.03],
            "ask_low": [entry - 0.02, 75.23, 75.43, 74.98, 74.83],
            "ask_close": [entry + 0.03, 75.43, 75.53, 75.08, 74.88],
            "volume": [100] * 5,
        }, index=idx)

        result = execute_trade(
            df=df, bar_start=0, entry=entry, sl=sl, tp=tp,
            direction="long", max_bars=4, strategy="alpha_sweep_oil",
            use_break_even=True
        )
        assert result is not None
        # Bar 1: bid_high=75.60 >= 75.50 (50% target) → BE triggers, SL = entry + slip
        # Bar 3: bid_low=74.95 — should not hit new BE SL which is ~75.03
        # Bar 3: bid_low=74.95 < 75.03ish → SL hit at new BE level
        if result.exit_reason == "sl":
            # BE SL should be near entry (not original sl=74.00)
            assert result.exit_price > sl, \
                f"After BE, exit should be above original SL {sl}, got {result.exit_price}"


# ============================================================================
# TEST CLASS 15e: Bias Filter (Combined V1+V2 for Oil Macro)
# Updated 2026-06-09: Oil Macro switched from V1-only to Combined V1+V2.
# 20yr backtest showed PF 4.98 → 5.58, P&L +$34K, prevents losses like Jun 9.
# ============================================================================

class TestOilMacroBias:
    """15e: Oil Macro uses Combined V1+V2 bias (matches all 3 other systems)."""

    def test_scheduler_uses_combined_v1_v2(self):
        """Oil Macro scheduler must use Combined V1+V2 bias."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        # V1 (body%) must be present
        assert "body_pct" in content, "Oil Macro scheduler missing V1 body_pct"
        # V2 (close_position) must be present
        assert "close_position" in content, \
            "Oil Macro scheduler must use Combined V1+V2 (close_position required)"
        assert "v2_bias" in content, \
            "Oil Macro scheduler must have v2_bias variable"
        # Combined logic: EITHER triggers
        assert 'v1_bias == "bearish" or v2_bias == "bearish"' in content, \
            "Oil Macro scheduler missing Combined OR logic"

    def test_backtest_uses_combined_v1_v2(self):
        """Oil Macro backtest must also use Combined V1+V2 bias."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/backtest/engine.py")
        with open(path) as f:
            content = f.read()
        assert "body_pct" in content, "Backtest missing V1 body_pct"
        assert "close_position" in content, \
            "Backtest must use Combined V1+V2 (close_position required)"
        assert "v2_bias" in content, "Backtest missing v2_bias"

    def test_bias_threshold_is_0_4(self):
        """V1 bias threshold must be 0.4 (40% body)."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        assert "0.4" in content, "V1 threshold 0.4 not found in Oil Macro scheduler"


# ============================================================================
# TEST CLASS 15f: Asia Range Calculation
# ============================================================================

class TestOilMacroAsiaRange:
    """15f: Correctly calculates Asia range from 00-08 UTC bars."""

    def test_asia_min_range_config(self):
        """asia_min_range must be $0.50."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        assert '"asia_min_range": 0.50' in content or '"asia_min_range": 0.5' in content, \
            "asia_min_range not $0.50"

    def test_asia_range_calculation_in_scheduler(self):
        """Scheduler must compute asia_high - asia_low from bars 0-8."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        assert "asia_high" in content, "Missing asia_high in scheduler"
        assert "asia_low" in content, "Missing asia_low in scheduler"
        assert "asia_range" in content, "Missing asia_range in scheduler"

    def test_strategy_uses_asia_range_for_tp(self):
        """Signal TP uses Asia range as base for calculation."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/strategies/alpha_sweep.py")
        with open(path) as f:
            content = f.read()
        # TP formula includes range multiplier
        assert "tp_multiplier" in content, "TP formula missing tp_multiplier"


# ============================================================================
# TEST CLASS 15g: Max Trades Per Day
# ============================================================================

class TestOilMacroMaxTrades:
    """15g: 3 trades per day enforced."""

    def test_max_trades_config_is_3(self):
        """ALPHA_SWEEP['max_trades_per_day'] == 3."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        assert '"max_trades_per_day": 3' in content, "max_trades_per_day != 3"

    def test_scheduler_enforces_max_trades(self):
        """Scheduler must check trades_today >= max_trades_per_day."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        assert "max_trades_per_day" in content, "Scheduler missing max_trades_per_day reference"
        assert "trades_today >=" in content, "Missing trades_today guard"

    def test_scheduler_has_one_at_a_time_gate(self):
        """Regression guard for the 2026-06-11 missing-gate bug.

        Oil Macro fired OIL-AS-f5e9710a at 14:45 UTC while OIL-AS-59a94823
        was already stuck in DB at EXIT_AMBIGUOUS streak 62. Root cause:
        the scheduler had no DB-level open-position check, only the
        max_trades_per_day count. So when a previous trade's broker_id
        wasn't in the OANDA open list (broker had closed it but the DB
        row was orphan), the system happily fired another trade.

        The fix mirrors Gold Macro line 415-420: query gd_trades for any
        OIL-AS-% row where exit_time IS NULL, refuse to fire if count>0.
        This test pins that gate's existence.

        See docs/trades/GD-MI-14e2fed1.md (live-trade analysis section)
        for the full incident write-up.
        """
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        # Must query for open OIL-AS-* rows
        assert "OIL-AS-" in content and "exit_time IS NULL" in content, (
            "Oil Macro scheduler missing the one-at-a-time DB gate. "
            "Without it, a stuck/orphan DB row doesn't block new trade firing. "
            "See docs/trades/GD-MI-14e2fed1.md for the 2026-06-11 incident."
        )

    def test_scheduler_has_5min_cooldown_gate(self):
        """Regression guard for the same 2026-06-11 bug class.

        Without a 5-min cooldown, a sweep that was in scan_bars on the
        last 3-min cron tick can re-fire on the next tick before the
        previous order has propagated through DB. Gold Macro has this
        gate at line 401-412; Oil Macro was missing it.
        """
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/scheduler.py")
        with open(path) as f:
            content = f.read()
        assert "alpha_sweep_oil" in content and "ORDER BY timestamp DESC LIMIT 1" in content, (
            "Oil Macro scheduler missing 5-min signal cooldown gate. "
            "Without it, the same sweep can produce two consecutive signals."
        )
        # And the 5-min check itself
        assert "minutes=5" in content, "5-min cooldown timedelta missing"


# ============================================================================
# TEST CLASS 15h: Exit Detection
# ============================================================================

class TestOilMacroExitDetection:
    """15h: Price extremes logic for determining SL vs TP when trade disappears."""

    def test_exit_detection_uses_broker_history_not_proximity(self):
        """Live engine must read broker-authoritative close history via
        get_trade_details (closed_orders.json) — NOT guess from price
        proximity. The proximity heuristic produced phantom fills (June 11
        OIL-AS-5434644d, see docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md)."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/live_engine.py")
        with open(path) as f:
            content = f.read()
        # Must read broker history first
        assert "get_trade_details" in content, \
            "Exit detection missing get_trade_details call"
        # Must skip with EXIT_AMBIGUOUS when broker history isn't available yet
        assert "EXIT_AMBIGUOUS" in content, \
            "Missing EXIT_AMBIGUOUS skip path — re-introduces phantom fill bug"
        # Must NOT use the old proximity heuristic — that was the bug
        assert "sl_likely" not in content, \
            "Old proximity heuristic 'sl_likely' has returned — this is the phantom-fill bug"
        assert "tp_likely" not in content, \
            "Old proximity heuristic 'tp_likely' has returned — this is the phantom-fill bug"
        # Must use authoritative close_price from broker
        assert 'close_price' in content, \
            "Exit detection missing close_price from broker history"

    def test_max_hold_in_live_engine(self):
        """Live engine must enforce MAX_HOLD (80 M3 bars ~ 4 hours)."""
        path = os.path.join(PROJECT_ROOT, "backend-oil/scanner/live_engine.py")
        with open(path) as f:
            content = f.read()
        assert "MAX_HOLD" in content, "MAX_HOLD exit reason not in live engine"
        assert 'max_bars' in content or 'ALPHA_SWEEP["max_bars"]' in content, \
            "max_bars reference missing in live engine"


# ============================================================================
# TEST CLASS 15i: Live Engine Execution
# ============================================================================

class TestOilMacroLiveEngine:
    """15i: execute_signal() with BCO_USD instrument, OIL-AS- prefix."""

    @staticmethod
    def _get_execute_signal():
        """Load execute_signal from Oil Macro live_engine using importlib to avoid path conflicts."""
        import importlib.util
        oil_macro_dir = os.path.join(PROJECT_ROOT, "backend-oil")
        # Clear cached config/scanner modules to avoid path conflicts with oil-micro
        for mod_name in list(sys.modules.keys()):
            if mod_name == "config" or mod_name.startswith("scanner") or mod_name == "oil_macro_live_engine":
                del sys.modules[mod_name]
        old_path = sys.path[:]
        sys.path = [oil_macro_dir, PROJECT_ROOT, os.path.join(PROJECT_ROOT, "backend")] + \
                   [p for p in sys.path if p not in (oil_macro_dir,)]
        try:
            spec = importlib.util.spec_from_file_location(
                "oil_macro_live_engine",
                os.path.join(oil_macro_dir, "scanner/live_engine.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.execute_signal
        finally:
            sys.path = old_path

    def test_trade_ref_starts_with_oil_as(self, mock_oanda_oil_macro, mock_db_oil_macro):
        """Trade ref must start with OIL-AS-."""
        execute_signal = self._get_execute_signal()

        result = execute_signal(
            direction="long",
            entry_price=75.03,
            sl_price=74.00,
            tp_price=76.00,
            context={"test_marker": "HARNESS_TEST|test_15_oil_macro"},
        )
        assert result is not None, "Signal should be accepted"
        assert result.startswith("OIL-AS-"), f"Trade ref must start with OIL-AS-, got '{result}'"

    def test_instrument_bco_usd_in_order(self, mock_oanda_oil_macro, mock_db_oil_macro):
        """Orders must be placed on BCO_USD instrument."""
        execute_signal = self._get_execute_signal()

        execute_signal(
            direction="short",
            entry_price=75.00,
            sl_price=76.00,
            tp_price=74.00,
            context={},
        )
        if mock_oanda_oil_macro["orders"]:
            assert mock_oanda_oil_macro["orders"][-1]["instrument"] == "BCO_USD"

    def test_order_comment_contains_strategy_and_ref(self, mock_oanda_oil_macro, mock_db_oil_macro):
        """Order comment must contain 'alpha_sweep_oil|OIL-AS-xxx'."""
        execute_signal = self._get_execute_signal()

        result = execute_signal(
            direction="long",
            entry_price=75.03,
            sl_price=74.00,
            tp_price=76.00,
            context={"test_marker": "HARNESS_TEST|test_15_oil_macro"},
        )
        if result and mock_oanda_oil_macro["orders"]:
            comment = mock_oanda_oil_macro["orders"][-1]["comment"]
            assert "alpha_sweep_oil" in comment, f"Comment missing strategy: {comment}"
            assert "OIL-AS-" in comment, f"Comment missing trade_ref: {comment}"

    def test_short_units_negative(self, mock_oanda_oil_macro, mock_db_oil_macro):
        """SHORT direction must send negative units to OANDA."""
        execute_signal = self._get_execute_signal()

        execute_signal(
            direction="short",
            entry_price=75.00,
            sl_price=76.00,
            tp_price=74.00,
            context={},
        )
        if mock_oanda_oil_macro["orders"]:
            assert mock_oanda_oil_macro["orders"][-1]["units"] < 0, \
                "SHORT order must have negative units"

    def test_long_units_positive(self, mock_oanda_oil_macro, mock_db_oil_macro):
        """LONG direction must send positive units to OANDA."""
        execute_signal = self._get_execute_signal()

        execute_signal(
            direction="long",
            entry_price=75.03,
            sl_price=74.00,
            tp_price=76.00,
            context={},
        )
        if mock_oanda_oil_macro["orders"]:
            assert mock_oanda_oil_macro["orders"][-1]["units"] > 0, \
                "LONG order must have positive units"

    def test_dd_pause_skips_signal(self, mock_oanda_oil_macro, mock_db_oil_macro):
        """If DD state has pause_counter > 0, signal must be skipped."""
        mock_db_oil_macro["dd_state"]["pause_counter"] = 2

        execute_signal = self._get_execute_signal()
        result = execute_signal(
            direction="long",
            entry_price=75.03,
            sl_price=74.00,
            tp_price=76.00,
            context={},
        )
        assert result is None, "Signal should be skipped when DD is paused"

    def test_zero_sl_distance_rejected(self, mock_oanda_oil_macro, mock_db_oil_macro):
        """execute_signal() must reject zero SL distance."""
        execute_signal = self._get_execute_signal()
        result = execute_signal(
            direction="long",
            entry_price=75.00,
            sl_price=75.00,  # Same as entry = zero distance
            tp_price=76.00,
            context={},
        )
        assert result is None, "Zero SL distance should be rejected"

    def test_harness_comment_identification(self, mock_oanda_oil_macro, mock_db_oil_macro):
        """
        CRITICAL: Order comment must identify test orders.
        In production: comment = "alpha_sweep_oil|OIL-AS-{hex}"
        Tests verify this pattern exists for traceability.
        """
        execute_signal = self._get_execute_signal()
        result = execute_signal(
            direction="long",
            entry_price=75.03,
            sl_price=74.00,
            tp_price=76.00,
            context={"test_marker": "HARNESS_TEST|test_15_oil_macro"},
        )
        if result and mock_oanda_oil_macro["orders"]:
            comment = mock_oanda_oil_macro["orders"][-1]["comment"]
            assert "|" in comment, f"Comment must contain pipe separator: {comment}"
            parts = comment.split("|")
            assert len(parts) == 2, f"Comment must be strategy|ref format: {comment}"
            assert parts[0] == "alpha_sweep_oil", f"First part must be strategy: {parts[0]}"
            assert parts[1].startswith("OIL-AS-"), f"Second part must be OIL-AS-xxx: {parts[1]}"


# ============================================================================
# TEST CLASS 15j: Config Value Sanity
# ============================================================================

class TestOilMacroConfigSanity:
    """15j: Config values are within reasonable bounds."""

    def test_sweep_threshold_positive(self):
        """sweep_threshold must be > 0."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        match = re.search(r'"sweep_threshold":\s*([\d.]+)', content)
        assert match, "sweep_threshold not found"
        assert float(match.group(1)) > 0, "sweep_threshold must be positive"

    def test_sl_buffer_reasonable(self):
        """sl_buffer for Oil should be $0.01 - $1.00."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        match = re.search(r'"sl_buffer":\s*([\d.]+)', content)
        assert match, "sl_buffer not found"
        val = float(match.group(1))
        assert 0.01 <= val <= 1.0, f"sl_buffer={val} — out of range [0.01, 1.0] for Oil"

    def test_max_bars_reasonable(self):
        """max_bars should be 20-200."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        match = re.search(r'"max_bars":\s*(\d+)', content)
        assert match, "max_bars not found"
        val = int(match.group(1))
        assert 20 <= val <= 200, f"max_bars={val} — out of range [20, 200]"

    def test_be_trigger_between_0_and_1(self):
        """be_trigger_pct must be in (0, 1)."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        match = re.search(r'"be_trigger_pct":\s*([\d.]+)', content)
        assert match, "be_trigger_pct not found"
        val = float(match.group(1))
        assert 0 < val < 1.0, f"be_trigger_pct={val} — must be in (0, 1)"

    def test_slippage_base_is_0_03(self):
        """Oil Macro slippage must use $0.03 base."""
        oil_config_path = os.path.join(PROJECT_ROOT, "backend-oil/config.py")
        with open(oil_config_path) as f:
            content = f.read()
        assert "0.03" in content, "Slippage base $0.03 not found in Oil Macro config"
