"""StrategyState base class — strategies subclass this for engine-managed state."""
from __future__ import annotations

import copy
from dataclasses import dataclass


@dataclass
class StrategyState:
    """Base for strategy state objects. Subclass and add fields.

    The engine deep-copies state before each on_bar to enforce purity.
    """

    def clone(self) -> "StrategyState":
        return copy.deepcopy(self)
