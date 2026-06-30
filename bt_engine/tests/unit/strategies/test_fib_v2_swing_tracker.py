"""Unit test: SwingTracker streamed output == research::add_m5_features
swing_low_20_lag / swing_high_20_lag columns row-for-row.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from bt_engine.strategies.fib_v2.swing_tracker import SwingTracker
from research.fib_retrace.run_fib_v2_21yr import add_m5_features


def _make_m5(seed: int = 42, n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 4000.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0.5, 0.5, n))
    low = close - np.abs(rng.normal(0.5, 0.5, n))
    open_ = close + rng.normal(0, 0.3, n)
    open_ = np.clip(open_, low, high)
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="5min", tz="UTC"),
        "open": open_, "high": high, "low": low, "close": close,
        "volume": rng.integers(1, 100, n),
    })


@pytest.mark.parametrize("lb", [5, 10, 20, 30])
def test_swing_tracker_matches_research(lb):
    m5 = _make_m5()
    m5_feat = add_m5_features(m5, swing_lb=lb)

    tracker = SwingTracker(lb=lb)
    streamed_lows = []
    streamed_highs = []
    for _, row in m5.iterrows():
        tracker.update(row)
        streamed_lows.append(tracker.swing_low_lag)
        streamed_highs.append(tracker.swing_high_lag)

    truth_lows = m5_feat[f"swing_low_{lb}_lag"].values
    truth_highs = m5_feat[f"swing_high_{lb}_lag"].values

    # Compare row-by-row. Truth is NaN before lb prior bars; streaming is None.
    for i, (s_lo, s_hi, t_lo, t_hi) in enumerate(zip(streamed_lows, streamed_highs, truth_lows, truth_highs)):
        if pd.isna(t_lo):
            assert s_lo is None, f"row {i}: streaming low {s_lo} but truth NaN"
        else:
            assert s_lo == pytest.approx(t_lo, abs=1e-9), f"row {i}: low {s_lo} vs {t_lo}"
        if pd.isna(t_hi):
            assert s_hi is None, f"row {i}: streaming high {s_hi} but truth NaN"
        else:
            assert s_hi == pytest.approx(t_hi, abs=1e-9), f"row {i}: high {s_hi} vs {t_hi}"
