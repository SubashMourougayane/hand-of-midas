"""MemoryBarProvider + MemoryClock — fast in-memory bar iterator for BT runs.

Matches the DataProvider + Clock protocol used by run_engine. Optimized:
- History slice via numpy searchsorted (O(log n)) not boolean filter (O(n)).
- Bar iteration via itertuples (~10x faster than iterrows).
- Sequential-tick assumption — no random access.

Use when the whole BT frame fits in memory (any XAU/EUR/BRENT parquet does).
"""
from __future__ import annotations

from typing import Iterator

import pandas as pd

from ..core.bar import Bar


class MemoryBarProvider:
    def __init__(self, frame: pd.DataFrame, *, symbol: str, timeframe: str) -> None:
        df = frame.reset_index(drop=True)
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
        df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        self._df = df
        self.symbol = symbol
        self.timeframe = timeframe
        self._ts_arr = self._df["timestamp"].values

    def __len__(self) -> int:
        return len(self._df)

    @property
    def frame(self) -> pd.DataFrame:
        return self._df

    def bars(self) -> Iterator[Bar]:
        for row in self._df.itertuples(index=False):
            yield Bar.from_row(
                symbol=self.symbol, timeframe=self.timeframe, row=row._asdict()
            )

    def history_up_to(self, ts: pd.Timestamp) -> pd.DataFrame:
        ts_val = pd.Timestamp(ts).to_datetime64()
        end_idx = self._ts_arr.searchsorted(ts_val, side="right")
        return self._df.iloc[:end_idx]


class MemoryClock:
    def __init__(self, provider: MemoryBarProvider) -> None:
        self._iter = iter(provider.bars())

    def tick(self) -> Bar | None:
        try:
            return next(self._iter)
        except StopIteration:
            return None


def resample_m5_to(m5: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample a M5 OHLCV frame to the target timeframe using left-closed bars.

    Contract: input `timestamp` column, output same schema. Left-closed matches
    research (bar timestamp = bar OPEN time).
    """
    tf = timeframe.upper()
    if tf == "M5":
        return m5.reset_index(drop=True)
    rule_map = {"M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h", "D1": "1D"}
    if tf not in rule_map:
        raise ValueError(f"Unsupported resample target: {tf}")
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = (
        idx.resample(rule_map[tf], label="left", closed="left")
        .agg(agg)
        .dropna()
        .reset_index()
    )
    return out
