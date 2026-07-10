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


def _partial_tp_check(trade: OpenTrade, bar: Bar, partial_tp_fail_pct: float = 0.0) -> bool:
    """If partial-TP configured and MFE crossed trigger, lock partial profit + move SL to BE.

    Pure mutation on `trade`. Idempotent (skips if already taken). No peek.
    Returns True iff the partial just fired on this call (caller can react).

    P2d: partial_tp_fail_pct models live broker modify-fail. Deterministic hash of
    (tag, partial_fill_ts) → if in fail bucket, partial is STILL banked but SL is
    NOT moved to BE (remainder stays exposed at original SL — worst case). Matches
    the live PARTIAL_TP_MODIFY_FAILED path minus safe-close.
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
    # P2d: deterministic modify-fail — skip SL→BE move for this fraction.
    if partial_tp_fail_pct > 0:
        key = f"{trade.order.tag}|{trade.trade_id}"
        if (hash(key) % 10000) < int(partial_tp_fail_pct * 10000):
            return True  # partial banked, but SL NOT moved (remainder exposed)
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
    sl_slip_pips: float = 0.0,
    tp_slip_pips: float = 0.0,
    swap_per_lot_per_night: dict[int, float] | None = None,
    bar_gap_seconds: float = 0.0,
    gap_threshold_seconds: float = 0.0,
    gap_extra_slip_pips: float = 0.0,
    partial_tp_fail_pct: float = 0.0,
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

    # Per-trade hold cap override: strategies can set order.extra["max_hold_bars"]
    # to override the engine-level max_bars_held. Necessary in composite
    # runners where legs have different max_hold_h (e.g. A=12h D=24h under
    # ONE engine loop that can only pass a single cap through EngineDeps).
    trade_extra = trade.order.extra or {}
    trade_cap = trade_extra.get("max_hold_bars")
    effective_cap = int(trade_cap) if trade_cap is not None else max_bars_held

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

    # Overnight swap (P1b): if bar.timestamp is at 22:00 UTC broker rollover
    # AND trade was open at that instant, deduct swap. Deterministic — depends
    # only on bar.timestamp hour + trade.side + trade.fill.qty. No forward peek.
    # swap_per_lot_per_night: {+1: long_swap_$, -1: short_swap_$}. Negative = cost.
    if swap_per_lot_per_night is not None and bar.timestamp.hour == 22:
        swap_per_lot = float(swap_per_lot_per_night.get(side, 0.0))
        # Convert to R: swap_$ / (qty × contract × risk_units × qty) — wait, this
        # collapses. Store swap_r on trade for aggregation at close.
        if trade.risk_units > 0 and abs(swap_per_lot) > 0:
            qty_lots = float(trade.fill.qty)
            # Assume XAU contract 100 oz. Swap R = (qty × swap_per_lot) / (qty × contract × risk)
            # = swap_per_lot / (contract × risk)
            contract_units = 100.0  # XAU; generalize per-symbol if needed
            swap_r = swap_per_lot / (contract_units * trade.risk_units)
            trade.accrued_swap_r = float(getattr(trade, "accrued_swap_r", 0.0)) + swap_r

    # Partial-TP safety net: must run AFTER MFE update, BEFORE exit checks.
    partial_just_fired = _partial_tp_check(trade, bar, partial_tp_fail_pct=partial_tp_fail_pct)
    if partial_just_fired and on_partial_tp is not None:
        on_partial_tp(trade, bar)

    partial = trade.partial_filled_r  # locked-in R from earlier partial close (0 if none)
    swap_r = float(getattr(trade, "accrued_swap_r", 0.0))  # negative = cost
    stop_is_be = trade.partial_taken and trade.stop_price == trade.entry_price

    # Exit detection. Default = CLOSE-based (baseline, A+D). Opt-in WICK mode
    # (order.extra["bracket_wick"]) hits SL/TP on the bar's intrabar high/low —
    # matching a hard server-side SL/TP (MT5 executes intrabar) and the COBRAX
    # research engine (bracket="wick"). A+D never set the flag → unchanged.
    wick = bool(trade_extra.get("bracket_wick"))
    lo_px = bar.low if wick else close
    hi_px = bar.high if wick else close
    hit_stop = (side > 0 and lo_px <= trade.stop_price) or (side < 0 and hi_px >= trade.stop_price)
    hit_tp = (
        trade.take_profit is not None
        and (
            (side > 0 and hi_px >= trade.take_profit)
            or (side < 0 and lo_px <= trade.take_profit)
        )
    )

    if hit_stop:
        # Research convention:
        # - SL at original stop → -1.0 R on remaining position
        # - SL at BE (moved by partial-TP) → 0.0 R on remaining position
        # Optional SL slip (P1a): fill BEYOND stop_price by sl_slip_pips (worse).
        # Long: exit_price = stop − slip. Short: exit_price = stop + slip.
        # Deterministic: no forward-bar peek, no random. Applied on close-based hit only.
        # P2a: if THIS bar followed a gap (weekend/session), add extra gap slip on SL.
        # Deterministic — bar_gap_seconds computed by engine from consecutive timestamps.
        effective_sl_slip = abs(sl_slip_pips)
        if (gap_threshold_seconds > 0 and bar_gap_seconds > gap_threshold_seconds
                and gap_extra_slip_pips > 0):
            effective_sl_slip += abs(gap_extra_slip_pips)
        sl_exit_price = trade.stop_price - side * effective_sl_slip if effective_sl_slip else trade.stop_price
        if trade.risk_units > 0 and effective_sl_slip:
            sl_r_on_remainder = (sl_exit_price - trade.entry_price) * side / trade.risk_units
        else:
            sl_r_on_remainder = 0.0 if stop_is_be else -1.0
        outcome_r = sl_r_on_remainder + partial + swap_r
        return BracketOutcome(
            exit_timestamp=bar.timestamp,
            exit_price=sl_exit_price,
            reason="SL_BE" if stop_is_be else "SL",
            bars_held=trade.bars_held,
            bracket_1r_outcome=outcome_r,
            event_type="EXIT_SL",
            detail={
                "close": close,
                "stop_price": trade.stop_price,
                "sl_slip_pips": sl_slip_pips,
                "partial_r": partial,
                "stop_is_be": stop_is_be,
            },
        )

    if hit_tp:
        # Research convention: TP fires → outcome capped to exact tp_R.
        # Optional TP slip (P1a): fill BELOW tp_price by tp_slip_pips (worse).
        # Long: exit = tp − slip. Short: exit = tp + slip.
        tp_exit_price = trade.take_profit - side * abs(tp_slip_pips) if tp_slip_pips else trade.take_profit
        tp_r = (
            (tp_exit_price - trade.entry_price) * side / trade.risk_units
            if trade.risk_units > 0 else 0.0
        )
        outcome_r = tp_r + partial + swap_r
        return BracketOutcome(
            exit_timestamp=bar.timestamp,
            exit_price=tp_exit_price,
            reason="TP",
            bars_held=trade.bars_held,
            bracket_1r_outcome=outcome_r,
            event_type="EXIT_TP",
            detail={
                "close": close,
                "take_profit": trade.take_profit,
                "tp_slip_pips": tp_slip_pips,
                "partial_r": partial,
            },
        )

    if effective_cap is not None and trade.bars_held >= effective_cap:
        timeout_r = (close - trade.entry_price) * side / trade.risk_units if trade.risk_units > 0 else 0.0
        outcome_r = timeout_r + partial + swap_r
        return BracketOutcome(
            exit_timestamp=bar.timestamp,
            exit_price=close,
            reason="TIMEOUT",
            bars_held=trade.bars_held,
            bracket_1r_outcome=outcome_r,
            event_type="EXIT_TIMEOUT",
            detail={
                "close": close,
                "max_bars_held": effective_cap,
                "partial_r": partial,
            },
        )

    return None
