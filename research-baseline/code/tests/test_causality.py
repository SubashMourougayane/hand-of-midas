from __future__ import annotations

import pandas as pd
import pytest

from intraday_edge_lab.causality import CausalityError, prepare_intraday_frame, validate_market_data


def test_duplicate_timestamps_are_rejected() -> None:
    raw = pd.DataFrame(
        {
            "timestamp": ["2024-01-01T14:30:00Z", "2024-01-01T14:30:00Z"],
            "open": [100, 101],
            "high": [101, 102],
            "low": [99, 100],
            "close": [100.5, 101.5],
            "volume": [1000, 1200],
        }
    )
    frame = prepare_intraday_frame(raw)
    with pytest.raises(CausalityError, match="Duplicate timestamps"):
        validate_market_data(frame)


def test_invalid_ohlc_is_rejected() -> None:
    raw = pd.DataFrame(
        {
            "timestamp": ["2024-01-01T14:30:00Z"],
            "open": [100],
            "high": [99],
            "low": [98],
            "close": [100],
            "volume": [1000],
        }
    )
    frame = prepare_intraday_frame(raw)
    with pytest.raises(CausalityError, match="Invalid OHLCV"):
        validate_market_data(frame)
