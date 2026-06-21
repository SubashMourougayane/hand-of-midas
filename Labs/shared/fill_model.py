"""Canonical fill model for Labs.

THIS IS THE ONE FILL MODEL. Every Labs strategy uses it. No exceptions.
If a strategy needs different exit semantics (e.g. trailing stop), it
adds them as POST-fill modifications, not as alternative fills.

Behaviour mirrors `backend/execution/fill_model.py:execute_trade()` after
the A0 fix. Copied here as a local file so Labs has zero production
imports.

Rules (from production):
1. LONG entries fill at ASK + slippage; SHORT at BID − slippage.
   For Labs simplicity we accept signal.entry as-is — the strategy is
   responsible for computing entry net of slippage if it wants.
2. SL gap-through (open past SL) → instant exit at adverse open price.
3. TP fills on touch (high ≥ TP for LONG, low ≤ TP for SHORT). No slip.
4. SL fills on touch (low ≤ SL for LONG, high ≥ SL for SHORT). With slip.
5. If both SL and TP touched in same bar with no gap-through: TP wins.
6. Slippage applied on SL fills only (adverse).
7. No phantom fills — price must reach the level.
8. Max-bars max hold → exit at bar's close.

Slippage formula (deterministic — no RNG, parity with Filter #11):
    slip = 0.0325 + bar_range × 0.01

This matches production `slippage()` in backend-oil-micro/config.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


Direction = Literal["long", "short"]
ExitReason = Literal["TP", "SL", "GAP_SL", "MAX_HOLD"]


@dataclass(frozen=True)
class TradeResult:
    """Filled-trade outcome. Pure data. No side effects."""
    entry: float
    exit_price: float
    pnl_per_unit: float
    exit_reason: ExitReason
    bars_held: int
    entry_bar_idx: int
    exit_bar_idx: int


def slippage(bar_range: float, base: float = 0.0325, range_coef: float = 0.01) -> float:
    """Deterministic adverse slippage on SL fills.

    Matches `backend-oil-micro/config.py:slippage()` (Filter #11, 2026-06-12)
    when called with default base=0.0325. Calibrated for oil/gold price scales.

    For forex, pass base=0.00005 (0.5 pip baseline). Leaving the range
    coefficient unchanged keeps the "wider bars = more slippage" shape;
    bar_range on forex is small enough (~0.001) that range_coef × range
    contributes 1 pip in the worst case.

    No RNG so BTs are reproducible.
    """
    return base + max(0.0, bar_range) * range_coef


def execute_trade(
    df: pd.DataFrame,
    bar_start: int,
    entry: float,
    sl: float,
    tp: float,
    direction: Direction,
    max_bars: int,
    slip_base: float = 0.0325,
    slip_range_coef: float = 0.01,
) -> TradeResult | None:
    """Walk M3 bars from bar_start+1 through bar_start+max_bars.

    Returns TradeResult or None if df runs out before max_bars and no
    exit fired (caller decides what None means).

    df MUST have bid_*/ask_*/mid_* columns. We use:
    - LONG: bid_high for TP touch (TP from below), bid_low for SL touch
            (SL from above), bid_open for gap detect, bid_close for max-hold
    - SHORT: ask_low for TP, ask_high for SL, ask_open for gap, ask_close
             for max-hold
    """
    n = len(df)

    for offset in range(1, max_bars + 1):
        idx = bar_start + offset
        if idx >= n:
            return None  # data ran out; caller logs a "missing" trade
        bar = df.iloc[idx]

        if direction == "long":
            bo = float(bar["bid_open"])
            bh = float(bar["bid_high"])
            bl = float(bar["bid_low"])
            bc = float(bar["bid_close"])
            bar_range = bh - bl

            # 1. Gap-through SL — open already past SL
            if bo <= sl:
                slip = slippage(bar_range, slip_base, slip_range_coef)
                exit_px = bo - slip
                pnl = exit_px - entry
                return TradeResult(entry, exit_px, pnl, "GAP_SL", offset, bar_start, idx)

            # 2. TP touch — checked BEFORE SL touch when both occur intra-bar
            if bh >= tp:
                pnl = tp - entry
                return TradeResult(entry, tp, pnl, "TP", offset, bar_start, idx)

            # 3. SL touch
            if bl <= sl:
                slip = slippage(bar_range, slip_base, slip_range_coef)
                exit_px = sl - slip
                pnl = exit_px - entry
                return TradeResult(entry, exit_px, pnl, "SL", offset, bar_start, idx)

        else:  # short
            ao = float(bar["ask_open"])
            ah = float(bar["ask_high"])
            al = float(bar["ask_low"])
            ac = float(bar["ask_close"])
            bar_range = ah - al

            if ao >= sl:
                slip = slippage(bar_range, slip_base, slip_range_coef)
                exit_px = ao + slip
                pnl = entry - exit_px
                return TradeResult(entry, exit_px, pnl, "GAP_SL", offset, bar_start, idx)

            if al <= tp:
                pnl = entry - tp
                return TradeResult(entry, tp, pnl, "TP", offset, bar_start, idx)

            if ah >= sl:
                slip = slippage(bar_range, slip_base, slip_range_coef)
                exit_px = sl + slip
                pnl = entry - exit_px
                return TradeResult(entry, exit_px, pnl, "SL", offset, bar_start, idx)

    # Max bars reached → exit at the close of the max-hold bar
    last_idx = min(bar_start + max_bars, n - 1)
    last_bar = df.iloc[last_idx]
    if direction == "long":
        exit_px = float(last_bar["bid_close"])
        pnl = exit_px - entry
    else:
        exit_px = float(last_bar["ask_close"])
        pnl = entry - exit_px
    return TradeResult(entry, exit_px, pnl, "MAX_HOLD", max_bars, bar_start, last_idx)


# ── Self-test: minimal sanity checks ─────────────────────────────────────


def _self_test() -> None:
    """Asserts the fill model behaves on hand-crafted bars. Run via:
        python -m Labs.shared.fill_model
    """
    import pandas as pd

    # 3 bars after entry. LONG entry @ 100, SL=99, TP=102.
    bars = pd.DataFrame({
        "bid_open":  [100.0, 100.5, 101.5, 102.5],
        "bid_high":  [100.5, 101.5, 102.5, 103.0],
        "bid_low":   [ 99.5, 100.0, 101.0, 101.5],
        "bid_close": [100.5, 101.5, 102.0, 102.5],
        "ask_open":  [100.05, 100.55, 101.55, 102.55],
        "ask_high":  [100.55, 101.55, 102.55, 103.05],
        "ask_low":   [ 99.55, 100.05, 101.05, 101.55],
        "ask_close": [100.55, 101.55, 102.05, 102.55],
    })
    r = execute_trade(bars, bar_start=0, entry=100.0, sl=99.0, tp=102.0,
                      direction="long", max_bars=10)
    assert r is not None
    assert r.exit_reason == "TP", f"expected TP, got {r.exit_reason}"
    assert r.exit_price == 102.0
    assert r.pnl_per_unit == 2.0
    print(f"  ✓ LONG TP fill: {r}")

    # LONG SL hit on bar 1 (low = 99.5 already nope, set lower)
    bars2 = bars.copy()
    bars2["bid_low"] = [99.5, 98.5, 99.0, 99.0]
    r = execute_trade(bars2, bar_start=0, entry=100.0, sl=99.0, tp=102.0,
                      direction="long", max_bars=10)
    assert r is not None
    assert r.exit_reason == "SL", f"expected SL, got {r.exit_reason}"
    assert r.exit_price < 99.0, "SL fill must include adverse slippage"
    print(f"  ✓ LONG SL with slip: {r}")

    # Gap-through SL on bar 1 (open already below SL)
    bars3 = bars.copy()
    bars3["bid_open"] = [100.0, 98.0, 100.0, 100.0]
    bars3["bid_low"] = [99.5, 97.5, 99.0, 99.0]
    r = execute_trade(bars3, bar_start=0, entry=100.0, sl=99.0, tp=102.0,
                      direction="long", max_bars=10)
    assert r is not None
    assert r.exit_reason == "GAP_SL", f"expected GAP_SL, got {r.exit_reason}"
    assert r.exit_price < 98.0, "GAP fill must be at adverse open"
    print(f"  ✓ LONG GAP_SL: {r}")

    # SHORT TP
    bars4 = pd.DataFrame({
        "bid_open":  [100.0, 99.5, 98.5, 97.5],
        "bid_high":  [100.5, 100.0, 99.0,  98.0],
        "bid_low":   [ 99.5,  98.5, 97.5,  96.5],
        "bid_close": [ 99.5,  98.5, 97.5,  97.0],
        "ask_open":  [100.05, 99.55, 98.55, 97.55],
        "ask_high":  [100.55, 100.05, 99.05, 98.05],
        "ask_low":   [ 99.55, 98.55, 97.55, 96.55],
        "ask_close": [ 99.55, 98.55, 97.55, 97.05],
    })
    r = execute_trade(bars4, bar_start=0, entry=100.0, sl=101.0, tp=98.0,
                      direction="short", max_bars=10)
    assert r is not None
    assert r.exit_reason == "TP"
    assert r.exit_price == 98.0
    assert r.pnl_per_unit == 2.0
    print(f"  ✓ SHORT TP: {r}")

    # MAX_HOLD
    bars5 = pd.DataFrame({
        "bid_open":  [100.0, 100.0, 100.0, 100.0, 100.0],
        "bid_high":  [100.5, 100.5, 100.5, 100.5, 100.5],
        "bid_low":   [ 99.5,  99.5,  99.5,  99.5,  99.5],
        "bid_close": [100.0, 100.0, 100.0, 100.0, 100.0],
        "ask_open":  [100.05] * 5,
        "ask_high":  [100.55] * 5,
        "ask_low":   [ 99.55] * 5,
        "ask_close": [100.05] * 5,
    })
    r = execute_trade(bars5, bar_start=0, entry=100.0, sl=98.0, tp=103.0,
                      direction="long", max_bars=3)
    assert r is not None
    assert r.exit_reason == "MAX_HOLD"
    assert r.bars_held == 3
    print(f"  ✓ MAX_HOLD: {r}")

    print()
    print("All fill-model self-tests pass.")


if __name__ == "__main__":
    _self_test()
