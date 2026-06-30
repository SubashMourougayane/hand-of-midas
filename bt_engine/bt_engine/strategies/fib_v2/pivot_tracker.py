"""PivotTracker — incremental causal H1 pivot detector.

Mirrors `research/fib_retrace/run_fib.py::detect_pivots` + `build_pivot_events`
exactly. NO center-rolling (would be look-ahead). For pivot_lb=N:

  Pivot at bar i is identified when bar i is a STRICT max (or min) over the
  window `[i-N, i+N]`. The pivot is "confirmed" once bar i+N has closed.
  We emit the PivotEvent at the moment bar i+N closes, tagging it with
  `confirm_ts = bar[i+N].timestamp` (the H1 left-label of the confirmation
  bar — same as research).

Strict-max means count(highs[i-N..i+N] == highs[i]) == 1. This matches the
research vectorized version (no ties allowed).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class PivotEvent:
    """One pivot, emitted when its confirmation bar closes."""

    confirm_ts: pd.Timestamp
    """Timestamp of the confirmation bar (bar at idx pivot_idx + lb)."""

    type: str  # "H" | "L"
    price: float
    pivot_ts: pd.Timestamp
    """Timestamp of the actual pivot bar (lb bars before confirm_ts)."""


class PivotTracker:
    """Streaming pivot detector. Feed CLOSED H1 bars one at a time."""

    def __init__(self, lb: int = 5) -> None:
        if lb < 1:
            raise ValueError(f"lb must be >= 1, got {lb}")
        self.lb = lb
        # Ring buffer of last 2*lb+1 H1 bars (timestamp, high, low). When full,
        # the center index is `lb`. If center is strict max/min over the window,
        # emit pivot at that point — its confirm_ts is the NEWEST bar's ts.
        self._win: deque[tuple[pd.Timestamp, float, float]] = deque(maxlen=2 * lb + 1)

    def update(self, bar_h1) -> list[PivotEvent]:
        """Feed one CLOSED H1 bar. Returns list of newly-confirmed pivots (0..2).

        bar_h1 must have attributes/keys: timestamp, high, low. Accepts Bar dataclass,
        pd.Series, or dict.
        """
        ts = _get(bar_h1, "timestamp")
        hi = float(_get(bar_h1, "high"))
        lo = float(_get(bar_h1, "low"))
        self._win.append((ts, hi, lo))

        if len(self._win) < 2 * self.lb + 1:
            return []

        # Window is full; center is index lb.
        center_ts, center_hi, center_lo = self._win[self.lb]
        confirm_ts = ts  # newest bar's timestamp = confirmation bar (research convention)

        events: list[PivotEvent] = []

        # Strict-max test for high pivot.
        max_hi = max(b[1] for b in self._win)
        if center_hi == max_hi and sum(1 for b in self._win if b[1] == center_hi) == 1:
            events.append(
                PivotEvent(confirm_ts=confirm_ts, type="H", price=center_hi, pivot_ts=center_ts)
            )

        # Strict-min test for low pivot.
        min_lo = min(b[2] for b in self._win)
        if center_lo == min_lo and sum(1 for b in self._win if b[2] == center_lo) == 1:
            events.append(
                PivotEvent(confirm_ts=confirm_ts, type="L", price=center_lo, pivot_ts=center_ts)
            )

        return events


def _get(obj, key: str):
    """Polymorphic getter: works on dataclass-like, Series, dict."""
    if hasattr(obj, key):
        return getattr(obj, key)
    if hasattr(obj, "get"):
        return obj.get(key) if not hasattr(obj, "iloc") else obj[key]
    return obj[key]
