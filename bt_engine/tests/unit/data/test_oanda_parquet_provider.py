"""Unit tests for OandaParquetProvider."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bt_engine.data.oanda_parquet_provider import OandaParquetProvider

XAU = Path("/tmp/oanda_xau_m5.parquet")
EUR = Path("/tmp/oanda_eur_m5.parquet")


@pytest.mark.skipif(not XAU.exists(), reason="XAU parquet missing")
def test_loads_xau_m5_utc_sorted_no_dups():
    p = OandaParquetProvider(symbol="XAUUSD.ecn", timeframe="M5", m5_path=str(XAU))
    df = p.frame
    assert df["timestamp"].dt.tz is not None
    assert str(df["timestamp"].dt.tz) == "UTC"
    assert df["timestamp"].is_monotonic_increasing
    assert df["timestamp"].is_unique


@pytest.mark.skipif(not XAU.exists(), reason="XAU parquet missing")
def test_history_up_to_strict_causality():
    p = OandaParquetProvider(symbol="XAUUSD.ecn", timeframe="M5", m5_path=str(XAU))
    df = p.frame
    mid_ts = df["timestamp"].iloc[len(df) // 2]
    hist = p.history_up_to(mid_ts)
    assert (hist["timestamp"] <= mid_ts).all()
    assert hist["timestamp"].iloc[-1] == mid_ts


@pytest.mark.skipif(not XAU.exists(), reason="XAU parquet missing")
def test_bars_iterator_yields_in_order():
    p = OandaParquetProvider(symbol="XAUUSD.ecn", timeframe="M5", m5_path=str(XAU))
    it = p.bars()
    bar1 = next(it)
    bar2 = next(it)
    assert bar2.timestamp > bar1.timestamp
    assert bar1.symbol == "XAUUSD.ecn"
    assert bar1.timeframe == "M5"


@pytest.mark.skipif(not EUR.exists(), reason="EUR parquet missing")
def test_loads_eur_m5():
    p = OandaParquetProvider(symbol="EURUSD.ecn", timeframe="M5", m5_path=str(EUR))
    assert len(p) > 0
    assert p.symbol == "EURUSD.ecn"


def test_rejects_non_m5_timeframe():
    with pytest.raises(ValueError, match="M5"):
        OandaParquetProvider(symbol="X", timeframe="H1", m5_path="/tmp/oanda_xau_m5.parquet")


def test_rejects_missing_file():
    with pytest.raises(FileNotFoundError):
        OandaParquetProvider(symbol="X", timeframe="M5", m5_path="/tmp/nonexistent_xyz.parquet")
