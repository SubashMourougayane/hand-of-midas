"""StepResult dataclass — return type of Strategy.on_bar."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .order import Order
from .state import StrategyState


@dataclass(frozen=True)
class StrategyEvent:
    """A journal event emitted by a strategy step (not a trade-level event)."""

    trade_or_zone_id: str
    type: str  # JournalEvent enum string
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    state: StrategyState
    new_orders: tuple[Order, ...] = ()
    new_events: tuple[StrategyEvent, ...] = ()
