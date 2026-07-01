"""Partial-TP callback fires ONCE, at the bar that crosses +1R, with post-mutation state."""
from __future__ import annotations

import uuid
from typing import Any

import pandas as pd

from bt_engine.core.bar import Bar
from bt_engine.core.bracket import walk_bracket_on_bar
from bt_engine.core.order import Fill, OpenTrade, Order


def _make_short_trade(entry: float = 100.0, risk: float = 1.0, tp: float = 90.0) -> OpenTrade:
    order = Order(
        symbol="TEST",
        side=-1,
        qty=0.10,
        intended_entry_bar=pd.Timestamp("2026-01-01 10:00:00", tz="UTC"),
        stop_price=entry + risk,
        take_profit=tp,
        risk_units=risk,
        tag="test",
        bracket_kind="1R",
        trade_id=uuid.uuid4(),
        extra={"partial_tp_at_r": 1.0, "partial_tp_pct": 0.5},
    )
    fill = Fill(
        symbol="TEST", side=-1, qty=0.10, price=entry,
        fill_timestamp=order.intended_entry_bar,
    )
    return OpenTrade(
        trade_id=order.trade_id, order=order, fill=fill,
        entry_price=entry, entry_timestamp=order.intended_entry_bar,
        side=-1, stop_price=order.stop_price, take_profit=tp,
        risk_units=risk, broker_ticket="42",
    )


def _bar(ts_offset_min: int, high: float, low: float, close: float, open_: float | None = None) -> Bar:
    return Bar(
        symbol="TEST", timeframe="M15",
        timestamp=pd.Timestamp("2026-01-01 10:00:00", tz="UTC") + pd.Timedelta(minutes=ts_offset_min),
        open=open_ if open_ is not None else close,
        high=high, low=low, close=close, volume=100.0,
    )


def test_partial_tp_callback_fires_once_at_trigger_bar() -> None:
    tr = _make_short_trade()  # entry=100, sl=101, risk=1
    calls: list[dict[str, Any]] = []

    def _on_partial(trade: OpenTrade, bar: Bar) -> None:
        calls.append({
            "trade_id": trade.trade_id,
            "ticket": trade.broker_ticket,
            "sl_after": trade.stop_price,
            "partial_taken": trade.partial_taken,
            "partial_r": trade.partial_filled_r,
            "bar_ts": bar.timestamp,
        })

    # Bar 1: price moves from 100 → 99.5 (low hit 99, +1R MFE crossed at low)
    out = walk_bracket_on_bar(tr, _bar(15, high=100.1, low=99.0, close=99.5), on_partial_tp=_on_partial)
    assert out is None
    assert len(calls) == 1, "callback must fire once when +1R crossed"
    c = calls[0]
    assert c["ticket"] == "42"
    assert c["partial_taken"] is True
    assert c["partial_r"] == 0.5  # 0.5 pct × 1.0 trigger
    assert c["sl_after"] == 100.0, "SL must be at entry (BE)"

    # Bar 2: same MFE, no re-fire.
    out = walk_bracket_on_bar(tr, _bar(30, high=99.6, low=99.2, close=99.4), on_partial_tp=_on_partial)
    assert out is None
    assert len(calls) == 1, "callback must NOT re-fire after partial already taken"


def test_partial_tp_callback_not_called_without_config() -> None:
    order = Order(
        symbol="TEST", side=-1, qty=0.10,
        intended_entry_bar=pd.Timestamp("2026-01-01 10:00:00", tz="UTC"),
        stop_price=101.0, take_profit=90.0, risk_units=1.0, tag="test",
        bracket_kind="1R", trade_id=uuid.uuid4(),
        extra={},  # no partial_tp_at_r
    )
    fill = Fill(
        symbol="TEST", side=-1, qty=0.10, price=100.0,
        fill_timestamp=order.intended_entry_bar,
    )
    tr = OpenTrade(
        trade_id=order.trade_id, order=order, fill=fill,
        entry_price=100.0, entry_timestamp=order.intended_entry_bar,
        side=-1, stop_price=101.0, take_profit=90.0, risk_units=1.0,
    )
    calls: list[Any] = []
    walk_bracket_on_bar(tr, _bar(15, high=100.1, low=98.0, close=98.5),
                       on_partial_tp=lambda *a: calls.append(a))
    assert calls == [], "no partial config → no callback"


def test_partial_tp_callback_sees_ticket_none_gracefully() -> None:
    """OpenTrade with broker_ticket=None (BT sim) still fires callback — caller decides what to do."""
    tr = _make_short_trade()
    tr.broker_ticket = None  # simulate BT mode
    got = []
    walk_bracket_on_bar(tr, _bar(15, high=100.1, low=99.0, close=99.5),
                       on_partial_tp=lambda trade, bar: got.append(trade.broker_ticket))
    assert got == [None]  # callback fired with None ticket; runner logs+skips


def test_close_then_sl_hit_at_be_records_partial() -> None:
    """After partial fires, SL at BE returns +0.5R (partial locked + 0R on remainder)."""
    tr = _make_short_trade()
    walk_bracket_on_bar(tr, _bar(15, high=100.1, low=99.0, close=99.5))  # partial fires
    # Bar 2: price whips back to entry, SL@BE hits
    out = walk_bracket_on_bar(tr, _bar(30, high=100.2, low=99.8, close=100.0))
    assert out is not None
    assert out.reason == "SL_BE"
    assert out.bracket_1r_outcome == 0.5  # 0.5R partial + 0R BE
