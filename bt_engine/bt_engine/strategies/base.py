"""Strategy ABC."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..core.bar import Bar
from ..core.signal import StepResult
from ..core.state import StrategyState


class Strategy(ABC):
    strategy_id: str
    config: object

    @abstractmethod
    def initial_state(self) -> StrategyState: ...

    @abstractmethod
    def on_bar(
        self,
        state: StrategyState,
        bar: Bar,
        history: pd.DataFrame,
    ) -> StepResult: ...
