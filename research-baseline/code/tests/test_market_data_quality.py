from __future__ import annotations

import pandas as pd

from intraday_edge_lab.market_data_quality import analyze_m1_quality


def test_market_data_quality_passes_clean_m1_frame() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01 00:00:00", periods=3, freq="min", tz="UTC"),
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [10, 11, 12],
            "spread_points": [2, 2, 3],
        }
    )

    quality = analyze_m1_quality(frame, symbol="TEST")

    assert quality.quality_status == "PASS"
    assert quality.rows == 3
    assert quality.off_step_gaps == 0
    assert quality.median_spread_points == 2


def test_market_data_quality_flags_duplicates_and_bad_ohlc() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [
                "2024-01-01 00:00:00+00:00",
                "2024-01-01 00:00:00+00:00",
                "2024-01-01 00:02:00+00:00",
            ],
            "open": [100.0, 105.0, 102.0],
            "high": [101.0, 104.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [10, 0, 12],
            "spread_points": [2, 0, 3],
        }
    )

    quality = analyze_m1_quality(frame, symbol="TEST")

    assert quality.quality_status == "CAUTION"
    assert quality.duplicate_timestamps == 1
    assert quality.invalid_ohlc_rows == 1
    assert quality.zero_or_negative_spread_rows == 1
    assert "duplicate_timestamps" in quality.quality_notes
