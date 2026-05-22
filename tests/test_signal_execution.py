"""Test signal execution pipeline — all paths for Gold and Oil."""
import sys
import os
import pytest
from unittest.mock import patch
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend-oil"))

from tests.conftest import query_db


class TestGoldExecuteSignalSuccess:
    """Gold happy path — signal taken, order filled."""

    def test_long_success(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import execute_signal

        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2610.0, 2640.0)

        assert ref is not None
        assert ref.startswith("GD-AL-")

        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE trade_ref = %s", (ref,))
        assert len(signals) == 1
        assert signals[0]["taken"] is True
        assert signals[0]["strategy"] == "alpha_sweep"
        assert signals[0]["direction"] == "long"

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE trade_ref = %s", (ref,))
        assert len(trades) == 1
        assert trades[0]["side"] == "LONG"
        assert trades[0]["oanda_trade_id"] == "12345"
        assert float(trades[0]["entry_price"]) == 2620.50

        journal = query_db(test_db, "SELECT * FROM gd_journal WHERE trade_ref = %s AND event_type = 'ENTRY_FILLED'", (ref,))
        assert len(journal) == 1

    def test_short_success(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import execute_signal

        mock_oanda_success["place"].return_value["fill_price"] = 2619.50
        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "short", 2620.0, 2630.0, 2600.0)

        assert ref is not None
        mock_oanda_success["place"].assert_called_once()
        call_kwargs = mock_oanda_success["place"].call_args
        assert call_kwargs[1]["units"] < 0 or call_kwargs[0][1] < 0  # negative units for short

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE trade_ref = %s", (ref,))
        assert trades[0]["side"] == "SHORT"


class TestGoldExecuteSignalSkips:
    """Gold skip paths — signal generated but not taken."""

    def test_skip_gold_below_50ma(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import execute_signal

        # 50MA = mean of 55 closes. All at 2700 → MA=2700, gold_close=2700
        # But we want close < MA, so set last close lower
        candles = [{"bid_close": 2700} for _ in range(54)] + [{"bid_close": 2500}]
        with patch("backend.scanner.live_engine.get_candles", return_value=candles):
            ref = execute_signal("mean_rev", "long", 2500.0, 2490.0, 2520.0)

        assert ref is None
        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE skip_reason = 'gold_below_50ma'")
        assert len(signals) == 1
        mock_oanda_success["place"].assert_not_called()

    def test_skip_paused_after_5_losses(self, test_db, mock_oanda_success, gold_dd_state):
        from backend.scanner.live_engine import execute_signal

        gold_dd_state(consecutive_losses=5, pause_counter=2)

        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2610.0, 2640.0)

        assert ref is None
        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE skip_reason = 'paused_after_5_losses'")
        assert len(signals) == 1

        # Pause counter decremented
        dd = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 1")
        assert dd[0]["pause_counter"] == 1

    def test_skip_zero_sl_distance(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import execute_signal

        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2620.0, 2640.0)

        assert ref is None
        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE skip_reason = 'zero_sl_distance'")
        assert len(signals) == 1

    def test_skip_units_too_small(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import execute_signal

        # Set equity very low so units = 0
        mock_oanda_success["account"].return_value["nav_usd"] = 50.0

        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2560.0, 2680.0)  # risk=$60, 50*0.04/60 = 0.03 → int(0)

        assert ref is None
        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE skip_reason = 'units_too_small'")
        assert len(signals) == 1

    def test_skip_oanda_error(self, test_db, mock_oanda_failure):
        from backend.scanner.live_engine import execute_signal

        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2610.0, 2640.0)

        assert ref is None
        signals = query_db(test_db, "SELECT * FROM gd_signals")
        assert signals[0]["skip_reason"].startswith("oanda_error:")
        journal = query_db(test_db, "SELECT * FROM gd_journal WHERE event_type = 'ORDER_FAILED'")
        assert len(journal) == 1
        trades = query_db(test_db, "SELECT * FROM gd_trades")
        assert len(trades) == 0


class TestGoldPositionSizing:
    """Verify unit calculations and caps."""

    def test_sizing_capped_at_max_units(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import execute_signal

        # sl_distance = $0.01 → units = 132000*0.04/0.01 = 528,000 → capped at 100
        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2619.99, 2640.0)

        assert ref is not None
        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE trade_ref = %s", (ref,))
        assert trades[0]["units"] == 100  # MAX_UNITS for Gold

    def test_50ma_not_checked_for_alpha_sweep(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import execute_signal

        # Gold close < 50MA, but strategy is alpha_sweep → should NOT skip
        candles = [{"bid_close": 2700} for _ in range(54)] + [{"bid_close": 2500}]
        with patch("backend.scanner.live_engine.get_candles", return_value=candles):
            ref = execute_signal("alpha_sweep", "long", 2500.0, 2490.0, 2520.0)

        assert ref is not None  # NOT skipped


class TestOilExecuteSignal:
    """Oil signal execution — verify separate DD, instrument, sizing."""

    @pytest.fixture(autouse=True)
    def _patch_oil_oanda(self, mock_oanda_success, monkeypatch):
        """Also patch Oil's live_engine module."""
        import importlib
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend-oil"))
        import scanner.live_engine as oil_le
        monkeypatch.setattr(oil_le, "place_market_order", mock_oanda_success["place"])
        monkeypatch.setattr(oil_le, "get_account_summary", mock_oanda_success["account"])
        monkeypatch.setattr(oil_le, "get_open_trades", mock_oanda_success["open_trades"])
        monkeypatch.setattr(oil_le, "get_current_price", mock_oanda_success["price"])
        monkeypatch.setattr(oil_le, "close_trade", mock_oanda_success["close"])
        monkeypatch.setattr(oil_le, "modify_stop_loss", mock_oanda_success["modify"])
        monkeypatch.setattr(oil_le, "_get_gbp_usd_rate", mock_oanda_success["rate"])

    def test_oil_long_success(self, test_db, mock_oanda_success):
        from scanner.live_engine import execute_signal as oil_execute

        mock_oanda_success["place"].return_value["fill_price"] = 104.55
        ref = oil_execute("long", 104.50, 104.20, 105.10)

        assert ref is not None
        assert ref.startswith("OIL-AS-")

        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE trade_ref = %s", (ref,))
        assert signals[0]["strategy"] == "alpha_sweep_oil"

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE trade_ref = %s", (ref,))
        assert trades[0]["strategy"] == "alpha_sweep_oil"
        assert float(trades[0]["lot_size"]) == pytest.approx(trades[0]["units"] / 1000.0, rel=0.01)

        # Verify OANDA called with BCO_USD
        mock_oanda_success["place"].assert_called_once()
        call_kwargs = mock_oanda_success["place"].call_args[1]
        assert call_kwargs["instrument"] == "BCO_USD"

    def test_oil_sizing_capped_at_5000(self, test_db, mock_oanda_success):
        from scanner.live_engine import execute_signal as oil_execute

        # sl_distance = $0.01 → units = 132000*0.04/0.01 = 528,000 → capped at 5000
        ref = oil_execute("long", 104.50, 104.49, 105.50)

        assert ref is not None
        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE trade_ref = %s", (ref,))
        assert trades[0]["units"] == 5000  # MAX_UNITS for Oil

    def test_oil_dd_separate_from_gold(self, test_db, mock_oanda_success, gold_dd_state, oil_dd_state):
        from scanner.live_engine import execute_signal as oil_execute

        # Gold paused (5 losses), Oil clean
        gold_dd_state(consecutive_losses=5, pause_counter=2)
        oil_dd_state(consecutive_losses=0, pause_counter=0)

        ref = oil_execute("long", 104.50, 104.20, 105.10)
        assert ref is not None  # Oil NOT paused despite Gold being paused

    def test_oil_oanda_rejects_insufficient_margin(self, test_db, mock_oanda_success, monkeypatch):
        import scanner.live_engine as oil_le
        from scanner.live_engine import execute_signal as oil_execute

        mock_oanda_success["place"].return_value = {"success": False, "error": "INSUFFICIENT_MARGIN"}
        monkeypatch.setattr(oil_le, "place_market_order", mock_oanda_success["place"])
        ref = oil_execute("long", 104.50, 104.40, 105.10)

        assert ref is None
        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE skip_reason LIKE '%%INSUFFICIENT_MARGIN%%'")
        assert len(signals) == 1
        journal = query_db(test_db, "SELECT * FROM gd_journal WHERE event_type = 'ORDER_FAILED'")
        assert len(journal) == 1
