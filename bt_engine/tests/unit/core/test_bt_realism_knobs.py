"""BT realism knob tests (P0-P2 from L99 BT-vs-Live parity audit).

Every knob asserted deterministic + no look-ahead. These are BT-only execution
realism additions; strategy code untouched. Defaults (all 0.0) reproduce the
ideal-fill baseline, so parity tests remain green.

Covered:
  P1a  entry slip direction (simulator)
  P1a  SL slip worse-fill (bracket)
  P1a  TP slip worse-fill (bracket)
  P1b  overnight swap deduction at 22:00 UTC rollover
  P1c  (engine cap tested in engine tests; here we test bracket-level knobs)
  P2a  gap-extra SL slip only when bar follows a gap > threshold
  P2d  partial-TP-fail keeps SL at original (remainder exposed)
"""
from __future__ import annotations

import uuid

import pandas as pd

from bt_engine.core.bar import Bar
from bt_engine.core.bracket import walk_bracket_on_bar
from bt_engine.core.order import Fill, OpenTrade, Order
from bt_engine.execution.simulator import BTExecutionModel


def _long_trade(entry=100.0, risk=1.0, tp=110.0, qty=0.10,
                partial=False, ts="2026-01-01 10:00:00") -> OpenTrade:
    extra = {}
    if partial:
        extra = {"partial_tp_at_r": 1.0, "partial_tp_pct": 0.5}
    order = Order(
        symbol="XAUUSD.ecn", side=1, qty=qty,
        intended_entry_bar=pd.Timestamp(ts, tz="UTC"),
        stop_price=entry - risk, take_profit=tp, risk_units=risk,
        tag="t", bracket_kind="1R", trade_id=uuid.uuid4(), extra=extra,
    )
    fill = Fill(symbol="XAUUSD.ecn", side=1, qty=qty, price=entry,
                fill_timestamp=order.intended_entry_bar)
    return OpenTrade(
        trade_id=order.trade_id, order=order, fill=fill,
        entry_price=entry, entry_timestamp=order.intended_entry_bar,
        side=1, stop_price=order.stop_price, take_profit=tp, risk_units=risk,
    )


def _bar(ts, high, low, close, open_=None) -> Bar:
    return Bar(symbol="XAUUSD.ecn", timeframe="M15",
               timestamp=pd.Timestamp(ts, tz="UTC"),
               open=open_ if open_ is not None else close,
               high=high, low=low, close=close, volume=100.0)


# ── P1a entry slip (simulator) ──

def test_entry_slip_pushes_fill_against_long() -> None:
    order = Order(symbol="XAUUSD.ecn", side=1, qty=0.1,
                  intended_entry_bar=pd.Timestamp("2026-01-01 10:00:00", tz="UTC"),
                  stop_price=99.0, take_profit=110.0, risk_units=1.0,
                  tag="t", bracket_kind="1R", trade_id=uuid.uuid4())
    bar = _bar("2026-01-01 10:00:00", high=101, low=99, close=100, open_=100.0)
    ideal = BTExecutionModel(entry_slip_pips=0.0).simulate_fill(order, bar)
    slipped = BTExecutionModel(entry_slip_pips=0.30).simulate_fill(order, bar)
    assert ideal.price == 100.0
    # Long: slip pushes fill UP (worse).
    assert slipped.price == 100.30


def test_entry_slip_pushes_fill_against_short() -> None:
    order = Order(symbol="XAUUSD.ecn", side=-1, qty=0.1,
                  intended_entry_bar=pd.Timestamp("2026-01-01 10:00:00", tz="UTC"),
                  stop_price=101.0, take_profit=90.0, risk_units=1.0,
                  tag="t", bracket_kind="1R", trade_id=uuid.uuid4())
    bar = _bar("2026-01-01 10:00:00", high=101, low=99, close=100, open_=100.0)
    slipped = BTExecutionModel(entry_slip_pips=0.30).simulate_fill(order, bar)
    # Short: slip pushes fill DOWN (worse).
    assert slipped.price == 99.70


def test_entry_slip_deterministic() -> None:
    order = Order(symbol="XAUUSD.ecn", side=1, qty=0.1,
                  intended_entry_bar=pd.Timestamp("2026-01-01 10:00:00", tz="UTC"),
                  stop_price=99.0, take_profit=110.0, risk_units=1.0,
                  tag="t", bracket_kind="1R", trade_id=uuid.uuid4())
    bar = _bar("2026-01-01 10:00:00", high=101, low=99, close=100, open_=100.0)
    m = BTExecutionModel(entry_slip_pips=0.30)
    assert m.simulate_fill(order, bar).price == m.simulate_fill(order, bar).price


# ── P1a SL slip (bracket) ──

def test_sl_slip_worse_fill_long() -> None:
    tr = _long_trade(entry=100.0, risk=1.0)  # sl=99
    # bar closes below sl → SL hit
    bar = _bar("2026-01-01 10:15:00", high=100, low=98, close=98.5)
    # No slip: exit at 99, R = -1
    tr0 = _long_trade(entry=100.0, risk=1.0)
    oc0 = walk_bracket_on_bar(tr0, bar)
    assert oc0.reason == "SL"
    assert oc0.exit_price == 99.0
    assert abs(oc0.bracket_1r_outcome - (-1.0)) < 1e-9
    # With 0.50 slip: exit at 98.5, R = -1.5
    oc1 = walk_bracket_on_bar(tr, bar, sl_slip_pips=0.50)
    assert oc1.exit_price == 98.5
    assert abs(oc1.bracket_1r_outcome - (-1.5)) < 1e-9


def test_tp_slip_worse_fill_long() -> None:
    tr = _long_trade(entry=100.0, risk=1.0, tp=110.0)
    bar = _bar("2026-01-01 10:15:00", high=112, low=100, close=111)  # TP hit
    oc = walk_bracket_on_bar(tr, bar, tp_slip_pips=0.50)
    # TP slip: exit at 110 - 0.50 = 109.50 → R = 9.5
    assert oc.reason == "TP"
    assert oc.exit_price == 109.50
    assert abs(oc.bracket_1r_outcome - 9.5) < 1e-9


# ── P1b overnight swap ──

def test_overnight_swap_deducted_at_22h() -> None:
    tr = _long_trade(entry=100.0, risk=1.0, qty=1.0)  # 1 lot
    # bar at 22:00 UTC, trade still open (no exit — mid-range close)
    bar_2200 = _bar("2026-01-01 22:00:00", high=101, low=99.5, close=100.5)
    swap = {1: -0.71, -1: -0.84}
    walk_bracket_on_bar(tr, bar_2200, swap_per_lot_per_night=swap)
    # accrued_swap_r = swap_per_lot / (contract × risk) = -0.71 / (100 × 1) = -0.0071
    assert abs(tr.accrued_swap_r - (-0.0071)) < 1e-9


def test_no_swap_off_rollover_hour() -> None:
    tr = _long_trade(entry=100.0, risk=1.0, qty=1.0)
    bar_1000 = _bar("2026-01-01 10:00:00", high=101, low=99.5, close=100.5)
    swap = {1: -0.71, -1: -0.84}
    walk_bracket_on_bar(tr, bar_1000, swap_per_lot_per_night=swap)
    assert tr.accrued_swap_r == 0.0


def test_swap_baked_into_outcome() -> None:
    tr = _long_trade(entry=100.0, risk=1.0, qty=1.0)
    swap = {1: -0.71, -1: -0.84}
    # First bar 22:00 accrues swap, trade open
    walk_bracket_on_bar(tr, _bar("2026-01-01 22:00:00", 101, 99.5, 100.5),
                        swap_per_lot_per_night=swap)
    # Second bar 23:15 (hour != 22 → no extra swap), SL hit
    oc = walk_bracket_on_bar(tr, _bar("2026-01-01 23:15:00", 100, 98, 98.5),
                             swap_per_lot_per_night=swap)
    # outcome = -1 (SL) + swap_r (-0.0071 from the single 22:00 bar)
    assert abs(oc.bracket_1r_outcome - (-1.0071)) < 1e-9


# ── P2a gap-extra SL slip ──

def test_gap_extra_slip_applied_after_gap() -> None:
    tr = _long_trade(entry=100.0, risk=1.0)  # sl=99
    bar = _bar("2026-01-05 10:00:00", high=100, low=97, close=97.5)  # SL hit
    # gap > threshold → extra 5.0 slip on top → exit 99 - 5 = 94 → R big negative
    oc = walk_bracket_on_bar(
        tr, bar,
        bar_gap_seconds=200000,  # > 172800 (weekend)
        gap_threshold_seconds=172800,
        gap_extra_slip_pips=5.0,
    )
    assert oc.exit_price == 94.0  # 99 - 5.0 gap slip
    assert abs(oc.bracket_1r_outcome - (-6.0)) < 1e-9


def test_no_gap_extra_slip_when_gap_below_threshold() -> None:
    tr = _long_trade(entry=100.0, risk=1.0)
    bar = _bar("2026-01-01 10:15:00", high=100, low=97, close=97.5)
    oc = walk_bracket_on_bar(
        tr, bar,
        bar_gap_seconds=900,  # 15min < threshold
        gap_threshold_seconds=172800,
        gap_extra_slip_pips=5.0,
    )
    # No gap slip → plain SL at 99, R = -1
    assert oc.exit_price == 99.0
    assert abs(oc.bracket_1r_outcome - (-1.0)) < 1e-9


# ── P2d partial-TP fail ──

def test_partial_tp_fail_keeps_sl_original() -> None:
    # fail_pct=1.0 → ALWAYS fail → SL never moves to BE
    tr = _long_trade(entry=100.0, risk=1.0, tp=110.0, partial=True)
    orig_sl = tr.stop_price  # 99
    # bar crosses +1R (high >= 101) → partial fires
    bar = _bar("2026-01-01 10:15:00", high=101.5, low=100, close=101)
    walk_bracket_on_bar(tr, bar, partial_tp_fail_pct=1.0)
    assert tr.partial_taken is True
    assert tr.partial_filled_r == 0.5
    # SL NOT moved to BE — stays at original 99 (remainder exposed)
    assert tr.stop_price == orig_sl


def test_partial_tp_success_moves_sl_to_be() -> None:
    tr = _long_trade(entry=100.0, risk=1.0, tp=110.0, partial=True)
    bar = _bar("2026-01-01 10:15:00", high=101.5, low=100, close=101)
    walk_bracket_on_bar(tr, bar, partial_tp_fail_pct=0.0)  # never fail
    assert tr.partial_taken is True
    # SL moved to BE (entry)
    assert tr.stop_price == 100.0
