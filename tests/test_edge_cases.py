"""Test edge cases — zero values, boundaries, degenerate inputs."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend-oil"))

from tests.conftest import query_db


class TestZeroEquity:
    """Zero and negative equity edge cases."""

    def test_execute_signal_equity_zero(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import execute_signal

        mock_oanda_success["account"].return_value["nav_usd"] = 0.0

        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2610.0, 2640.0)

        assert ref is None
        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE skip_reason = 'units_too_small'")
        assert len(signals) == 1

    def test_execute_signal_negative_equity(self, test_db, mock_oanda_success):
        from backend.scanner.live_engine import execute_signal

        mock_oanda_success["account"].return_value["nav_usd"] = -500.0

        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2610.0, 2640.0)

        assert ref is None
        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE skip_reason = 'units_too_small'")
        assert len(signals) == 1


class TestRealizedPLZero:
    """realized_pl = 0 counted as loss (condition is > 0)."""

    def test_realized_pl_zero_counted_as_loss(self, test_db, mock_oanda_success, open_gold_trade, gold_dd_state, monkeypatch):
        import backend.scanner.live_engine as gold_le
        from backend.scanner.live_engine import check_open_positions

        gold_dd_state(consecutive_losses=2)
        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        monkeypatch.setattr(gold_le, "get_trade_details", MagicMock(return_value={
            "state": "CLOSED", "realized_pl": 0.0, "price": 2620.0,
            "close_time": "2026-05-22T12:00:00Z",
        }))

        check_open_positions()

        dd = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 1")
        # 0.0 is not > 0, so treated as loss
        assert dd[0]["consecutive_losses"] == 3


class TestTPEqualsEntry:
    """tp=entry BE guard (degenerate case)."""

    def test_be_tp_equals_entry_long_does_not_trigger(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven

        # tp == entry → degenerate. Code has `if tp <= entry: continue` guard
        open_gold_trade(entry_price=2620.0, tp_price=2620.0, sl_price=2610.0,
                       oanda_trade_id="12345", side="LONG")

        mock_oanda_success["price"].return_value = {
            "bid": 2625.0, "ask": 2626.0, "mid": 2625.5, "spread": 1.0, "tradeable": True,
        }

        check_alpha_sweep_breakeven()

        mock_oanda_success["modify"].assert_not_called()

    def test_be_tp_equals_entry_short_does_not_trigger(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven

        # tp == entry → degenerate for short. Code has `if tp >= entry: continue`
        open_gold_trade(entry_price=2620.0, tp_price=2620.0, sl_price=2630.0,
                       oanda_trade_id="12345", side="SHORT")

        mock_oanda_success["price"].return_value = {
            "bid": 2615.0, "ask": 2616.0, "mid": 2615.5, "spread": 1.0, "tradeable": True,
        }

        check_alpha_sweep_breakeven()

        mock_oanda_success["modify"].assert_not_called()


class TestGBPUSDRateZero:
    """GBP/USD rate = 0 edge case."""

    def test_gbp_usd_rate_zero_no_crash(self, test_db, mock_oanda_success, open_gold_trade, monkeypatch):
        import backend.scanner.live_engine as gold_le
        from backend.scanner.live_engine import check_open_positions

        open_gold_trade(sl_price=2610.0, tp_price=2640.0, oanda_trade_id="12345")

        mock_oanda_success["open_trades"].return_value = []
        monkeypatch.setattr(gold_le, "get_trade_details", MagicMock(return_value={
            "state": "CLOSED", "realized_pl": 100.0, "price": 2639.8,
            "close_time": "2026-05-22T12:00:00Z",
        }))
        monkeypatch.setattr(gold_le, "_get_gbp_usd_rate", MagicMock(return_value=0.0))

        # Should not crash
        check_open_positions()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert trades[0]["exit_time"] is not None
        # pnl_usd = 100 * 0 = 0 (silent data loss, but no crash)
        assert float(trades[0]["pnl_usd"]) == 0.0


class TestMaxHoldBoundary:
    """Max hold exact boundary at 80 bars."""

    def test_max_hold_exact_80_bars(self, test_db, mock_oanda_success, open_gold_trade, monkeypatch):
        from backend.scanner.live_engine import check_open_positions
        import backend.execution as execution_mod

        # Exactly 80 bars = 80 * 180s = 14400s
        entry_time = datetime.now(timezone.utc) - timedelta(seconds=14400)
        open_gold_trade(strategy="alpha_sweep", oanda_trade_id="12345", entry_time=entry_time)

        mock_oanda_success["open_trades"].return_value = [{"trade_id": "12345"}]

        close_mock = MagicMock(return_value={
            "success": True, "close_price": 2625.0, "realized_pl": 30.0, "time": "2026-05-22T12:00:00Z",
        })
        monkeypatch.setattr(execution_mod, "close_trade", close_mock)

        check_open_positions()

        # bars_held = 14400/180 = 80.0 → >= 80 → triggers
        close_mock.assert_called_once()
        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert trades[0]["exit_reason"] == "MAX_HOLD"

    def test_max_hold_79_point_9_bars(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_open_positions

        # 79.9 bars = 79.9 * 180s = 14382s → < 80 → no trigger
        entry_time = datetime.now(timezone.utc) - timedelta(seconds=14382)
        open_gold_trade(strategy="alpha_sweep", oanda_trade_id="12345", entry_time=entry_time)

        mock_oanda_success["open_trades"].return_value = [{"trade_id": "12345"}]

        check_open_positions()

        mock_oanda_success["close"].assert_not_called()


class TestAlreadyTradedToday:
    """UTC midnight boundary for 'already traded today' check."""

    def test_yesterday_trade_allows_new_today(self, test_db, mock_oanda_success, monkeypatch):
        """A trade entered yesterday at 23:59 UTC should not block today's signal."""
        from backend.scanner.live_engine import execute_signal

        # Insert a trade from yesterday
        yesterday = datetime.now(timezone.utc).replace(hour=23, minute=59) - timedelta(days=1)
        cur = test_db.cursor()
        cur.execute(
            """INSERT INTO gd_trades (trade_ref, strategy, side, entry_time, entry_price, sl_price, tp_price, lot_size, units, mode, oanda_trade_id)
               VALUES ('GD-AL-yester1', 'alpha_sweep', 'LONG', %s, 2620.0, 2610.0, 2640.0, 1.0, 100, 'live', '99999')""",
            (yesterday,)
        )

        # Today's signal should still execute (no "already traded today" blocking in execute_signal itself)
        with patch("backend.scanner.live_engine.get_candles", return_value=[{"bid_close": 2620} for _ in range(55)]):
            ref = execute_signal("alpha_sweep", "long", 2620.0, 2610.0, 2640.0)

        assert ref is not None


class TestOilEdgeCases:
    """Oil-specific edge cases."""

    @pytest.fixture(autouse=True)
    def _patch_oil_oanda(self, mock_oanda_success, monkeypatch):
        from conftest import get_oil_live_engine; oil_le = get_oil_live_engine()
        monkeypatch.setattr(oil_le, "place_market_order", mock_oanda_success["place"])
        monkeypatch.setattr(oil_le, "get_account_summary", mock_oanda_success["account"])
        monkeypatch.setattr(oil_le, "get_open_trades", mock_oanda_success["open_trades"])
        monkeypatch.setattr(oil_le, "get_current_price", mock_oanda_success["price"])
        monkeypatch.setattr(oil_le, "close_trade", mock_oanda_success["close"])
        monkeypatch.setattr(oil_le, "modify_stop_loss", mock_oanda_success["modify"])
        monkeypatch.setattr(oil_le, "_get_gbp_usd_rate", mock_oanda_success["rate"])
        monkeypatch.setattr(oil_le, "get_trade_details", mock_oanda_success["details"])

    def test_oil_zero_equity(self, test_db, mock_oanda_success):
        from conftest import get_oil_live_engine; oil_execute = get_oil_live_engine().execute_signal

        mock_oanda_success["account"].return_value["nav_usd"] = 0.0

        ref = oil_execute("long", 104.50, 104.20, 105.10)
        assert ref is None
        signals = query_db(test_db, "SELECT * FROM gd_signals WHERE skip_reason = 'units_too_small'")
        assert len(signals) == 1

    def test_oil_realized_pl_zero_is_loss(self, test_db, mock_oanda_success, open_oil_trade, oil_dd_state, monkeypatch):
        from conftest import get_oil_live_engine; oil_le = get_oil_live_engine()
        from conftest import get_oil_live_engine; oil_check = get_oil_live_engine().check_open_positions

        oil_dd_state(consecutive_losses=1)
        open_oil_trade(sl_price=104.00, tp_price=105.50, oanda_trade_id="67890")

        mock_oanda_success["open_trades"].return_value = []
        monkeypatch.setattr(oil_le, "get_trade_details", MagicMock(return_value={
            "state": "CLOSED", "realized_pl": 0.0, "price": 104.50,
            "close_time": "2026-05-22T12:00:00Z",
        }))

        oil_check()

        dd = query_db(test_db, "SELECT * FROM gd_dd_state WHERE id = 2")
        assert dd[0]["consecutive_losses"] == 2  # Incremented (0 is not > 0)

    def test_oil_details_returns_none_no_crash(self, test_db, mock_oanda_success, open_oil_trade, monkeypatch):
        from conftest import get_oil_live_engine; oil_le = get_oil_live_engine()
        from conftest import get_oil_live_engine; oil_check = get_oil_live_engine().check_open_positions

        open_oil_trade(oanda_trade_id="67890")

        mock_oanda_success["open_trades"].return_value = []
        monkeypatch.setattr(oil_le, "get_trade_details", MagicMock(return_value=None))

        # Should not crash, logs DETAILS_FETCH_FAILED
        oil_check()

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '67890'")
        assert trades[0]["exit_time"] is None

        journal = query_db(test_db, "SELECT * FROM gd_journal WHERE event_type = 'DETAILS_FETCH_FAILED'")
        assert len(journal) == 1
