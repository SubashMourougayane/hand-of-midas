"""Unit tests for LiveClock."""
from __future__ import annotations

import pandas as pd

from bt_engine.core.bar import Bar
from bt_engine.core.clock_live import LiveClock


def _bar(ts: str) -> Bar:
    return Bar("X", "M15", pd.Timestamp(ts), 100, 101, 99, 100.5, 1.0)


class _Provider:
    def __init__(self, seq: list[Bar | None]) -> None:
        self._seq = list(seq)
        self.polls = 0

    def next_closed_bar(self) -> Bar | None:
        self.polls += 1
        if not self._seq:
            return None
        return self._seq.pop(0)


def test_returns_bar_immediately_if_available() -> None:
    b = _bar("2026-06-29T00:00:00Z")
    p = _Provider([b])
    clk = LiveClock(p, poll_interval_s=0.0)
    assert clk.tick() == b


def test_blocks_until_bar_appears() -> None:
    b = _bar("2026-06-29T00:00:00Z")
    p = _Provider([None, None, b])
    sleep_calls = []
    clk = LiveClock(p, poll_interval_s=0.01, sleep_fn=lambda s: sleep_calls.append(s))
    assert clk.tick() == b
    assert len(sleep_calls) == 2


def test_max_wait_returns_none_on_timeout() -> None:
    p = _Provider([None, None, None])
    clk = LiveClock(p, poll_interval_s=0.0, max_wait_s=0.0, sleep_fn=lambda s: None)
    # immediate deadline -> None
    assert clk.tick() is None


def test_stop_exits_loop() -> None:
    b = _bar("2026-06-29T00:00:00Z")
    p = _Provider([None])
    def stop_after_one(s):
        clk.stop()
    clk = LiveClock(p, poll_interval_s=0.0, sleep_fn=stop_after_one)
    assert clk.tick() is None


def test_now_returns_utc() -> None:
    p = _Provider([])
    clk = LiveClock(p)
    n = clk.now()
    assert n.tzinfo is not None
