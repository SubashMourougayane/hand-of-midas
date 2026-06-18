"""Tests for `backend/scanner/broker_to_dataframe.py` — Phase 1 deliverable.

Plan-literal tasks 1.2-1.7. Each test maps to a numbered task:
- test_dwx_format             → 1.2 (DWX format)
- test_oanda_format           → 1.3 (OANDA format with 9-digit ns)
- test_index_is_utc_aware     → 1.4 (DatetimeIndex tz='UTC')
- test_drops_incomplete_bars  → 1.5 (drop complete=False)
- test_computes_mid_columns   → 1.6 (mid_* and spread)
- test_empty_input            → 1.7 (returns empty DataFrame, not raise)
- test_missing_keys_raises    → defensive (extra)
- test_dedup_keeps_last       → matches load_candles behaviour
"""
from __future__ import annotations

import pandas as pd
import pytest

from backend.scanner.broker_to_dataframe import broker_bars_to_dataframe


def _ohlc_dict(ts, base):
    """Build a complete bar dict at price `base` (bid=base, ask=base+0.10)."""
    return {
        "timestamp": ts,
        "bid_open": base, "bid_high": base + 0.10, "bid_low": base - 0.10, "bid_close": base + 0.05,
        "ask_open": base + 0.10, "ask_high": base + 0.20, "ask_low": base, "ask_close": base + 0.15,
        "volume": 100,
        "complete": True,
    }


# 1.2 — DWX format
def test_dwx_format():
    """DWX timestamps look like '2026.06.18 13:00:00' (server-time, no tz)."""
    bars = [_ohlc_dict("2026.06.18 13:00:00", 4300.0)]
    df = broker_bars_to_dataframe(bars)
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2026-06-18 13:00:00", tz="UTC")


# 1.3 — OANDA format
def test_oanda_format():
    """OANDA timestamps look like '2026-06-18T13:00:00.000000000Z' (9-digit ns)."""
    bars = [_ohlc_dict("2026-06-18T13:00:00.000000000Z", 4300.0)]
    df = broker_bars_to_dataframe(bars)
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2026-06-18 13:00:00", tz="UTC")


def test_oanda_with_microseconds():
    """OANDA precision varies — 6-digit microseconds also valid."""
    bars = [_ohlc_dict("2026-06-18T13:00:00.123456Z", 4300.0)]
    df = broker_bars_to_dataframe(bars)
    expected = pd.Timestamp("2026-06-18 13:00:00.123456", tz="UTC")
    assert df.index[0] == expected


def test_iso_with_offset():
    """ISO 8601 with explicit offset should pass through."""
    bars = [_ohlc_dict("2026-06-18T13:00:00+00:00", 4300.0)]
    df = broker_bars_to_dataframe(bars)
    assert df.index[0] == pd.Timestamp("2026-06-18 13:00:00", tz="UTC")


# 1.4 — DatetimeIndex must be tz-aware UTC
def test_index_is_utc_aware():
    bars = [
        _ohlc_dict("2026.06.18 13:00:00", 4300.0),
        _ohlc_dict("2026.06.18 14:00:00", 4310.0),
    ]
    df = broker_bars_to_dataframe(bars)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"


# 1.5 — Drop complete=False bars
def test_drops_incomplete_bars():
    bars = [
        _ohlc_dict("2026.06.18 13:00:00", 4300.0),  # complete=True
        {**_ohlc_dict("2026.06.18 14:00:00", 4310.0), "complete": False},
        _ohlc_dict("2026.06.18 15:00:00", 4320.0),
    ]
    df = broker_bars_to_dataframe(bars)
    assert len(df) == 2
    # The 14:00 in-progress bar must be gone.
    assert pd.Timestamp("2026-06-18 14:00:00", tz="UTC") not in df.index


def test_all_bars_incomplete_returns_empty():
    """If every bar is complete=False, return empty DataFrame (not raise)."""
    bars = [{**_ohlc_dict("2026.06.18 13:00:00", 4300.0), "complete": False}]
    df = broker_bars_to_dataframe(bars)
    assert df.empty
    assert isinstance(df, pd.DataFrame)


def test_complete_key_optional():
    """Bars without a `complete` key are kept (default True)."""
    bar = _ohlc_dict("2026.06.18 13:00:00", 4300.0)
    del bar["complete"]
    df = broker_bars_to_dataframe([bar])
    assert len(df) == 1


# 1.6 — Mid columns and spread
def test_computes_mid_columns():
    bars = [_ohlc_dict("2026.06.18 13:00:00", 4300.0)]
    df = broker_bars_to_dataframe(bars)
    row = df.iloc[0]
    # bid_open=4300.0, ask_open=4300.10 → mid_open=4300.05
    assert row["mid_open"] == pytest.approx((4300.0 + 4300.10) / 2)
    assert row["mid_high"] == pytest.approx((4300.10 + 4300.20) / 2)
    assert row["mid_low"]  == pytest.approx((4299.90 + 4300.0) / 2)
    assert row["mid_close"] == pytest.approx((4300.05 + 4300.15) / 2)
    # spread = ask_close - bid_close = 4300.15 - 4300.05 = 0.10
    assert row["spread"] == pytest.approx(0.10)


# 1.7 — Empty input → empty DataFrame, no raise
def test_empty_list_returns_empty_dataframe():
    df = broker_bars_to_dataframe([])
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_none_input_returns_empty_dataframe():
    df = broker_bars_to_dataframe(None)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


# Defensive: missing required keys raises KeyError (not silent NaN)
def test_missing_required_keys_raises():
    bar = _ohlc_dict("2026.06.18 13:00:00", 4300.0)
    del bar["ask_close"]
    with pytest.raises(KeyError, match="ask_close"):
        broker_bars_to_dataframe([bar])


# Match cache.py behaviour: dedup keeps LAST
def test_dedup_keeps_last_on_duplicate_timestamp():
    """Two bars at same timestamp — second overrides first."""
    bars = [
        _ohlc_dict("2026.06.18 13:00:00", 4300.0),  # bid_open=4300.00
        _ohlc_dict("2026.06.18 13:00:00", 4350.0),  # bid_open=4350.00 ← keeper
    ]
    df = broker_bars_to_dataframe(bars)
    assert len(df) == 1
    assert df["bid_open"].iloc[0] == 4350.0


# Index is sorted ascending
def test_index_sorted_ascending():
    """Even if bars arrive out of order, index is sorted."""
    bars = [
        _ohlc_dict("2026.06.18 15:00:00", 4320.0),
        _ohlc_dict("2026.06.18 13:00:00", 4300.0),
        _ohlc_dict("2026.06.18 14:00:00", 4310.0),
    ]
    df = broker_bars_to_dataframe(bars)
    assert list(df.index) == [
        pd.Timestamp("2026-06-18 13:00:00", tz="UTC"),
        pd.Timestamp("2026-06-18 14:00:00", tz="UTC"),
        pd.Timestamp("2026-06-18 15:00:00", tz="UTC"),
    ]


# Volume defaults to 0 if missing
def test_missing_volume_defaults_zero():
    bar = _ohlc_dict("2026.06.18 13:00:00", 4300.0)
    del bar["volume"]
    df = broker_bars_to_dataframe([bar])
    assert df["volume"].iloc[0] == 0


# Schema: all expected columns present
def test_output_schema():
    bars = [_ohlc_dict("2026.06.18 13:00:00", 4300.0)]
    df = broker_bars_to_dataframe(bars)
    expected_cols = {
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
        "mid_open", "mid_high", "mid_low", "mid_close",
        "spread", "volume",
    }
    assert set(df.columns) == expected_cols
