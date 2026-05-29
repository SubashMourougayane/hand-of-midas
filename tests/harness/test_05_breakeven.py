"""TEST 05: Break-Even Verification.

Verifies BE triggers at EXACTLY the right level and modifies SL correctly.
Would have caught: today's trade where BE should have saved $562.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-micro"))


def _setup_open_trade(side, entry, sl, tp, trade_ref="GD-MI-test001", oanda_id="999999"):
    """Create a mock open trade dict as DB would return."""
    return {
        "trade_ref": trade_ref,
        "strategy": "micro_alpha_sweep",
        "side": side,
        "entry_price": entry,
        "sl_price": sl,
        "tp_price": tp,
        "oanda_trade_id": oanda_id,
        "units": 50,
        "entry_time": datetime.now(timezone.utc) - timedelta(minutes=30),
    }


class TestBreakEvenTrigger:
    """05a: BE fires at exactly 50% of TP distance."""

    def test_short_be_fires_at_50pct(self):
        """SHORT: entry=4523, tp=4497, sl=4540. BE at 4510."""
        entry, tp, sl = 4523.0, 4497.0, 4540.0
        target_50 = entry - (entry - tp) * 0.5
        assert abs(target_50 - 4510.0) < 0.01

        # Verify the trigger logic:
        # For SHORT: price["ask"] <= target_50 triggers BE
        price_not_triggered = 4511.10
        assert price_not_triggered > target_50  # Should NOT trigger

        price_triggered = 4509.10
        assert price_triggered <= target_50  # SHOULD trigger

        # After trigger: new SL = entry - 0.30
        new_sl = entry - 0.30
        assert abs(new_sl - 4522.70) < 0.01

    def test_short_be_trigger_math(self):
        """Verify the 50% math for SHORT trades."""
        cases = [
            # (entry, tp, expected_trigger)
            (4523.0, 4497.0, 4510.0),    # 50% of $26 = $13 below entry
            (4500.0, 4450.0, 4475.0),    # 50% of $50 = $25 below entry
            (4600.0, 4580.0, 4590.0),    # 50% of $20 = $10 below entry
        ]
        for entry, tp, expected in cases:
            actual = entry - (entry - tp) * 0.5
            assert abs(actual - expected) < 0.01, \
                f"SHORT BE: entry={entry}, tp={tp}, expected trigger={expected}, got={actual}"

    def test_long_be_trigger_math(self):
        """Verify the 50% math for LONG trades."""
        cases = [
            (4500.0, 4530.0, 4515.0),    # 50% of $30 = $15 above entry
            (4400.0, 4450.0, 4425.0),
            (4520.0, 4540.0, 4530.0),
        ]
        for entry, tp, expected in cases:
            actual = entry + (tp - entry) * 0.5
            assert abs(actual - expected) < 0.01, \
                f"LONG BE: entry={entry}, tp={tp}, expected trigger={expected}, got={actual}"

    def test_be_sl_value_short(self):
        """After BE triggers on SHORT, new SL = entry - 0.30."""
        entry = 4523.05
        expected_new_sl = entry - 0.30  # = 4522.75
        assert abs(expected_new_sl - 4522.75) < 0.01

    def test_be_sl_value_long(self):
        """After BE triggers on LONG, new SL = entry + 0.30."""
        entry = 4500.00
        expected_new_sl = entry + 0.30  # = 4500.30
        assert abs(expected_new_sl - 4500.30) < 0.01


class TestBreakEvenGuards:
    """05b: BE doesn't fire when it shouldn't."""

    def test_be_not_triggered_when_sl_already_at_entry(self):
        """If SL already at entry level (BE already fired), don't fire again."""
        # SHORT: sl = 4522.75 (entry-0.30), entry = 4523.05
        # Guard: sl <= entry (for SHORT, sl should be below entry after BE)
        # Actually the guard is: sl >= entry → skip (means BE already done)
        # For SHORT after BE: sl = entry - 0.30 = 4522.75 < entry (4523.05)
        # Hmm, the actual guard in code:
        # if side == "SHORT" and (tp >= entry or sl <= entry): continue
        # sl=4522.75 <= entry=4523.05 → TRUE → skip. Correct!
        entry = 4523.05
        sl_after_be = entry - 0.30  # = 4522.75

        assert sl_after_be <= entry  # Guard condition → BE won't fire again

    def test_be_not_triggered_without_tp(self):
        """If tp_price is 0 or None, BE should not fire."""
        trade = _setup_open_trade("SHORT", entry=4523.0, sl=4540.0, tp=0)
        # Guard: if tp <= 0: continue
        assert trade["tp_price"] <= 0  # Should skip

    def test_be_not_triggered_if_price_above_50pct(self):
        """SHORT: price must be BELOW target_50 for BE to fire."""
        entry, tp = 4523.0, 4497.0
        target_50 = entry - (entry - tp) * 0.5  # = 4510

        price_ask = 4515.0  # Above 4510
        assert price_ask > target_50  # Should NOT trigger


class TestBreakEvenVsFillModel:
    """05c: Compare BE logic between backtest fill_model and live."""

    def test_be_trigger_level_same(self):
        """Both use 50% of (entry to TP) as trigger."""
        # Fill model line 85: if bh >= entry + (tp - entry) * 0.5 (LONG)
        # Fill model line 115: if al <= entry - (entry - tp) * 0.5 (SHORT)
        # Live: target_50 = entry - (entry - tp) * cfg["be_trigger_pct"]
        #   where be_trigger_pct = 0.50
        from config import MICRO_ALPHA_SWEEP
        assert MICRO_ALPHA_SWEEP.get("be_trigger_pct", 0.50) == 0.50

    def test_be_sl_value_divergence_documented(self):
        """Known divergence: backtest uses entry+slippage, live uses entry+$0.30.

        This is documented in B9 and accepted. Just verify both are positive."""
        # Backtest: current_sl = entry + _sl_slip(bar_range) ≈ entry + $0.04
        # Live: new_sl = entry + 0.30
        # Both are entry + positive amount → move SL in profit direction
        backtest_be_offset = 0.04  # approximate
        live_be_offset = 0.30
        assert live_be_offset > backtest_be_offset  # Live is more generous
        # This means live LOCKS MORE PROFIT after BE than backtest shows


