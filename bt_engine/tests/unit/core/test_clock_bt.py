"""Unit tests for BacktestClock."""
from __future__ import annotations

import pandas as pd

from bt_engine.core.bar import Bar
from bt_engine.core.clock_bt import BacktestClock


def _b(ts: str) -> Bar:
    return Bar("X", "M15", pd.Timestamp(ts), 100, 101, 99, 100.5, 1.0)


def test_clock_yields_bars_in_order() -> None:
    bars = [_b("2026-06-29T00:00:00Z"), _b("2026-06-29T00:15:00Z"), _b("2026-06-29T00:30:00Z")]
    c = BacktestClock(iter(bars))
    assert c.tick() == bars[0]
    assert c.tick() == bars[1]
    assert c.tick() == bars[2]
    assert c.tick() is None


def test_clock_idempotent_after_exhaust() -> None:
    c = BacktestClock(iter([_b("2026-06-29T00:00:00Z")]))
    assert c.tick() is not None
    assert c.tick() is None
    assert c.tick() is None


def test_clock_now_tracks_last_yielded() -> None:
    bars = [_b("2026-06-29T00:00:00Z"), _b("2026-06-29T00:15:00Z")]
    c = BacktestClock(iter(bars))
    c.tick()
    assert c.now() == bars[0].timestamp
    c.tick()
    assert c.now() == bars[1].timestamp
