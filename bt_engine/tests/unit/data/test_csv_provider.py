"""Unit tests for CsvHistoricalProvider."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bt_engine.data.csv_provider import CsvHistoricalProvider


REPO_ROOT = Path(__file__).resolve().parents[4]
M1_CSV = REPO_ROOT / "research-baseline" / "data" / "raw" / "XAUUSD.ecn_M1_201601040000_202606181903.csv"


pytestmark = pytest.mark.skipif(not M1_CSV.is_file(), reason="baseline M1 CSV not present")


# Real M1 data starts ~2019-09-30 in the mixed-timeframe baseline CSV.
M1_PERIOD_START = pd.Timestamp("2019-10-01T00:00:00Z")
M1_PERIOD_END = pd.Timestamp("2019-10-01T23:59:59Z")


def test_csv_provider_loads_m1() -> None:
    p = CsvHistoricalProvider(
        M1_CSV,
        symbol="XAUUSD.ecn",
        timeframe="M1",
        source_timeframe="M1",
        start=M1_PERIOD_START,
        end=M1_PERIOD_END,
    )
    f = p.frame
    assert len(f) > 0
    assert f["timestamp"].dt.tz is not None
    assert (f["timestamp"] >= M1_PERIOD_START).all()
    assert (f["timestamp"] <= M1_PERIOD_END).all()


def test_csv_provider_resamples_m1_to_m15() -> None:
    p = CsvHistoricalProvider(
        M1_CSV,
        symbol="XAUUSD.ecn",
        timeframe="M15",
        source_timeframe="M1",
        start=M1_PERIOD_START,
        end=M1_PERIOD_END,
    )
    f = p.frame
    # 24h / 15min = 96 bars max; weekend hours empty so expect >50 on a weekday
    assert len(f) > 50
    deltas = f["timestamp"].diff().dropna().unique()
    assert pd.Timedelta(minutes=15) in deltas


def test_csv_provider_history_up_to() -> None:
    p = CsvHistoricalProvider(
        M1_CSV,
        symbol="XAUUSD.ecn",
        timeframe="M15",
        source_timeframe="M1",
        start=M1_PERIOD_START,
        end=M1_PERIOD_END,
    )
    cutoff = pd.Timestamp("2019-10-01T12:00:00Z")
    h = p.history_up_to(cutoff)
    assert (h["timestamp"] <= cutoff).all()
    assert h["timestamp"].iloc[-1] <= cutoff


def test_csv_provider_bars_iterator_yields_valid_bars() -> None:
    p = CsvHistoricalProvider(
        M1_CSV,
        symbol="XAUUSD.ecn",
        timeframe="M15",
        source_timeframe="M1",
        start=M1_PERIOD_START,
        end=pd.Timestamp("2019-10-01T03:00:00Z"),
    )
    bars = list(p.bars())
    assert len(bars) >= 3
    for b in bars:
        assert b.symbol == "XAUUSD.ecn"
        assert b.timeframe == "M15"
        assert b.low <= b.open <= b.high
        assert b.low <= b.close <= b.high
