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
    trail_after_be_pct: float = 0.0,
    partial_tp_at_pct: float = 0.0,
    partial_tp_size: float = 0.0,
    partial_arms_be: bool = False,
) -> Optional[TradeResult]:
    """
    Walk bar-by-bar from bar_start+1, checking exits.

    df must have columns: bid_open, bid_high, bid_low, bid_close,
                          ask_open, ask_high, ask_low, ask_close

    Order of checks per bar:
    0. Partial TP touch (Filter #7): bank fraction at halfway, remainder rides
    1. Gap-through SL (open past SL) → instant SL fill at open
    2. TP touch (high >= TP for long, low <= TP for short) → fill at TP
    3. SL touch (low <= SL for long, high >= SL for short) → fill at SL
    4. Break-even update (if not yet armed)
    5. After-BE trail update (high-water-mark, only ratchets up)
    6. If neither hit → continue to next bar

    be_trigger_pct: fraction of distance to TP that triggers BE move.
      Default 0.5 (production), Filter #5 ships 0.35 to 3 of 4 systems.
    trail_after_be_pct: fraction of best-favorable-excursion (since BE armed)
      to trail SL to. 0.0 (default) = no trail (legacy BE-only behavior).
      Filter #6 tests 0.5 (trail SL to 50% of high-water-mark from entry).
      High-water-mark semantics: SL only ratchets UP for longs / DOWN for shorts.
    partial_tp_at_pct: Filter #7. Fraction of distance to TP at which to bank
      partial profit. 0.0 = off (legacy single-leg). 0.5 = halfway.
    partial_tp_size: fraction of position to close at the partial level.
      0.0 = off. 0.5 = close half, let half ride.
      Reported pnl_per_unit is the size-weighted blend of both legs so
      downstream sizing/equity code is unchanged.
    partial_arms_be: Variant B. If True, partial TP firing also arms BE
      immediately (SL ratchets to entry+slip on the partial bar) regardless
      of be_trigger_pct. Variant A (False) keeps BE on its original schedule.
    """
    use_partial = (partial_tp_at_pct > 0 and partial_tp_size > 0)
    partial_target = entry + (tp - entry) * partial_tp_at_pct  # signed; works for both sides
    partial_done = False
    partial_pnl_per_unit = 0.0  # banked at the partial fill
    runner_size = 1.0 - partial_tp_size if use_partial else 1.0
    partial_size = partial_tp_size if use_partial else 0.0

    current_sl = sl
    bars_held = 0
    be_armed = False
    # High-water-mark since BE armed (longs: highest high; shorts: lowest low)
    hwm = entry

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
                runner_pnl = exit_price - entry
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                reason = "tp_partial+sl" if partial_done else "sl"
                return TradeResult(blended, bars_held, reason, exit_price)

            # 0. Partial TP touch (Filter #7): bank fraction at halfway, runner continues
            if use_partial and not partial_done and bh >= partial_target:
                partial_pnl_per_unit = partial_target - entry
                partial_done = True
                if partial_arms_be and not be_armed:
                    current_sl = entry + _sl_slip(bar_range)
                    be_armed = True
                    hwm = bh

            # 2. TP touch: bar high reaches TP → fill at TP (OANDA instant fill)
            if tp > 0 and bh >= tp:
                runner_pnl = tp - entry
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                reason = "tp_partial+tp" if partial_done else "tp"
                return TradeResult(blended, bars_held, reason, tp)

            # 3. SL touch: bar low reaches SL
            if bl <= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = current_sl - slip * 0.2
                runner_pnl = exit_price - entry
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                reason = "tp_partial+sl" if partial_done else "sl"
                return TradeResult(blended, bars_held, reason, exit_price)

            # 4. Break-even check (Alpha-Sweep only) — fires once
            if use_break_even and not be_armed and bh >= entry + (tp - entry) * be_trigger_pct:
                current_sl = entry + _sl_slip(bar_range)
                be_armed = True
                # Initialize HWM at the BE trigger bar's high
                hwm = bh

            # 5. After-BE trail: ratchet SL up using high-water-mark of bar high
            if be_armed and trail_after_be_pct > 0:
                if bh > hwm:
                    hwm = bh
                # Proposed trail SL: entry + (hwm - entry) × trail_pct
                # Only move SL UP (high-water-mark semantics)
                proposed_sl = entry + (hwm - entry) * trail_after_be_pct
                if proposed_sl > current_sl:
                    current_sl = proposed_sl

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
                runner_pnl = entry - exit_price
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                reason = "tp_partial+sl" if partial_done else "sl"
                return TradeResult(blended, bars_held, reason, exit_price)

            # 0. Partial TP touch (Filter #7): bank fraction at halfway
            if use_partial and not partial_done and al <= partial_target:
                partial_pnl_per_unit = entry - partial_target
                partial_done = True
                if partial_arms_be and not be_armed:
                    current_sl = entry - _sl_slip(bar_range)
                    be_armed = True
                    hwm = al

            # 2. TP touch: bar low reaches TP → fill at TP
            if tp > 0 and al <= tp:
                runner_pnl = entry - tp
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                reason = "tp_partial+tp" if partial_done else "tp"
                return TradeResult(blended, bars_held, reason, tp)

            # 3. SL touch: bar high reaches SL
            if ah >= current_sl:
                slip = _sl_slip(bar_range)
                exit_price = current_sl + slip * 0.2
                runner_pnl = entry - exit_price
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                reason = "tp_partial+sl" if partial_done else "sl"
                return TradeResult(blended, bars_held, reason, exit_price)

            # 4. Break-even for shorts — fires once
            if use_break_even and not be_armed and al <= entry - (entry - tp) * be_trigger_pct:
                current_sl = entry - _sl_slip(bar_range)
                be_armed = True
                hwm = al  # for shorts, "favorable" means lower lows

            # 5. After-BE trail (shorts): ratchet SL DOWN using low-water-mark of bar low
            if be_armed and trail_after_be_pct > 0:
                if al < hwm:
                    hwm = al
                # Proposed trail SL: entry - (entry - hwm) × trail_pct
                # Only move SL DOWN (matches longs' "ratchet only in favorable direction")
                proposed_sl = entry - (entry - hwm) * trail_after_be_pct
                if proposed_sl < current_sl:
                    current_sl = proposed_sl

    # Max bars reached — exit at last bar close
    last_b = min(bar_start + max_bars - 1, len(df) - 1)
    if direction == "long":
        exit_price = df["bid_close"].iat[last_b]
        runner_pnl = exit_price - entry
    else:
        exit_price = df["ask_close"].iat[last_b]
        runner_pnl = entry - exit_price
    blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
    reason = "tp_partial+expired" if partial_done else "expired"
    return TradeResult(blended, bars_held, reason, exit_price)


def _sl_slip(bar_range: float) -> float:
    """Slippage on SL fills — same formula as entry slippage."""
    return 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)
