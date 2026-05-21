"""
Fill model — THE critical module. Shared identically by backtest and live.

Rules (NON-NEGOTIABLE):
1. Longs fill at ASK + slippage, Shorts at BID - slippage
2. SL checked BEFORE TP each bar (pessimistic order)
3. TP requires candle CLOSE through level (not wick touch)
4. Slippage applied on SL fills (adverse)
5. Gap fills at gap price (worse than intended SL)
6. Break-even (Alpha-Sweep only): moves SL to entry+slip once at 50% TP
7. No phantom fills — if a level isn't traded through, no fill
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
) -> Optional[TradeResult]:
    """
    Walk bar-by-bar from bar_start+1, checking exits.

    df must have columns: bid_open, bid_high, bid_low, bid_close,
                          ask_open, ask_high, ask_low, ask_close

    Ported from generate_portfolio_dashboard.py execute_on_tf() lines 83-106.
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

            # SL CHECK FIRST (Rule #2)
            # Gap-through: open already below SL
            if bo <= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = bo - slip * 0.2
                pnl = exit_price - entry
                return TradeResult(pnl, bars_held, "sl", exit_price)

            # Normal SL hit: low touches SL
            if bl <= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = current_sl - slip * 0.2
                pnl = exit_price - entry
                return TradeResult(pnl, bars_held, "sl", exit_price)

            # Break-even check (Alpha-Sweep only)
            if use_break_even and bh >= entry + (tp - entry) * 0.5:
                current_sl = entry + _sl_slip(bar_range)

            # TP CHECK: requires CLOSE through level (Rule #3)
            if tp > 0 and bc >= tp:
                pnl = tp - entry
                return TradeResult(pnl, bars_held, "tp", tp)

        else:  # short
            ao = df["ask_open"].iat[b]
            ah = df["ask_high"].iat[b]
            ac = df["ask_close"].iat[b]
            al = df["ask_low"].iat[b]
            bar_range = ah - al

            # SL CHECK FIRST
            if ao >= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = ao + slip * 0.2
                pnl = entry - exit_price
                return TradeResult(pnl, bars_held, "sl", exit_price)

            if ah >= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = current_sl + slip * 0.2
                pnl = entry - exit_price
                return TradeResult(pnl, bars_held, "sl", exit_price)

            # Break-even for shorts
            if use_break_even and al <= entry - (entry - tp) * 0.5:
                current_sl = entry - _sl_slip(bar_range)

            # TP: requires CLOSE through level
            if tp > 0 and ac <= tp:
                pnl = entry - tp
                return TradeResult(pnl, bars_held, "tp", tp)

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
