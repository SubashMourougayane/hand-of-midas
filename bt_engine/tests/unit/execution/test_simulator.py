"""Unit tests for BTExecutionModel."""
from __future__ import annotations

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.core.order import Order
from bt_engine.execution.simulator import BTExecutionModel


def _order(side: int, ts: str) -> Order:
    return Order(
        symbol="X", side=side, qty=1.0,
        intended_entry_bar=pd.Timestamp(ts),
        stop_price=99.0, take_profit=101.0, risk_units=1.0,
        tag="t", bracket_kind="1R",
    )


def test_fill_at_open_zero_slippage() -> None:
    e = BTExecutionModel(slippage_bps_value=0.0)
    bar = Bar("X", "M15", pd.Timestamp("2026-06-29T00:00:00Z"), 100.0, 101, 99, 100.5, 1.0)
    f = e.simulate_fill(_order(1, "2026-06-29T00:00:00Z"), bar)
    assert f.price == 100.0
    assert f.side == 1


def test_fill_with_positive_slippage_long() -> None:
    e = BTExecutionModel(slippage_bps_value=10.0)
    bar = Bar("X", "M15", pd.Timestamp("2026-06-29T00:00:00Z"), 100.0, 101, 99, 100.5, 1.0)
    f = e.simulate_fill(_order(1, "2026-06-29T00:00:00Z"), bar)
    # 100 * (1 + 10/10000) = 100.1
    assert f.price == pytest.approx(100.1)


def test_fill_with_positive_slippage_short() -> None:
    e = BTExecutionModel(slippage_bps_value=10.0)
    bar = Bar("X", "M15", pd.Timestamp("2026-06-29T00:00:00Z"), 100.0, 101, 99, 100.5, 1.0)
    f = e.simulate_fill(_order(-1, "2026-06-29T00:00:00Z"), bar)
    # 100 * (1 - 10/10000) = 99.9
    assert f.price == pytest.approx(99.9)


def test_fill_rejects_mismatched_bar() -> None:
    e = BTExecutionModel()
    bar = Bar("X", "M15", pd.Timestamp("2026-06-29T00:15:00Z"), 100.0, 101, 99, 100.5, 1.0)
    with pytest.raises(ValueError):
        e.simulate_fill(_order(1, "2026-06-29T00:00:00Z"), bar)
