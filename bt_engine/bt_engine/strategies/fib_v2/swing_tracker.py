"""SwingTracker — M5 lagged rolling swing high/low.

Mirrors `research/fib_retrace/run_fib_v2_21yr.py::add_m5_features`:
  swing_low_20_lag  = df["low"].shift(1).rolling(20).min()
  swing_high_20_lag = df["high"].shift(1).rolling(20).max()

i.e. at bar t, only the PRIOR 20 M5 bars are used (current bar NOT included).

Used for raw_features only (not in entry rule). Kept for parity audit + debug.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SwingTracker:
    """Lagged rolling swing-low / swing-high over `lb` prior M5 bars."""

    lb: int = 20
    _prior_lows: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    _prior_highs: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    _last_low: Optional[float] = None
    _last_high: Optional[float] = None

    def __post_init__(self) -> None:
        if self.lb < 1:
            raise ValueError(f"lb must be >= 1, got {self.lb}")
        self._prior_lows = deque(maxlen=self.lb)
        self._prior_highs = deque(maxlen=self.lb)

    def update(self, bar) -> None:
        """Feed one M5 bar. AFTER this call, current_swing_*_lag returns the
        lag-1 rolling value (NOT including this bar).

        We achieve causality by:
          1. AT call start: snapshot `_last_low`/`_last_high` of the bar
             previously seen (these enter the prior-window for THIS bar).
          2. Then push them into the deque.
          3. Stash THIS bar's low/high in `_last_low`/`_last_high` for next call.

        Therefore at any moment, the deque holds the prior `lb` bars'
        low/high (matches shift(1).rolling(lb)).
        """
        # Step 1+2: previous bar's low/high enters the rolling window for THIS bar.
        if self._last_low is not None:
            self._prior_lows.append(self._last_low)
            self._prior_highs.append(self._last_high)
        # Step 3: stash current bar's values for next call.
        self._last_low = float(_get(bar, "low"))
        self._last_high = float(_get(bar, "high"))

    @property
    def swing_low_lag(self) -> Optional[float]:
        """Min over prior `lb` bars (excluding current). None until lb full."""
        if len(self._prior_lows) < self.lb:
            return None
        return min(self._prior_lows)

    @property
    def swing_high_lag(self) -> Optional[float]:
        """Max over prior `lb` bars (excluding current). None until lb full."""
        if len(self._prior_highs) < self.lb:
            return None
        return max(self._prior_highs)


def _get(obj, key: str):
    if hasattr(obj, key) and not hasattr(obj, "iloc"):
        return getattr(obj, key)
    return obj[key]
