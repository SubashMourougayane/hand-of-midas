"""Core protocols: DataProvider, Strategy, ExecutionModel, BrokerAdapter, Clock."""
from __future__ import annotations

from typing import Iterator, Protocol, Sequence
from uuid import UUID

import pandas as pd

from .bar import Bar
from .order import Fill, Order
from .signal import StepResult
from .state import StrategyState


class DataProvider(Protocol):
    symbol: str
    timeframe: str

    def bars(self) -> Iterator[Bar]: ...

    def history_up_to(self, t: pd.Timestamp) -> pd.DataFrame: ...


class Clock(Protocol):
    def tick(self) -> Bar | None: ...

    def now(self) -> pd.Timestamp: ...


class Strategy(Protocol):
    strategy_id: str
    config: object

    def initial_state(self) -> StrategyState: ...

    def on_bar(
        self,
        state: StrategyState,
        bar: Bar,
        history: pd.DataFrame,
    ) -> StepResult: ...


class ExecutionModel(Protocol):
    def simulate_fill(self, order: Order, next_bar: Bar) -> Fill: ...

    def slippage_bps(self) -> float: ...


class BrokerAdapter(Protocol):
    def submit_order(self, order: Order) -> str: ...

    def cancel(self, order_id: str) -> None: ...

    def fills(self) -> Iterator[Fill]: ...

    def positions(self) -> Sequence[dict]: ...
