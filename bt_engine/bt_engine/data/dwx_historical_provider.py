"""Mt5HistoricalDataProvider — reads MT5 bars via the DWX file bridge.

The DWX EA writes periodic JSON dumps (M3=500 bars, H1=30 bars, D1=5 bars) at
3-second cadence. This provider reads a single snapshot, normalizes it through
the same causality pipeline as CSV, and exposes the engine DataProvider contract.

For deeper history a future EA enhancement (GET_HISTORIC_DATA command) is
required; the current EA does not support arbitrary date ranges.
"""
from __future__ import annotations

from typing import Iterator

import pandas as pd

from ..core.bar import Bar
from .dwx_bridge import DwxBridge
from .normalize import normalize_frame
from .timeframes import is_valid_timeframe


_DWX_TF_TO_ENGINE = {"M3": "M3", "H1": "H1", "D1": "D1"}


def _bars_json_to_frame(bars: list[dict]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "spread"])
    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["time"], format="%Y.%m.%d %H:%M:%S", utc=True)
    df = df.drop(columns=["time"])
    df["volume"] = df["volume"].astype(float)
    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    if "spread" in df.columns:
        cols.append("spread")
    return df[cols]


class Mt5HistoricalDataProvider:
    """Snapshot historical provider over the DWX file bridge.

    Reads bars_<SYMBOL>_<TF>.json once at construction; supports the same
    DataProvider contract as CsvHistoricalProvider so the engine can swap
    providers transparently.
    """

    def __init__(
        self,
        bridge: DwxBridge,
        symbol: str,
        timeframe: str,
        *,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> None:
        if not is_valid_timeframe(timeframe):
            raise ValueError(f"Unknown timeframe: {timeframe}")
        if timeframe not in _DWX_TF_TO_ENGINE:
            raise ValueError(
                f"DWX EA does not write bars at timeframe {timeframe}; "
                f"supported: {sorted(_DWX_TF_TO_ENGINE)}"
            )
        self.bridge = bridge
        self.symbol = symbol
        self.timeframe = timeframe
        self._frame = self._load(start, end)

    def _load(
        self,
        start: pd.Timestamp | None,
        end: pd.Timestamp | None,
    ) -> pd.DataFrame:
        bars = self.bridge.bars(self.symbol, self.timeframe)
        df = _bars_json_to_frame(bars)
        if df.empty:
            return df
        df, _ = normalize_frame(df)
        if start is not None:
            df = df[df["timestamp"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["timestamp"] <= pd.Timestamp(end)]
        return df.reset_index(drop=True)

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    def bars(self) -> Iterator[Bar]:
        for _, row in self._frame.iterrows():
            yield Bar.from_row(self.symbol, self.timeframe, row)

    def history_up_to(self, t: pd.Timestamp) -> pd.DataFrame:
        return self._frame[self._frame["timestamp"] <= t].reset_index(drop=True)

    def refresh(self) -> int:
        """Re-read the bars JSON. Returns count of new bars appended."""
        bars = self.bridge.bars(self.symbol, self.timeframe)
        new_df = _bars_json_to_frame(bars)
        if new_df.empty:
            return 0
        new_df, _ = normalize_frame(new_df)
        if self._frame.empty:
            self._frame = new_df.reset_index(drop=True)
            return len(new_df)
        last_ts = self._frame["timestamp"].iloc[-1]
        appended = new_df[new_df["timestamp"] > last_ts]
        if appended.empty:
            return 0
        self._frame = pd.concat([self._frame, appended], ignore_index=True)
        return len(appended)
