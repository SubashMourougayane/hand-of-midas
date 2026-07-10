"""HtfBiasTracker — causal M15 trend bias derived from the M5 stream.

Exact streaming mirror of research/cobrax/cobrax.py::bias_at:

    htf   = resample(M5, 15min, label="left", closed="left")
    sma   = htf.close.rolling(20).mean()
    bias  = sign(close - nan_to_num(sma, nan=close))     # 0 during warmup (<20 M15 bars)
    close_ts = htf_label + 15min                          # M15 CLOSE time
    bias_at(t) = bias[ searchsorted(close_ts, t, "right") - 1 ]   # last M15 CLOSED by t

Causal guarantee: the bias returned for an M5 bar reflects ONLY M15 bars whose
CLOSE time is <= that M5 bar's OPEN (left-label) timestamp. No interior peek —
an M15 bar is finalized on the bar-boundary rollover, using the last M5 close it
contained, and never contributes to bias until then.

Usage (in the strategy's on_bar, per just-closed M5 bar):
    tracker.update(bar)     # finalizes the previous M15 bucket on rollover
    b = tracker.bias()      # -1 / 0 / +1 for THIS bar (matches bias_at(bar.ts))
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import pandas as pd

from ..fib_v2.pivot_tracker import _get


class HtfBiasTracker:
    """Streaming M15 SMA20 bias. Feed CLOSED M5 bars in order."""

    def __init__(self, tf_min: int = 15, sma_period: int = 20) -> None:
        self.tf = pd.Timedelta(minutes=tf_min)
        self.sma_period = sma_period
        # Current (still-accumulating) M15 bucket.
        self._cur_label: Optional[pd.Timestamp] = None
        self._cur_close: Optional[float] = None
        # Finalized M15 closes (for the rolling SMA) + latest finalized bias/close_ts.
        self._closes: deque[float] = deque(maxlen=sma_period)
        self._latest_bias: int = 0
        self._latest_close_ts: Optional[pd.Timestamp] = None

    def _floor(self, ts: pd.Timestamp) -> pd.Timestamp:
        # Align to the M15 grid (left label of the bucket this M5 bar belongs to).
        return ts.floor(self.tf)

    def _finalize_current(self) -> None:
        """Close the current M15 bucket: append its close, refresh bias."""
        if self._cur_label is None or self._cur_close is None:
            return
        self._closes.append(self._cur_close)
        # Research: nan_to_num(sma, nan=close) → bias 0 until 20 M15 bars exist.
        if len(self._closes) >= self.sma_period:
            sma = sum(self._closes) / len(self._closes)
        else:
            sma = self._cur_close  # (close - close) = 0 → bias 0
        d = self._cur_close - sma
        self._latest_bias = 1 if d > 0 else (-1 if d < 0 else 0)
        self._latest_close_ts = self._cur_label + self.tf

    def update(self, bar) -> None:
        """Feed one CLOSED M5 bar (Bar / Series / dict with timestamp, close)."""
        ts = _get(bar, "timestamp")
        close = float(_get(bar, "close"))
        label = self._floor(ts)
        if self._cur_label is None:
            self._cur_label = label
            self._cur_close = close
            return
        if label != self._cur_label:
            # Rollover: the previous bucket is complete → finalize it BEFORE this
            # bar can query bias (matches bias_at including a bucket whose close_ts
            # == this bar's ts). Then start the new bucket.
            self._finalize_current()
            self._cur_label = label
            self._cur_close = close
        else:
            # Still inside the same bucket — track the running (last) close.
            self._cur_close = close

    def bias(self) -> int:
        """Bias for the current bar: -1 / 0 / +1. 0 until the first M15 bucket
        finalizes and during the <20-bar SMA warmup (research parity)."""
        return self._latest_bias
