"""LiveClock — drives the engine on real-time closed bars from a live provider."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol

import pandas as pd

from .bar import Bar


class _LiveProvider(Protocol):
    def next_closed_bar(self) -> Bar | None: ...


class LiveClock:
    """Polls a live provider for the next closed bar.

    `tick()` blocks until a new closed bar is available, then returns it. Use
    `stop()` to signal shutdown from another thread/signal handler.

    Args:
        provider: live bar provider exposing next_closed_bar()
        poll_interval_s: sleep between polls (default 1s)
        max_wait_s: maximum wait per tick before giving up (returns None);
                    default None means block forever
    """

    def __init__(
        self,
        provider: _LiveProvider,
        *,
        poll_interval_s: float = 1.0,
        max_wait_s: float | None = None,
        sleep_fn=None,
    ) -> None:
        self.provider = provider
        self.poll_interval_s = poll_interval_s
        self.max_wait_s = max_wait_s
        self._sleep_fn = sleep_fn or time.sleep
        self._stopped = False
        self._last_bar: Bar | None = None

    def stop(self) -> None:
        self._stopped = True

    def tick(self) -> Bar | None:
        deadline = None
        if self.max_wait_s is not None:
            deadline = time.time() + self.max_wait_s
        while not self._stopped:
            bar = self.provider.next_closed_bar()
            if bar is not None:
                self._last_bar = bar
                return bar
            # poll at least once before honouring deadline
            if deadline is not None and time.time() >= deadline:
                return None
            if deadline == time.time():  # zero-wait + nothing -> bail
                return None
            self._sleep_fn(self.poll_interval_s)
        return None

    def now(self) -> pd.Timestamp:
        return pd.Timestamp(datetime.now(timezone.utc))
