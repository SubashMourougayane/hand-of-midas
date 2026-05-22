"""Test position monitoring — SL/TP detection, max hold, DD state updates."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend-oil"))

from tests.conftest import query_db


class TestGoldSLTPDetection:
    """Gold: detect SL/TP closure from OANDA trade details."""

    def test_detect_sl_closure(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        # OANDA says trade is gone (not in open trades) and details show SL fill
        mock_oanda_success["open_trades"].return_value = []
        oanda.get_trade_details = MagicMock(return_value={
            "state": "CLOSED", "realized_pl": -50.0, "price": 2610.2,
            "close_time": "2026-05-22T12:00:00Z",
        })

        check_open_positions()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert trades[0]["exit_reason"] == "SL"
        assert float(trades[0]["exit_price"]) == 2610.2
        assert float(trades[0]["pnl_gbp"]) == -50.0

        journal = query_db(test_db, "SELECT * FROM gd_journal WHERE event_type = 'EXIT_FILLED'")
        assert len(journal) == 1

    def test_detect_tp_closure(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        oanda.get_trade_details = MagicMock(return_value={
            "state": "CLOSED", "realized_pl": 100.0, "price": 2639.8,
            "close_time": "2026-05-22T12:00:00Z",
        })

        check_open_positions()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert trades[0]["exit_reason"] == "TP"

        # Win resets consecutive losses
        dd = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 1")
        assert dd[0]["consecutive_losses"] == 0

    def test_detect_manual_close(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        oanda.get_trade_details = MagicMock(return_value={
            "state": "CLOSED", "realized_pl": 20.0, "price": 2625.0,
            "close_time": "2026-05-22T12:00:00Z",
        })

        check_open_positions()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert trades[0]["exit_reason"] == "CLOSED"


class TestOilSLTPDetection:
    """Oil: uses ±0.05 tolerance instead of ±2."""

    @pytest.fixture(autouse=True)
    def _patch_oil_oanda(self, mock_oanda_success, monkeypatch):
        import scanner.live_engine as oil_le
        monkeypatch.setattr(oil_le, "get_open_trades", mock_oanda_success["open_trades"])
        monkeypatch.setattr(oil_le, "close_trade", mock_oanda_success["close"])
        monkeypatch.setattr(oil_le, "get_trade_details", MagicMock())
        monkeypatch.setattr(oil_le, "_get_gbp_usd_rate", mock_oanda_success["rate"])

    def test_oil_detect_sl_with_tolerance(self, test_db, mock_oanda_success, open_oil_trade, monkeypatch):
        import scanner.live_engine as oil_le
        from scanner.live_engine import check_open_positions as oil_check

        open_oil_trade(sl_price=104.20, tp_price=105.10, oanda_trade_id="67890")

        mock_oanda_success["open_trades"].return_value = []
        monkeypatch.setattr(oil_le, "get_trade_details", MagicMock(return_value={
            "state": "CLOSED", "realized_pl": -30.0, "price": 104.23,
            "close_time": "2026-05-22T12:00:00Z",
        }))

        oil_check()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '67890'")
        assert trades[0]["exit_reason"] == "SL"

    def test_oil_detect_tp_with_tolerance(self, test_db, mock_oanda_success, open_oil_trade, monkeypatch):
        import scanner.live_engine as oil_le
        from scanner.live_engine import check_open_positions as oil_check

        open_oil_trade(sl_price=104.00, tp_price=105.10, oanda_trade_id="67890")

        mock_oanda_success["open_trades"].return_value = []
        monkeypatch.setattr(oil_le, "get_trade_details", MagicMock(return_value={
            "state": "CLOSED", "realized_pl": 60.0, "price": 105.07,
            "close_time": "2026-05-22T12:00:00Z",
        }))

        oil_check()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '67890'")
        assert trades[0]["exit_reason"] == "TP"


class TestMaxHold:
    """Max hold enforcement at 80 M3 bars."""

    def test_gold_max_hold_80_bars_triggers_close(self, test_db, mock_oanda_success, open_gold_trade, monkeypatch):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        # 80 bars × 180s = 14400s = 4 hours ago
        entry_time = datetime.now(timezone.utc) - timedelta(seconds=14500)
        open_gold_trade(strategy="alpha_sweep", oanda_trade_id="12345", entry_time=entry_time)

        # Trade is still on OANDA's open list so max-hold path runs
        mock_oanda_success["open_trades"].return_value = [{"trade_id": "12345"}]

        # close_trade is imported locally inside the function
        close_mock = MagicMock(return_value={
            "success": True, "close_price": 2625.0, "realized_pl": 30.0, "time": "2026-05-22T12:00:00Z",
        })
        monkeypatch.setattr(oanda, "close_trade", close_mock)

        check_open_positions()

        close_mock.assert_called_once_with("12345")

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert trades[0]["exit_reason"] == "MAX_HOLD"

        journal = query_db(test_db, "SELECT * FROM gd_journal WHERE event_type = 'EXIT_FILLED'")
        assert len(journal) == 1

    def test_gold_max_hold_79_bars_no_close(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_open_positions

        # 78 bars < 80 → no close
        entry_time = datetime.now(timezone.utc) - timedelta(seconds=78 * 180)
        open_gold_trade(strategy="alpha_sweep", oanda_trade_id="12345", entry_time=entry_time)

        mock_oanda_success["open_trades"].return_value = [{"trade_id": "12345"}]

        check_open_positions()

        mock_oanda_success["close"].assert_not_called()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert trades[0]["exit_time"] is None

    def test_gold_max_hold_close_fails(self, test_db, mock_oanda_success, open_gold_trade, monkeypatch):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        entry_time = datetime.now(timezone.utc) - timedelta(seconds=14500)
        open_gold_trade(strategy="alpha_sweep", oanda_trade_id="12345", entry_time=entry_time)

        mock_oanda_success["open_trades"].return_value = [{"trade_id": "12345"}]

        # close_trade is imported locally inside the function from oanda_executor
        monkeypatch.setattr(oanda, "close_trade", MagicMock(return_value={"success": False, "error": "timeout"}))

        check_open_positions()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert trades[0]["exit_time"] is None  # Still open

        journal = query_db(test_db, "SELECT * FROM gd_journal WHERE event_type = 'CLOSE_FAILED'")
        assert len(journal) == 1

    def test_oil_max_hold_triggers(self, test_db, mock_oanda_success, open_oil_trade, monkeypatch):
        import scanner.live_engine as oil_le
        from scanner.live_engine import check_open_positions as oil_check

        entry_time = datetime.now(timezone.utc) - timedelta(seconds=14500)
        open_oil_trade(strategy="alpha_sweep_oil", oanda_trade_id="67890", entry_time=entry_time)

        monkeypatch.setattr(oil_le, "get_open_trades", MagicMock(return_value=[{"trade_id": "67890"}]))
        monkeypatch.setattr(oil_le, "close_trade", mock_oanda_success["close"])
        monkeypatch.setattr(oil_le, "_get_gbp_usd_rate", mock_oanda_success["rate"])

        oil_check()

        mock_oanda_success["close"].assert_called_once_with("67890")

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '67890'")
        assert trades[0]["exit_reason"] == "MAX_HOLD"


class TestEdgeCases:
    """Edge cases for position monitoring."""

    def test_no_open_trades_returns_immediately(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import check_open_positions

        check_open_positions()

        mock_oanda_success["open_trades"].assert_not_called()

    def test_trade_details_returns_none(self, test_db, mock_oanda_success, open_gold_trade, monkeypatch):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        open_gold_trade(oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        monkeypatch.setattr(oanda, "get_trade_details", MagicMock(return_value=None))

        # Should not crash
        check_open_positions()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert trades[0]["exit_time"] is None  # Left open

    def test_multiple_open_trades_handled(self, test_db, mock_oanda_success, open_gold_trade, monkeypatch):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        # 3 trades: one closed by SL, one at max hold, one still open
        open_gold_trade(trade_ref="GD-AL-trade001", oanda_trade_id="111", sl_price=2610.0, tp_price=2640.0)
        entry_old = datetime.now(timezone.utc) - timedelta(seconds=14500)
        open_gold_trade(trade_ref="GD-AL-trade002", oanda_trade_id="222", strategy="alpha_sweep", entry_time=entry_old)
        open_gold_trade(trade_ref="GD-AL-trade003", oanda_trade_id="333", sl_price=2610.0, tp_price=2640.0)

        # 111 is closed (not in open trades), 222 still open (max hold), 333 still open
        mock_oanda_success["open_trades"].return_value = [{"trade_id": "222"}, {"trade_id": "333"}]
        monkeypatch.setattr(oanda, "get_trade_details", MagicMock(return_value={
            "state": "CLOSED", "realized_pl": -50.0, "price": 2610.1,
            "close_time": "2026-05-22T12:00:00Z",
        }))
        # close_trade is imported locally for max-hold path
        close_mock = MagicMock(return_value={
            "success": True, "close_price": 2625.0, "realized_pl": 30.0, "time": "2026-05-22T12:00:00Z",
        })
        monkeypatch.setattr(oanda, "close_trade", close_mock)

        check_open_positions()

        # Trade 111 should be closed (SL detected)
        t1 = query_db(test_db, "SELECT * FROM gd_trades WHERE trade_ref = 'GD-AL-trade001'")
        assert t1[0]["exit_time"] is not None

        # Trade 222 max-hold triggered (was still open on OANDA)
        t2 = query_db(test_db, "SELECT * FROM gd_trades WHERE trade_ref = 'GD-AL-trade002'")
        assert t2[0]["exit_reason"] == "MAX_HOLD"

        # Trade 333 still open (on OANDA list, not at max hold)
        t3 = query_db(test_db, "SELECT * FROM gd_trades WHERE trade_ref = 'GD-AL-trade003'")
        assert t3[0]["exit_time"] is None


class TestDDStateAfterExit:
    """DD state transitions after position closure."""

    def test_loss_increments_consecutive(self, test_db, mock_oanda_success, open_gold_trade, gold_dd_state):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        gold_dd_state(consecutive_losses=2)
        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        oanda.get_trade_details = MagicMock(return_value={
            "state": "CLOSED", "realized_pl": -50.0, "price": 2610.1,
            "close_time": "2026-05-22T12:00:00Z",
        })

        check_open_positions()

        dd = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 1")
        assert dd[0]["consecutive_losses"] == 3

    def test_win_resets_consecutive(self, test_db, mock_oanda_success, open_gold_trade, gold_dd_state):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        gold_dd_state(consecutive_losses=4)
        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        oanda.get_trade_details = MagicMock(return_value={
            "state": "CLOSED", "realized_pl": 100.0, "price": 2639.8,
            "close_time": "2026-05-22T12:00:00Z",
        })

        check_open_positions()

        dd = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 1")
        assert dd[0]["consecutive_losses"] == 0

    def test_5_losses_sets_pause(self, test_db, mock_oanda_success, open_gold_trade, gold_dd_state):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        gold_dd_state(consecutive_losses=4)
        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        oanda.get_trade_details = MagicMock(return_value={
            "state": "CLOSED", "realized_pl": -50.0, "price": 2610.1,
            "close_time": "2026-05-22T12:00:00Z",
        })

        check_open_positions()

        dd = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 1")
        assert dd[0]["consecutive_losses"] == 5
        assert dd[0]["pause_counter"] == 2

    def test_equity_updated_on_exit(self, test_db, mock_oanda_success, open_gold_trade, gold_dd_state):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        gold_dd_state(equity=5000, peak_equity=5000)
        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        # realized_pl is in GBP, gbp_usd_rate=1.337 → pnl_usd = 100 * 1.337 = 133.7
        oanda.get_trade_details = MagicMock(return_value={
            "state": "CLOSED", "realized_pl": 100.0, "price": 2639.8,
            "close_time": "2026-05-22T12:00:00Z",
        })

        check_open_positions()

        dd = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 1")
        assert float(dd[0]["equity"]) == pytest.approx(5000 + 100 * 1.337, abs=1)
        assert float(dd[0]["peak_equity"]) == pytest.approx(5000 + 100 * 1.337, abs=1)

    def test_peak_equity_not_lowered(self, test_db, mock_oanda_success, open_gold_trade, gold_dd_state):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution.oanda_executor as oanda

        gold_dd_state(equity=5500, peak_equity=6000)
        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        # Loss: pnl_usd = -50 * 1.337 = -66.85
        oanda.get_trade_details = MagicMock(return_value={
            "state": "CLOSED", "realized_pl": -50.0, "price": 2610.1,
            "close_time": "2026-05-22T12:00:00Z",
        })

        check_open_positions()

        dd = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 1")
        assert float(dd[0]["equity"]) < 5500  # Decreased
        assert float(dd[0]["peak_equity"]) == 6000  # Peak stays at 6000
