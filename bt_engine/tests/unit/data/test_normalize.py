"""Unit tests for data.normalize (wraps research-baseline causality)."""
from __future__ import annotations

import pandas as pd
import pytest

from bt_engine.data.normalize import CausalityError, normalize_frame


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_normalize_happy_path() -> None:
    raw = _df(
        [
            {"timestamp": "2026-06-29 00:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
            {"timestamp": "2026-06-29 00:15:00", "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 800.0},
        ]
    )
    frame, report = normalize_frame(raw)
    assert len(frame) == 2
    assert report.rows == 2
    assert report.duplicate_timestamps == 0
    assert frame["timestamp"].dt.tz is not None


def test_normalize_rejects_duplicates() -> None:
    raw = _df(
        [
            {"timestamp": "2026-06-29 00:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0},
            {"timestamp": "2026-06-29 00:00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0},
        ]
    )
    with pytest.raises(CausalityError, match="Duplicate"):
        normalize_frame(raw)


def test_normalize_rejects_invalid_ohlc() -> None:
    raw = _df(
        [
            {"timestamp": "2026-06-29 00:00:00", "open": 100.0, "high": 95.0, "low": 99.0, "close": 100.5, "volume": 1.0},
        ]
    )
    with pytest.raises(CausalityError, match="Invalid OHLCV"):
        normalize_frame(raw)


def test_normalize_rejects_missing_columns() -> None:
    raw = _df([{"timestamp": "2026-06-29 00:00:00", "open": 100.0}])
    with pytest.raises(CausalityError, match="Missing required columns"):
        normalize_frame(raw)
