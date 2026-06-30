"""Mt5LiveBarProvider — tails bars_*.json from DWX, yields only closed bars.

A bar is considered CLOSED when its open timestamp + timeframe seconds is past
the current UTC wall clock. This avoids signalling on the still-forming last row.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..core.bar import Bar
from .dwx_bridge import DwxBridge
from .dwx_historical_provider import _bars_json_to_frame
from .normalize import normalize_frame
from .timeframes import is_valid_timeframe, seconds


class Mt5LiveBarProvider:
    """Polls the DWX bars JSON; yields each newly-closed bar exactly once.

    `next_closed_bar()` returns:
        - the most recent CLOSED Bar that the caller has not yet seen, or
        - None if no new closed bar is available.

    `history_up_to(t)` returns all bars with timestamp <= t (matches engine
    DataProvider contract).
    """

    def __init__(
        self,
        bridge: DwxBridge,
        symbol: str,
        timeframe: str,
        *,
        now_fn=None,
        server_utc_offset_hours: float = 0.0,
    ) -> None:
        if not is_valid_timeframe(timeframe):
            raise ValueError(f"Unknown timeframe: {timeframe}")
        self.bridge = bridge
        self.symbol = symbol
        self.timeframe = timeframe
        self._tf_seconds = seconds(timeframe)
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._server_utc_offset = pd.Timedelta(hours=server_utc_offset_hours)
        self._frame: pd.DataFrame = self._read_normalized()
        self._last_yielded_ts: pd.Timestamp | None = None

    def _read_normalized(self) -> pd.DataFrame:
        try:
            raw = self.bridge.bars(self.symbol, self.timeframe)
        except RuntimeError:
            # file not yet written by EA — tolerate
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "spread"])
        df = _bars_json_to_frame(raw)
        if df.empty:
            return df
        if self._server_utc_offset != pd.Timedelta(0):
            df["timestamp"] = df["timestamp"] - self._server_utc_offset
        df, _ = normalize_frame(df)
        return df.reset_index(drop=True)

    def _is_closed(self, bar_open: pd.Timestamp) -> bool:
        now = pd.Timestamp(self._now_fn())
        if now.tzinfo is None:
            now = now.tz_localize("UTC")
        bar_close = bar_open + pd.Timedelta(seconds=self._tf_seconds)
        return now >= bar_close

    def next_closed_bar(self) -> Bar | None:
        """Refresh bars JSON; return next CLOSED bar past last_yielded_ts (FIFO catchup)."""
        self._frame = self._read_normalized()
        if self._frame.empty:
            return None
        closed_mask = self._frame["timestamp"].apply(self._is_closed)
        closed = self._frame[closed_mask]
        if closed.empty:
            return None
        if self._last_yielded_ts is not None:
            closed = closed[closed["timestamp"] > self._last_yielded_ts]
        if closed.empty:
            return None
        # FIFO: yield the OLDEST unyielded closed bar so callers see every bar
        row = closed.iloc[0]
        self._last_yielded_ts = row["timestamp"]
        return Bar.from_row(self.symbol, self.timeframe, row)

    def latest_closed_timestamp(self) -> pd.Timestamp | None:
        self._frame = self._read_normalized()
        if self._frame.empty:
            return None
        closed_mask = self._frame["timestamp"].apply(self._is_closed)
        closed = self._frame[closed_mask]
        if closed.empty:
            return None
        return pd.Timestamp(closed["timestamp"].max())

    def mark_yielded_through(self, ts: pd.Timestamp) -> None:
        self._last_yielded_ts = pd.Timestamp(ts)

    def history_up_to(self, t: pd.Timestamp) -> pd.DataFrame:
        return self._frame[self._frame["timestamp"] <= t].reset_index(drop=True)

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    @property
    def last_yielded_ts(self) -> pd.Timestamp | None:
        return self._last_yielded_ts
