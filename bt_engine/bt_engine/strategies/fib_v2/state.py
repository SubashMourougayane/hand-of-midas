"""FibV2State + FibSetup — strategy state for the streaming port."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ...core.state import StrategyState
from .pivot_tracker import PivotEvent, PivotTracker
from .regime_tracker import RegimeTracker
from .swing_tracker import SwingTracker


@dataclass(frozen=True)
class FibSetup:
    """One active fib setup for one leg. Immutable — replaced on new pivot."""

    leg_name: str  # "long_bull_strong" | "short_bear_strong" | ...
    side: int  # +1 long | -1 short
    L: float  # impulse low
    H: float  # impulse high
    diff: float  # H - L
    fib_382: float
    fib_786: float
    fib_100: float  # invalidation level (= L for long, = H for short)
    tp_price: float  # H + ext*diff (long) / L - ext*diff (short)
    sl_price: float  # L - sl_buf*diff (long) / H + sl_buf*diff (short)
    setup_confirm_ts: pd.Timestamp  # max(L_ts, H_ts) — when both pivots confirmed
    L_ts: pd.Timestamp
    H_ts: pd.Timestamp


@dataclass
class FibV2State(StrategyState):
    """State for Fib V2 ENSEMBLE.

    Per-leg active setups live here. Trackers are part of state to make
    `state.clone()` safe (deep-copy preserves their internal buffers).
    """

    bars_seen: int = 0

    # Last seen H1 timestamp (used to detect when a NEW H1 bar has closed).
    last_h1_seen: Optional[pd.Timestamp] = None
    last_d1_seen: Optional[pd.Timestamp] = None

    # Pivot history from H1.
    last_L: Optional[float] = None
    last_L_ts: Optional[pd.Timestamp] = None
    last_H: Optional[float] = None
    last_H_ts: Optional[pd.Timestamp] = None

    # Pending setups per leg: list of (FibSetup, fired_or_invalidated_flag).
    # Each pivot event spawns a new setup; each setup fires AT MOST one entry
    # (research `break` after first valid bar in window) and expires after
    # `max_hold_bars` from setup_confirm_ts.
    pending_setups: dict[str, list[FibSetup]] = field(default_factory=dict)

    # Setup keys (leg_name, setup_confirm_ts) already entered. Used for idempotency.
    consumed_setup_keys: set[tuple[str, pd.Timestamp]] = field(default_factory=set)

    # Entry-bar dedup: (entry_ts, side, leg_name) already emitted as an Order.
    # Used by FibV2Intraday subclass to drop multi-pivot stacks landing on the
    # SAME M15 bar with different SL/TP geometry. Base FibV2EnsembleStrategy
    # NEVER reads or writes this set — additive, no behavior change for base.
    # NOTE: state.clone() returns self (perf override), so adds mutate in place.
    consumed_entry_keys: set[tuple[pd.Timestamp, int, str]] = field(default_factory=set)

    # Trackers — internal buffers; safe to deep-copy.
    pivot_tracker: PivotTracker = field(default_factory=lambda: PivotTracker(lb=5))
    regime_tracker: RegimeTracker = field(default_factory=RegimeTracker)
    swing_tracker: SwingTracker = field(default_factory=lambda: SwingTracker(lb=20))

    # Cached prior bar (for confirmation candle detection).
    prev_open: Optional[float] = None
    prev_close: Optional[float] = None

    # Pending entry triggers: (leg_name, setup) tuples queued by signal bar k.
    # On the NEXT bar k+1, finalize using bar.open as entry_price (matches
    # research's `entry_price = m5.open[k+1]`).
    pending_entries: list[tuple[str, "FibSetup"]] = field(default_factory=list)

    def clone(self) -> "FibV2State":
        """Override base StrategyState.clone() — return self.

        FibV2State carries large internal buffers (PivotTracker deque,
        RegimeTracker EMA history, SwingTracker deque). Deep-copying these per
        bar is the dominant cost (~75% of run time). The strategy mutates state
        in-place and returns it via StepResult, so the engine receives the
        SAME object. No deep copy needed for correctness.

        This is safe BECAUSE:
          1. The engine never inspects state between on_bar calls (only stores
             the returned StepResult.state).
          2. The strategy is single-threaded (no concurrent mutation).
          3. We never compare state snapshots across bars.
        """
        return self
