from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class MTExportMeta:
    symbol: str
    timeframe: str
    source_path: str
    raw_rows: int
    retained_rows: int
    dropped_zero_spread_rows: int


def _parse_name(path: Path) -> tuple[str, str]:
    parts = path.name.split("_")
    head = parts[0]
    symbol = head.split(".")[0]
    timeframe = parts[1] if len(parts) > 1 else "UNKNOWN"
    return symbol, timeframe


def load_mt_export(
    path: str | Path,
    *,
    point_size: float = 0.01,
    drop_zero_spread: bool = True,
) -> tuple[pd.DataFrame, MTExportMeta]:
    """Load a MetaTrader-style tab-separated OHLC export into the research schema."""
    source = Path(path)
    raw = pd.read_csv(source, sep="\t")
    symbol, timeframe = _parse_name(source)
    raw_rows = len(raw)

    renamed = raw.rename(
        columns={
            "<OPEN>": "open",
            "<HIGH>": "high",
            "<LOW>": "low",
            "<CLOSE>": "close",
            "<TICKVOL>": "volume",
            "<SPREAD>": "spread_points",
        }
    )
    timestamp = pd.to_datetime(
        raw["<DATE>"].astype(str) + " " + raw["<TIME>"].astype(str),
        format="%Y.%m.%d %H:%M:%S",
        errors="coerce",
        utc=True,
    )
    frame = pd.DataFrame(
        {
            "timestamp": timestamp,
            "session": timestamp.dt.date.astype(str),
            "symbol": symbol,
            "timeframe": timeframe,
            "open": renamed["open"],
            "high": renamed["high"],
            "low": renamed["low"],
            "close": renamed["close"],
            "volume": renamed["volume"],
            "spread_points": renamed["spread_points"],
        }
    )
    for col in ("open", "high", "low", "close", "volume", "spread_points"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    dropped_zero = int((frame["spread_points"] <= 0).sum()) if drop_zero_spread else 0
    if drop_zero_spread:
        frame = frame[frame["spread_points"] > 0].copy()

    spread_price = frame["spread_points"] * point_size
    frame["bid"] = frame["close"] - spread_price / 2.0
    frame["ask"] = frame["close"] + spread_price / 2.0
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume", "bid", "ask"])
    frame = frame.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    return frame, MTExportMeta(
        symbol=symbol,
        timeframe=timeframe,
        source_path=str(source),
        raw_rows=raw_rows,
        retained_rows=len(frame),
        dropped_zero_spread_rows=dropped_zero,
    )
