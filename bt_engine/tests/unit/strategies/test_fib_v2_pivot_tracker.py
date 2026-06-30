"""Unit test: PivotTracker streamed output == research::build_pivot_events vectorized output.

The streaming tracker MUST emit pivots at the exact same `confirm_ts`+`type`+`price`
as the vectorized research function. This is the foundational causality check
for Fib V2.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from bt_engine.strategies.fib_v2.pivot_tracker import PivotTracker

# Research vectorized truth.
from research.fib_retrace.run_fib_v2 import build_pivot_events


def _make_h1(seed: int = 42, n: int = 500) -> pd.DataFrame:
    """Deterministic synthetic H1 frame with rich pivot structure."""
    rng = np.random.default_rng(seed)
    base = 4000.0 + np.cumsum(rng.normal(0, 5, n))
    # Inject some clean pivots: alternating spikes.
    high = base + rng.uniform(2, 8, n)
    low = base - rng.uniform(2, 8, n)
    # Add a few large spikes to make clear strict-max pivots.
    for i in range(20, n - 20, 25):
        high[i] += rng.uniform(20, 50)
    for i in range(35, n - 20, 25):
        low[i] -= rng.uniform(20, 50)
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC"),
        "high": high,
        "low": low,
        "open": (high + low) / 2,
        "close": (high + low) / 2,
        "volume": rng.integers(100, 1000, n),
    })


@pytest.mark.parametrize("lb", [2, 3, 5, 8])
def test_pivot_tracker_matches_vectorized(lb):
    h1 = _make_h1()
    # Stream
    tracker = PivotTracker(lb=lb)
    streamed = []
    for _, row in h1.iterrows():
        events = tracker.update(row)
        for ev in events:
            streamed.append({
                "confirm_ts": ev.confirm_ts,
                "type": ev.type,
                "price": ev.price,
            })

    # Vectorized truth from research.
    vectorized = build_pivot_events(h1, lb)
    truth = [{"confirm_ts": ev["confirm_ts"], "type": ev["type"], "price": ev["price"]} for ev in vectorized]

    # Sort by (confirm_ts, type) — research emits H+L on same ts in undefined order.
    # Normalize timestamps: research uses .values (naive datetime64), streaming
    # preserves UTC tz. Strip tz for comparison since the wall-clock value is identical.
    def _ts(x):
        ts = pd.Timestamp(x)
        return ts.tz_localize(None) if ts.tzinfo is not None else ts

    def _key(e):
        return (_ts(e["confirm_ts"]), e["type"])
    streamed.sort(key=_key)
    truth.sort(key=_key)

    assert len(streamed) == len(truth), (
        f"streamed={len(streamed)} vs truth={len(truth)} pivots\n"
        f"first 5 streamed: {streamed[:5]}\nfirst 5 truth: {truth[:5]}"
    )
    for s, t in zip(streamed, truth):
        assert _ts(s["confirm_ts"]) == _ts(t["confirm_ts"]), f"{s} vs {t}"
        assert s["type"] == t["type"], f"{s} vs {t}"
        assert s["price"] == pytest.approx(t["price"], abs=1e-9), f"{s} vs {t}"


def test_pivot_tracker_no_emission_before_window_full():
    h1 = _make_h1(n=20)
    tracker = PivotTracker(lb=5)
    # First 2*lb = 10 bars: tracker should emit nothing (window not full).
    for _, row in h1.iloc[:10].iterrows():
        assert tracker.update(row) == []


def test_pivot_tracker_emits_at_confirm_ts_not_pivot_ts():
    """Pivot at H1 bar i must be tagged with confirm_ts = bar[i+lb].timestamp."""
    n = 30
    lb = 3
    ts_idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    high = np.full(n, 100.0)
    high[10] = 200.0  # strict-max pivot at i=10
    low = np.full(n, 90.0)
    h1 = pd.DataFrame({
        "timestamp": ts_idx,
        "high": high, "low": low,
        "open": high, "close": high,
        "volume": np.ones(n),
    })

    tracker = PivotTracker(lb=lb)
    emissions = []
    for _, row in h1.iterrows():
        for ev in tracker.update(row):
            emissions.append(ev)

    # Pivot at i=10, lb=3 → confirm at bar 13.
    high_pivots = [e for e in emissions if e.type == "H"]
    assert len(high_pivots) == 1
    assert high_pivots[0].pivot_ts == ts_idx[10]
    assert high_pivots[0].confirm_ts == ts_idx[13]
    assert high_pivots[0].price == 200.0


def test_pivot_tracker_skips_ties():
    """Research uses strict-max (count==1). Tied highs should NOT pivot."""
    n = 30
    lb = 2
    ts_idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    high = np.full(n, 100.0)
    high[10] = 200.0
    high[12] = 200.0  # tied — neither is strict
    low = np.full(n, 90.0)
    h1 = pd.DataFrame({
        "timestamp": ts_idx,
        "high": high, "low": low,
        "open": high, "close": high,
        "volume": np.ones(n),
    })

    tracker = PivotTracker(lb=lb)
    emissions = []
    for _, row in h1.iterrows():
        for ev in tracker.update(row):
            emissions.append(ev)

    # i=10 has high 200 but tied with i=12 within window — strict count == 2 → no pivot.
    high_pivots = [e for e in emissions if e.type == "H"]
    # Depending on window timing, both might be suppressed.
    assert all(e.pivot_ts not in (ts_idx[10], ts_idx[12]) for e in high_pivots)
