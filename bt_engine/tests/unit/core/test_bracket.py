"""Unit tests for walk_bracket_on_bar."""
from __future__ import annotations

import uuid

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.core.bracket import walk_bracket_on_bar
from bt_engine.core.order import Fill, OpenTrade, Order


def _bar(ts: str, *, o: float, h: float, l: float, c: float) -> Bar:
    return Bar("X", "M15", pd.Timestamp(ts), o, h, l, c, 1.0)


def _trade(side: int, *, entry: float, stop: float, tp: float | None, risk: float = 10.0) -> OpenTrade:
    order = Order(
        symbol="X", side=side, qty=1.0,
        intended_entry_bar=pd.Timestamp("2026-06-29T00:00:00Z"),
        stop_price=stop, take_profit=tp, risk_units=risk,
        tag="t", bracket_kind="1R",
    )
    fill = Fill("X", side, 1.0, entry, pd.Timestamp("2026-06-29T00:00:00Z"))
    return OpenTrade(
        trade_id=uuid.uuid4(), order=order, fill=fill,
        entry_price=entry, entry_timestamp=fill.fill_timestamp,
        side=side, stop_price=stop, take_profit=tp, risk_units=risk,
    )


def test_long_tp_hit_on_close() -> None:
    """Research-parity: TP exit = exact TP price (not close), outcome = exact tp_R."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1010.0)
    bar = _bar("2026-06-29T00:15:00Z", o=1000, h=1011, l=1000, c=1010.5)
    o = walk_bracket_on_bar(tr, bar)
    assert o is not None
    assert o.reason == "TP"
    assert o.exit_price == 1010.0  # snap to TP
    assert o.bracket_1r_outcome == pytest.approx(1.0)  # exact 1R


def test_long_sl_hit_on_close() -> None:
    """Research-parity: SL exit = stop price (not close), outcome = -1.0R exactly."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1010.0)
    bar = _bar("2026-06-29T00:15:00Z", o=1000, h=1000.5, l=985, c=988)
    o = walk_bracket_on_bar(tr, bar)
    assert o is not None
    assert o.reason == "SL"
    assert o.exit_price == 990.0  # snap to SL
    assert o.bracket_1r_outcome == pytest.approx(-1.0)  # exact -1R


def test_long_neither_hit_returns_none() -> None:
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1010.0)
    bar = _bar("2026-06-29T00:15:00Z", o=1000, h=1005, l=995, c=1003)
    assert walk_bracket_on_bar(tr, bar) is None
    assert tr.bars_held == 1
    assert tr.mfe_r == pytest.approx(0.5)
    assert tr.mae_r == pytest.approx(-0.5)


def test_short_tp_hit() -> None:
    tr = _trade(-1, entry=1000.0, stop=1010.0, tp=990.0)
    bar = _bar("2026-06-29T00:15:00Z", o=1000, h=1001, l=985, c=988)
    o = walk_bracket_on_bar(tr, bar)
    assert o is not None
    assert o.reason == "TP"


def test_short_sl_hit() -> None:
    tr = _trade(-1, entry=1000.0, stop=1010.0, tp=990.0)
    bar = _bar("2026-06-29T00:15:00Z", o=1000, h=1015, l=999, c=1012)
    o = walk_bracket_on_bar(tr, bar)
    assert o is not None
    assert o.reason == "SL"


def test_stop_precedes_tp_when_both_hit_on_close() -> None:
    """If close is past both levels, stop takes precedence (worst-case for trader)."""
    tr = _trade(1, entry=1000.0, stop=1005.0, tp=995.0)
    # impossible bracket geometry, but explicit precedence test
    bar = _bar("2026-06-29T00:15:00Z", o=1000, h=1010, l=990, c=994)
    o = walk_bracket_on_bar(tr, bar)
    assert o is not None
    assert o.reason == "SL"


def test_timeout_triggers_at_max_bars() -> None:
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1100.0)
    bar = _bar("2026-06-29T00:15:00Z", o=1000, h=1001, l=999, c=1000)
    o = walk_bracket_on_bar(tr, bar, max_bars_held=1)
    assert o is not None
    assert o.reason == "TIMEOUT"
