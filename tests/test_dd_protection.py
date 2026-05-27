"""Test DD (drawdown) protection state machine."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend-oil"))

from tests.conftest import query_db


class TestRiskMultiplier:
    """_get_risk_multiplier returns correct multiplier based on losses and equity MA."""

    def test_1x_under_3_losses(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _get_risk_multiplier, _get_dd_state

        gold_dd_state(consecutive_losses=2)
        dd = _get_dd_state()
        mult = _get_risk_multiplier(dd)
        assert mult == 1.0

    def test_0_5x_at_3_losses(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _get_risk_multiplier, _get_dd_state

        gold_dd_state(consecutive_losses=3)
        dd = _get_dd_state()
        mult = _get_risk_multiplier(dd)
        assert mult == 0.5

    def test_0_5x_at_5_losses(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _get_risk_multiplier, _get_dd_state

        gold_dd_state(consecutive_losses=5)
        dd = _get_dd_state()
        mult = _get_risk_multiplier(dd)
        assert mult == 0.5

    def test_0_5x_equity_below_ma(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _get_risk_multiplier, _get_dd_state

        # Need 20 completed trades with pnl_usd to trigger equity MA check
        # equity=3000, sum of last 20 pnl_usd = 2000 → equity_20_ago = 3000-2000 = 1000
        # equity_ma = (1000+3000)/2 = 2000. current 3000 > 2000 → NOT below MA
        # To make current < MA: equity=1000, sum=2000 → equity_20_ago=-1000, MA=(-1000+1000)/2=0, 1000>0 → still not below
        # Actually: equity=2000, sum=3000 → equity_20_ago=2000-3000=-1000, MA=(-1000+2000)/2=500, current=2000 > 500 still above
        # Need: equity < MA. equity=1000, sum=-2000 → equity_20_ago=1000-(-2000)=3000, MA=(3000+1000)/2=2000, current 1000 < 2000 ✓
        gold_dd_state(consecutive_losses=0, equity=1000)

        # Insert 20 completed trades with negative pnl_usd to make equity below MA
        cur = test_db.cursor()
        for i in range(20):
            cur.execute(
                """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, exit_time, entry_price, sl_price, tp_price, lot_size, units, pnl_usd, exit_reason, mode, oanda_trade_id)
                   VALUES (%s, 'alpha_sweep', 'LONG', NOW(), NOW(), 2620.0, 2610.0, 2640.0, 1.0, 100, %s, 'SL', 'live', %s)""",
                (f"GD-AL-hist{i:04d}", -100.0, f"hist{i}")
            )

        dd = _get_dd_state()
        mult = _get_risk_multiplier(dd)
        assert mult == 0.5

    def test_0_25x_combined_losses_and_equity(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _get_risk_multiplier, _get_dd_state

        gold_dd_state(consecutive_losses=3, equity=1000)

        cur = test_db.cursor()
        for i in range(20):
            cur.execute(
                """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, exit_time, entry_price, sl_price, tp_price, lot_size, units, pnl_usd, exit_reason, mode, oanda_trade_id)
                   VALUES (%s, 'alpha_sweep', 'LONG', NOW(), NOW(), 2620.0, 2610.0, 2640.0, 1.0, 100, %s, 'SL', 'live', %s)""",
                (f"GD-AL-comb{i:04d}", -100.0, f"comb{i}")
            )

        dd = _get_dd_state()
        mult = _get_risk_multiplier(dd)
        assert mult == 0.25

    def test_equity_ma_fewer_than_20_trades(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _get_risk_multiplier, _get_dd_state

        # Only 5 completed trades → equity MA check skipped
        gold_dd_state(consecutive_losses=0, equity=1000)

        cur = test_db.cursor()
        for i in range(5):
            cur.execute(
                """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, exit_time, entry_price, sl_price, tp_price, lot_size, units, pnl_usd, exit_reason, mode, oanda_trade_id)
                   VALUES (%s, 'alpha_sweep', 'LONG', NOW(), NOW(), 2620.0, 2610.0, 2640.0, 1.0, 100, %s, 'SL', 'live', %s)""",
                (f"GD-AL-few{i:04d}", -100.0, f"few{i}")
            )

        dd = _get_dd_state()
        mult = _get_risk_multiplier(dd)
        assert mult == 1.0  # No equity penalty with < 20 trades


class TestPauseCounter:
    """Pause counter decrement on _should_skip."""

    def test_pause_counter_decrement(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _should_skip, _get_dd_state

        gold_dd_state(pause_counter=2)
        dd = _get_dd_state()
        reason = _should_skip("alpha_sweep", "long", dd)

        assert reason == "paused_after_5_losses"
        dd_after = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 1")
        assert dd_after[0]["pause_counter"] == 1

    def test_pause_counter_reaches_zero(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _should_skip, _get_dd_state

        gold_dd_state(pause_counter=1)
        dd = _get_dd_state()

        # First call: skips and decrements 1→0
        reason = _should_skip("alpha_sweep", "long", dd)
        assert reason == "paused_after_5_losses"

        # Second call: counter is now 0, should pass
        dd2 = _get_dd_state()
        reason2 = _should_skip("alpha_sweep", "long", dd2)
        assert reason2 is None


class TestGold50MAGate:
    """50MA gate only applies to mean_rev/cross_market LONG."""

    def test_mean_rev_long_below_50ma_skipped(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _should_skip, _get_dd_state

        gold_dd_state(consecutive_losses=0, pause_counter=0)
        dd = _get_dd_state()
        reason = _should_skip("mean_rev", "long", dd, gold_close=2500, gold_50ma=2600)
        assert reason == "gold_below_50ma"

    def test_cross_market_long_below_50ma_skipped(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _should_skip, _get_dd_state

        gold_dd_state(consecutive_losses=0, pause_counter=0)
        dd = _get_dd_state()
        reason = _should_skip("cross_market", "long", dd, gold_close=2500, gold_50ma=2600)
        assert reason == "gold_below_50ma"

    def test_alpha_sweep_long_below_50ma_not_skipped(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _should_skip, _get_dd_state

        gold_dd_state(consecutive_losses=0, pause_counter=0)
        dd = _get_dd_state()
        reason = _should_skip("alpha_sweep", "long", dd, gold_close=2500, gold_50ma=2600)
        assert reason is None

    def test_mean_rev_short_below_50ma_not_skipped(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import _should_skip, _get_dd_state

        gold_dd_state(consecutive_losses=0, pause_counter=0)
        dd = _get_dd_state()
        reason = _should_skip("mean_rev", "short", dd, gold_close=2500, gold_50ma=2600)
        assert reason is None


class TestOilNo50MAGate:
    """Oil _should_skip only checks pause — no 50MA gate."""

    def test_oil_no_50ma_gate(self, test_db, mock_oanda_success, oil_dd_state):
        from conftest import get_oil_live_engine; _oil_mod = get_oil_live_engine(); oil_should_skip = _oil_mod._should_skip; oil_get_dd = _oil_mod._get_dd_state

        oil_dd_state(consecutive_losses=0, pause_counter=0)
        dd = oil_get_dd()
        # Oil's _should_skip only takes dd_state, no gold_close/gold_50ma args
        reason = oil_should_skip(dd)
        assert reason is None

    def test_oil_pause_works(self, test_db, mock_oanda_success, oil_dd_state):
        from conftest import get_oil_live_engine; _oil_mod = get_oil_live_engine(); oil_should_skip = _oil_mod._should_skip; oil_get_dd = _oil_mod._get_dd_state

        oil_dd_state(pause_counter=2)
        dd = oil_get_dd()
        reason = oil_should_skip(dd)
        assert reason == "paused_after_5_losses"


class TestPerInstrumentDDIsolation:
    """Gold DD (id=1) and Oil DD (id=2) are independent."""

    def test_oil_not_affected_by_gold_dd(self, test_db, mock_oanda_success, gold_dd_state, oil_dd_state, monkeypatch):
        from conftest import get_oil_live_engine; oil_le = get_oil_live_engine()
        from conftest import get_oil_live_engine; oil_execute = get_oil_live_engine().execute_signal

        # Gold paused, Oil clean
        gold_dd_state(consecutive_losses=5, pause_counter=2)
        oil_dd_state(consecutive_losses=0, pause_counter=0)

        monkeypatch.setattr(oil_le, "place_market_order", mock_oanda_success["place"])
        monkeypatch.setattr(oil_le, "get_account_summary", mock_oanda_success["account"])

        mock_oanda_success["place"].return_value["fill_price"] = 104.55
        ref = oil_execute("long", 104.50, 104.20, 105.10)
        assert ref is not None

    def test_gold_not_affected_by_oil_dd(self, test_db, mock_oanda_success, gold_dd_state, oil_dd_state):
        from backend.scanner.live_engine import execute_signal

        # Oil paused, Gold clean
        oil_dd_state(consecutive_losses=5, pause_counter=2)
        gold_dd_state(consecutive_losses=0, pause_counter=0)

        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2610.0, 2640.0)

        assert ref is not None
