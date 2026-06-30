"""OandaParquetProvider — load cached OANDA parquet (M5 grid) and serve bars
to the engine. Companion `MultiTfHistoryView` resamples M5 → H1/D1 for HTF
strategy lookups (see `multi_tf_view.py`).

Causality contract:
    - All timestamps are UTC, sorted, deduplicated.
    - history_up_to(t) returns only rows with timestamp <= t (no peeking).
    - bars() iterator emits one bar per row in chronological order.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pandas as pd

from ..core.bar import Bar


class OandaParquetProvider:
    """Reads an OANDA M5 parquet (e.g. /tmp/oanda_xau_m5.parquet) and serves
    bars. Same DataProvider contract as `CsvHistoricalProvider`.
    """

    def __init__(
        self,
        *,
        symbol: str,
        timeframe: str,
        m5_path: str | Path,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> None:
        if timeframe.upper() != "M5":
            raise ValueError(
                f"OandaParquetProvider only supports M5 (engine drives M5). Got {timeframe}."
            )
        self.symbol = symbol
        self.timeframe = "M5"
        self.m5_path = Path(m5_path)
        if not self.m5_path.exists():
            raise FileNotFoundError(f"OANDA parquet not found: {self.m5_path}")

        df = pd.read_parquet(self.m5_path)
        # Normalize tz to UTC if missing.
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
        df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        if start is not None:
            df = df[df["timestamp"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["timestamp"] < pd.Timestamp(end)]
        self._df = df.reset_index(drop=True)

    def __len__(self) -> int:
        return len(self._df)

    @property
    def frame(self) -> pd.DataFrame:
        """Read-only access to the underlying M5 frame."""
        return self._df

    def bars(self) -> Iterator[Bar]:
        for _, row in self._df.iterrows():
            yield Bar.from_row(symbol=self.symbol, timeframe=self.timeframe, row=row)

    def history_up_to(self, ts: pd.Timestamp) -> pd.DataFrame:
        """Return all M5 rows with timestamp <= ts. Strict causality."""
        ts = pd.Timestamp(ts)
        return self._df[self._df["timestamp"] <= ts].reset_index(drop=True)
