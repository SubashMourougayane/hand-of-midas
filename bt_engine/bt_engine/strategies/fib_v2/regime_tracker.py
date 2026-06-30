"""RegimeTracker — incremental D1 regime detection (causal, lagged 1 day).

Mirrors research/fib_retrace/run_fib_v2_regime.py::{add_d1_features, attach_d1_to_m5}
exactly:
  - D1 EMA200, EMA50 (ewm span, adjust=False).
  - D1 ATR14 (rolling mean of true-range).
  - All features lagged via shift(1) → at M5 timestamp t, only the prior closed
    D1's features are visible. attach_d1_to_m5 uses `t.dt.floor("1D")` to lookup
    the D1 row whose left-label matches t's UTC date; the row's `_lag` columns
    hold the prior D1's features.

  In streaming terms: when D1 day-K closes (= UTC midnight of day K+1), we
  immediately update internal state with day-K's features. M5 bars on day K+1
  query `regime_for(ts)` which returns features computed from days <= K.

Causality contract:
  - Strategy MUST only call `regime_for(ts)` when ts.floor('1D') has at least
    one prior closed day in the tracker. Returns None otherwise.
  - The "lag" is implicit: regime_for(ts) returns features as of the LAST
    closed D1 (i.e. the one with timestamp == ts.floor('1D') - 1D or earlier).
    This matches `close_lag_d1`, `ema200_lag_d1`, etc. in attach_d1_to_m5.

Regime gates (per research line 89-102):
  bull         = close_lag > ema200_lag
  bull_strong  = close_lag > ema200_lag AND ema50_lag > ema200_lag
  bear         = close_lag < ema200_lag
  bear_strong  = close_lag < ema200_lag AND ema50_lag < ema200_lag
  sideways     = |close_lag - ema200_lag| / ema200_lag < sideways_band_pct
  any          = always True (subject to finite features)

  All gates also require np.isfinite(close_lag) AND np.isfinite(ema200_lag).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import math
import pandas as pd


@dataclass
class _D1Features:
    """Features computed AT the close of a D1 bar (NOT yet lagged).

    These become the `_lag` features for the NEXT day's M5 bars.
    """

    bar_open_ts: pd.Timestamp  # left-label of the D1 bar
    close: float
    ema200: float
    ema50: float
    atr14: Optional[float]  # None until we have 14 TR samples


@dataclass
class RegimeTracker:
    """Streaming D1 regime tracker. Call `update(d1_bar)` with each CLOSED D1.

    Then `regime_for(m5_ts)` returns the regime row that the M5 bar should
    observe (matches `attach_d1_to_m5` semantics).
    """

    ema_fast: int = 50  # EMA50 period
    ema_slow: int = 200  # EMA200 period
    atr_period: int = 14
    sideways_band_pct: float = 0.03

    # Running EMA state.
    _ema_fast_val: Optional[float] = None
    _ema_slow_val: Optional[float] = None
    # Running TR buffer for ATR.
    _tr_buf: list[float] = field(default_factory=list)
    _prev_close: Optional[float] = None
    # Map from `bar_open_ts` (D1 left-label) → features computed AT close of that bar.
    _features: dict[pd.Timestamp, _D1Features] = field(default_factory=dict)
    # Ordered list of D1 left-labels we've ingested (for lookup of prior day).
    _ordered_ts: list[pd.Timestamp] = field(default_factory=list)

    def update(self, d1_bar) -> None:
        """Ingest one CLOSED D1 bar. Updates internal EMA/ATR state."""
        ts = _get(d1_bar, "timestamp")
        hi = float(_get(d1_bar, "high"))
        lo = float(_get(d1_bar, "low"))
        cl = float(_get(d1_bar, "close"))

        # True range with PRIOR close
        if self._prev_close is None:
            tr = hi - lo
        else:
            tr = max(hi - lo, abs(hi - self._prev_close), abs(lo - self._prev_close))
        self._tr_buf.append(tr)
        if len(self._tr_buf) > self.atr_period:
            self._tr_buf.pop(0)
        atr = sum(self._tr_buf) / len(self._tr_buf) if len(self._tr_buf) == self.atr_period else None

        # ewm(span=N, adjust=False): seed with first value, then k = 2/(N+1).
        self._ema_fast_val = _ewm_update(self._ema_fast_val, cl, self.ema_fast)
        self._ema_slow_val = _ewm_update(self._ema_slow_val, cl, self.ema_slow)

        feat = _D1Features(
            bar_open_ts=ts,
            close=cl,
            ema200=self._ema_slow_val,
            ema50=self._ema_fast_val,
            atr14=atr,
        )
        self._features[ts] = feat
        self._ordered_ts.append(ts)
        self._prev_close = cl

    def regime_for(self, m5_ts: pd.Timestamp) -> Optional[dict]:
        """Return regime features for the M5 timestamp's day (= prior D1's features).

        Matches research's attach_d1_to_m5:
          - floor(m5_ts, '1D') → D1 left-label for the day M5 lives in.
          - The `_lag` features at that floor = features computed AT close of
            the PRIOR D1 bar (the one labeled `floor - 1D`).

        Returns None if no prior D1 closed yet (causal gate).

        Returns dict with keys: close_lag, ema200_lag, ema50_lag, atr14_lag,
        d1_dist_pct_lag — all matching the `_d1` suffix columns in research.
        """
        day_floor = pd.Timestamp(m5_ts).floor("1D")
        # The "lag" row for day D = features of the LAST closed D1 < day D.
        # We need the D1 whose bar_open_ts is the GREATEST value strictly < day_floor.
        # Most recent D1 left-label is _ordered_ts[-1]. If it < day_floor, use it.
        # If it == day_floor, we need _ordered_ts[-2] (the day before).
        prior_feat: Optional[_D1Features] = None
        for prev_ts in reversed(self._ordered_ts):
            if prev_ts < day_floor:
                prior_feat = self._features[prev_ts]
                break
        if prior_feat is None:
            return None

        ema200_lag = prior_feat.ema200
        close_lag = prior_feat.close
        ema50_lag = prior_feat.ema50
        atr14_lag = prior_feat.atr14

        # Sanity (matches research line 102: regime_mask requires finite features).
        if not math.isfinite(close_lag) or not math.isfinite(ema200_lag) or not math.isfinite(ema50_lag):
            return None

        dist_pct_lag = (close_lag - ema200_lag) / ema200_lag if ema200_lag != 0 else float("nan")
        return {
            "close_lag": close_lag,
            "ema200_lag": ema200_lag,
            "ema50_lag": ema50_lag,
            "atr14_lag": atr14_lag,
            "d1_dist_pct_lag": dist_pct_lag,
        }

    def gate_passes(self, regime_label: str, m5_ts: pd.Timestamp) -> bool:
        """Evaluate the regime gate for the given M5 ts.

        regime_label ∈ {bull, bull_strong, bear, bear_strong, sideways, any}.
        """
        feat = self.regime_for(m5_ts)
        if feat is None:
            return False
        close_lag = feat["close_lag"]
        ema200_lag = feat["ema200_lag"]
        ema50_lag = feat["ema50_lag"]
        dist_pct = feat["d1_dist_pct_lag"]

        if regime_label == "bull":
            return close_lag > ema200_lag
        if regime_label == "bull_strong":
            return close_lag > ema200_lag and ema50_lag > ema200_lag
        if regime_label == "bear":
            return close_lag < ema200_lag
        if regime_label == "bear_strong":
            return close_lag < ema200_lag and ema50_lag < ema200_lag
        if regime_label == "sideways":
            return abs(dist_pct) < self.sideways_band_pct
        if regime_label == "any":
            return True
        raise ValueError(f"unknown regime label: {regime_label}")


def _ewm_update(prev: Optional[float], value: float, span: int) -> float:
    """Pandas ewm(span=N, adjust=False) update.

    First value: seed = value (matches ewm with adjust=False initialisation).
    Subsequent: alpha = 2/(N+1); new = alpha*value + (1-alpha)*prev.
    """
    if prev is None:
        return value
    alpha = 2.0 / (span + 1.0)
    return alpha * value + (1.0 - alpha) * prev


def _get(obj, key: str):
    """Polymorphic getter: works on Bar dataclass, dict, pd.Series, namedtuple."""
    if hasattr(obj, key) and not hasattr(obj, "iloc"):
        return getattr(obj, key)
    return obj[key]
