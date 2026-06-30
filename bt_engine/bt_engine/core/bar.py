"""Immutable Bar dataclass — the single bar contract for BT and live."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Bar:
    symbol: str
    timeframe: str
    timestamp: pd.Timestamp  # UTC, bar OPEN time
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread: float | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Bar.timestamp must be timezone-aware (UTC).")
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(
                f"Invalid OHLC: open={self.open}, high={self.high}, "
                f"low={self.low}, close={self.close}"
            )
        if self.volume < 0:
            raise ValueError(f"Volume must be >= 0, got {self.volume}")

    @classmethod
    def from_row(cls, symbol: str, timeframe: str, row: pd.Series | dict[str, Any]) -> "Bar":
        get = row.get if hasattr(row, "get") else row.__getitem__
        spread = get("spread") if (hasattr(row, "get") or "spread" in row) else None
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=pd.Timestamp(row["timestamp"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0.0)) if hasattr(row, "get") else float(row["volume"]),
            spread=float(spread) if spread is not None and not pd.isna(spread) else None,
        )
