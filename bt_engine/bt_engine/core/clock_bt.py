"""BacktestClock — iterates pre-fetched closed bars from a DataProvider."""
from __future__ import annotations

from typing import Iterator

import pandas as pd

from .bar import Bar


class BacktestClock:
    """Yields bars in order from an iterator; returns None at EOF.

    The clock owns the iteration cursor. Multiple ticks past EOF return None.
    """

    def __init__(self, bars: Iterator[Bar]) -> None:
        self._it = iter(bars)
        self._exhausted = False
        self._last_bar: Bar | None = None

    def tick(self) -> Bar | None:
        if self._exhausted:
            return None
        try:
            bar = next(self._it)
        except StopIteration:
            self._exhausted = True
            return None
        self._last_bar = bar
        return bar

    def now(self) -> pd.Timestamp:
        if self._last_bar is None:
            return pd.Timestamp.min.tz_localize("UTC")
        return self._last_bar.timestamp
