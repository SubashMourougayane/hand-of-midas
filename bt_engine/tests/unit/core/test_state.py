"""Unit tests for StrategyState base."""
from __future__ import annotations

from dataclasses import dataclass, field

from bt_engine.core.state import StrategyState


@dataclass
class DemoState(StrategyState):
    counter: int = 0
    items: list[int] = field(default_factory=list)


def test_clone_creates_deep_copy() -> None:
    s = DemoState(counter=5, items=[1, 2, 3])
    c = s.clone()
    assert c is not s
    assert c.items is not s.items
    c.items.append(99)
    assert 99 not in s.items
