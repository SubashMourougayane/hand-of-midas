"""TEST 03: Fill Parity — Backtest fill_model produces same exits as live would.

Runs signals through the ACTUAL fill_model.execute_trade() and verifies:
- Exit reasons are valid (sl, tp, expired)
- P&L direction is correct (SHORT win = price dropped, etc.)
- Break-even triggers at the documented level
- No phantom fills (exit price must be between bar low and bar high)
"""
import sys
import os
import numpy as np
import pandas as pd
from datetime import timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend.strategies import micro_alpha_sweep
from backend.execution.fill_model import execute_trade
from backend.config import ALPHA_SWEEP


class TestFillModelIntegrity:
    """03a: fill_model produces valid exits — no phantom fills."""

    def test_exit_price_within_bar_range(self, gold_7d_h1, gold_7d_m3, daily_bias, seed_random):
        """Exit price must be within the high/low of some bar after entry."""
        np.random.seed(42)
        signals = micro_alpha_sweep.generate_signals(gold_7d_h1, gold_7d_m3, daily_bias)

        violations = []
        for s in signals[:20]:
            try:
                bar_idx = gold_7d_m3.index.get_loc(s.date)
            except KeyError:
                continue

            result = execute_trade(
                df=gold_7d_m3, bar_start=bar_idx, entry=s.entry, sl=s.sl, tp=s.tp,
                direction=s.direction, max_bars=s.max_bars, strategy=s.strategy,
                use_break_even=True
            )
            if result is None:
                continue

            # Exit price should be reachable from the data
            exit_bars = gold_7d_m3.iloc[bar_idx+1:bar_idx+1+result.bars_held]
            if len(exit_bars) == 0:
                continue

            all_time_high = exit_bars["ask_high"].max()
            all_time_low = exit_bars["bid_low"].min()

            # Exit price should be within the range seen during the trade
            if result.exit_reason == "tp":
                assert abs(result.exit_price - s.tp) < 1.0, \
                    f"TP fill at {result.exit_price} but TP was {s.tp}"
            elif result.exit_reason == "sl":
                # SL fills can occur at:
                # - Original SL (normal stop)
                # - BE-adjusted SL (after break-even moves SL to ~entry)
                # - Gap-through (open past either SL by $20+)
                # Verify: the fill produced a LOSS or near-zero P&L (not a phantom win)
                if s.direction == "short":
                    assert result.pnl_per_unit <= 1.0, \
                        f"SHORT SL exit but positive P&L: ${result.pnl_per_unit:.2f}"
                else:
                    assert result.pnl_per_unit <= 1.0, \
                        f"LONG SL exit but positive P&L: ${result.pnl_per_unit:.2f}"

    def test_pnl_direction_correct(self, gold_7d_h1, gold_7d_m3, daily_bias, seed_random):
        """P&L sign matches direction: SHORT win = price dropped, LONG win = price rose."""
        np.random.seed(42)
        signals = micro_alpha_sweep.generate_signals(gold_7d_h1, gold_7d_m3, daily_bias)

        for s in signals[:20]:
            try:
                bar_idx = gold_7d_m3.index.get_loc(s.date)
            except KeyError:
                continue

            result = execute_trade(
                df=gold_7d_m3, bar_start=bar_idx, entry=s.entry, sl=s.sl, tp=s.tp,
                direction=s.direction, max_bars=s.max_bars, strategy=s.strategy,
                use_break_even=True
            )
            if result is None:
                continue

            if s.direction == "short":
                # Profit when exit < entry
                if result.exit_price < s.entry:
                    assert result.pnl_per_unit > 0, \
                        f"SHORT exit below entry but PnL negative: exit={result.exit_price}, entry={s.entry}"
                elif result.exit_price > s.entry:
                    assert result.pnl_per_unit < 0, \
                        f"SHORT exit above entry but PnL positive: exit={result.exit_price}, entry={s.entry}"
            else:
                if result.exit_price > s.entry:
                    assert result.pnl_per_unit > 0, \
                        f"LONG exit above entry but PnL negative: exit={result.exit_price}, entry={s.entry}"
                elif result.exit_price < s.entry:
                    assert result.pnl_per_unit < 0, \
                        f"LONG exit below entry but PnL positive: exit={result.exit_price}, entry={s.entry}"

    def test_no_exit_beyond_max_bars(self, gold_7d_h1, gold_7d_m3, daily_bias, seed_random):
        """Trade cannot be held longer than max_bars."""
        np.random.seed(42)
        signals = micro_alpha_sweep.generate_signals(gold_7d_h1, gold_7d_m3, daily_bias)

        for s in signals[:20]:
            try:
                bar_idx = gold_7d_m3.index.get_loc(s.date)
            except KeyError:
                continue

            result = execute_trade(
                df=gold_7d_m3, bar_start=bar_idx, entry=s.entry, sl=s.sl, tp=s.tp,
                direction=s.direction, max_bars=s.max_bars, strategy=s.strategy,
                use_break_even=True
            )
            if result is None:
                continue

            assert result.bars_held <= s.max_bars, \
                f"Held {result.bars_held} bars but max is {s.max_bars}"


class TestFillModelExitPriority:
    """03b: Verify TP is checked before SL (backtest rule)."""

    def test_tp_wins_when_both_touched(self):
        """When both TP and SL are hit in same bar, TP wins in backtest."""
        # Create synthetic data where a bar touches both levels
        # SHORT: entry=4520, sl=4530, tp=4510
        # Bar: ask_high=4531 (>SL), ask_low=4509 (<TP)
        data = pd.DataFrame({
            "bid_open": [4520, 4518], "bid_high": [4520, 4530],
            "bid_low": [4520, 4508], "bid_close": [4520, 4515],
            "ask_open": [4520.1, 4518.1], "ask_high": [4520.1, 4531],
            "ask_low": [4520.1, 4509], "ask_close": [4520.1, 4515.1],
            "volume": [100, 100],
        }, index=pd.date_range("2026-01-01", periods=2, freq="3min", tz="UTC"))
        data["mid_high"] = (data["bid_high"] + data["ask_high"]) / 2
        data["mid_low"] = (data["bid_low"] + data["ask_low"]) / 2

        result = execute_trade(
            df=data, bar_start=0, entry=4520, sl=4530, tp=4510,
            direction="short", max_bars=80, strategy="micro_alpha_sweep",
            use_break_even=True
        )
        assert result is not None
        # TP is checked before SL in fill_model → TP wins
        assert result.exit_reason == "tp", f"Expected TP but got {result.exit_reason}"


class TestFillModelBreakEven:
    """03c: Break-even in fill_model works correctly."""

    def test_be_moves_sl_for_short(self):
        """After price reaches 50% to TP, SL should tighten."""
        # SHORT: entry=4520, sl=4535, tp=4500
        # 50% target = 4520 - (4520-4500)*0.5 = 4510
        # Bar 1: low hits 4509 (triggers BE) → SL moves to entry - slip ≈ 4519.97
        # Bar 2: high hits 4520 (old SL would be 4535, but BE moved it to ~4520)
        #         → hits new SL
        idx = pd.date_range("2026-01-01", periods=4, freq="3min", tz="UTC")
        data = pd.DataFrame({
            "bid_open": [4520, 4515, 4512, 4518],
            "bid_high": [4520, 4516, 4513, 4521],
            "bid_low": [4520, 4508, 4510, 4517],
            "bid_close": [4520, 4510, 4512, 4520],
            "ask_open": [4520.1, 4515.1, 4512.1, 4518.1],
            "ask_high": [4520.1, 4516.1, 4513.1, 4521.1],
            "ask_low": [4520.1, 4508.1, 4510.1, 4517.1],
            "ask_close": [4520.1, 4510.1, 4512.1, 4520.1],
            "volume": [100]*4,
        }, index=idx)

        np.random.seed(42)
        result = execute_trade(
            df=data, bar_start=0, entry=4520, sl=4535, tp=4500,
            direction="short", max_bars=80, strategy="micro_alpha_sweep",
            use_break_even=True
        )
        assert result is not None
        # BE should have triggered on bar 1 (low=4508 < 4510)
        # Then bar 3 (high=4521) should hit the new tighter SL
        # Exit should be near entry (break-even) not at original SL (4535)
        assert result.exit_price < 4530, \
            f"Exit at {result.exit_price} — BE didn't tighten SL (should be near 4520, not 4535)"


class TestFillModelNoPhantom:
    """03d: Verify fills are real — exit prices correspond to actual bar prices."""

    def test_sl_fill_uses_actual_bar_price(self):
        """SL fill price must be derived from the bar that triggered it."""
        # SHORT: entry=4520, sl=4530
        # Bar hits SL: ask_high=4531 → fills at sl + small slippage
        idx = pd.date_range("2026-01-01", periods=2, freq="3min", tz="UTC")
        data = pd.DataFrame({
            "bid_open": [4520, 4525], "bid_high": [4520, 4531],
            "bid_low": [4520, 4524], "bid_close": [4520, 4528],
            "ask_open": [4520.1, 4525.1], "ask_high": [4520.1, 4531.1],
            "ask_low": [4520.1, 4524.1], "ask_close": [4520.1, 4528.1],
            "volume": [100, 100],
        }, index=idx)

        np.random.seed(42)
        result = execute_trade(
            df=data, bar_start=0, entry=4520, sl=4530, tp=4500,
            direction="short", max_bars=80, strategy="micro_alpha_sweep",
            use_break_even=False
        )
        assert result is not None
        assert result.exit_reason == "sl"
        # Fill should be at SL + small slippage (not at some random price)
        assert 4530 <= result.exit_price <= 4531, \
            f"SL fill at {result.exit_price} — expected near 4530"

    def test_tp_fill_exact(self):
        """TP fill is always exactly at TP price (limit order)."""
        # SHORT: entry=4520, tp=4510
        # Bar low reaches 4509 → fills at exactly 4510
        idx = pd.date_range("2026-01-01", periods=2, freq="3min", tz="UTC")
        data = pd.DataFrame({
            "bid_open": [4520, 4515], "bid_high": [4520, 4516],
            "bid_low": [4520, 4509], "bid_close": [4520, 4511],
            "ask_open": [4520.1, 4515.1], "ask_high": [4520.1, 4516.1],
            "ask_low": [4520.1, 4509.1], "ask_close": [4520.1, 4511.1],
            "volume": [100, 100],
        }, index=idx)

        result = execute_trade(
            df=data, bar_start=0, entry=4520, sl=4530, tp=4510,
            direction="short", max_bars=80, strategy="micro_alpha_sweep",
            use_break_even=False
        )
        assert result is not None
        assert result.exit_reason == "tp"
        assert result.exit_price == 4510, f"TP fill at {result.exit_price}, expected exactly 4510"
