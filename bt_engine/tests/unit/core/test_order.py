"""Unit tests for Order, Fill, OpenTrade, BracketOutcome."""
from __future__ import annotations

import pandas as pd
import pytest

from bt_engine.core.order import BracketOutcome, Fill, OpenTrade, Order


def _ts(s: str = "2026-06-29T00:00:00Z") -> pd.Timestamp:
    return pd.Timestamp(s)


def test_order_happy_path() -> None:
    o = Order(
        symbol="XAUUSD",
        side=1,
        qty=1.0,
        intended_entry_bar=_ts(),
        stop_price=1980.0,
        take_profit=2020.0,
        risk_units=20.0,
        tag="zone_42",
        bracket_kind="1R",
    )
    assert o.side == 1
    assert o.risk_units == 20.0


def test_order_rejects_invalid_side() -> None:
    with pytest.raises(ValueError, match="side"):
        Order("XAUUSD", 0, 1.0, _ts(), 1.0, 2.0, 1.0, "t", "1R")


def test_order_rejects_zero_qty() -> None:
    with pytest.raises(ValueError, match="qty"):
        Order("XAUUSD", 1, 0.0, _ts(), 1.0, 2.0, 1.0, "t", "1R")


def test_order_rejects_zero_risk() -> None:
    with pytest.raises(ValueError, match="risk_units"):
        Order("XAUUSD", 1, 1.0, _ts(), 1.0, 2.0, 0.0, "t", "1R")


def test_order_rejects_naive_timestamp() -> None:
    naive = pd.Timestamp("2026-06-29T00:00:00")
    with pytest.raises(ValueError, match="timezone-aware"):
        Order("XAUUSD", 1, 1.0, naive, 1.0, 2.0, 1.0, "t", "1R")


def test_order_is_frozen() -> None:
    o = Order("XAUUSD", 1, 1.0, _ts(), 1.0, 2.0, 1.0, "t", "1R")
    with pytest.raises(Exception):
        o.side = -1  # type: ignore[misc]


def test_fill_dataclass() -> None:
    f = Fill("XAUUSD", 1, 1.0, 2000.0, _ts())
    assert f.price == 2000.0


def test_bracket_outcome_dataclass() -> None:
    o = BracketOutcome(
        exit_timestamp=_ts(),
        exit_price=2010.0,
        reason="TP",
        bars_held=10,
        bracket_1r_outcome=1.0,
        event_type="EXIT_TP",
    )
    assert o.reason == "TP"


def test_open_trade_dataclass() -> None:
    import uuid

    fill = Fill("XAUUSD", 1, 1.0, 2000.0, _ts())
    order = Order("XAUUSD", 1, 1.0, _ts(), 1980.0, 2020.0, 20.0, "t", "1R")
    tr = OpenTrade(
        trade_id=uuid.uuid4(),
        order=order,
        fill=fill,
        entry_price=2000.0,
        entry_timestamp=_ts(),
        side=1,
        stop_price=1980.0,
        take_profit=2020.0,
        risk_units=20.0,
    )
    assert tr.mfe_r == 0.0
    assert tr.bars_held == 0
