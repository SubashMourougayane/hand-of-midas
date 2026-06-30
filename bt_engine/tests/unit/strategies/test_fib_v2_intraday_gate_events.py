"""Phase 1E: Gate-decision event emission tests (Option D instrumentation).

Verifies every gate site emits the right `GATE_*` event with structured detail,
and that control flow is UNCHANGED by emission (gate emit is pure-write).

Coverage:
  - GATE_PIVOT_DETECTED                  (on_bar pivot loop)
  - GATE_SETUP_BUILT                     (on_bar new-setup loop)
  - GATE_SETUP_REJECT_PIVOT_ORDER        (_build_setup bad ordering)
  - GATE_SETUP_REJECT_DIFF                (_build_setup zero/negative diff)
  - GATE_SETUP_INVALIDATED                (_signal_bar_matches close past fib_100)
  - GATE_SETUP_EXPIRED                    (on_bar walk past max_hold_h)
  - GATE_SIGNAL_ZONE_MISS                 (_signal_bar_matches close out of zone)
  - GATE_SIGNAL_SESSION_FAIL              (_signal_bar_matches off-session)
  - GATE_SIGNAL_CONFIRM_FAIL              (_signal_bar_matches no engulf / no pin)
  - GATE_SIGNAL_STRICT_AFTER_FAIL         (intraday: bar.ts == setup_confirm_ts)
  - GATE_FINALIZE_RISK_INVALID            (_finalize_entry risk<=0)
  - GATE_FINALIZE_RISK_PCT_CAP            (_finalize_entry risk > 2% entry)
  - GATE_FINALIZE_MIN_RISK_FLOOR          (intraday: risk_units < 0.50)
  - GATE_FINALIZE_DEDUP_COLLISION         (intraday: 2nd entry same (ts,side,leg))
  - GATE_SIGNAL_PASSED                    (_signal_bar_matches all green)

Test strategy: drive each gate site directly with synthetic inputs and assert
StrategyEvent buffer matches. Control-flow regression check: re-run existing
dedup test logic and assert identical Order outputs.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.journal.events import JournalEvent
from bt_engine.strategies.fib_v2.config import LegSpec
from bt_engine.strategies.fib_v2.state import FibSetup
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD


# ── helpers ──────────────────────────────────────────────────────────────────

def _bar(ts_iso: str, *, o, h, l, c) -> Bar:
    return Bar(
        symbol="XAUUSD.ecn", timeframe="M15",
        timestamp=pd.Timestamp(ts_iso, tz="UTC"),
        open=o, high=h, low=l, close=c, volume=1.0,
    )


def _long_setup(*, L=2000.0, H=2010.0, sl=1998.0, tp=2026.18,
                confirm_ts="2026-01-01 00:00:00") -> FibSetup:
    diff = H - L
    return FibSetup(
        leg_name="intraday_a_long",
        side=1,
        L=L, H=H, diff=diff,
        fib_382=H - 0.382 * diff,
        fib_786=H - 0.786 * diff,
        fib_100=L,
        tp_price=tp,
        sl_price=sl,
        setup_confirm_ts=pd.Timestamp(confirm_ts, tz="UTC"),
        L_ts=pd.Timestamp("2025-12-31 22:00:00", tz="UTC"),
        H_ts=pd.Timestamp(confirm_ts, tz="UTC"),
    )


def _drain_gates(strat) -> list:
    out = list(strat._gate_buf)
    strat._gate_buf.clear()
    return out


def _seed_regime(state, day_iso="2025-12-31") -> None:
    """Seed RegimeTracker with one prior closed D1 so regime_for() returns features.

    `regime='any'` still requires regime_for() to return non-None — otherwise
    `gate_passes` returns False (no D1 closed yet, no regime evaluable).
    """
    class _D1:
        timestamp = pd.Timestamp(day_iso, tz="UTC")
        high = 2010.0
        low = 1990.0
        close = 2000.0
    state.regime_tracker.update(_D1())


def _types(events) -> list[str]:
    return [e.type for e in events]


# ── _build_setup rejection paths ─────────────────────────────────────────────

def test_build_setup_emits_pivot_order_long_invalid():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    leg = strat.legs[0]
    # LONG requires H_ts > L_ts. Provide reversed.
    L = 2000.0
    H = 2010.0
    L_ts = pd.Timestamp("2026-01-01 02:00:00", tz="UTC")
    H_ts = pd.Timestamp("2026-01-01 01:00:00", tz="UTC")  # before L → invalid
    bar_ts = pd.Timestamp("2026-01-01 03:00:00", tz="UTC")
    out = strat._build_setup(leg, L, L_ts, H, H_ts, _gate_emit_bar_ts=bar_ts)
    assert out is None
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_SETUP_REJECT_PIVOT_ORDER.value]


def test_build_setup_emits_diff_zero():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    leg = strat.legs[0]
    L = 2000.0
    H = 2000.0  # diff == 0
    L_ts = pd.Timestamp("2026-01-01 01:00:00", tz="UTC")
    H_ts = pd.Timestamp("2026-01-01 02:00:00", tz="UTC")
    bar_ts = pd.Timestamp("2026-01-01 03:00:00", tz="UTC")
    out = strat._build_setup(leg, L, L_ts, H, H_ts, _gate_emit_bar_ts=bar_ts)
    assert out is None
    assert _types(_drain_gates(strat)) == [JournalEvent.GATE_SETUP_REJECT_DIFF.value]


def test_build_setup_no_emit_when_bar_ts_omitted():
    """Calling _build_setup without _gate_emit_bar_ts must NOT emit (back-compat)."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    leg = strat.legs[0]
    L_ts = pd.Timestamp("2026-01-01 02:00:00", tz="UTC")
    H_ts = pd.Timestamp("2026-01-01 01:00:00", tz="UTC")
    out = strat._build_setup(leg, 2000.0, L_ts, 2010.0, H_ts)
    assert out is None
    assert _drain_gates(strat) == []


# ── _signal_bar_matches rejection paths ──────────────────────────────────────

def test_signal_bar_zone_miss_emits():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    leg = strat.legs[0]
    setup = _long_setup()  # zone [2002.14, 2006.18] approx
    # bar.close way above fib_382 (not in zone) but above fib_100 (not invalidated)
    bar = _bar("2026-01-01 01:00:00", o=2009.0, h=2009.5, l=2008.5, c=2009.0)
    assert strat._signal_bar_matches(state, bar, leg, setup) is False
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_SIGNAL_ZONE_MISS.value]


def test_signal_bar_invalidation_emits():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    leg = strat.legs[0]
    setup = _long_setup(L=2000.0, H=2010.0)
    # LONG invalidates when close < fib_100 = L = 2000.0
    bar = _bar("2026-01-01 01:00:00", o=1999.5, h=1999.9, l=1998.0, c=1999.0)
    assert strat._signal_bar_matches(state, bar, leg, setup) is False
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_SETUP_INVALIDATED.value]


def test_signal_bar_session_fail_emits():
    """A leg session = london_ny (NY 03-17). Bar at NY hr 20 must fail."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    leg = strat.legs[0]
    setup = _long_setup()
    # Pick UTC ts that converts to NY 20:00 = UTC 01:00 next day (UTC->NY = -5)
    # NY 20:00 → UTC 01:00 next day. Use 2026-01-02 01:00 UTC = NY 20:00 prior.
    # fib zone [2002.14, 2006.18] — pick bar.close inside.
    bar = _bar("2026-01-02 01:00:00", o=2004.0, h=2004.5, l=2003.5, c=2004.0)
    # confirm NY hr
    from bt_engine.strategies.fib_v2.strategy import _ny_hour
    assert _ny_hour(bar.timestamp) == 20
    assert strat._signal_bar_matches(state, bar, leg, setup) is False
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_SIGNAL_SESSION_FAIL.value]


def test_signal_bar_confirm_fail_no_prev_bar_emits():
    """state.prev_open/close are None on first bar → CONFIRM_FAIL fires."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    _seed_regime(state)
    assert state.prev_open is None
    leg = strat.legs[0]
    setup = _long_setup()
    # bar.close in zone, NY hr in session (NY 08:00 UTC 13:00)
    bar = _bar("2026-01-01 13:00:00", o=2004.0, h=2004.5, l=2003.5, c=2004.0)
    assert strat._signal_bar_matches(state, bar, leg, setup) is False
    types = _types(_drain_gates(strat))
    assert JournalEvent.GATE_SIGNAL_CONFIRM_FAIL.value in types


def test_signal_bar_confirm_fail_no_engulf_no_pin_emits():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    _seed_regime(state)
    # prev bar: green (close>open), no engulfing pattern fit for LONG.
    state.prev_open = 2003.0
    state.prev_close = 2003.5  # green
    leg = strat.legs[0]
    setup = _long_setup()
    # bar.close in zone, NY 08:00, but NOT engulfing (prev was green, no bull_eng)
    # AND not a lower pinbar (open close at top of range)
    bar = _bar("2026-01-01 13:00:00", o=2004.0, h=2004.2, l=2003.8, c=2004.1)
    out = strat._signal_bar_matches(state, bar, leg, setup)
    assert out is False
    types = _types(_drain_gates(strat))
    assert JournalEvent.GATE_SIGNAL_CONFIRM_FAIL.value in types


def test_signal_bar_passed_emits():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    _seed_regime(state)
    # prev bar: red (close<open) — required for bull engulfing
    state.prev_open = 2005.0
    state.prev_close = 2004.0  # red
    leg = strat.legs[0]
    setup = _long_setup()
    # bar: bull engulfing — close > open, close >= prev_open, open <= prev_close
    bar = _bar("2026-01-01 13:00:00", o=2003.8, h=2005.5, l=2003.7, c=2005.2)
    assert strat._signal_bar_matches(state, bar, leg, setup) is True
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_SIGNAL_PASSED.value]


def test_signal_bar_regime_fail_emits():
    """No D1 closed → regime_for returns None → gate_passes False → REGIME_FAIL."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()  # NO regime seed
    leg = strat.legs[0]
    setup = _long_setup()
    bar = _bar("2026-01-01 13:00:00", o=2004.0, h=2004.5, l=2003.5, c=2004.0)
    assert strat._signal_bar_matches(state, bar, leg, setup) is False
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_SIGNAL_REGIME_FAIL.value]


def test_signal_bar_strict_after_fail_intraday_emits():
    """Intraday: bar.ts == setup_confirm_ts must reject + emit STRICT_AFTER."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    leg = strat.legs[0]
    confirm_ts_iso = "2026-01-01 13:00:00"
    setup = _long_setup(confirm_ts=confirm_ts_iso)
    bar = _bar(confirm_ts_iso, o=2004.0, h=2004.2, l=2003.5, c=2004.0)
    assert strat._signal_bar_matches(state, bar, leg, setup) is False
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_SIGNAL_STRICT_AFTER_FAIL.value]


# ── _finalize_entry rejection paths ──────────────────────────────────────────

def test_finalize_entry_risk_invalid_emits():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state
    leg = strat.legs[0]
    # LONG with sl_price > entry_price → risk <= 0 → INVALID
    setup = _long_setup(sl=2010.0)  # sl above bar.open
    bar = _bar("2026-01-01 13:00:00", o=2005.0, h=2005.5, l=2004.5, c=2005.0)
    order, ev = strat._finalize_entry(bar, leg, setup)
    assert order is None
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_FINALIZE_RISK_INVALID.value]


def test_finalize_entry_risk_pct_cap_emits():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state
    leg = strat.legs[0]
    # max_risk_pct default 0.02; bar.open=2000 → cap 40. SL 1950 → risk 50 > cap.
    setup = _long_setup(L=1950.0, H=2010.0, sl=1950.0)
    bar = _bar("2026-01-01 13:00:00", o=2000.0, h=2000.5, l=1999.5, c=2000.0)
    order, _ = strat._finalize_entry(bar, leg, setup)
    assert order is None
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_FINALIZE_RISK_PCT_CAP.value]


def test_finalize_entry_min_risk_floor_emits():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state
    leg = strat.legs[0]
    # risk_units = 0.30 < 0.50 floor → MIN_RISK_FLOOR
    setup = _long_setup(L=2000.0, H=2010.0, sl=2000.70)
    bar = _bar("2026-01-01 13:00:00", o=2001.0, h=2001.5, l=2000.5, c=2001.0)
    order, _ = strat._finalize_entry(bar, leg, setup)
    assert order is None
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_FINALIZE_MIN_RISK_FLOOR.value]


def test_finalize_entry_dedup_collision_emits():
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state
    leg = strat.legs[0]
    setup_a = _long_setup(L=2000.0, H=2010.0, sl=1998.0)
    setup_b = _long_setup(L=1999.0, H=2010.5, sl=1997.5)
    bar = _bar("2026-01-01 13:00:00", o=2001.0, h=2001.5, l=2000.5, c=2001.0)
    o1, _ = strat._finalize_entry(bar, leg, setup_a)
    assert o1 is not None
    _drain_gates(strat)  # discard first call's events
    o2, _ = strat._finalize_entry(bar, leg, setup_b)
    assert o2 is None
    types = _types(_drain_gates(strat))
    assert types == [JournalEvent.GATE_FINALIZE_DEDUP_COLLISION.value]


# ── on_bar drains buffer into StepResult.new_events ──────────────────────────

def test_on_bar_drains_gate_buffer_into_new_events():
    """Gate emit during on_bar must surface via StepResult.new_events."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    history = pd.DataFrame(columns=["timestamp", "high", "low", "close"])
    # Feed bar that triggers _setup_invalidated_or_expired path: needs a setup
    # in state.pending_setups first. Inject manually.
    setup = _long_setup(L=2000.0, H=2010.0,
                        confirm_ts="2026-01-01 00:00:00")
    state.pending_setups[strat.legs[0].leg_name] = [setup]

    # Bar past 12h expiry (A leg max_hold_h=12)
    bar = _bar("2026-01-02 00:00:00", o=2005.0, h=2005.5, l=2004.5, c=2005.0)
    result = strat.on_bar(state, bar, history)

    # Buffer must be drained.
    assert strat._gate_buf == []
    # new_events should contain GATE_SETUP_EXPIRED.
    types = [e.type for e in result.new_events]
    assert JournalEvent.GATE_SETUP_EXPIRED.value in types


# ── parity sanity: gate emit must NOT alter order generation ────────────────

def test_dedup_behavior_unchanged_by_gate_emit():
    """Repeats the dedup contract; if gate emit accidentally mutated state or
    short-circuited the path, this would break."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state
    bar = _bar("2026-01-01 00:15:00", o=2001.0, h=2002.0, l=2000.5, c=2001.5)
    leg = strat.legs[0]
    setup_a = _long_setup(L=2000.0, H=2010.0, sl=1998.0)
    setup_b = _long_setup(L=1999.0, H=2010.5, sl=1997.5)
    o1, _ = strat._finalize_entry(bar, leg, setup_a)
    assert o1 is not None
    assert o1.risk_units == pytest.approx(3.0)
    assert len(state.consumed_entry_keys) == 1
    o2, _ = strat._finalize_entry(bar, leg, setup_b)
    assert o2 is None
    assert len(state.consumed_entry_keys) == 1
