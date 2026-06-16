"""Filter #27 — limit-order entry fill model unit tests.

Synthetic-fill sanity:
  1. M3 bar with bid_low <= limit_price ⇒ filled=True, entry == limit_price
  2. M3 bars with bid_low > limit_price for full TTL window ⇒ filled=False,
     exit_reason="missed_unfilled", would_have_won is bool (not None).
  3. limit_fill_strict requires both touch AND close beyond limit.
  4. Baseline equivalence: entry_mode="market" vs no kwarg ⇒ identical TradeResult.
"""
import sys
import os
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from backend.execution.fill_model import execute_trade, TradeResult


def make_bars(n, base=2620, volatility=5):
    """Synthetic OHLC. Same shape as test_fill_model.make_bars."""
    return pd.DataFrame({
        "bid_open":  [float(base)] * n,
        "bid_high":  [float(base + volatility)] * n,
        "bid_low":   [float(base - volatility)] * n,
        "bid_close": [float(base)] * n,
        "ask_open":  [float(base + 0.5)] * n,
        "ask_high":  [float(base + volatility + 0.5)] * n,
        "ask_low":   [float(base - volatility + 0.5)] * n,
        "ask_close": [float(base + 0.5)] * n,
    })


# ---- Sanity 1: limit fills when price visits the level ----

def test_limit_long_fill_on_touch():
    """LONG limit at 2618: bar 1 dips to 2617 → fills at limit."""
    df = make_bars(20, base=2620, volatility=1)
    # Bar 1: bid_low dips to 2617 (below limit 2618)
    df.at[1, "bid_low"] = 2617.0
    df.at[1, "bid_close"] = 2620.0  # close back at base
    # Bar 6: high reaches TP 2630 to give us a clean exit
    df.at[6, "bid_high"] = 2630.0

    result = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=False,
    )
    assert result.filled is True
    assert result.exit_reason == "tp"
    # exit_price is TP, but pnl_per_unit reflects entry at ~2618 (plus tiny slip)
    # so pnl_per_unit ≈ 2630 - 2618 = 12, much more than baseline 2630 - 2620 = 10.
    assert result.pnl_per_unit > 11.5  # filled at limit, not at signal.entry


def test_limit_short_fill_on_touch():
    """SHORT limit at 2622: bar 2 spikes to 2623 → fills at limit."""
    df = make_bars(20, base=2620, volatility=1)
    df.at[2, "ask_high"] = 2623.0
    df.at[2, "ask_close"] = 2620.5
    df.at[6, "ask_low"] = 2610.0  # SHORT TP

    result = execute_trade(
        df, bar_start=0, entry=2620.5, sl=2630.5, tp=2610.0,
        direction="short", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2622.0, limit_ttl_bars=5,
        limit_fill_strict=False,
    )
    assert result.filled is True
    assert result.exit_reason == "tp"
    # SHORT filled at 2622, exit at 2610 → pnl ~12 (vs baseline 2620.5-2610=10.5)
    assert result.pnl_per_unit > 11.5


# ---- Sanity 2: limit misses and reports would_have_won ----

def test_limit_miss_reports_would_have_won_winner():
    """LONG limit at 2618: price never dips → miss. Hypothetical limit fill
    would have caught TP, so would_have_won=True."""
    df = make_bars(20, base=2620, volatility=1)
    # No bar dips below 2619.5 in the TTL window
    # Bar 8 (after TTL of 5) reaches TP 2630
    df.at[8, "bid_high"] = 2630.0

    result = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=False,
    )
    assert result.filled is False
    assert result.exit_reason == "missed_unfilled"
    assert result.exit_price == 2618.0
    assert result.would_have_won is True
    assert result.pnl_per_unit == 0.0
    assert result.bars_held == 0


def test_limit_miss_reports_would_have_won_loser():
    """LONG limit at 2618: price never dips → miss. After TTL, price falls
    to SL → would_have_won=False."""
    df = make_bars(20, base=2620, volatility=1)
    # Bar 8 (post-TTL): low hits SL 2610
    df.at[8, "bid_low"] = 2609.0
    df.at[8, "bid_open"] = 2620.0  # avoid gap-through

    result = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=False,
    )
    assert result.filled is False
    assert result.would_have_won is False


# ---- Sanity 3: strict mode requires close beyond limit ----

def test_limit_strict_rejects_wick_only():
    """LONG limit at 2618: bar 1 wick to 2617 but close back at 2620.
    Loose mode fills; strict mode rejects."""
    df = make_bars(20, base=2620, volatility=1)
    df.at[1, "bid_low"] = 2617.0
    df.at[1, "bid_close"] = 2620.0  # closes ABOVE limit
    df.at[6, "bid_high"] = 2630.0

    # Loose: fills on wick touch
    loose = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=False,
    )
    assert loose.filled is True

    # Strict: same bar wick, but close above limit → does NOT fill
    strict = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=True,
    )
    assert strict.filled is False
    assert strict.exit_reason == "missed_unfilled"


def test_limit_strict_accepts_sustained_close():
    """LONG limit at 2618: bar 1 wick to 2617 AND closes at 2617.5 (below limit).
    Both loose and strict fill."""
    df = make_bars(20, base=2620, volatility=1)
    df.at[1, "bid_low"] = 2617.0
    df.at[1, "bid_close"] = 2617.5  # below limit
    df.at[6, "bid_high"] = 2630.0

    strict = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=True,
    )
    assert strict.filled is True
    assert strict.exit_reason == "tp"


# ---- Sanity 4: baseline equivalence ----

def test_baseline_default_kwargs_identical_to_market():
    """No-kwarg call must be byte-identical to entry_mode='market' explicit."""
    df = make_bars(50, base=2620, volatility=2)
    df.at[8, "bid_high"] = 2630.0  # TP

    np.random.seed(42)
    r_default = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
    )
    np.random.seed(42)
    r_explicit = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="market",
    )
    assert r_default.pnl_per_unit == r_explicit.pnl_per_unit
    assert r_default.exit_reason == r_explicit.exit_reason
    assert r_default.exit_price == r_explicit.exit_price
    assert r_default.bars_held == r_explicit.bars_held
    assert r_default.filled is True
    assert r_explicit.filled is True


# ---- Sanity 5: pessimistic ⊆ optimistic ----

def test_strict_fills_subset_of_loose_fills():
    """For the same bar pattern, every strict fill must also be a loose fill."""
    df = make_bars(20, base=2620, volatility=1)
    # Wick touch with sustained close (both should fill)
    df.at[1, "bid_low"] = 2617.0
    df.at[1, "bid_close"] = 2617.5
    df.at[6, "bid_high"] = 2630.0

    loose = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=False,
    )
    strict = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=True,
    )
    assert loose.filled is True
    assert strict.filled is True  # close is below limit too

    # Now modify so wick touches but close is above (strict should reject)
    df.at[1, "bid_close"] = 2620.0
    loose2 = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=False,
    )
    strict2 = execute_trade(
        df, bar_start=0, entry=2620.0, sl=2610.0, tp=2630.0,
        direction="long", max_bars=80, strategy="alpha_sweep",
        entry_mode="limit", limit_price=2618.0, limit_ttl_bars=5,
        limit_fill_strict=True,
    )
    assert loose2.filled is True
    assert strict2.filled is False  # wick only, close above limit
