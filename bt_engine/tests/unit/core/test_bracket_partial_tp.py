"""Unit tests for partial-TP safety net in walk_bracket_on_bar.

Verifies exact research semantics (research/fib_retrace/safety_net_sweep.simulate_with_safety):
- On bar where MFE >= partial_tp_at_r: lock partial_tp_pct * partial_tp_at_r R,
  move stop to entry (BE on remainder).
- Subsequent SL at BE returns 0.0 + partial_r on remainder.
- Subsequent TP returns tp_r + partial_r.
- Subsequent TIMEOUT returns timeout_r + partial_r.
- partial_tp_at_r=None preserves baseline behaviour (no partial).
- Idempotent: partial only taken once.
- Causality: partial fill ts = the bar that crossed trigger (no peek).
"""
from __future__ import annotations

import uuid

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.core.bracket import walk_bracket_on_bar
from bt_engine.core.order import Fill, OpenTrade, Order


def _bar(ts: str, *, o: float, h: float, l: float, c: float) -> Bar:
    return Bar("X", "M5", pd.Timestamp(ts), o, h, l, c, 1.0)


def _trade(
    side: int,
    *,
    entry: float,
    stop: float,
    tp: float | None,
    risk: float = 10.0,
    partial_tp_at_r: float | None = None,
    partial_tp_pct: float = 0.5,
) -> OpenTrade:
    extra = {}
    if partial_tp_at_r is not None:
        extra["partial_tp_at_r"] = partial_tp_at_r
        extra["partial_tp_pct"] = partial_tp_pct
    order = Order(
        symbol="X", side=side, qty=1.0,
        intended_entry_bar=pd.Timestamp("2026-06-29T00:00:00Z"),
        stop_price=stop, take_profit=tp, risk_units=risk,
        tag="t", bracket_kind="1R",
        extra=extra,
    )
    fill = Fill("X", side, 1.0, entry, pd.Timestamp("2026-06-29T00:00:00Z"))
    return OpenTrade(
        trade_id=uuid.uuid4(), order=order, fill=fill,
        entry_price=entry, entry_timestamp=fill.fill_timestamp,
        side=side, stop_price=stop, take_profit=tp, risk_units=risk,
    )


# ---------- baseline preservation ----------

def test_partial_tp_none_is_baseline_sl():
    """No partial_tp_at_r → identical -1R outcome."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1100.0)
    bar = _bar("2026-06-29T00:05:00Z", o=1000, h=1005, l=985, c=988)
    o = walk_bracket_on_bar(tr, bar)
    assert o is not None
    assert o.reason == "SL"
    assert o.bracket_1r_outcome == pytest.approx(-1.0)
    assert tr.partial_taken is False


def test_partial_tp_none_is_baseline_tp():
    """No partial_tp_at_r → exact tp_R outcome."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1010.0)
    bar = _bar("2026-06-29T00:05:00Z", o=1000, h=1011, l=1000, c=1010.5)
    o = walk_bracket_on_bar(tr, bar)
    assert o.bracket_1r_outcome == pytest.approx(1.0)


# ---------- partial trigger ----------

def test_partial_tp_long_triggers_on_mfe_cross():
    """MFE crosses +1R on bar → partial taken, stop moves to entry, partial_r=0.5."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1100.0, partial_tp_at_r=1.0)
    # high reaches 1010 (= entry + 1.0 * risk_units) → mfe=1.0 → trigger
    bar = _bar("2026-06-29T00:05:00Z", o=1000, h=1010, l=1000, c=1005)
    o = walk_bracket_on_bar(tr, bar)
    assert o is None  # close didn't hit TP/SL, trade continues
    assert tr.partial_taken is True
    assert tr.partial_filled_r == pytest.approx(0.5)  # 0.5 * 1.0R
    assert tr.partial_fill_price == pytest.approx(1010.0)
    assert tr.partial_fill_timestamp == pd.Timestamp("2026-06-29T00:05:00Z")
    assert tr.stop_price == pytest.approx(1000.0)  # moved to entry (BE)


def test_partial_tp_short_triggers_on_mfe_cross():
    """SHORT mirror: MFE = (entry - low) / risk."""
    tr = _trade(-1, entry=1000.0, stop=1010.0, tp=900.0, partial_tp_at_r=1.0)
    bar = _bar("2026-06-29T00:05:00Z", o=1000, h=1000, l=990, c=995)
    o = walk_bracket_on_bar(tr, bar)
    assert o is None
    assert tr.partial_taken is True
    assert tr.partial_filled_r == pytest.approx(0.5)
    assert tr.partial_fill_price == pytest.approx(990.0)  # entry - 1.0 * risk
    assert tr.stop_price == pytest.approx(1000.0)


def test_partial_tp_below_trigger_no_action():
    """MFE doesn't reach trigger → no partial."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1100.0, partial_tp_at_r=2.0)
    bar = _bar("2026-06-29T00:05:00Z", o=1000, h=1015, l=999, c=1010)
    o = walk_bracket_on_bar(tr, bar)
    assert o is None
    assert tr.partial_taken is False
    assert tr.stop_price == pytest.approx(990.0)  # unchanged


# ---------- subsequent exits ----------

def test_partial_tp_then_sl_be_returns_partial_only():
    """After partial taken at BE, SL_BE outcome = 0 + partial_r = 0.5."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1100.0, partial_tp_at_r=1.0)
    # bar 1: trigger partial
    walk_bracket_on_bar(tr, _bar("2026-06-29T00:05:00Z", o=1000, h=1010, l=1000, c=1005))
    assert tr.partial_taken
    # bar 2: close drops below BE
    o = walk_bracket_on_bar(tr, _bar("2026-06-29T00:10:00Z", o=1005, h=1006, l=998, c=999))
    assert o is not None
    assert o.reason == "SL_BE"
    assert o.exit_price == pytest.approx(1000.0)
    assert o.bracket_1r_outcome == pytest.approx(0.5)  # 0 on remainder + 0.5 partial


def test_partial_tp_then_tp_returns_tp_plus_partial():
    """After partial, hitting TP gives tp_R + partial_r = (target_r) + 0.5."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1020.0, partial_tp_at_r=1.0)  # tp = +2R
    walk_bracket_on_bar(tr, _bar("2026-06-29T00:05:00Z", o=1000, h=1010, l=1000, c=1005))
    assert tr.partial_taken
    o = walk_bracket_on_bar(tr, _bar("2026-06-29T00:10:00Z", o=1005, h=1022, l=1004, c=1020.5))
    assert o is not None
    assert o.reason == "TP"
    assert o.exit_price == pytest.approx(1020.0)
    # tp_r = (1020-1000)/10 = 2.0; outcome = 2.0 + 0.5 = 2.5
    assert o.bracket_1r_outcome == pytest.approx(2.5)


def test_partial_tp_then_timeout_returns_timeout_plus_partial():
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1100.0, partial_tp_at_r=1.0)
    walk_bracket_on_bar(tr, _bar("2026-06-29T00:05:00Z", o=1000, h=1010, l=1000, c=1005))
    o = walk_bracket_on_bar(
        tr, _bar("2026-06-29T00:10:00Z", o=1005, h=1006, l=1001, c=1003),
        max_bars_held=2,
    )
    assert o is not None
    assert o.reason == "TIMEOUT"
    # timeout_r = (1003-1000)/10 = 0.3; total = 0.3 + 0.5 = 0.8
    assert o.bracket_1r_outcome == pytest.approx(0.8)


def test_partial_tp_idempotent():
    """Once partial taken, subsequent MFE crossings don't re-fire."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1100.0, partial_tp_at_r=1.0)
    walk_bracket_on_bar(tr, _bar("2026-06-29T00:05:00Z", o=1000, h=1010, l=1000, c=1005))
    walk_bracket_on_bar(tr, _bar("2026-06-29T00:10:00Z", o=1005, h=1020, l=1004, c=1015))
    assert tr.partial_taken
    assert tr.partial_filled_r == pytest.approx(0.5)  # not 1.0


def test_partial_tp_same_bar_trigger_and_sl():
    """Trigger AND original-SL on same bar: partial fires (MFE crossed first via high),
    stop moves to BE, then close hits ORIGINAL stop. Original stop is now BELOW BE,
    so it's stale — only BE matters. close=985 hits BE (close <= 1000) → SL_BE."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1100.0, partial_tp_at_r=1.0)
    bar = _bar("2026-06-29T00:05:00Z", o=1000, h=1010, l=985, c=988)
    o = walk_bracket_on_bar(tr, bar)
    assert tr.partial_taken
    assert tr.stop_price == pytest.approx(1000.0)  # moved to BE
    assert o is not None
    assert o.reason == "SL_BE"
    assert o.bracket_1r_outcome == pytest.approx(0.5)  # 0 + 0.5


def test_partial_tp_two_r_target():
    """Validate ptp+2R: lock 1.0R partial when MFE crosses 2.0R."""
    tr = _trade(1, entry=1000.0, stop=990.0, tp=1030.0, partial_tp_at_r=2.0)  # tp = +3R
    # bar high 1020 → mfe = 2.0 → trigger
    walk_bracket_on_bar(tr, _bar("2026-06-29T00:05:00Z", o=1000, h=1020, l=1000, c=1015))
    assert tr.partial_taken
    assert tr.partial_filled_r == pytest.approx(1.0)  # 0.5 * 2.0R
    assert tr.partial_fill_price == pytest.approx(1020.0)
