"""
Fill model — THE critical module. Shared identically by backtest and live.

Rules:
1. Longs fill at ASK + slippage, Shorts at BID - slippage
2. SL gap-through checked first (open past SL = instant loss)
3. TP fills on touch (bar HIGH >= TP for longs, bar LOW <= TP for shorts) — matches OANDA instant fill
4. SL fills on touch (bar LOW <= SL for longs, bar HIGH >= SL for shorts)
5. If BOTH SL and TP touched in same bar (and no gap-through): TP wins — OANDA limit order fills first
6. Slippage applied on SL fills (adverse)
7. Gap fills at gap price (worse than intended SL)
8. Break-even (Alpha-Sweep only): moves SL to entry+slip once at 50% TP
9. No phantom fills — price must reach the level
"""
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class TradeResult:
    pnl_per_unit: float
    bars_held: int
    exit_reason: str  # 'sl', 'tp', 'expired', 'condition_exit'
    exit_price: float


def execute_trade(
    df,
    bar_start: int,
    entry: float,
    sl: float,
    tp: float,
    direction: str,
    max_bars: int,
    strategy: str,
    use_break_even: bool = False,
    be_trigger_pct: float = 0.5,
) -> Optional[TradeResult]:
    """
    Walk bar-by-bar from bar_start+1, checking exits.

    df must have columns: bid_open, bid_high, bid_low, bid_close,
                          ask_open, ask_high, ask_low, ask_close

    Order of checks per bar:
    1. Gap-through SL (open past SL) → instant SL fill at open
    2. TP touch (high >= TP for long, low <= TP for short) → fill at TP
    3. SL touch (low <= SL for long, high >= SL for short) → fill at SL
    4. Break-even update
    5. If neither hit → continue to next bar

    be_trigger_pct: fraction of distance to TP that triggers BE move.
      Default 0.5 (production behavior). Filter #5 tests 0.35.
    """
    current_sl = sl
    bars_held = 0

    for b in range(bar_start + 1, min(bar_start + max_bars, len(df))):
        bars_held += 1

        if direction == "long":
            bo = df["bid_open"].iat[b]
            bl = df["bid_low"].iat[b]
            bc = df["bid_close"].iat[b]
            bh = df["bid_high"].iat[b]
            bar_range = bh - bl

            # 1. Gap-through SL: open already below SL → instant loss
            if bo <= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = bo - slip * 0.2
                pnl = exit_price - entry
                return TradeResult(pnl, bars_held, "sl", exit_price)

            # 2. TP touch: bar high reaches TP → fill at TP (OANDA instant fill)
            if tp > 0 and bh >= tp:
                pnl = tp - entry
                return TradeResult(pnl, bars_held, "tp", tp)

            # 3. SL touch: bar low reaches SL
            if bl <= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = current_sl - slip * 0.2
                pnl = exit_price - entry
                return TradeResult(pnl, bars_held, "sl", exit_price)

            # 4. Break-even check (Alpha-Sweep only)
            if use_break_even and bh >= entry + (tp - entry) * be_trigger_pct:
                current_sl = entry + _sl_slip(bar_range)

        else:  # short
            ao = df["ask_open"].iat[b]
            ah = df["ask_high"].iat[b]
            ac = df["ask_close"].iat[b]
            al = df["ask_low"].iat[b]
            bar_range = ah - al

            # 1. Gap-through SL: open already above SL → instant loss
            if ao >= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = ao + slip * 0.2
                pnl = entry - exit_price
                return TradeResult(pnl, bars_held, "sl", exit_price)

            # 2. TP touch: bar low reaches TP → fill at TP
            if tp > 0 and al <= tp:
                pnl = entry - tp
                return TradeResult(pnl, bars_held, "tp", tp)

            # 3. SL touch: bar high reaches SL
            if ah >= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = current_sl + slip * 0.2
                pnl = entry - exit_price
                return TradeResult(pnl, bars_held, "sl", exit_price)

            # 4. Break-even for shorts
            if use_break_even and al <= entry - (entry - tp) * be_trigger_pct:
                current_sl = entry - _sl_slip(bar_range)

    # Max bars reached — exit at last bar close
    last_b = min(bar_start + max_bars - 1, len(df) - 1)
    if direction == "long":
        exit_price = df["bid_close"].iat[last_b]
        pnl = exit_price - entry
    else:
        exit_price = df["ask_close"].iat[last_b]
        pnl = entry - exit_price
    return TradeResult(pnl, bars_held, "expired", exit_price)


def _sl_slip(bar_range: float) -> float:
    """Slippage on SL fills — same formula as entry slippage."""
    return 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)
