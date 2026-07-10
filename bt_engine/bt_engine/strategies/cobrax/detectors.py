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


@dataclass(frozen=True)
class SetupCandidate:
    """A sweep→MSS→FVG∩OTE setup confirmed AT signal bar i (fill not yet found)."""

    side: int
    entry_level: float   # elvl
    stop: float
    sweep_ext: float
    sweep_i: int         # local index of the sweep bar
    mss_i: int           # local index of the MSS bar
    fvg_i: int           # local index of the FVG bar


def _detect_setup_side(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
    cp: "ConfirmedPivots", i: int, bias: int, cfg, iside: int,
) -> Optional[SetupCandidate]:
    """Research run() inner logic (cobrax.py:99-168) for ONE signal bar i + ONE side,
    up to FVG∩OTE (retrace fill handled separately). Faithful line-for-line."""
    n = len(h)
    shi_ci, shi_px = cp.hi_confirm_idx, cp.hi_price
    slo_ci, slo_px = cp.lo_confirm_idx, cp.lo_price
    sweep_lb = cfg.sweep_lb
    mss_lb = cfg.mss_lb
    w0 = max(0, i - sweep_lb)

    if iside < 0:  # short: sweep a HIGH, MSS breaks a LOW
        a = int(np.searchsorted(shi_ci, w0 - mss_lb, "left"))
        b = int(np.searchsorted(shi_ci, i, "left"))
        if b <= a:
            return None
        sw_level = sw_ext = sw_k = None
        for si in range(b - 1, a - 1, -1):
            ci = int(shi_ci[si]); lvl = float(shi_px[si]); s = max(ci, w0)
            hh = h[s:i + 1]
            if len(hh) == 0:
                continue
            if hh.max() > lvl:
                k = s + int(np.argmax(hh > lvl))
                if cfg.sweep_reject and not (c[k] < lvl):
                    continue
                sw_level = lvl; sw_ext = float(hh.max()); sw_k = k; break
        if sw_level is None:
            return None
        lb_ = int(np.searchsorted(slo_ci, i, "left"))
        if lb_ <= 0:
            return None
        mss_lvl = float(slo_px[lb_ - 1]); mss_bar = -1
        for k in range(sw_k + 1, i + 1):
            if c[k] < mss_lvl:
                mss_bar = k; break
        if mss_bar < 0:
            return None
    else:  # long: sweep a LOW, MSS breaks a HIGH
        a = int(np.searchsorted(slo_ci, w0 - mss_lb, "left"))
        b = int(np.searchsorted(slo_ci, i, "left"))
        if b <= a:
            return None
        sw_level = sw_ext = sw_k = None
        for si in range(b - 1, a - 1, -1):
            ci = int(slo_ci[si]); lvl = float(slo_px[si]); s = max(ci, w0)
            ll = l[s:i + 1]
            if len(ll) == 0:
                continue
            if ll.min() < lvl:
                k = s + int(np.argmax(ll < lvl))
                if cfg.sweep_reject and not (c[k] > lvl):
                    continue
                sw_level = lvl; sw_ext = float(ll.min()); sw_k = k; break
        if sw_level is None:
            return None
        hb = int(np.searchsorted(shi_ci, i, "left"))
        if hb <= 0:
            return None
        mss_lvl = float(shi_px[hb - 1]); mss_bar = -1
        for k in range(sw_k + 1, i + 1):
            if c[k] > mss_lvl:
                mss_bar = k; break
        if mss_bar < 0:
            return None

    if cfg.bias_align and bias != iside:
        return None

    fvg = None
    for k in range(max(mss_bar, 2), min(mss_bar + cfg.fvg_wait, n)):
        f = detect_fvg(h, l, k, iside, cfg.fvg_min)
        if f is not None:
            fvg = f; break
    if fvg is None:
        return None
    elvl = fvg["ce"] if cfg.entry == "ce" else fvg["prox"]

    rr = ote_ratio(iside, sw_ext, sw_k, fvg["k"], elvl, h, l)
    if rr is None or not (cfg.ote_lo <= rr <= cfg.ote_hi):
        return None

    stop = sw_ext if cfg.sl == "sweep" else fvg["far"]
    return SetupCandidate(
        side=iside, entry_level=float(elvl), stop=float(stop), sweep_ext=float(sw_ext),
        sweep_i=int(sw_k), mss_i=int(mss_bar), fvg_i=int(fvg["k"]),
    )


def detect_setup_at(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
    cp: "ConfirmedPivots", i: int, bias: int, cfg,
) -> Optional[SetupCandidate]:
    """Most-recent setup at signal bar i, short side first (research side order)."""
    sides = (-1, 1) if cfg.direction == "both" else ((-1,) if cfg.direction == "short" else (1,))
    for iside in sides:
        s = _detect_setup_side(o, h, l, c, cp, i, bias, cfg, iside)
        if s is not None:
            return s
    return None


def _retrace_fill(h: np.ndarray, l: np.ndarray, setup: "SetupCandidate", cfg, n: int) -> int:
    """First retrace touch of the entry level after the FVG bar (cobrax.py:170-174).
    Returns the local fill index, or -1 if untouched within retrace_wait."""
    elvl = setup.entry_level
    for k in range(setup.fvg_i + 1, min(setup.fvg_i + 1 + cfg.retrace_wait, n)):
        if setup.side < 0 and h[k] >= elvl:
            return k
        if setup.side > 0 and l[k] <= elvl:
            return k
    return -1


def fills_at_bar(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
    cp: "ConfirmedPivots", bias_arr: np.ndarray, cfg, m: int, lookback: int = 120,
) -> list["SetupCandidate"]:
    """All trades whose retrace fill lands EXACTLY on local bar m — one per side, using
    the SMALLEST signal bar i that produces it (== research's greedy `used=set((fi,side))`
    dedup, since all candidate i for fill m lie within [m - (fvg_wait+retrace_wait), m]).

    This reproduces research's outer-loop enumeration causally: at bar m (just closed)
    we know h[m]/l[m], so a fill touching on m is detectable now with NO forward peek.
    Returns SetupCandidate(s) (side/entry/stop/geometry) to fill at bar m.
    """
    out: list[SetupCandidate] = []
    sides = (-1, 1) if cfg.direction == "both" else ((-1,) if cfg.direction == "short" else (1,))
    lo = max(cfg.mss_lb + 2, m - lookback)
    for iside in sides:
        for i in range(lo, m + 1):  # ascending → first (smallest i) wins, like research
            setup = _detect_setup_side(o, h, l, c, cp, i, int(bias_arr[i]), cfg, iside)
            if setup is None:
                continue
            fi = _retrace_fill(h, l, setup, cfg, len(h))
            if fi == m:
                out.append(setup)
                break  # smallest-i winner for this side
    return out


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
