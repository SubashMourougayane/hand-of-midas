"""Test break-even logic for Gold and Oil trades."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend-oil"))

from tests.conftest import query_db


class TestGoldBreakEvenLong:
    """Gold LONG break-even triggers at 50% to TP."""

    def test_long_triggers_at_50pct(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven

        # entry=2620, tp=2640, sl=2610 → target_50 = 2620 + (2640-2620)*0.5 = 2630
        open_gold_trade(entry_price=2620.0, tp_price=2640.0, sl_price=2610.0,
                       oanda_trade_id="12345", side="LONG")

        # bid=2630.01 → >= target_50=2630
        mock_oanda_success["price"].return_value = {
            "bid": 2630.01, "ask": 2631.0, "mid": 2630.5, "spread": 1.0, "tradeable": True,
        }

        check_alpha_sweep_breakeven()

        # SL moved to entry + 0.30 = 2620.30
        mock_oanda_success["modify"].assert_called_once_with("12345", 2620.30)

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert float(trades[0]["sl_price"]) == 2620.30

        journal = query_db(test_db, "SELECT * FROM gd_journal WHERE event_type = 'BREAK_EVEN'")
        assert len(journal) == 1

    def test_long_not_triggered_below_50pct(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven

        open_gold_trade(entry_price=2620.0, tp_price=2640.0, sl_price=2610.0,
                       oanda_trade_id="12345", side="LONG")

        # bid=2629.99 → below target_50=2630
        mock_oanda_success["price"].return_value = {
            "bid": 2629.99, "ask": 2631.0, "mid": 2630.5, "spread": 1.0, "tradeable": True,
        }

        check_alpha_sweep_breakeven()

        mock_oanda_success["modify"].assert_not_called()

    def test_long_already_at_be_skip(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven

        # sl already >= entry → already at BE
        open_gold_trade(entry_price=2620.0, tp_price=2640.0, sl_price=2620.30,
                       oanda_trade_id="12345", side="LONG")

        mock_oanda_success["price"].return_value = {
            "bid": 2635.0, "ask": 2636.0, "mid": 2635.5, "spread": 1.0, "tradeable": True,
        }

        check_alpha_sweep_breakeven()

        mock_oanda_success["modify"].assert_not_called()


class TestGoldBreakEvenShort:
    """Gold SHORT break-even triggers at 50% to TP."""

    def test_short_triggers_at_50pct(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven

        # entry=2620, tp=2600, sl=2630 → target_50 = 2620 - (2620-2600)*0.5 = 2610
        open_gold_trade(entry_price=2620.0, tp_price=2600.0, sl_price=2630.0,
                       oanda_trade_id="12345", side="SHORT")

        # ask=2609.99 → <= target_50=2610
        mock_oanda_success["price"].return_value = {
            "bid": 2609.0, "ask": 2609.99, "mid": 2609.5, "spread": 1.0, "tradeable": True,
        }

        check_alpha_sweep_breakeven()

        # SL moved to entry - 0.30 = 2619.70
        mock_oanda_success["modify"].assert_called_once_with("12345", 2619.70)

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert float(trades[0]["sl_price"]) == 2619.70

    def test_short_already_at_be_skip(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven

        # sl already <= entry → already at BE
        open_gold_trade(entry_price=2620.0, tp_price=2600.0, sl_price=2619.70,
                       oanda_trade_id="12345", side="SHORT")

        mock_oanda_success["price"].return_value = {
            "bid": 2605.0, "ask": 2606.0, "mid": 2605.5, "spread": 1.0, "tradeable": True,
        }

        check_alpha_sweep_breakeven()

        mock_oanda_success["modify"].assert_not_called()


class TestOilBreakEven:
    """Oil uses entry + 0.01 (not 0.30) for break-even offset."""

    @pytest.fixture(autouse=True)
    def _patch_oil_oanda(self, mock_oanda_success, monkeypatch):
        import scanner.live_engine as oil_le
        monkeypatch.setattr(oil_le, "get_current_price", mock_oanda_success["price"])
        monkeypatch.setattr(oil_le, "modify_stop_loss", mock_oanda_success["modify"])

    def test_oil_long_triggers_at_50pct(self, test_db, mock_oanda_success, open_oil_trade):
        from scanner.live_engine import check_alpha_sweep_breakeven as oil_be

        # entry=104.50, tp=105.50, sl=104.00 → target_50 = 104.50 + (105.50-104.50)*0.5 = 105.00
        open_oil_trade(entry_price=104.50, tp_price=105.50, sl_price=104.00,
                      oanda_trade_id="67890", side="LONG")

        mock_oanda_success["price"].return_value = {
            "bid": 105.01, "ask": 105.05, "mid": 105.03, "spread": 0.04, "tradeable": True,
        }

        oil_be()

        # SL moved to entry + 0.01 = 104.51
        mock_oanda_success["modify"].assert_called_once_with("67890", 104.51)

        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '67890'")
        assert float(trades[0]["sl_price"]) == pytest.approx(104.51, abs=0.001)

    def test_oil_short_triggers_at_50pct(self, test_db, mock_oanda_success, open_oil_trade):
        from scanner.live_engine import check_alpha_sweep_breakeven as oil_be

        # entry=104.50, tp=103.50, sl=105.00 → target_50 = 104.50 - (104.50-103.50)*0.5 = 104.00
        open_oil_trade(entry_price=104.50, tp_price=103.50, sl_price=105.00,
                      oanda_trade_id="67890", side="SHORT")

        mock_oanda_success["price"].return_value = {
            "bid": 103.95, "ask": 103.99, "mid": 103.97, "spread": 0.04, "tradeable": True,
        }

        oil_be()

        # SL moved to entry - 0.01 = 104.49
        mock_oanda_success["modify"].assert_called_once_with("67890", 104.49)


class TestBreakEvenFailures:
    """Break-even failure handling."""

    def test_modify_fails_logs_event(self, test_db, mock_oanda_failure, open_gold_trade, monkeypatch):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven
        import backend.scanner.live_engine as gold_le

        open_gold_trade(entry_price=2620.0, tp_price=2640.0, sl_price=2610.0,
                       oanda_trade_id="12345", side="LONG")

        # Price triggers BE
        monkeypatch.setattr(gold_le, "get_current_price", MagicMock(return_value={
            "bid": 2631.0, "ask": 2632.0, "mid": 2631.5, "spread": 1.0, "tradeable": True,
        }))

        check_alpha_sweep_breakeven()

        # SL NOT changed in DB
        trades = query_db(test_db, "SELECT * FROM gd_trades WHERE oanda_trade_id = '12345'")
        assert float(trades[0]["sl_price"]) == 2610.0

        # BREAK_EVEN_FAILED logged
        journal = query_db(test_db, "SELECT * FROM gd_journal WHERE event_type = 'BREAK_EVEN_FAILED'")
        assert len(journal) == 1

    def test_price_returns_none_no_crash(self, test_db, mock_oanda_success, open_gold_trade, monkeypatch):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven
        import backend.scanner.live_engine as gold_le

        open_gold_trade(entry_price=2620.0, tp_price=2640.0, sl_price=2610.0,
                       oanda_trade_id="12345", side="LONG")

        monkeypatch.setattr(gold_le, "get_current_price", MagicMock(return_value=None))

        # Should not crash
        check_alpha_sweep_breakeven()

        mock_oanda_success["modify"].assert_not_called()


class TestBreakEvenGuards:
    """Guard conditions: tp<=entry for LONG, tp>=entry for SHORT."""

    def test_long_tp_le_entry_skips(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven

        # tp <= entry → degenerate, should skip (guarded by tp <= entry check)
        open_gold_trade(entry_price=2620.0, tp_price=2620.0, sl_price=2610.0,
                       oanda_trade_id="12345", side="LONG")

        mock_oanda_success["price"].return_value = {
            "bid": 2625.0, "ask": 2626.0, "mid": 2625.5, "spread": 1.0, "tradeable": True,
        }

        check_alpha_sweep_breakeven()

        # Should not trigger BE (guard: tp <= entry → continue)
        mock_oanda_success["modify"].assert_not_called()

    def test_short_tp_ge_entry_skips(self, test_db, mock_oanda_success, open_gold_trade):
        from backend.scanner.live_engine import check_alpha_sweep_breakeven

        # tp >= entry → degenerate for short
        open_gold_trade(entry_price=2620.0, tp_price=2620.0, sl_price=2630.0,
                       oanda_trade_id="12345", side="SHORT")

        mock_oanda_success["price"].return_value = {
            "bid": 2615.0, "ask": 2616.0, "mid": 2615.5, "spread": 1.0, "tradeable": True,
        }

        check_alpha_sweep_breakeven()

        mock_oanda_success["modify"].assert_not_called()
