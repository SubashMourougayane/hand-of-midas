"""Test fill model — backtest trade simulation edge cases."""
import sys
import os
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from backend.execution.fill_model import execute_trade, TradeResult


def make_bars(n, base=2620, volatility=5):
    """Create n bars of synthetic price data with controllable OHLC."""
    data = {
        "bid_open": [float(base)] * n,
        "bid_high": [float(base + volatility)] * n,
        "bid_low": [float(base - volatility)] * n,
        "bid_close": [float(base)] * n,
        "ask_open": [float(base + 0.5)] * n,
        "ask_high": [float(base + volatility + 0.5)] * n,
        "ask_low": [float(base - volatility + 0.5)] * n,
        "ask_close": [float(base + 0.5)] * n,
    }
    return pd.DataFrame(data)


class TestLongTP:
    """LONG: TP touch fills at TP."""

    def test_long_tp_touch_fills_at_tp(self, test_db):
        # Low volatility so no bar accidentally hits SL or TP
        df = make_bars(10, base=2620, volatility=1)
        # Bar 3: high reaches TP of 2630
        df.at[3, "bid_high"] = 2630.0

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
                              direction="long", max_bars=80, strategy="alpha_sweep")
        assert result.exit_reason == "tp"
        assert result.exit_price == 2630.0
        assert result.bars_held == 3

    def test_long_tp_exact_touch(self, test_db):
        df = make_bars(10, base=2620, volatility=1)
        df.at[4, "bid_high"] = 2640.0

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2610.0, tp=2640.0,
                              direction="long", max_bars=80, strategy="alpha_sweep")
        assert result.exit_reason == "tp"
        assert result.exit_price == 2640.0


class TestLongSL:
    """LONG: SL touch fills at SL - slippage."""

    def test_long_sl_touch_fills_at_sl(self, test_db):
        # volatility=1 means default bars have low at 2619, won't hit SL=2610
        df = make_bars(10, base=2620, volatility=1)
        # Bar 3: low hits SL=2610, high doesn't hit TP=2640
        df.at[3, "bid_low"] = 2609.0
        df.at[3, "bid_high"] = 2621.0

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2610.0, tp=2640.0,
                              direction="long", max_bars=80, strategy="alpha_sweep")
        assert result.exit_reason == "sl"
        # Exit price = SL - slip (slip is small with deterministic seed)
        assert result.exit_price < 2610.0
        assert result.exit_price > 2608.0  # Slippage shouldn't be huge

    def test_long_gap_through_fills_at_open(self, test_db):
        df = make_bars(10, base=2620, volatility=1)
        # Bar 2 opens below SL (gap down)
        df.at[2, "bid_open"] = 2608.0
        df.at[2, "bid_low"] = 2607.0
        df.at[2, "bid_high"] = 2618.0

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2610.0, tp=2640.0,
                              direction="long", max_bars=80, strategy="alpha_sweep")
        assert result.exit_reason == "sl"
        # Gap fills at open - micro_slip (slip * 0.2)
        assert result.exit_price < 2608.0  # open - slip*0.2


class TestLongBothSLTPTouched:
    """LONG: when both SL and TP touched in same bar (no gap), TP wins."""

    def test_long_both_touched_no_gap_tp_wins(self, test_db):
        # Use low volatility so earlier bars don't accidentally trigger
        df = make_bars(10, base=2620, volatility=1)
        # Bar 2: open > SL (no gap), low <= SL AND high >= TP
        df.at[2, "bid_open"] = 2618.0  # Above SL=2610 (no gap)
        df.at[2, "bid_low"] = 2609.0   # Below SL=2610
        df.at[2, "bid_high"] = 2635.0  # Above TP=2630

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
                              direction="long", max_bars=80, strategy="alpha_sweep")
        # TP checked before SL when no gap
        assert result.exit_reason == "tp"
        assert result.exit_price == 2630.0

    def test_long_gap_overrides_tp(self, test_db):
        df = make_bars(10, base=2620, volatility=1)
        # Bar 2: open below SL (gap) AND high >= TP — gap wins
        df.at[2, "bid_open"] = 2608.0  # Below SL=2610 (GAP)
        df.at[2, "bid_low"] = 2607.0
        df.at[2, "bid_high"] = 2640.0  # Also hits TP=2630

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
                              direction="long", max_bars=80, strategy="alpha_sweep")
        # Gap-through SL checked FIRST
        assert result.exit_reason == "sl"
        assert result.exit_price < 2608.0  # open - micro_slip


class TestShortTP:
    """SHORT: TP fills on touch (bar low <= TP)."""

    def test_short_tp_touch_fills_at_tp(self, test_db):
        # volatility=1: ask_high=2621.5 (below SL=2635), ask_low=2619.5 (above TP=2610)
        df = make_bars(10, base=2620, volatility=1)
        # Bar 3 ask_low <= TP=2610
        df.at[3, "ask_low"] = 2609.0

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2635.0, tp=2610.0,
                              direction="short", max_bars=80, strategy="alpha_sweep")
        assert result.exit_reason == "tp"
        assert result.exit_price == 2610.0


class TestShortSL:
    """SHORT: SL fills at SL + slippage."""

    def test_short_sl_touch_fills_at_sl(self, test_db):
        # volatility=1: ask_high=2621.5 (below SL=2635), ask_low=2619.5 (above TP=2605)
        df = make_bars(10, base=2620, volatility=1)
        # Bar 3: ask_high >= SL=2635, ask_low doesn't hit TP=2605
        df.at[3, "ask_high"] = 2636.0
        df.at[3, "ask_low"] = 2617.0

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2635.0, tp=2605.0,
                              direction="short", max_bars=80, strategy="alpha_sweep")
        assert result.exit_reason == "sl"
        # Exit price = SL + slip (adverse for short)
        assert result.exit_price > 2635.0
        assert result.exit_price < 2637.0

    def test_short_gap_through_fills_at_open(self, test_db):
        # volatility=1: default ask_high = 2621.5 (below SL=2635)
        df = make_bars(10, base=2620, volatility=1)
        # Bar 2: gap up: ask_open >= SL=2635
        df.at[2, "ask_open"] = 2636.0
        df.at[2, "ask_high"] = 2638.0
        df.at[2, "ask_low"] = 2634.0

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2635.0, tp=2605.0,
                              direction="short", max_bars=80, strategy="alpha_sweep")
        assert result.exit_reason == "sl"
        # Gap fills at open + micro slip
        assert result.exit_price > 2636.0


class TestBreakEven:
    """Break-even trigger at 50% to TP, then SL at new level."""

    def test_break_even_long_triggers_at_50pct(self, test_db):
        # entry=2620, tp=2640 → 50% target = 2630. SL far away at 2600.
        # After BE triggers, new SL ≈ entry + slip ≈ 2620.07
        # Use base=2625, vol=1 → bid_low=2624 (well above new SL of 2620.07)
        df = make_bars(20, base=2625, volatility=1)
        # Bar 3: high reaches 50% level → triggers BE
        df.at[3, "bid_high"] = 2631.0
        df.at[3, "bid_low"] = 2624.0  # keep default low high enough

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2600.0, tp=2640.0,
                              direction="long", max_bars=20, strategy="alpha_sweep",
                              use_break_even=True)
        # Since no bar hits new SL or TP (bid_high=2626 < TP=2640), expires
        assert result is not None
        assert result.exit_reason == "expired"

    def test_break_even_then_sl_hit_at_new_level(self, test_db):
        # entry=2620, tp=2640, sl=2600 → 50% = 2630
        # volatility=1: bid_low=2619 (well above SL=2600)
        df = make_bars(20, base=2620, volatility=1)
        # Bar 3: high triggers BE (>= 2630)
        df.at[3, "bid_high"] = 2631.0
        df.at[3, "bid_low"] = 2619.0
        # After BE, new SL ≈ entry + _sl_slip(bar_range) where bar_range = 2631-2619=12
        # _sl_slip = 0.03 + 12*0.003 + uniform(0,0.02) ≈ 0.066+rand ≈ 0.07-0.09
        # So new_sl ≈ 2620.07. Bar 5 needs bid_low < 2620.07
        df.at[5, "bid_open"] = 2620.5
        df.at[5, "bid_low"] = 2619.5
        df.at[5, "bid_high"] = 2622.0

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2600.0, tp=2640.0,
                              direction="long", max_bars=80, strategy="alpha_sweep",
                              use_break_even=True)
        assert result.exit_reason == "sl"
        # Exit near entry (small loss due to BE)
        assert abs(result.exit_price - 2620.0) < 1.0

    def test_break_even_short_triggers_at_50pct(self, test_db):
        # entry=2620, tp=2600 → 50% target = 2610. SL far at 2640.
        # volatility=1: ask_high=2621.5 (below SL=2640), ask_low=2619.5 (above TP=2600)
        df = make_bars(20, base=2620, volatility=1)
        # Bar 3: ask_low hits 50% level → triggers BE
        df.at[3, "ask_low"] = 2609.0
        df.at[3, "ask_high"] = 2621.0
        # After BE, SL moves to entry - _sl_slip ≈ 2619.93
        # Bar 5: ask_high >= new SL (near entry)
        df.at[5, "ask_open"] = 2619.0
        df.at[5, "ask_high"] = 2620.5  # Hits new SL near entry
        df.at[5, "ask_low"] = 2617.0

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2640.0, tp=2600.0,
                              direction="short", max_bars=80, strategy="alpha_sweep",
                              use_break_even=True)
        assert result.exit_reason == "sl"
        assert abs(result.exit_price - 2620.0) < 1.0


class TestMaxBars:
    """Max bars expiration."""

    def test_max_bars_expired_exits_at_close(self, test_db):
        df = make_bars(100, base=2620, volatility=1)
        # No bar hits SL=2600 or TP=2650 (volatility too small)

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2600.0, tp=2650.0,
                              direction="long", max_bars=80, strategy="alpha_sweep")
        assert result.exit_reason == "expired"
        # Loop: range(1, min(80, 100)) = range(1, 80) → 79 iterations
        assert result.bars_held == 79

    def test_max_bars_1_exits_immediately(self, test_db):
        df = make_bars(5, base=2620, volatility=1)

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2600.0, tp=2650.0,
                              direction="long", max_bars=1, strategy="alpha_sweep")
        # max_bars=1: range(1, min(1,5)) = range(1,1) = empty → falls through to expired
        assert result.exit_reason == "expired"


class TestSlippage:
    """Slippage is deterministic with np.random.seed(42)."""

    def test_slippage_deterministic(self, test_db):
        # volatility=1: bid_low=2619 won't hit SL=2610
        df = make_bars(10, base=2620, volatility=1)
        # Bar 3: low hits SL=2610
        df.at[3, "bid_low"] = 2609.0
        df.at[3, "bid_high"] = 2621.0  # Below TP=2650

        # With seed=42 (set by conftest autouse fixture), results are reproducible
        np.random.seed(42)
        result1 = execute_trade(df, bar_start=0, entry=2620.0, sl=2610.0, tp=2650.0,
                               direction="long", max_bars=80, strategy="alpha_sweep")

        np.random.seed(42)
        result2 = execute_trade(df, bar_start=0, entry=2620.0, sl=2610.0, tp=2650.0,
                               direction="long", max_bars=80, strategy="alpha_sweep")

        assert result1.exit_price == result2.exit_price


class TestShortBothTouched:
    """SHORT: both SL and TP touched in same bar."""

    def test_short_both_touched_no_gap_tp_wins(self, test_db):
        # volatility=1: default ask_high=2621.5 (below SL=2635), ask_low=2619.5 (above TP=2605)
        df = make_bars(10, base=2620, volatility=1)
        # Bar 2: open < SL (no gap for short), ask_high >= SL AND ask_low <= TP
        df.at[2, "ask_open"] = 2634.0  # Below SL=2635 (no gap-through)
        df.at[2, "ask_high"] = 2636.0  # Hits SL=2635
        df.at[2, "ask_low"] = 2604.0   # Hits TP=2605

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2635.0, tp=2605.0,
                              direction="short", max_bars=80, strategy="alpha_sweep")
        # TP checked before SL (no gap)
        assert result.exit_reason == "tp"
        assert result.exit_price == 2605.0

    def test_short_gap_overrides_tp(self, test_db):
        # volatility=1: default ask_high=2621.5 (below SL=2635)
        df = make_bars(10, base=2620, volatility=1)
        # Bar 2: ask_open >= SL (gap through) AND ask_low also hits TP
        df.at[2, "ask_open"] = 2636.0  # Gap above SL=2635
        df.at[2, "ask_high"] = 2638.0
        df.at[2, "ask_low"] = 2604.0   # Would hit TP=2605

        result = execute_trade(df, bar_start=0, entry=2620.0, sl=2635.0, tp=2605.0,
                              direction="short", max_bars=80, strategy="alpha_sweep")
        # Gap checked first
        assert result.exit_reason == "sl"
        assert result.exit_price > 2636.0  # open + micro_slip
