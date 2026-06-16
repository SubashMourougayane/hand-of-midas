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
    exit_reason: str  # 'sl', 'tp', 'expired', 'condition_exit', 'missed_unfilled'
    exit_price: float
    filled: bool = True
    would_have_won: Optional[bool] = None  # Filter #27 informational lookahead — None when filled


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
    entry_mode: str = "market",
    limit_price: Optional[float] = None,
    limit_ttl_bars: int = 0,
    limit_fill_strict: bool = False,
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

    entry_mode: Filter #27. "market" (default) is byte-identical to legacy
      behavior — entry passed in is used as-is. "limit" walks bar_start+1
      through bar_start+limit_ttl_bars looking for a fill at limit_price.
    limit_price: target price for the limit order (ignored if entry_mode=market).
      LONG fills when bid_low <= limit_price; SHORT fills when ask_high >= limit_price.
    limit_ttl_bars: how many M3 bars after the engulfing bar the limit lives.
      1 / 2 / 5 = 3min / 6min / 15min. 0 = market.
    limit_fill_strict: when True, additionally requires the bar's close to be
      beyond the limit (LONG: bid_close <= limit_price; SHORT: ask_close >= limit_price).
      Pessimistic mode — addresses the M3-wick parity tax (1-second touches that
      a real broker can't fill). When False, any wick touch counts.

    Filter #27 miss return: TradeResult(0.0, 0, "missed_unfilled", limit_price,
      filled=False, would_have_won=<bool>). would_have_won is INFORMATIONAL
      LOOKAHEAD — must NEVER be used in ship-decision ranking. It runs the
      exit-walk hypothetically with entry=limit_price starting at the bar
      after TTL expiry, and reports whether that simulated trade would have
      profited. Use only for slicing/diagnostics in the runner, never as a
      ranking signal.
    """
    # Filter #27: limit-order entry pre-walk. On fill, mutate entry/bar_start
    # and fall through to legacy exit logic. On miss, return synthetic result.
    if entry_mode == "limit" and limit_ttl_bars > 0 and limit_price is not None:
        fill_bar_idx = None
        ttl_end = min(bar_start + limit_ttl_bars, len(df) - 1)
        for fb in range(bar_start + 1, ttl_end + 1):
            if direction == "long":
                bid_low = df["bid_low"].iat[fb]
                bid_close = df["bid_close"].iat[fb]
                touched = bid_low <= limit_price
                sustained = bid_close <= limit_price
            else:
                ask_high = df["ask_high"].iat[fb]
                ask_close = df["ask_close"].iat[fb]
                touched = ask_high >= limit_price
                sustained = ask_close >= limit_price
            fill_ok = touched and (sustained if limit_fill_strict else True)
            if fill_ok:
                fill_bar_idx = fb
                break
        if fill_bar_idx is None:
            # TTL expired without fill. Compute would_have_won (lookahead) by
            # running the exit-walk hypothetically starting at the bar after
            # TTL with entry=limit_price. NEVER use this in ship ranking.
            wwl_pnl = _hypothetical_exit_walk(
                df, ttl_end, limit_price, sl, tp, direction, max_bars,
                use_break_even, be_trigger_pct, trail_after_be_pct,
                partial_tp_at_pct, partial_tp_size, partial_arms_be,
            )
            return TradeResult(
                pnl_per_unit=0.0,
                bars_held=0,
                exit_reason="missed_unfilled",
                exit_price=limit_price,
                filled=False,
                would_have_won=bool(wwl_pnl > 0) if wwl_pnl is not None else False,
            )
        # Filled. Apply slippage on the fill bar's range so parity-tax
        # accounting is symmetric with market-order baseline.
        if direction == "long":
            br_fill = df["bid_high"].iat[fill_bar_idx] - df["bid_low"].iat[fill_bar_idx]
            entry = limit_price + _sl_slip(br_fill) * 0.2  # LONG pays slip up
        else:
            br_fill = df["ask_high"].iat[fill_bar_idx] - df["ask_low"].iat[fill_bar_idx]
            entry = limit_price - _sl_slip(br_fill) * 0.2  # SHORT pays slip down
        bar_start = fill_bar_idx  # legacy walk continues from here

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


def _hypothetical_exit_walk(
    df, bar_start: int, entry: float, sl: float, tp: float,
    direction: str, max_bars: int,
    use_break_even: bool, be_trigger_pct: float, trail_after_be_pct: float,
    partial_tp_at_pct: float, partial_tp_size: float, partial_arms_be: bool,
) -> Optional[float]:
    """Filter #27 informational lookahead. Runs the same exit logic as
    execute_trade() but returns only pnl_per_unit (or None on no-data).
    Used to compute would_have_won for missed limit orders. NEVER use the
    output for ship-decision ranking — it's lookahead by definition.

    Implemented as a delegating call to execute_trade() with entry_mode="market"
    so the logic stays in one place. Suppresses NumPy random state side
    effects by snapshotting + restoring.
    """
    rng_state = np.random.get_state()
    try:
        result = execute_trade(
            df=df, bar_start=bar_start, entry=entry, sl=sl, tp=tp,
            direction=direction, max_bars=max_bars, strategy="lookahead",
            use_break_even=use_break_even,
            be_trigger_pct=be_trigger_pct,
            trail_after_be_pct=trail_after_be_pct,
            partial_tp_at_pct=partial_tp_at_pct,
            partial_tp_size=partial_tp_size,
            partial_arms_be=partial_arms_be,
            entry_mode="market",
        )
    finally:
        np.random.set_state(rng_state)
    return result.pnl_per_unit if result is not None else None
