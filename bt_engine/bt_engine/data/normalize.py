"""Normalise raw bar frames to the engine contract."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class CausalityError(ValueError):
    """Raised when data violates the engine's causal bar contract."""


@dataclass(frozen=True)
class CausalityReport:
    rows: int
    start: pd.Timestamp
    end: pd.Timestamp
    duplicate_timestamps: int
    missing_required_values: int
    warnings: tuple[str, ...]

__all__ = ["CausalityError", "CausalityReport", "normalize_frame"]


def normalize_frame(raw: pd.DataFrame) -> tuple[pd.DataFrame, CausalityReport]:
    """Validate and normalise a raw bar frame to the engine contract.

    Returns (frame, causality_report). frame columns:
        timestamp (UTC), open, high, low, close, volume[, bid, ask, spread, ...]
    """
    frame = _prepare_intraday_frame(raw)
    report = _validate_market_data(frame)
    return frame, report


def _prepare_intraday_frame(raw: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in REQUIRED_COLUMNS if col not in raw.columns]
    if missing:
        raise CausalityError(f"Missing required columns: {missing}")

    frame = raw.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if frame["timestamp"].isna().any():
        raise CausalityError("At least one timestamp could not be parsed.")

    frame = frame.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    numeric_cols = [c for c in ("open", "high", "low", "close", "volume", "bid", "ask", "spread") if c in frame]
    for col in numeric_cols:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def _validate_market_data(frame: pd.DataFrame) -> CausalityReport:
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
        wide_spread = ((frame["ask"] - frame["bid"]) / frame["close"]).fillna(0)
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
