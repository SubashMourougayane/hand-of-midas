"""Shared production gates — single source of truth for BT and live.

Phase 6 of REFACTOR_PLAN_LIVE_BT_UNIFY. Both BT execution loop and live
scheduler call `apply_gates(...)`. Same code = same decisions = byte-level
trade-list parity (with documented live-only exceptions).

Architecture:

    +-------------------+        +---------------------+
    | BT execution loop |        | Live scheduler      |
    +---------+---------+        +---------+-----------+
              |                            |
              v                            v
    +---------+----------------------------+----------+
    |  apply_gates(signal, state, *, cfg, callbacks) |
    +-------------------------------------------------+
              |
              v
    Returns skip_reason (str) or None (= fire)

`callbacks` is a dict of pluggable predicates for live-only checks.
BT passes empty {} (or callbacks that always return False/None).
Live passes real DB / MT5 lookups.

Live-only gates exposed via callbacks (BT can't simulate):
- check_db_open_positions()  -> int  : # open trades for this strategy
- check_mt5_open_positions() -> int  : # account-wide open trades
- check_startup_cooldown(now) -> bool : True if startup cooldown active

Strategy-level gates (in shared code, work for both):
- daily cap on FILLED trades
- one-at-a-time blocker (position_exit_time)
- 5-min cooldown after last signal attempt
- persistent sweep blacklist (per-day reset)
- DD pause (5 consecutive losses → skip 2)

Risk sizing helper:
- compute_risk_multiplier(state) -> float
  Returns 1.0, 0.5, or 0.25 based on consecutive losses + equity-MA.
  Used by sizing logic (not gate decision).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional


@dataclass
class GateState:
    """Mutable state shared across signal iterations.

    Both BT execution loop and live scheduler maintain a GateState. BT's
    state lives in `run_backtest`'s local frame; live's lives at module
    level (reset per day at midnight UTC by the scheduler).
    """
    # Cooldown / blocker timestamps (tz-aware UTC datetimes)
    last_signal_time: Optional[datetime] = None       # set on FIRE or filled-skip
    position_exit_time: Optional[datetime] = None     # set on FIRE; cleared on EXIT

    # Persistent sweep blacklist for the current day
    consumed_sweeps: set = field(default_factory=set)

    # Daily counters (reset at midnight UTC)
    day_filled_trades: int = 0
    day_pnl: float = 0.0

    # DD protection — tracked across trades
    consecutive_losses: int = 0
    pause_counter: int = 0  # >0 means skip next N signals

    # Equity history for equity-MA risk reduction
    equity: float = 0.0
    equity_history: list = field(default_factory=list)

    # Date scope — gates reset when date crosses
    current_date: Optional[datetime] = None


def apply_gates(
    signal,
    state: GateState,
    *,
    cfg: dict,
    callbacks: Optional[dict] = None,
    cooldown_minutes: int = 5,
    dd_pause_threshold: int = 5,
    dd_pause_skip_count: int = 2,
) -> Optional[str]:
    """Apply all production gates. Returns skip_reason str OR None (= fire).

    Args:
        signal: a Signal object with `.date` (tz-aware datetime) and
            `.metadata` (dict with sweep_time + start_hour + sweep_dir for
            blacklist keying).
        state: mutable GateState — caller mutates AFTER fire (call-site
            responsibility, not this fn's).
        cfg: strategy config dict (must have `max_trades_per_day`).
        callbacks: dict of optional pluggable live-only predicates:
            - "check_db_open_positions": () -> int
            - "check_mt5_open_positions": () -> int
            - "check_startup_cooldown": (now: datetime) -> bool
            BT passes {} or omits → all live-only gates skipped.
        cooldown_minutes: 5 (default — matches live).
        dd_pause_threshold: 5 (default).
        dd_pause_skip_count: 2 (default).

    Returns:
        str: skip_reason if any gate blocks. Caller logs + skips.
        None: signal passes all gates. Caller fires.

    Order of checks (matches live's existing order, deterministic):
        1. Daily cap (max_trades_per_day)
        2. DD pause counter (skip-N-after-5-losses)
        3. One-at-a-time (position_exit_time)
        4. 5-min cooldown
        5. Sweep blacklist
        6. DB open-position check (live-only callback)
        7. MT5 open-position check (live-only callback)
        8. Startup cooldown (live-only callback)
    """
    callbacks = callbacks or {}

    # 1. Daily cap on FILLED trades (cap rework Jun 18 — TTL_EXPIRED excluded)
    if state.day_filled_trades >= cfg.get("max_trades_per_day", 3):
        return "daily_cap_reached"

    # 2. DD pause — counts down skips after 5 consecutive losses
    if state.pause_counter > 0:
        state.pause_counter -= 1
        return "dd_pause"

    # 3. One-at-a-time blocker — signal fires only after prior position exits
    if state.position_exit_time and signal.date < state.position_exit_time:
        return "open_position"

    # 4. 5-min cooldown after last signal attempt (TTL_EXPIRED also counts
    #    per live's "or _skip.startswith('order_error')" semantics)
    if state.last_signal_time and signal.date < state.last_signal_time + timedelta(minutes=cooldown_minutes):
        return "cooldown_5min"

    # 5. Persistent sweep blacklist — once consumed, never re-fire that day
    sweep_key = make_sweep_key(signal)
    if sweep_key in state.consumed_sweeps:
        return "sweep_already_traded"

    # 6. Live-only DB open-position check
    if "check_db_open_positions" in callbacks:
        if callbacks["check_db_open_positions"]() > 0:
            return "open_position_db"

    # 7. Live-only MT5 cross-account check (BT no-op)
    if "check_mt5_open_positions" in callbacks:
        if callbacks["check_mt5_open_positions"]() > 0:
            return "open_position_mt5"

    # 8. Live-only startup cooldown (BT no-op — no restart concept)
    if "check_startup_cooldown" in callbacks:
        if callbacks["check_startup_cooldown"](signal.date):
            return "startup_cooldown"

    return None  # fire


def make_sweep_key(signal) -> str:
    """Build a deterministic sweep-blacklist key from a Signal.

    BT and live MUST produce the same key for the same signal. Key format
    matches the post-Phase-5 keying: `{sweep_time}_{start_hour}_{sweep_dir}`.

    Falls back to signal.date + direction if metadata missing (legacy
    callers — should not happen for Micros post-refactor).
    """
    if signal.metadata:
        sweep_time = signal.metadata.get("sweep_time")
        start_hour = signal.metadata.get("start_hour")
        sweep_dir = signal.metadata.get("sweep_dir")
        if sweep_time is not None and start_hour is not None and sweep_dir is not None:
            return f"{sweep_time}_{start_hour}_{sweep_dir}"
    # Legacy fallback
    return f"{signal.date.isoformat()}_{getattr(signal, 'direction', 'unknown')}"


def compute_risk_multiplier(state: GateState) -> float:
    """Risk reduction based on consecutive losses + equity-MA.

    NOT a gate — used by sizing math after `apply_gates` returns None.
    Same logic both BT and live should use to compute position size.

    Returns:
        1.0 (full risk) — default
        0.5 (half risk) — after 3+ consecutive losses OR equity below 20-bar MA
        0.25 (quarter risk) — both conditions true
    """
    mult = 1.0
    if state.consecutive_losses >= 3:
        mult *= 0.5
    if len(state.equity_history) >= 20:
        eq_ma = sum(state.equity_history[-20:]) / 20
        if state.equity < eq_ma:
            mult *= 0.5
    return mult


def update_state_after_fire(state: GateState, signal, *, expected_exit_seconds: int) -> None:
    """Call AFTER a signal is fired (BT trade entered, or live order placed).

    Mutations:
    - last_signal_time = signal.date  (5-min cooldown anchor)
    - position_exit_time = signal.date + expected_exit_seconds  (one-at-a-time)
    - consumed_sweeps.add(sweep_key)  (blacklist)

    Caller may also bump day_filled_trades, depending on whether the fire
    is a FILLED trade vs LIMIT_TTL_EXPIRED (cap rework: TTL_EXPIRED doesn't
    count). That bump lives at the call site — apply_gates only reads it.
    """
    state.last_signal_time = signal.date
    state.position_exit_time = signal.date + timedelta(seconds=expected_exit_seconds)
    state.consumed_sweeps.add(make_sweep_key(signal))


# Narrow set of skip reasons that ARM the 5-min cooldown — must match live's
# Issue #19 fix (2026-06-15) at backend-{micro,oil-micro}/scanner/scheduler.py.
# All other skip reasons (bias_block, range_too_small, risk_out_of_band,
# tp_too_close, etc.) do NOT arm cooldown — strategy-filtered, not noise.
_COOLDOWN_ARMING_SKIP_REASONS = frozenset({
    "sl_too_close_to_price",
})

_COOLDOWN_ARMING_PREFIXES = ("order_error", "oanda_error")


def cooldown_arms_on_skip(skip_reason: Optional[str]) -> bool:
    """Returns True if `skip_reason` should arm the 5-min cooldown.

    Live (per Issue #19): cooldown engages on FILL or on these specific
    failure-mode skip reasons that imply an actual order attempt happened.
    Bias/risk/range filters DO NOT arm cooldown — those are 'didn't even
    try' filters.
    """
    if skip_reason is None:
        return False
    if skip_reason in _COOLDOWN_ARMING_SKIP_REASONS:
        return True
    return any(skip_reason.startswith(p) for p in _COOLDOWN_ARMING_PREFIXES)


def update_state_after_exit(state: GateState, *, pnl_dollar: float, equity_after: float) -> None:
    """Call AFTER a trade exits with a known P&L.

    Mutations:
    - consecutive_losses: increment on loss, reset on win
    - pause_counter: armed if losses >= dd_pause_threshold
    - equity, equity_history: track for equity-MA
    - day_pnl: accumulated daily P&L
    """
    state.day_pnl += pnl_dollar
    state.equity = equity_after
    state.equity_history.append(equity_after)
    if pnl_dollar > 0:
        state.consecutive_losses = 0
    else:
        state.consecutive_losses += 1
        if state.consecutive_losses >= 5:
            state.pause_counter = 2


def reset_for_new_day(state: GateState, new_date) -> None:
    """Reset day-scoped counters at midnight UTC.

    Sweep blacklist + day_filled_trades + day_pnl are cleared. Cross-day
    state (consecutive_losses, equity, equity_history, pause_counter)
    persists.
    """
    state.consumed_sweeps = set()
    state.day_filled_trades = 0
    state.day_pnl = 0.0
    state.current_date = new_date


# ─── Phase 6 #10 — broker costs (commission + swap) ──────────


def compute_broker_costs(
    units: float,
    direction: str,
    bars_held: int,
    *,
    broker_costs: dict,
    bar_minutes: int = 3,
    rollover_hour_utc: int = 0,
    entry_hour_utc: int = 12,
) -> dict:
    """Compute commission + swap for a closed BT trade.

    Returns:
        dict {commission, swap, total} — all dollar amounts (positive = cost).

    Args:
        units: position size in instrument units
        direction: "long" or "short"
        bars_held: number of M3 bars (or whatever bar_minutes scale) held
        broker_costs: dict from config — must have lot_size, commission_per_lot_rt,
            swap_long_per_lot_per_night, swap_short_per_lot_per_night.
        bar_minutes: 3 for M3 (default).
        rollover_hour_utc: broker rollover (00:00 UTC for most ECN brokers).
        entry_hour_utc: hour the trade entered (used to count overnight crossings).
            Defaults to 12 (mid-day) for the simple case where BT doesn't pass it.

    Commission semantics:
        Round-trip per lot (entry + exit combined). Charged once per closed trade.

    Swap semantics:
        Paid for each rollover crossed while position was open.
        Approximation: minutes_held / 1440 (= days_held), rounded down + 1
        if any rollover was crossed. Conservative — slightly over-charges.
        For sub-day trades: no swap (most Micro trades are <4hr, no swap).
    """
    lot_size = broker_costs["lot_size"]
    lots = units / lot_size

    # Commission — round-trip per lot
    commission = lots * broker_costs["commission_per_lot_rt"]

    # Swap — only if trade held overnight (approximate)
    minutes_held = bars_held * bar_minutes
    nights_crossed = minutes_held // 1440  # full 24hr cycles
    # Add 1 if entry-hour straddled rollover (entry before, exit after)
    # Conservative: assume any trade with bars_held > rollover-distance crossed
    if minutes_held >= (24 - entry_hour_utc) * 60 and nights_crossed == 0:
        nights_crossed = 1

    if direction == "long":
        swap_per_lot = broker_costs["swap_long_per_lot_per_night"]
    else:
        swap_per_lot = broker_costs["swap_short_per_lot_per_night"]
    # swap_per_lot is negative (cost). Multiply by nights crossed and lots.
    # Return as POSITIVE cost.
    swap = -lots * swap_per_lot * nights_crossed  # negate to express as cost

    total = commission + swap
    return {
        "commission": commission,
        "swap": swap,
        "total": total,
        "lots": lots,
        "nights_crossed": nights_crossed,
    }
