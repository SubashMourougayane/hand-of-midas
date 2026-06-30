"""Phase 3: M15 pivot timing test. HIGHEST priority causality check.

Verifies:
  - PivotTracker fed with M15 bars (not H1) emits at idx+lb confirmation.
  - Specifically: a synthetic 30-bar M15 frame with a strict-max at idx 10
    causes the H pivot to be emitted with confirm_ts == ts[13] for lb=3.
  - NO emission for bars before idx+lb (no look-ahead).
  - Pivot_ts correctly points to the actual pivot bar (idx 10), NOT the
    confirmation bar (idx 13).

Strategy is fed bars via on_bar; uses FibV2IntradayBase._update_h1_pivots
override which directly feeds state.pivot_tracker.
"""
from __future__ import annotations

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.strategies.fib_v2.pivot_tracker import PivotTracker


def _make_m15_bars(highs, lows) -> list[Bar]:
    """Construct N M15 bars with specified high/low arrays."""
    n = len(highs)
    base = pd.Timestamp("2026-01-01 00:00:00", tz="UTC")
    bars = []
    for i in range(n):
        ts = base + pd.Timedelta(minutes=15 * i)
        o = (highs[i] + lows[i]) / 2  # midpoint open
        c = o  # neutral close, doesn't affect pivot
        bars.append(Bar(
            symbol="XAUUSD.ecn",
            timeframe="M15",
            timestamp=ts,
            open=o, high=float(highs[i]), low=float(lows[i]), close=c,
            volume=1.0,
        ))
    return bars


def test_m15_pivot_high_at_idx_10_confirms_at_idx_13_lb3():
    """Strict-max at idx 10, lb=3 → emit at idx 13 with pivot_ts=ts[10]."""
    # Build 30 bars where idx 10 has the highest high, all others flat.
    highs = [100.0] * 30
    highs[10] = 105.0  # strict max
    lows = [99.0] * 30
    bars = _make_m15_bars(highs, lows)

    tracker = PivotTracker(lb=3)
    emitted = []
    for i, bar in enumerate(bars):
        events = tracker.update(bar)
        for e in events:
            emitted.append((i, e))

    # Expect exactly ONE H pivot. Strict-min over flat lows would yield 0 L events
    # (sum==1 strict-min check fails when all lows equal).
    h_events = [(i, e) for (i, e) in emitted if e.type == "H"]
    assert len(h_events) == 1, f"expected 1 H pivot, got {len(h_events)}: {h_events}"

    fire_idx, ev = h_events[0]
    # Window fills at idx=2*lb=6 (need 7 bars in deque). Pivot at idx 10 is
    # window center when newest bar is idx 13 (window = [7..13], center idx 10).
    assert fire_idx == 13, f"expected fire at bar idx 13, got {fire_idx}"
    assert ev.confirm_ts == bars[13].timestamp, "confirm_ts must be ts[13]"
    assert ev.pivot_ts == bars[10].timestamp, "pivot_ts must be ts[10]"
    assert ev.price == 105.0


def test_m15_pivot_low_lb3():
    """Symmetric: strict-min at idx 10, lb=3 → emit at idx 13."""
    highs = [101.0] * 30
    lows = [100.0] * 30
    lows[10] = 95.0  # strict min
    bars = _make_m15_bars(highs, lows)

    tracker = PivotTracker(lb=3)
    emitted = []
    for i, bar in enumerate(bars):
        for e in tracker.update(bar):
            emitted.append((i, e))

    l_events = [(i, e) for (i, e) in emitted if e.type == "L"]
    assert len(l_events) == 1, f"expected 1 L pivot, got {len(l_events)}"
    fire_idx, ev = l_events[0]
    assert fire_idx == 13
    assert ev.confirm_ts == bars[13].timestamp
    assert ev.pivot_ts == bars[10].timestamp
    assert ev.price == 95.0


def test_m15_pivot_no_emit_before_window_full():
    """Before idx 2*lb=6 (window not full), NO emission possible."""
    highs = [105.0] + [100.0] * 29  # huge first bar
    lows = [99.0] * 30
    bars = _make_m15_bars(highs, lows)

    tracker = PivotTracker(lb=3)
    for i, bar in enumerate(bars[:7]):  # first 7 bars
        events = tracker.update(bar)
        assert events == [], f"unexpected emission at bar idx {i}: {events}"


def test_m15_pivot_tie_rejected_strict_max():
    """Strict-max requires count==1. Tie → NO pivot."""
    highs = [100.0] * 30
    highs[10] = 105.0
    highs[8] = 105.0  # tie!
    lows = [99.0] * 30
    bars = _make_m15_bars(highs, lows)

    tracker = PivotTracker(lb=3)
    emitted = []
    for bar in bars:
        for e in tracker.update(bar):
            emitted.append(e)

    h_events = [e for e in emitted if e.type == "H"]
    # idx 10's window [7..13] contains idx 8 at 105 → tie. count==2 → rejected.
    assert len(h_events) == 0, f"strict-max tied should not emit, got {h_events}"


def test_intraday_strategy_feeds_pivottracker_directly():
    """Integration: FibV2IntradayBase._update_h1_pivots feeds tracker per-bar."""
    from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA
    from bt_engine.strategies.fib_v2.state import FibV2State

    strat = FibV2IntradayA(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    assert isinstance(state, FibV2State)
    assert state.pivot_tracker.lb == 3

    # Feed 30 bars with strict-max at idx 10
    highs = [100.0] * 30
    highs[10] = 105.0
    lows = [99.0] * 30
    bars = _make_m15_bars(highs, lows)

    all_events = []
    for bar in bars:
        events = strat._update_h1_pivots(state, bar, history=pd.DataFrame())
        all_events.extend(events)

    h_events = [e for e in all_events if e.type == "H"]
    assert len(h_events) == 1
    assert h_events[0].confirm_ts == bars[13].timestamp
    assert h_events[0].pivot_ts == bars[10].timestamp
