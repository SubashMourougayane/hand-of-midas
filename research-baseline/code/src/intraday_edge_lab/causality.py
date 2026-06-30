from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class CausalityError(ValueError):
    """Raised when data or features violate temporal research constraints."""


@dataclass(frozen=True)
class CausalityReport:
    rows: int
    start: pd.Timestamp
    end: pd.Timestamp
    duplicate_timestamps: int
    missing_required_values: int
    warnings: tuple[str, ...]


def prepare_intraday_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize a raw intraday frame and enforce timestamp ordering."""
    missing = [col for col in REQUIRED_COLUMNS if col not in raw.columns]
    if missing:
        raise CausalityError(f"Missing required columns: {missing}")

    frame = raw.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if frame["timestamp"].isna().any():
        raise CausalityError("At least one timestamp could not be parsed.")

    frame = frame.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    numeric_cols = [c for c in ("open", "high", "low", "close", "volume", "bid", "ask") if c in frame]
    for col in numeric_cols:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    return frame


def validate_market_data(frame: pd.DataFrame) -> CausalityReport:
    """Reject common replay and aggregation defects before research begins."""
    missing_required = int(frame[list(REQUIRED_COLUMNS)].isna().sum().sum())
    if missing_required:
        raise CausalityError(f"Required OHLCV fields contain {missing_required} missing values.")

    if not frame["timestamp"].is_monotonic_increasing:
        raise CausalityError("Timestamps must be strictly sorted before validation.")

    duplicate_count = int(frame["timestamp"].duplicated().sum())
    if duplicate_count:
        raise CausalityError(f"Duplicate timestamps detected: {duplicate_count}")

    bad_ohlc = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        | (frame["volume"] < 0)
    )
    if bool(bad_ohlc.any()):
        raise CausalityError(f"Invalid OHLCV rows detected: {int(bad_ohlc.sum())}")

    warnings: list[str] = []
    if {"bid", "ask"}.issubset(frame.columns):
        crossed = (frame["ask"] < frame["bid"]).sum()
        if crossed:
            raise CausalityError(f"Crossed quotes detected: {int(crossed)}")
        wide_spread = ((frame["ask"] - frame["bid"]) / frame["close"]).replace([pd.NA], 0)
        if (wide_spread > 0.02).any():
            warnings.append("Some quoted spreads exceed 2 percent of price.")
    else:
        warnings.append("Bid/ask columns missing; execution must use conservative synthetic spread.")

    return CausalityReport(
        rows=len(frame),
        start=frame["timestamp"].iloc[0],
        end=frame["timestamp"].iloc[-1],
        duplicate_timestamps=duplicate_count,
        missing_required_values=missing_required,
        warnings=tuple(warnings),
    )


def assert_no_feature_label_overlap(feature_columns: Iterable[str], label_columns: Iterable[str]) -> None:
    overlap = set(feature_columns).intersection(label_columns)
    if overlap:
        raise CausalityError(f"Feature/label overlap detected: {sorted(overlap)}")


def assert_feature_timestamps(feature_frame: pd.DataFrame, source_frame: pd.DataFrame) -> None:
    """Ensure feature rows align one-for-one with source decision timestamps."""
    if len(feature_frame) != len(source_frame):
        raise CausalityError("Feature frame length differs from source frame length.")
    if not feature_frame["timestamp"].equals(source_frame["timestamp"]):
        raise CausalityError("Feature timestamps do not match source decision timestamps.")
