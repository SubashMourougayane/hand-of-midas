"""COBRAX structure detectors — pure functions, ported bit-for-bit from
research/cobrax/cobrax.py.

These are the geometric primitives (pivots, FVG, OTE) shared by:
  - the Phase-2 parity oracle (tested directly against the research engine), and
  - the streaming strategy (state.py / strategy.py), which wraps them per-bar.

Causal note: `confirmed_pivots` mirrors research's center-rolling `pivots()` but
returns each pivot tagged with its CONFIRMATION index (pivot_idx + lb) — a pivot
is only knowable once bar pivot_idx+lb has closed. The streaming strategy must
never reference a swing before its confirm index. FVG/OTE are point-wise on
already-closed bars.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ConfirmedPivots:
    """Swing extremes tagged by CONFIRMATION index (pivot_idx + lb)."""

    hi_confirm_idx: np.ndarray  # int[] confirm indices for swing HIGHs (sorted asc)
    hi_price: np.ndarray        # float[] the swing-high price at each
    lo_confirm_idx: np.ndarray  # int[] confirm indices for swing LOWs
    lo_price: np.ndarray        # float[] the swing-low price at each


def confirmed_pivots(high: np.ndarray, low: np.ndarray, lb: int) -> ConfirmedPivots:
    """Port of research `pivots()` + confirm-index derivation (cobrax.py:60-82).

    NON-STRICT (`>=` / `<=`) center-rolling — ties CAN mark multiple pivots, exactly
    like research. (PivotTracker in fib_v2 is STRICT; do not swap it in here or
    parity breaks on ties. On XAU M5 exact ties are near-zero — parity confirms.)
    """
    n = len(high)
    w = 2 * lb + 1
    rmax = pd.Series(high).rolling(w, center=True).max().values
    rmin = pd.Series(low).rolling(w, center=True).min().values
    ph = (high >= rmax) & ~np.isnan(rmax)
    pl = (low <= rmin) & ~np.isnan(rmin)
    hpiv = np.where(ph)[0]
    lpiv = np.where(pl)[0]
    hc = hpiv + lb
    lc = lpiv + lb
    mh = hc < n
    ml = lc < n
    return ConfirmedPivots(
        hi_confirm_idx=hc[mh],
        hi_price=high[hpiv[mh]],
        lo_confirm_idx=lc[ml],
        lo_price=low[lpiv[ml]],
    )


def detect_fvg(
    high: np.ndarray, low: np.ndarray, k: int, side: int, fvg_min: float,
) -> Optional[dict]:
    """3-bar FVG at bar k (port of cobrax.py:150-155). Returns None if no gap /
    below fvg_min. `prox` = proximal edge (entry='edge' level), `far` = far edge
    (SL='fvg' anchor), `ce` = mid.

    side<0 (short): bearish gap where high[k] < low[k-2].
    side>0 (long):  bullish gap where low[k]  > high[k-2].
    """
    if k < 2:
        return None
    if side < 0 and high[k] < low[k - 2]:
        sz = low[k - 2] - high[k]
        if sz >= fvg_min:
            return {"k": k, "prox": float(high[k]), "far": float(low[k - 2]),
                    "ce": float((low[k - 2] + high[k]) / 2.0)}
    if side > 0 and low[k] > high[k - 2]:
        sz = low[k] - high[k - 2]
        if sz >= fvg_min:
            return {"k": k, "prox": float(low[k]), "far": float(high[k - 2]),
                    "ce": float((low[k] + high[k - 2]) / 2.0)}
    return None


def ote_ratio(
    side: int, sw_ext: float, sw_k: int, fvg_k: int, elvl: float,
    high: np.ndarray, low: np.ndarray,
) -> Optional[float]:
    """Fib-OTE position of the entry level within the swing→retrace leg
    (port of cobrax.py:159-167). Returns the ratio in [0,1]-ish or None if the
    leg has non-positive range. Caller checks `ote_lo <= ratio <= ote_hi`.

    Causal: fib0 is the extreme over [sw_k, fvg_k] — all bars <= the FVG bar,
    strictly before any fill.
    """
    if side < 0:
        fib1 = sw_ext
        fib0 = float(low[sw_k:fvg_k + 1].min())
        rng = fib1 - fib0
        if rng <= 0:
            return None
        return (elvl - fib0) / rng
    else:
        fib1 = sw_ext
        fib0 = float(high[sw_k:fvg_k + 1].max())
        rng = fib0 - fib1
        if rng <= 0:
            return None
        return (fib0 - elvl) / rng
