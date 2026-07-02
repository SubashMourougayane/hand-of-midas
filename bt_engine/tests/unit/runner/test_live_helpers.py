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
from bt_engine.runner.live import (
    _bt_trade_from_open,
    _close_partial_succeeded,
    _sl_at_be,
    _to_dt,
)


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


# ---------------------------------------------------------------------------
# Partial-TP slow-ack recovery (2026-07-02 bug).
#
# JustMarkets' DWX EA executed CLOSE_PARTIAL / MODIFY but acked slower than the
# 5s command wait. The runner raised TimeoutError and logged PARTIAL_TP_CLOSE_FAILED,
# leaving DB partial_taken=False and SL at full distance while the broker had
# actually halved volume. These helpers decide success from BROKER GROUND TRUTH
# (open_orders volume / SL), not from whether the command acked in time.
# ---------------------------------------------------------------------------


def test_close_partial_succeeded_when_volume_halved():
    # pre 0.02 → post 0.01, requested close 0.01 → success despite ack timeout.
    assert _close_partial_succeeded(0.02, {"volume": 0.01}, 0.01) is True


def test_close_partial_succeeded_when_position_gone():
    # Position no longer open → the close (over-)filled → success.
    assert _close_partial_succeeded(0.02, None, 0.01) is True


def test_close_partial_failed_when_volume_unchanged():
    # Volume didn't move → genuine failure, must NOT claim success.
    assert _close_partial_succeeded(0.02, {"volume": 0.02}, 0.01) is False


def test_close_partial_failed_when_pre_volume_unknown():
    # Can't verify (no pre snapshot) → conservative: do not claim success.
    assert _close_partial_succeeded(None, {"volume": 0.01}, 0.01) is False


def test_close_partial_accepts_partial_shrink_at_least_half():
    # EA closed only part of the requested qty but ≥ half → still counts.
    assert _close_partial_succeeded(0.02, {"volume": 0.015}, 0.01) is True
    # less than half the requested reduction → not enough evidence.
    assert _close_partial_succeeded(0.02, {"volume": 0.018}, 0.01) is False


def test_sl_at_be_true_within_tolerance():
    assert _sl_at_be({"sl": 4068.31}, 4068.31) is True
    assert _sl_at_be({"sl": 4068.315}, 4068.31, tol=0.01) is True


def test_sl_at_be_false_when_original_distance():
    # SL still at original (far) price → BE modify did NOT apply.
    assert _sl_at_be({"sl": 4010.89}, 4068.31) is False


def test_sl_at_be_false_when_no_position_or_missing_sl():
    assert _sl_at_be(None, 4068.31) is False
    assert _sl_at_be({"volume": 0.01}, 4068.31) is False
