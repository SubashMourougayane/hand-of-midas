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
from bt_engine.core.bar import Bar
from bt_engine.runner.live import (
    _bt_trade_from_open,
    _close_partial_succeeded,
    _close_partial_succeeded_retry,
    _elapsed_m15_bars_fx,
    _find_ticket_by_tag,
    _fx_open_at,
    _leg_owns_position,
    _needs_be_sync,
    _open_trades_from_positions,
    _reconcile_partial_be,
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


def test_close_partial_retry_catches_slow_ack():
    """Slow-ack: open_orders still shows pre-volume on the first read(s), then
    updates. The retry helper must poll until the reduction appears (the
    2026-07-03 orphan bug: single read saw stale vol -> false failure)."""
    class _Bridge:
        def __init__(self, seq): self._seq = list(seq); self._i = 0
        def open_orders(self):
            v = self._seq[min(self._i, len(self._seq) - 1)]; self._i += 1
            return {"555": {"volume": v}} if v is not None else {}
    # reads: stale 0.12, stale 0.12, then reduced 0.06 -> success on 3rd poll
    b = _Bridge([0.12, 0.12, 0.06])
    assert _close_partial_succeeded_retry(b, "555", 0.12, 0.06, attempts=4, backoff_s=0) is True
    # genuine failure: volume never drops
    b2 = _Bridge([0.12, 0.12, 0.12, 0.12])
    assert _close_partial_succeeded_retry(b2, "555", 0.12, 0.06, attempts=4, backoff_s=0) is False
    # position gone entirely -> success
    b3 = _Bridge([0.12, None])
    assert _close_partial_succeeded_retry(b3, "555", 0.12, 0.06, attempts=4, backoff_s=0) is True


def test_sl_at_be_true_within_tolerance():
    assert _sl_at_be({"sl": 4068.31}, 4068.31) is True
    assert _sl_at_be({"sl": 4068.315}, 4068.31, tol=0.01) is True


def test_sl_at_be_false_when_original_distance():
    # SL still at original (far) price → BE modify did NOT apply.
    assert _sl_at_be({"sl": 4010.89}, 4068.31) is False


def test_sl_at_be_false_when_no_position_or_missing_sl():
    assert _sl_at_be(None, 4068.31) is False
    assert _sl_at_be({"volume": 0.01}, 4068.31) is False


# ---------------------------------------------------------------------------
# OPEN slow-ack recovery (2026-07-02 incident).
#
# JustMarkets' DWX EA filled an OPEN but acked slower than the 5s command
# timeout → submit_order raised TimeoutError → crashed the D-leg process AND
# orphaned ticket 2123464608 (0.13 short) that the DB never recorded.
# _find_ticket_by_tag recovers the ticket by matching the order tag against
# each open position's (often truncated) comment.
# ---------------------------------------------------------------------------


class _TagBridge:
    """Fake bridge exposing open_orders() with comment fields."""

    def __init__(self, orders):
        self._orders = orders

    def open_orders(self):
        return self._orders


def test_find_ticket_by_tag_matches_truncated_comment():
    tag = "intraday_d_short_2026-07-02T17:15:00+00:00"
    bridge = _TagBridge({
        "2123464608": {"symbol": "XAUUSD.ecn", "comment": "intraday_d_short_2026-07-02T17:"},
        "999": {"symbol": "XAUUSD.ecn", "comment": "intraday_a_long_2026-07-01T20:"},
    })
    assert _find_ticket_by_tag(bridge, tag) == "2123464608"


def test_find_ticket_by_tag_none_when_no_match():
    bridge = _TagBridge({
        "999": {"symbol": "XAUUSD.ecn", "comment": "something_else"},
    })
    assert _find_ticket_by_tag(bridge, "intraday_d_short_2026") is None


def test_find_ticket_by_tag_ignores_short_prefix_collisions():
    # 'intra' shares <8 chars — must NOT match.
    bridge = _TagBridge({
        "1": {"symbol": "XAUUSD.ecn", "comment": "intra_something_totally_different"},
    })
    assert _find_ticket_by_tag(bridge, "intraday_d_short_x") is None


def test_find_ticket_by_tag_handles_nested_orders_key():
    tag = "intraday_a_long_2026-07-01T20:30:00+00:00"
    bridge = _TagBridge({"orders": {
        "2118599832": {"comment": "intraday_a_long_2026-07-01T20:"},
    }})
    assert _find_ticket_by_tag(bridge, tag) == "2118599832"


def test_find_ticket_by_tag_empty_tag_returns_none():
    bridge = _TagBridge({"1": {"comment": "x"}})
    assert _find_ticket_by_tag(bridge, "") is None


# ---------------------------------------------------------------------------
# Per-leg position adoption (prevents A+D double-managing each other).
# ---------------------------------------------------------------------------


def test_leg_owns_position_by_comment():
    long_pos = {"comment": "intraday_a_long_2026-07-01T20:", "type": "BUY"}
    short_pos = {"comment": "intraday_d_short_2026-07-02T17:", "type": "SELL"}
    # A leg owns the long, not the short.
    assert _leg_owns_position("fib_v2_intraday_a", long_pos, 1) is True
    assert _leg_owns_position("fib_v2_intraday_a", short_pos, -1) is False
    # D leg owns the short, not the long.
    assert _leg_owns_position("fib_v2_intraday_d", short_pos, -1) is True
    assert _leg_owns_position("fib_v2_intraday_d", long_pos, 1) is False


def test_leg_owns_position_falls_back_to_side_without_comment():
    assert _leg_owns_position("fib_v2_intraday_a", {"type": "BUY"}, 1) is True
    assert _leg_owns_position("fib_v2_intraday_a", {"type": "SELL"}, -1) is False
    assert _leg_owns_position("fib_v2_intraday_d", {"type": "SELL"}, -1) is True


def test_leg_owns_position_combined_adopts_all():
    assert _leg_owns_position("fib_v2_intraday_a_plus_d", {"type": "SELL"}, -1) is True
    assert _leg_owns_position(None, {"type": "BUY"}, 1) is True


def test_adopt_breakeven_sl_recovers_risk_from_db():
    """Regression 2026-07-03 ticket 2125844421: broker SL trailed to breakeven
    (sl==entry) → live stop distance 0 → adoption dropped the position, stranding
    it unmanaged on restart. Fix: recover the original risk_units from the DB via
    risk_lookup instead of dropping."""
    pos = {
        "ticket": "2125844421", "type": "SELL", "volume": 0.18,
        "open_price": 4185.89, "sl": 4185.89, "tp": 4137.22,  # sl == entry (BE)
        "comment": "intraday_d_short_2026-07-03T14:",
        "open_time": "2026.07.03 14:45:05",
    }
    # Without a lookup → dropped (no usable risk).
    dropped = _open_trades_from_positions([pos], symbol="XAUUSD.ecn", strategy_id="fib_v2_intraday_d")
    assert dropped == []
    # With a lookup returning the original stop distance → adopted + managed.
    adopted = _open_trades_from_positions(
        [pos], symbol="XAUUSD.ecn", strategy_id="fib_v2_intraday_d",
        risk_lookup=lambda tk: 48.6672 if tk == "2125844421" else None,
    )
    assert len(adopted) == 1
    tr = adopted[0]
    assert tr.side == -1
    assert tr.broker_ticket == "2125844421"
    assert abs(tr.risk_units - 48.6672) < 1e-6  # recovered, not 0
    assert tr.order.extra["qty_lots"] == 0.18


def test_fx_open_at_weekend_guard():
    T = lambda s: pd.Timestamp(s, tz="UTC").to_pydatetime()
    assert _fx_open_at(T("2026-07-01 12:00")) is True    # Wed
    assert _fx_open_at(T("2026-07-04 12:00")) is False   # Sat
    assert _fx_open_at(T("2026-07-05 12:00")) is False   # Sun before 21:00
    assert _fx_open_at(T("2026-07-05 21:30")) is True    # Sun after 21:00 (reopen)
    assert _fx_open_at(T("2026-07-03 21:00")) is True    # Fri before 22:00
    assert _fx_open_at(T("2026-07-03 22:30")) is False   # Fri after 22:00 (close)


def test_elapsed_m15_bars_weekday():
    # 2026-07-01 (Wed) 12:00 -> 13:00 UTC = 4 M15 closes (12:15,12:30,12:45,13:00).
    start = pd.Timestamp("2026-07-01 12:00", tz="UTC")
    end = pd.Timestamp("2026-07-01 13:00", tz="UTC")
    assert _elapsed_m15_bars_fx(start, end) == 4


def test_elapsed_m15_bars_excludes_weekend():
    # Fri 2026-07-03 21:00 UTC -> Sun 2026-07-05 21:00 UTC. Only Fri 21:15..22:00
    # (4 closes, market shuts 22:00) count; all of Sat + Sun-before-21:00 are shut.
    start = pd.Timestamp("2026-07-03 21:00", tz="UTC")
    end = pd.Timestamp("2026-07-05 21:00", tz="UTC")
    n = _elapsed_m15_bars_fx(start, end)
    assert n == 4, n


def test_adopt_seeds_bars_held_from_true_age():
    """2026-07-06 fix: a re-adopted position seeds bars_held from real elapsed
    FX-open M15 bars, so its hold cap honors true age across restarts instead of
    resetting to 0 every adoption (which let A-longs run 74h/119h past a 12h cap).
    open_time is broker-local (UTC+3 here); with a recent open the seed is > 0."""
    import datetime as _dt
    # open ~2h ago in broker-local time. server_utc_offset_hours=0 for the test so
    # the parsed open_time is treated as UTC; 2h => ~8 M15 bars (market open).
    now = _dt.datetime.now(_dt.timezone.utc)
    open_utc = now - _dt.timedelta(hours=2)
    # Skip if the 2h window straddles a weekend edge (keeps the test deterministic).
    pos = {
        "ticket": "9999001", "type": "BUY", "volume": 0.03,
        "open_price": 4100.0, "sl": 4080.0, "tp": 4200.0,
        "comment": "intraday_a_long_test",
        "open_time": open_utc.strftime("%Y.%m.%d %H:%M:%S"),
    }
    adopted = _open_trades_from_positions(
        [pos], symbol="XAUUSD.ecn", strategy_id="fib_v2_intraday_a",
        server_utc_offset_hours=0,
    )
    assert len(adopted) == 1
    tr = adopted[0]
    # In market hours a 2h-old trade seeds ~8 bars (not 0). If the window was fully
    # weekend-shut it'd be 0 — accept >=0 but assert it's not silently negative and
    # that a clearly-open recent window seeds > 0 when _fx_open_at(now) is True.
    if _fx_open_at(now) and _fx_open_at(open_utc):
        assert tr.bars_held >= 6, tr.bars_held
    assert tr.bars_held >= 0


# ---------------------------------------------------------------------------
# Per-bar breakeven self-heal (2026-07-08 ticket 2138348483).
#
# on_partial_tp is one-shot: a CLOSE_PARTIAL whose ack timed out can book the
# partial on the broker yet skip the SL->BE modify, orphaning the runner on its
# original (far) stop with no retry. _reconcile_partial_be re-issues the BE
# modify every bar from broker ground truth. _needs_be_sync is the pure guard.
# ---------------------------------------------------------------------------


def test_needs_be_sync_true_when_partial_done_and_sl_far():
    # vol halved (0.09 -> 0.04) AND sl still original (far above entry 4128.34).
    pos = {"volume": 0.04, "sl": 4149.31}
    assert _needs_be_sync(pos, 4128.34, 0.09) is True


def test_needs_be_sync_false_when_already_at_be():
    # partial done but SL already at entry → idempotent skip.
    pos = {"volume": 0.04, "sl": 4128.34}
    assert _needs_be_sync(pos, 4128.34, 0.09) is False


def test_needs_be_sync_false_when_volume_still_full():
    # partial NOT reflected on broker → must NOT touch a full position's SL.
    pos = {"volume": 0.09, "sl": 4149.31}
    assert _needs_be_sync(pos, 4128.34, 0.09) is False


def test_needs_be_sync_false_when_no_position_or_missing_fields():
    assert _needs_be_sync(None, 4128.34, 0.09) is False
    assert _needs_be_sync({"sl": 4149.31}, 4128.34, 0.09) is False  # no volume
    assert _needs_be_sync({"volume": 0.04, "sl": 4149.31}, 4128.34, 0.0) is False  # full_qty=0


def _partial_trade(*, ticket="2138348483", entry=4128.34, full_qty=0.09,
                   tp=3946.20, partial=True) -> OpenTrade:
    ts = pd.Timestamp("2026-07-08 05:15:00+00:00")
    order = Order(
        symbol="XAUUSD.ecn", side=-1, qty=full_qty, intended_entry_bar=ts,
        stop_price=entry + 20.97, take_profit=tp, risk_units=34.56,
        tag="intraday_d_short", bracket_kind="fixed_tp", trade_id=uuid.uuid4(),
        extra={"partial_tp_at_r": 1.0, "partial_tp_pct": 0.5},
    )
    fill = Fill("XAUUSD.ecn", -1, full_qty, entry, ts)
    tr = OpenTrade(
        trade_id=order.trade_id, order=order, fill=fill,
        entry_price=entry, entry_timestamp=ts, side=-1,
        stop_price=entry, take_profit=tp, risk_units=34.56, broker_ticket=ticket,
    )
    tr.partial_taken = partial  # walker sets this True before on_partial_tp
    return tr


def _bar_now() -> Bar:
    return Bar(
        symbol="XAUUSD.ecn", timeframe="M15",
        timestamp=pd.Timestamp("2026-07-08 08:30:00+00:00"),
        open=4090.0, high=4092.0, low=4055.0, close=4056.72, volume=100.0,
    )


class _ReconBridge:
    """Fake DWX bridge: open_orders() from a mutable {ticket: {volume, sl}} map."""

    def __init__(self, positions):
        self._positions = positions

    def open_orders(self):
        return {t: dict(p) for t, p in self._positions.items()}

    def set_sl(self, ticket, sl):
        self._positions[ticket]["sl"] = sl


class _ReconBroker:
    def __init__(self, *, raise_on_modify=False, bridge=None, apply_on_raise=False):
        self.calls = []
        self._raise = raise_on_modify
        self._bridge = bridge
        self._apply_on_raise = apply_on_raise

    def modify(self, ticket, *, sl, tp=0.0):
        self.calls.append((ticket, sl, tp))
        if self._apply_on_raise and self._bridge is not None:
            self._bridge.set_sl(ticket, sl)  # slow-ack: applied despite raising
        if self._raise:
            raise TimeoutError("No response within 5.0s")


def test_reconcile_repairs_orphaned_breakeven():
    # ticket 2138348483 real case: 0.09 -> 0.04, SL stuck at original 4149.31.
    bridge = _ReconBridge({"2138348483": {"volume": 0.04, "sl": 4149.31}})
    broker = _ReconBroker()
    events = []
    tr = _partial_trade()
    n = _reconcile_partial_be(
        [tr], bridge, broker, _bar_now(),
        persist_event=lambda *a: events.append(a),
    )
    assert n == 1
    assert broker.calls == [("2138348483", 4128.34, 3946.20)]
    assert events and events[0][0] == "BE_RECONCILE_APPLIED"


def test_reconcile_noop_when_already_at_be():
    bridge = _ReconBridge({"42": {"volume": 0.04, "sl": 4128.34}})
    broker = _ReconBroker()
    tr = _partial_trade(ticket="42")
    n = _reconcile_partial_be([tr], bridge, broker, _bar_now())
    assert n == 0
    assert broker.calls == []


def test_reconcile_skips_when_partial_not_taken():
    bridge = _ReconBridge({"42": {"volume": 0.09, "sl": 4149.31}})
    broker = _ReconBroker()
    tr = _partial_trade(ticket="42", partial=False)
    assert _reconcile_partial_be([tr], bridge, broker, _bar_now()) == 0
    assert broker.calls == []


def test_reconcile_skips_when_no_broker_ticket():
    bridge = _ReconBridge({})
    broker = _ReconBroker()
    tr = _partial_trade(ticket="42")
    tr.broker_ticket = None
    assert _reconcile_partial_be([tr], bridge, broker, _bar_now()) == 0
    assert broker.calls == []


def test_reconcile_does_not_touch_full_size_position():
    # partial_taken flagged but broker still full volume (partial genuinely failed)
    # → must NOT move SL to BE on the full position.
    bridge = _ReconBridge({"42": {"volume": 0.09, "sl": 4149.31}})
    broker = _ReconBroker()
    tr = _partial_trade(ticket="42")
    assert _reconcile_partial_be([tr], bridge, broker, _bar_now()) == 0
    assert broker.calls == []


def test_reconcile_treats_slow_ack_modify_as_applied():
    # modify() raises TimeoutError but the EA DID apply it → SL reads BE on re-read.
    bridge = _ReconBridge({"42": {"volume": 0.04, "sl": 4149.31}})
    broker = _ReconBroker(raise_on_modify=True, bridge=bridge, apply_on_raise=True)
    events = []
    tr = _partial_trade(ticket="42")
    n = _reconcile_partial_be(
        [tr], bridge, broker, _bar_now(),
        persist_event=lambda *a: events.append(a),
    )
    assert n == 1
    assert events[0][0] == "BE_RECONCILE_APPLIED"


def test_reconcile_reports_failure_when_modify_truly_fails():
    # modify() raises AND SL never reaches BE → FAILED event, retry deferred to next bar.
    bridge = _ReconBridge({"42": {"volume": 0.04, "sl": 4149.31}})
    broker = _ReconBroker(raise_on_modify=True, bridge=bridge, apply_on_raise=False)
    events = []
    tr = _partial_trade(ticket="42")
    n = _reconcile_partial_be(
        [tr], bridge, broker, _bar_now(),
        persist_event=lambda *a: events.append(a),
    )
    assert n == 0
    assert events[0][0] == "BE_RECONCILE_FAILED"
