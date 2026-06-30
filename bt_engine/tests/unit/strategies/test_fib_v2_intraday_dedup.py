"""Phase 4: Dedup + min_risk tests for FibV2Intraday.

Verifies:
  - Two _finalize_entry calls with SAME (bar.timestamp, side, leg_name) → only FIRST returns order.
  - consumed_entry_keys grows to 1 (not 2).
  - Different leg_name OR different side → both fire (different keys).
"""
from __future__ import annotations

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA
from bt_engine.strategies.fib_v2.state import FibSetup
from bt_engine.strategies.fib_v2.config import LegSpec


def _bar(ts_iso: str, *, o, h, l, c) -> Bar:
    return Bar(
        symbol="XAUUSD.ecn", timeframe="M15",
        timestamp=pd.Timestamp(ts_iso, tz="UTC"),
        open=o, high=h, low=l, close=c, volume=1.0,
    )


def _setup_long(*, L=2000.0, H=2010.0, sl=1998.0, tp=2026.18) -> FibSetup:
    """LONG fib setup. Use exact numbers so risk_units is predictable."""
    diff = H - L
    return FibSetup(
        leg_name="intraday_a_long",
        side=1,
        L=L, H=H, diff=diff,
        fib_382=L + 0.618 * diff,
        fib_786=L + 0.214 * diff,
        fib_100=L,
        tp_price=tp,
        sl_price=sl,
        setup_confirm_ts=pd.Timestamp("2026-01-01 00:00:00", tz="UTC"),
        L_ts=pd.Timestamp("2025-12-31 22:00:00", tz="UTC"),
        H_ts=pd.Timestamp("2026-01-01 00:00:00", tz="UTC"),
    )


def test_dedup_blocks_second_entry_on_same_bar_side_leg():
    """Two _finalize_entry calls with same (bar.ts, side, leg) → 1 order, 1 dedup key."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state  # pin (normally on_bar shim does this)

    bar = _bar("2026-01-01 00:15:00", o=2001.0, h=2002.0, l=2000.5, c=2001.5)
    leg = strat.legs[0]
    setup_a = _setup_long(L=2000.0, H=2010.0, sl=1998.0)
    setup_b = _setup_long(L=1999.0, H=2010.5, sl=1997.5)  # different geometry, same bar

    # FIRST: should fire
    order1, _ = strat._finalize_entry(bar, leg, setup_a)
    assert order1 is not None, "first entry must fire"
    assert order1.risk_units == 3.0  # 2001.0 - 1998.0
    assert len(state.consumed_entry_keys) == 1
    key = (bar.timestamp, 1, "intraday_a_long")
    assert key in state.consumed_entry_keys

    # SECOND: same bar.ts, same side, same leg → MUST be deduped
    order2, _ = strat._finalize_entry(bar, leg, setup_b)
    assert order2 is None, "second entry MUST be deduped"
    assert len(state.consumed_entry_keys) == 1, "no new key"


def test_dedup_allows_opposite_side_same_bar():
    """Long A + Short D on same bar = legitimate hedge. Different leg + side → both fire."""
    from bt_engine.strategies.fib_v2_intraday import FibV2IntradayD

    a_strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    d_strat = FibV2IntradayD(symbol="XAUUSD.ecn")

    bar = _bar("2026-01-01 00:15:00", o=2001.0, h=2002.0, l=2000.5, c=2001.5)
    a_state = a_strat.initial_state()
    d_state = d_strat.initial_state()
    a_strat._current_state_ref = a_state
    d_strat._current_state_ref = d_state

    a_setup = _setup_long()
    # short setup
    d_setup = FibSetup(
        leg_name="intraday_d_short", side=-1,
        L=1990.0, H=2002.0, diff=12.0,
        fib_382=2002.0 - 0.618 * 12.0,
        fib_786=2002.0 - 0.214 * 12.0,
        fib_100=2002.0,
        tp_price=1970.58,  # ext = 1.618
        sl_price=2002.24,  # sl_buf 0.02 * 12 above H
        setup_confirm_ts=pd.Timestamp("2026-01-01 00:00:00", tz="UTC"),
        L_ts=pd.Timestamp("2025-12-31 23:00:00", tz="UTC"),
        H_ts=pd.Timestamp("2026-01-01 00:00:00", tz="UTC"),
    )

    a_order, _ = a_strat._finalize_entry(bar, a_strat.legs[0], a_setup)
    d_order, _ = d_strat._finalize_entry(bar, d_strat.legs[0], d_setup)

    assert a_order is not None, "A long must fire"
    assert d_order is not None, "D short must fire (different leg + opposite side)"


def test_min_risk_floor_rejects_tiny_stop():
    """risk_units < 0.50 → rejected by min_risk gate."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state

    # Build setup with TINY stop: entry=2001, sl=2000.70 → risk=0.30
    bar = _bar("2026-01-01 00:15:00", o=2001.0, h=2002.0, l=2000.5, c=2001.5)
    tiny_setup = _setup_long(L=2000.0, H=2010.0, sl=2000.70)  # risk = 0.30

    order, _ = strat._finalize_entry(bar, strat.legs[0], tiny_setup)
    assert order is None, "tiny-stop (0.30 < 0.50) must be rejected"
    assert len(state.consumed_entry_keys) == 0, "no dedup key on rejected order"


def test_min_risk_floor_accepts_above_threshold():
    """risk_units == 0.55 → accepted (above $0.50 floor)."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state

    # entry=2001, sl=2000.45 → risk=0.55
    bar = _bar("2026-01-01 00:15:00", o=2001.0, h=2002.0, l=2000.5, c=2001.5)
    accepted_setup = _setup_long(L=2000.0, H=2010.0, sl=2000.45)

    order, _ = strat._finalize_entry(bar, strat.legs[0], accepted_setup)
    assert order is not None, "risk=0.55 (>=0.50) must be accepted"
    assert order.risk_units == pytest.approx(0.55)
    assert len(state.consumed_entry_keys) == 1


def test_dedup_persists_across_calls_until_new_bar():
    """Once a key lands in consumed_entry_keys, all subsequent calls for it reject."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state

    bar = _bar("2026-01-01 00:15:00", o=2001.0, h=2002.0, l=2000.5, c=2001.5)
    setup = _setup_long(L=2000.0, H=2010.0, sl=1998.0)

    o1, _ = strat._finalize_entry(bar, strat.legs[0], setup)
    o2, _ = strat._finalize_entry(bar, strat.legs[0], setup)
    o3, _ = strat._finalize_entry(bar, strat.legs[0], setup)
    assert o1 is not None
    assert o2 is None
    assert o3 is None
    assert len(state.consumed_entry_keys) == 1


def test_dedup_allows_different_bar_same_side_leg():
    """Different bar.timestamp → different key → fires again."""
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    strat._current_state_ref = state

    bar1 = _bar("2026-01-01 00:15:00", o=2001.0, h=2002.0, l=2000.5, c=2001.5)
    bar2 = _bar("2026-01-01 00:30:00", o=2001.0, h=2002.0, l=2000.5, c=2001.5)
    setup = _setup_long(L=2000.0, H=2010.0, sl=1998.0)

    o1, _ = strat._finalize_entry(bar1, strat.legs[0], setup)
    o2, _ = strat._finalize_entry(bar2, strat.legs[0], setup)
    assert o1 is not None
    assert o2 is not None
    assert len(state.consumed_entry_keys) == 2
