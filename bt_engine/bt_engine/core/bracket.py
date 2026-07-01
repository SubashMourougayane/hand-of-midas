"""walk_bracket_on_bar — shared close-based exit logic for BT and live.

Default semantics (matches research-baseline trade_manager._simulate_close_based_bracket):
- Stop hit when bar.close crosses against the trade beyond stop_price.
- Take-profit hit when bar.close crosses past take_profit.
- For LONG: stop = close <= stop_price; tp = close >= take_profit.
- For SHORT: stop = close >= stop_price; tp = close <= take_profit.
- If both fire on the same bar, stop takes precedence (worst-case for trader).
- Optional max_bars_held => EXIT_TIMEOUT.

Optional partial-TP safety net (matches research/fib_retrace/safety_net_sweep.simulate_with_safety):
- If trade.order.extra["partial_tp_at_r"] is set:
    * On every bar, after MFE update, if not partial_taken AND mfe_r >= partial_tp_at_r:
        - Lock partial_tp_pct * partial_tp_at_r R as partial_filled_r.
        - Move trade.stop_price to entry_price (breakeven on remainder).
        - Mark partial_taken = True.
    * On subsequent SL hit at active_stop == entry → outcome = 0.0 + partial_filled_r.
    * On TP / SL / TIMEOUT → outcome += partial_filled_r at end.
- Causality: all logic uses bar.high/low/close of the CLOSED bar. No peek.
"""
from __future__ import annotations

from typing import Callable

from .bar import Bar
from .order import BracketOutcome, OpenTrade


def _partial_tp_check(trade: OpenTrade, bar: Bar) -> bool:
    """If partial-TP configured and MFE crossed trigger, lock partial profit + move SL to BE.

    Pure mutation on `trade`. Idempotent (skips if already taken). No peek.
    Returns True iff the partial just fired on this call (caller can react).
    """
    if trade.partial_taken:
        return False
    extra = trade.order.extra or {}
    trigger = extra.get("partial_tp_at_r")
    if trigger is None:
        return False
    if trade.risk_units <= 0:
        return False
    if trade.mfe_r < trigger:
        return False

    pct = float(extra.get("partial_tp_pct", 0.5))
    trade.partial_taken = True
    trade.partial_filled_r = pct * float(trigger)
    # Partial fill price = exact +trigger R level (research convention).
    # Long: entry + trigger * risk_units; Short: entry - trigger * risk_units.
    trade.partial_fill_price = trade.entry_price + trade.side * float(trigger) * trade.risk_units
    trade.partial_fill_timestamp = bar.timestamp
    # Move active stop to BE on remainder. Never loosen.
    if trade.side > 0:
        trade.stop_price = max(trade.stop_price, trade.entry_price)
    else:
        trade.stop_price = min(trade.stop_price, trade.entry_price)
    return True


def walk_bracket_on_bar(
    trade: OpenTrade,
    bar: Bar,
    *,
    max_bars_held: int | None = None,
    on_partial_tp: "Callable[[OpenTrade, Bar], None] | None" = None,
) -> BracketOutcome | None:
    """Return outcome if bar closes the trade, else None.

    on_partial_tp fires ONCE — the bar the partial trigger crosses. Callers use it
    to notify the broker (send CLOSE_PARTIAL + MODIFY sl=BE). The walker's own
    state is already updated before the callback runs, so the callback sees the
    post-partial trade (partial_taken=True, stop_price=entry).
    """
    trade.bars_held += 1
    side = trade.side
    close = bar.close

    # update intra-bar MFE/MAE in R
    if trade.risk_units > 0:
        if side > 0:
            mfe = (bar.high - trade.entry_price) / trade.risk_units
            mae = (bar.low - trade.entry_price) / trade.risk_units
        else:
            mfe = (trade.entry_price - bar.low) / trade.risk_units
            mae = (trade.entry_price - bar.high) / trade.risk_units
        trade.mfe_r = max(trade.mfe_r, mfe)
        trade.mae_r = min(trade.mae_r, mae)

    # Partial-TP safety net: must run AFTER MFE update, BEFORE exit checks.
    partial_just_fired = _partial_tp_check(trade, bar)
    if partial_just_fired and on_partial_tp is not None:
        on_partial_tp(trade, bar)

    partial = trade.partial_filled_r  # locked-in R from earlier partial close (0 if none)
    stop_is_be = trade.partial_taken and trade.stop_price == trade.entry_price

    # stop hit (close-based, baseline semantics)
    hit_stop = (side > 0 and close <= trade.stop_price) or (side < 0 and close >= trade.stop_price)
    hit_tp = (
        trade.take_profit is not None
        and (
            (side > 0 and close >= trade.take_profit)
            or (side < 0 and close <= trade.take_profit)
        )
    )

    if hit_stop:
        # Research convention:
        # - SL at original stop → -1.0 R on remaining position
        # - SL at BE (moved by partial-TP) → 0.0 R on remaining position
        sl_r_on_remainder = 0.0 if stop_is_be else -1.0
        outcome_r = sl_r_on_remainder + partial
        return BracketOutcome(
            exit_timestamp=bar.timestamp,
            exit_price=trade.stop_price,
            reason="SL_BE" if stop_is_be else "SL",
            bars_held=trade.bars_held,
            bracket_1r_outcome=outcome_r,
            event_type="EXIT_SL",
            detail={
                "close": close,
                "stop_price": trade.stop_price,
                "partial_r": partial,
                "stop_is_be": stop_is_be,
            },
        )

    if hit_tp:
        # Research convention: TP fires → outcome capped to exact tp_R
        # ((tp_price - entry_price) * side / risk_units) + partial.
        tp_r = (
            (trade.take_profit - trade.entry_price) * side / trade.risk_units
            if trade.risk_units > 0 else 0.0
        )
        outcome_r = tp_r + partial
        return BracketOutcome(
            exit_timestamp=bar.timestamp,
            exit_price=trade.take_profit,
            reason="TP",
            bars_held=trade.bars_held,
            bracket_1r_outcome=outcome_r,
            event_type="EXIT_TP",
            detail={
                "close": close,
                "take_profit": trade.take_profit,
                "partial_r": partial,
            },
        )

    if max_bars_held is not None and trade.bars_held >= max_bars_held:
        timeout_r = (close - trade.entry_price) * side / trade.risk_units if trade.risk_units > 0 else 0.0
        outcome_r = timeout_r + partial
        return BracketOutcome(
            exit_timestamp=bar.timestamp,
            exit_price=close,
            reason="TIMEOUT",
            bars_held=trade.bars_held,
            bracket_1r_outcome=outcome_r,
            event_type="EXIT_TIMEOUT",
            detail={
                "close": close,
                "max_bars_held": max_bars_held,
                "partial_r": partial,
            },
        )

    return None
