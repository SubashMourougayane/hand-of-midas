"""MultiTfHistoryView — resample M5 base frame to H1+D1 once at init, then
serve causal `history_up_to(t)` lookups for each timeframe.

Used by FibV2EnsembleStrategy so the strategy doesn't have to resample M5
history on every tick. Returned frames respect the close-bar causality rule:
a bar at left-label L is visible at time `t` only if `L + tf_seconds <= t`.

Mirrors research::run_fib_v2_regime.py::resample_d1 + run_fib.py::resample
which both use `label='left', closed='left'`.
"""
from __future__ import annotations

import pandas as pd


class MultiTfHistoryView:
    """Build H1 + D1 frames ONCE from an M5 source frame; serve causal lookups."""

    def __init__(self, m5_frame: pd.DataFrame) -> None:
        if m5_frame["timestamp"].dt.tz is None:
            raise ValueError("M5 frame must have UTC tz-aware timestamps.")
        m5 = m5_frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        self._m5 = m5
        self._h1 = self._resample(m5, "1h")
        self._d1 = self._resample(m5, "1D")

    @staticmethod
    def _resample(m5: pd.DataFrame, rule: str) -> pd.DataFrame:
        """label='left', closed='left' — matches research::resample.

        Bar at left-label L spans [L, L + rule). Bar CLOSES at L + rule.
        """
        out = (
            m5.set_index("timestamp")
            .resample(rule, label="left", closed="left")
            .agg(open=("open", "first"), high=("high", "max"),
                 low=("low", "min"), close=("close", "last"),
                 volume=("volume", "sum"))
            .dropna()
            .reset_index()
        )
        return out

    def h1_history_up_to(self, t: pd.Timestamp) -> pd.DataFrame:
        """All H1 bars CLOSED at or before t. Returns rows where L + 1h <= t."""
        t = pd.Timestamp(t)
        close_ts = self._h1["timestamp"] + pd.Timedelta(hours=1)
        return self._h1[close_ts <= t].reset_index(drop=True)

    def d1_history_up_to(self, t: pd.Timestamp) -> pd.DataFrame:
        """All D1 bars CLOSED at or before t. Returns rows where L + 1D <= t."""
        t = pd.Timestamp(t)
        close_ts = self._d1["timestamp"] + pd.Timedelta(days=1)
        return self._d1[close_ts <= t].reset_index(drop=True)

    @property
    def h1(self) -> pd.DataFrame:
        return self._h1

    @property
    def d1(self) -> pd.DataFrame:
        return self._d1
