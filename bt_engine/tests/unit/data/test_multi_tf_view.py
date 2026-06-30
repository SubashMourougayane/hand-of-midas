"""Unit tests for MultiTfHistoryView."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bt_engine.data.multi_tf_view import MultiTfHistoryView

XAU = Path("/tmp/oanda_xau_m5.parquet")
H1_XAU = Path("/tmp/oanda_xau_h1.parquet")


def _make_m5(n: int = 24 * 12 * 30) -> pd.DataFrame:
    """30 days of synthetic M5."""
    rng = np.random.default_rng(0)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = 4000.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + np.abs(rng.normal(0.5, 0.3, n))
    low = close - np.abs(rng.normal(0.5, 0.3, n))
    open_ = np.clip(close + rng.normal(0, 0.3, n), low, high)
    return pd.DataFrame({
        "timestamp": ts, "open": open_, "high": high,
        "low": low, "close": close, "volume": rng.integers(1, 100, n),
    })


def test_h1_resample_correct():
    m5 = _make_m5()
    view = MultiTfHistoryView(m5)
    # H1 bar count = n / 12
    assert len(view.h1) == len(m5) // 12


def test_d1_resample_correct():
    m5 = _make_m5()
    view = MultiTfHistoryView(m5)
    # D1 bar count = n / (24*12)
    assert len(view.d1) == len(m5) // (24 * 12)


def test_h1_history_up_to_closed_only():
    m5 = _make_m5()
    view = MultiTfHistoryView(m5)
    # Pick time inside an H1 bar (15min past hour).
    t = pd.Timestamp("2024-01-02 05:15", tz="UTC")
    h1_hist = view.h1_history_up_to(t)
    # Last closed H1 bar should be the one labeled 04:00 (closes at 05:00).
    last = h1_hist["timestamp"].iloc[-1]
    assert last == pd.Timestamp("2024-01-02 04:00", tz="UTC")
    # CRITICAL: 05:00 bar is OPEN at 05:15, must NOT be in history.
    assert pd.Timestamp("2024-01-02 05:00", tz="UTC") not in h1_hist["timestamp"].values


def test_h1_history_at_exact_close_ts_includes_bar():
    """At t = bar_open + 1h (exact close), the bar IS visible."""
    m5 = _make_m5()
    view = MultiTfHistoryView(m5)
    t = pd.Timestamp("2024-01-02 05:00", tz="UTC")
    h1_hist = view.h1_history_up_to(t)
    last = h1_hist["timestamp"].iloc[-1]
    assert last == pd.Timestamp("2024-01-02 04:00", tz="UTC")


def test_d1_history_up_to_closed_only():
    m5 = _make_m5()
    view = MultiTfHistoryView(m5)
    t = pd.Timestamp("2024-01-05 12:00", tz="UTC")
    d1_hist = view.d1_history_up_to(t)
    last = d1_hist["timestamp"].iloc[-1]
    assert last == pd.Timestamp("2024-01-04", tz="UTC")  # closes at 2024-01-05 00:00
    assert pd.Timestamp("2024-01-05", tz="UTC") not in d1_hist["timestamp"].values


@pytest.mark.skipif(not (XAU.exists() and H1_XAU.exists()), reason="OANDA parquets missing")
def test_h1_derived_from_m5_matches_oanda_h1_parquet():
    """M5-derived H1 should match the OANDA H1 parquet (ignoring last partial bar)."""
    m5 = pd.read_parquet(XAU)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    view = MultiTfHistoryView(m5)
    h1_derived = view.h1

    h1_oanda = pd.read_parquet(H1_XAU)
    if h1_oanda["timestamp"].dt.tz is None:
        h1_oanda["timestamp"] = h1_oanda["timestamp"].dt.tz_localize("UTC")

    # Inner join on timestamp, compare OHLC.
    merged = h1_derived.merge(h1_oanda, on="timestamp", suffixes=("_derived", "_oanda"))
    # OANDA aggregates BID/ASK ticks; M5 derivation uses mid. Small drift OK.
    # Sample 100 random rows for sanity.
    sample = merged.sample(n=min(100, len(merged)), random_state=42)
    # Assert high >= low always.
    assert (sample["high_derived"] >= sample["low_derived"]).all()
    assert (sample["high_oanda"] >= sample["low_oanda"]).all()
    # Assert close prices are within reasonable tolerance (smaller than 1% gap).
    diff_pct = abs(sample["close_derived"] - sample["close_oanda"]) / sample["close_oanda"]
    assert (diff_pct < 0.005).mean() > 0.85, "85%+ of rows should match within 0.5%"


def test_requires_utc_tz():
    """Naive (tz-less) timestamps should raise."""
    n = 100
    m5 = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="5min"),
        "open": np.ones(n), "high": np.ones(n) * 1.1,
        "low": np.ones(n) * 0.9, "close": np.ones(n), "volume": np.ones(n),
    })
    with pytest.raises(ValueError, match="UTC"):
        MultiTfHistoryView(m5)
