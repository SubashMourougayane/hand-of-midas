"""CSV historical bar provider — reads MT5 tab-separated export.

Used for the Phase-1 parity test against research-baseline data.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pandas as pd

from ..core.bar import Bar
from .normalize import normalize_frame
from .timeframes import is_valid_timeframe, pandas_rule


class CsvHistoricalProvider:
    """Reads an MT5 tab-separated bar export and yields normalised bars.

    Supports M1 input resampled to the requested timeframe via
    research-baseline.zone_detector.resample_ohlcv semantics
    (label='left', closed='left' — bar timestamp = bar OPEN).
    """

    def __init__(
        self,
        path: str | Path,
        symbol: str,
        timeframe: str,
        *,
        source_timeframe: str = "M1",
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> None:
        if not is_valid_timeframe(timeframe):
            raise ValueError(f"Unknown timeframe: {timeframe}")
        if not is_valid_timeframe(source_timeframe):
            raise ValueError(f"Unknown source_timeframe: {source_timeframe}")
        self.path = Path(path)
        self.symbol = symbol
        self.timeframe = timeframe
        self._source_timeframe = source_timeframe
        self._frame = self._load(start, end)

    def _load(
        self,
        start: pd.Timestamp | None,
        end: pd.Timestamp | None,
    ) -> pd.DataFrame:
        raw = pd.read_csv(self.path, sep="\t")
        # MT5 export header: <DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>
        raw.columns = [c.strip().strip("<>").lower() for c in raw.columns]
        raw["timestamp"] = pd.to_datetime(
            raw["date"] + " " + raw["time"],
            format="%Y.%m.%d %H:%M:%S",
            utc=True,
        )
        raw = raw.drop(columns=["date", "time"])
        rename_map = {"tickvol": "volume_tick", "vol": "volume_real", "spread": "spread"}
        raw = raw.rename(columns=rename_map)
        # use tickvol as the canonical volume (matches research-baseline behaviour)
        raw["volume"] = raw["volume_tick"].astype(float)
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        if "spread" in raw.columns:
            cols.append("spread")
        raw = raw[cols]
        frame, _ = normalize_frame(raw)
        if self._source_timeframe != self.timeframe:
            frame = self._resample(frame, self.timeframe)
        if start is not None:
            frame = frame[frame["timestamp"] >= pd.Timestamp(start)]
        if end is not None:
            frame = frame[frame["timestamp"] <= pd.Timestamp(end)]
        return frame.reset_index(drop=True)

    @staticmethod
    def _resample(frame: pd.DataFrame, target_tf: str) -> pd.DataFrame:
        rule = pandas_rule(target_tf)
        indexed = frame.set_index("timestamp")
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        if "spread" in indexed.columns:
            agg["spread"] = "mean"
        out = indexed.resample(rule, label="left", closed="left").agg(agg)
        return out.dropna(subset=["open", "high", "low", "close"]).reset_index()

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    def bars(self) -> Iterator[Bar]:
        for _, row in self._frame.iterrows():
            yield Bar.from_row(self.symbol, self.timeframe, row)

    def history_up_to(self, t: pd.Timestamp) -> pd.DataFrame:
        return self._frame[self._frame["timestamp"] <= t].reset_index(drop=True)
