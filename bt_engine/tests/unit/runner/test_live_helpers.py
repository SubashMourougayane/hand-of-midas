"""Unit tests for live runner helpers (_to_dt, _bt_trade_from_open).

Audit regression guards:
- _to_dt: naive pd.Timestamp must be coerced to UTC tz-aware datetime
  (live broker may return naive fill_timestamp).
- _bt_trade_from_open: fib + partial-TP columns must populate from order.extra.
"""
from __future__ import annotations

import uuid
from datetime import timezone

import pandas as pd

from bt_engine.core.order import Fill, OpenTrade, Order
from bt_engine.runner.live import _bt_trade_from_open, _to_dt


def test_to_dt_naive_is_localized_to_utc():
    ts = pd.Timestamp("2026-06-30 12:00:00")  # naive
    assert ts.tzinfo is None
    dt = _to_dt(ts)
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_to_dt_aware_is_preserved():
    ts = pd.Timestamp("2026-06-30 12:00:00", tz="UTC")
    dt = _to_dt(ts)
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_bt_trade_from_open_populates_fib_and_partial_columns():
    """Audit regression: live trade builder must carry fib + partial-TP metadata."""
    ts = pd.Timestamp("2026-06-30 09:00:00+00:00")
    extra = {
        "leg": "long_bull_strong",
        "regime": "bull_strong",
        "regime_at_entry": "bull_strong",
        "pivot_lb": 5,
        "ext_target_pct": 1.618,
        "sl_buffer_pct": 0.02,
        "fib_diff": 12.5,
        "partial_tp_at_r": 1.0,
        "partial_tp_pct": 0.5,
        "cost_r": 0.03,
    }
    order = Order(
        symbol="XAUUSD.ecn", side=1, qty=0.01,
        intended_entry_bar=ts,
        stop_price=2000.0, take_profit=2050.0, risk_units=5.0,
        tag="fib_v2", bracket_kind="fixed_tp",
        trade_id=uuid.uuid4(), extra=extra,
    )
    fill = Fill("XAUUSD.ecn", 1, 0.01, 2010.0, ts)
    tr = OpenTrade(
        trade_id=order.trade_id, order=order, fill=fill,
        entry_price=2010.0, entry_timestamp=ts,
        side=1, stop_price=2000.0, take_profit=2050.0,
        risk_units=5.0,
    )

    bt = _bt_trade_from_open(
        tr, run_id=uuid.uuid4(),
        strategy_id="fib_v2_xau_ensemble_ptp1r", timeframe="M5",
    )
    assert bt.leg == "long_bull_strong"
    assert bt.regime == "bull_strong"
    assert bt.regime_at_entry == "bull_strong"
    assert bt.pivot_lb == 5
    assert bt.ext_target_pct == 1.618
    assert bt.sl_buffer_pct == 0.02
    assert bt.fib_diff == 12.5
    assert bt.partial_tp_at_r == 1.0
    assert bt.partial_tp_pct == 0.5
    assert bt.partial_taken is False
    assert bt.partial_r == 0.0
    assert bt.partial_fill_price is None
    assert bt.partial_fill_ts is None


def test_bt_trade_from_open_handles_missing_extra_keys():
    """Live trade may have empty extra (legacy/zone strategies). Must not crash."""
    ts = pd.Timestamp("2026-06-30 09:00:00+00:00")
    order = Order(
        symbol="XAUUSD.ecn", side=-1, qty=0.01,
        intended_entry_bar=ts,
        stop_price=2050.0, take_profit=2000.0, risk_units=5.0,
        tag="x", bracket_kind="1R",
        trade_id=uuid.uuid4(), extra={},
    )
    fill = Fill("XAUUSD.ecn", -1, 0.01, 2030.0, ts)
    tr = OpenTrade(
        trade_id=order.trade_id, order=order, fill=fill,
        entry_price=2030.0, entry_timestamp=ts,
        side=-1, stop_price=2050.0, take_profit=2000.0,
        risk_units=5.0,
    )
    bt = _bt_trade_from_open(tr, run_id=uuid.uuid4(), strategy_id="x", timeframe="M5")
    assert bt.leg is None
    assert bt.pivot_lb is None
    assert bt.partial_tp_at_r is None
    assert bt.partial_taken is False  # default not None
