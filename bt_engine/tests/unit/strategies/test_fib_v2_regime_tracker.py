"""Unit test: RegimeTracker streaming output == research::attach_d1_to_m5 row-for-row.

This is the second foundational causality check: D1 regime features must lag
exactly by 1 day and match research's vectorized D1 EMA+ATR pipeline.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from bt_engine.strategies.fib_v2.regime_tracker import RegimeTracker

# Research truth.
from research.fib_retrace.run_fib_v2_regime import (
    resample_d1, add_d1_features, attach_d1_to_m5,
)


def _make_m5(seed: int = 42, n_days: int = 100) -> pd.DataFrame:
    """Synthetic M5 frame spanning n_days. Used to build D1 + check attach."""
    rng = np.random.default_rng(seed)
    n = n_days * 24 * 12  # M5 bars per day
    ts = pd.date_range("2020-01-01", periods=n, freq="5min", tz="UTC")
    # Daily-ish trend with intraday noise.
    daily_drift = np.repeat(np.cumsum(rng.normal(0, 5, n_days)), 24 * 12)[:n]
    intraday = rng.normal(0, 0.5, n)
    close = 4000.0 + daily_drift + intraday
    high = close + np.abs(rng.normal(0.5, 0.3, n))
    low = close - np.abs(rng.normal(0.5, 0.3, n))
    open_ = close + rng.normal(0, 0.3, n)
    open_ = np.clip(open_, low, high)
    return pd.DataFrame({
        "timestamp": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": rng.integers(1, 100, n),
    })


def _ts_strip_tz(t):
    ts = pd.Timestamp(t)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def test_regime_tracker_features_match_research():
    """Compare streaming RegimeTracker output vs research's attach_d1_to_m5."""
    m5 = _make_m5(n_days=60)
    d1 = resample_d1(m5)
    d1_feat = add_d1_features(d1, ema_period=200, atr_period=14)

    # research-side: D1 features attached to M5 (lagged 1 day via shift(1)).
    m5_with_d1 = attach_d1_to_m5(m5, d1_feat)

    # Stream D1 through RegimeTracker.
    tracker = RegimeTracker(ema_fast=50, ema_slow=200, atr_period=14)
    for _, row in d1.iterrows():
        tracker.update(row)

    # Sample 100 M5 timestamps spread across the dataset.
    sample = m5.iloc[::500].copy()
    for i, row in sample.iterrows():
        ts = row["timestamp"]
        # Truth row from attach_d1_to_m5.
        truth_close_lag = m5_with_d1.loc[i, "close_lag_d1"]
        truth_ema200_lag = m5_with_d1.loc[i, "ema200_lag_d1"]
        truth_ema50_lag = m5_with_d1.loc[i, "ema50_lag_d1"]

        # Streaming output.
        feat = tracker.regime_for(ts)
        if pd.isna(truth_close_lag) or pd.isna(truth_ema200_lag):
            # Truth doesn't have features (early days). Streaming should also return None.
            assert feat is None, f"ts={ts}: streaming has {feat} but truth is NaN"
        else:
            assert feat is not None, f"ts={ts}: streaming None but truth has {truth_close_lag}"
            assert feat["close_lag"] == pytest.approx(truth_close_lag, abs=1e-6), \
                f"ts={ts}: close_lag {feat['close_lag']} vs {truth_close_lag}"
            assert feat["ema200_lag"] == pytest.approx(truth_ema200_lag, abs=1e-3), \
                f"ts={ts}: ema200_lag {feat['ema200_lag']} vs {truth_ema200_lag}"
            assert feat["ema50_lag"] == pytest.approx(truth_ema50_lag, abs=1e-3), \
                f"ts={ts}: ema50_lag {feat['ema50_lag']} vs {truth_ema50_lag}"


def test_regime_tracker_gates_match_research_logic():
    """bull_strong / bear_strong gates fire on same days as the vectorized boolean."""
    m5 = _make_m5(n_days=80)
    d1 = resample_d1(m5)
    d1_feat = add_d1_features(d1)
    m5_with_d1 = attach_d1_to_m5(m5, d1_feat)

    tracker = RegimeTracker(ema_fast=50, ema_slow=200, atr_period=14)
    for _, row in d1.iterrows():
        tracker.update(row)

    cl = m5_with_d1["close_lag_d1"].values
    ema200 = m5_with_d1["ema200_lag_d1"].values
    ema50 = m5_with_d1["ema50_lag_d1"].values

    bull_strong = (cl > ema200) & (ema50 > ema200) & np.isfinite(cl) & np.isfinite(ema200) & np.isfinite(ema50)
    bear_strong = (cl < ema200) & (ema50 < ema200) & np.isfinite(cl) & np.isfinite(ema200) & np.isfinite(ema50)

    # Sample 200 rows.
    for i in range(0, len(m5_with_d1), max(1, len(m5_with_d1) // 200)):
        ts = m5_with_d1.iloc[i]["timestamp"]
        assert tracker.gate_passes("bull_strong", ts) == bool(bull_strong[i]), f"bull_strong mismatch at {ts}"
        assert tracker.gate_passes("bear_strong", ts) == bool(bear_strong[i]), f"bear_strong mismatch at {ts}"


def test_regime_tracker_returns_none_when_no_prior_day():
    """Before any D1 closed, regime_for must return None."""
    tracker = RegimeTracker()
    ts = pd.Timestamp("2020-01-05 12:00", tz="UTC")
    assert tracker.regime_for(ts) is None


def test_regime_tracker_returns_prior_day_features():
    """When current M5 day == day-K, regime_for must use day (K-1)'s features."""
    tracker = RegimeTracker(ema_fast=2, ema_slow=4, atr_period=2)

    class _Lite:
        def __init__(self, ts, high, low, close):
            self.timestamp = ts; self.high = high; self.low = low; self.close = close

    days = [
        _Lite(pd.Timestamp("2020-01-01", tz="UTC"), 110, 90, 100),
        _Lite(pd.Timestamp("2020-01-02", tz="UTC"), 120, 100, 110),
        _Lite(pd.Timestamp("2020-01-03", tz="UTC"), 130, 110, 120),
    ]
    for d in days:
        tracker.update(d)

    # Query M5 on day 3 (midday); should get features from day 2 close.
    feat_d3 = tracker.regime_for(pd.Timestamp("2020-01-03 12:00", tz="UTC"))
    assert feat_d3 is not None
    assert feat_d3["close_lag"] == 110.0  # day 2 close

    # Query M5 on day 2; should get features from day 1.
    feat_d2 = tracker.regime_for(pd.Timestamp("2020-01-02 12:00", tz="UTC"))
    assert feat_d2 is not None
    assert feat_d2["close_lag"] == 100.0  # day 1 close
