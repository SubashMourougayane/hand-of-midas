"""Unit tests for Bar dataclass."""
from __future__ import annotations

import pandas as pd
import pytest

from bt_engine.core.bar import Bar


def _ts(s: str = "2026-06-29T00:00:00Z") -> pd.Timestamp:
    return pd.Timestamp(s)


def test_bar_happy_path() -> None:
    b = Bar("XAUUSD", "M15", _ts(), 100.0, 101.0, 99.0, 100.5, 1000.0, spread=0.5)
    assert b.symbol == "XAUUSD"
    assert b.timeframe == "M15"
    assert b.timestamp == _ts()
    assert b.open == 100.0
    assert b.close == 100.5
    assert b.spread == 0.5


def test_bar_is_frozen() -> None:
    b = Bar("XAUUSD", "M15", _ts(), 100.0, 101.0, 99.0, 100.5, 1000.0)
    with pytest.raises(Exception):
        b.open = 200.0  # type: ignore[misc]


def test_bar_rejects_naive_timestamp() -> None:
    naive = pd.Timestamp("2026-06-29T00:00:00")
    with pytest.raises(ValueError, match="timezone-aware"):
        Bar("XAUUSD", "M15", naive, 100.0, 101.0, 99.0, 100.5, 1000.0)


def test_bar_rejects_invalid_ohlc_high_below_open() -> None:
    with pytest.raises(ValueError, match="Invalid OHLC"):
        Bar("XAUUSD", "M15", _ts(), 100.0, 99.5, 99.0, 99.2, 1000.0)


def test_bar_rejects_invalid_ohlc_low_above_close() -> None:
    with pytest.raises(ValueError, match="Invalid OHLC"):
        Bar("XAUUSD", "M15", _ts(), 100.0, 101.0, 100.6, 100.5, 1000.0)


def test_bar_rejects_negative_volume() -> None:
    with pytest.raises(ValueError, match="Volume"):
        Bar("XAUUSD", "M15", _ts(), 100.0, 101.0, 99.0, 100.5, -1.0)


def test_bar_from_row() -> None:
    row = {
        "timestamp": _ts(),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 500.0,
        "spread": 0.3,
    }
    b = Bar.from_row("XAUUSD", "M15", row)
    assert b.open == 100.0
    assert b.spread == 0.3


def test_bar_from_row_no_spread() -> None:
    row = {
        "timestamp": _ts(),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 500.0,
    }
    b = Bar.from_row("XAUUSD", "M15", row)
    assert b.spread is None
