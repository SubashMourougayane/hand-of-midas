"""FibV2 INTRADAY A+D combined strategy.

Runs BOTH `FibV2IntradayA` (long) and `FibV2IntradayD` (short) inside ONE
engine loop via a single composite strategy. Shares:
  - one `run_engine()` invocation → one `run_id`
  - one `EngineDeps` + one BT execution + one sizer + one max_open_positions
  - one `on_bar` per M15 bar → merged orders + events

Each leg keeps its own `FibV2State` (pivot tracker, pending setups, consumed
keys). The composite state holds both.

Deterministic order: A leg first, then D leg. Events + orders concatenated in
that fixed order so downstream persistence is reproducible.

Parity: aggregate BT output MUST match post-hoc union of two separate A+D
runs. This is the correctness gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ...core.bar import Bar
from ...core.signal import StepResult, StrategyEvent
from ...core.state import StrategyState
from ...core.order import Order
from ..fib_v2.state import FibV2State
from .strategy import FibV2IntradayA, FibV2IntradayD


@dataclass
class FibV2IntradayADState(StrategyState):
    a_state: Optional[FibV2State] = None
    d_state: Optional[FibV2State] = None
    bars_seen: int = 0

    def clone(self) -> "FibV2IntradayADState":
        # Per-leg FibV2State.clone() returns self (perf). Mutations happen
        # in place inside each leg's on_bar. Composite mirrors that contract.
        return self

    def clear_pending_entries(self) -> None:
        """Recurse into BOTH leg states. The composite holds no pending_entries
        of its own — a bare attr clear on this object would miss the warmup
        entries queued inside a_state / d_state (F5). Called by the live runner
        after warmup replay."""
        if self.a_state is not None:
            self.a_state.clear_pending_entries()
        if self.d_state is not None:
            self.d_state.clear_pending_entries()


class FibV2IntradayAPlusD:
    """Composite strategy — A + D under one on_bar.

    Not a subclass of `FibV2IntradayBase` because we hold two INSTANCES of it,
    not extend one. Implements the `Strategy` protocol (initial_state + on_bar).
    """

    strategy_id = "fib_v2_intraday_a_plus_d"

    def __init__(
        self,
        *,
        symbol: str = "XAUUSD.ecn",
        strict_after: bool = True,
        edge: bool = False,
        ote: Optional[float] = None,
        qty: Optional[float] = None,
        cost_usd: Optional[float] = None,
        **_runner_kwargs,
    ) -> None:
        self.symbol = symbol
        self.a = FibV2IntradayA(symbol=symbol, strict_after=strict_after, edge=edge, ote=ote, qty=qty, cost_usd=cost_usd)
        self.d = FibV2IntradayD(symbol=symbol, strict_after=strict_after, edge=edge, ote=ote, qty=qty, cost_usd=cost_usd)
        # Expose a config attr so runner/dashboard can inspect timeframe etc.
        # A + D share base_tf/pivot_tf ('M15') and cost. Pick A's.
        self.config = self.a._intraday_cfg

    def initial_state(self) -> FibV2IntradayADState:
        return FibV2IntradayADState(
            a_state=self.a.initial_state(),
            d_state=self.d.initial_state(),
        )

    def validate_for_live(self, *, timeframe: str) -> None:
        self.a.validate_for_live(timeframe=timeframe)
        self.d.validate_for_live(timeframe=timeframe)

    def on_bar(
        self,
        state: FibV2IntradayADState,
        bar: Bar,
        history: pd.DataFrame,
    ) -> StepResult:
        # A first, then D — deterministic order.
        a_step = self.a.on_bar(state.a_state, bar, history)
        d_step = self.d.on_bar(state.d_state, bar, history)

        state.a_state = a_step.state  # type: ignore[assignment]
        state.d_state = d_step.state  # type: ignore[assignment]
        state.bars_seen += 1

        merged_orders: tuple[Order, ...] = a_step.new_orders + d_step.new_orders
        merged_events: tuple[StrategyEvent, ...] = a_step.new_events + d_step.new_events
        return StepResult(state=state, new_orders=merged_orders, new_events=merged_events)
