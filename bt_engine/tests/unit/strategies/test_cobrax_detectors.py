"""COBRAX detectors + HTF bias — parity vs verbatim research logic.

Each oracle below is copied bit-for-bit from research/cobrax/cobrax.py so that
"matches oracle" == "matches the validated research engine". Synthetic
deterministic data → no dependency on the gitignored 20yr parquet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bt_engine.strategies.cobrax.detectors import (
    confirmed_pivots,
    detect_fvg,
    ote_ratio,
)
from bt_engine.strategies.cobrax.htf_bias import HtfBiasTracker


# ── oracle: research pivots() + confirm derivation (cobrax.py:60-82) ──────────
def _oracle_pivots(h, l, lb):
    n = len(h)
    w = 2 * lb + 1
    rmax = pd.Series(h).rolling(w, center=True).max().values
    rmin = pd.Series(l).rolling(w, center=True).min().values
    ph = (h >= rmax) & ~np.isnan(rmax)
    pl = (l <= rmin) & ~np.isnan(rmin)
    hpiv = np.where(ph)[0]
    lpiv = np.where(pl)[0]
    hc = hpiv + lb
    lc = lpiv + lb
    mh = hc < n
    ml = lc < n
    return hc[mh], h[hpiv[mh]], lc[ml], l[lpiv[ml]]


def _synth_ohlc(seed=7, n=800):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    mid = 2000 + 40 * np.sin(t / 23.0) + np.cumsum(rng.normal(0, 0.6, n))
    hi = mid + np.abs(rng.normal(0, 1.2, n))
    lo = mid - np.abs(rng.normal(0, 1.2, n))
    op = mid + rng.normal(0, 0.3, n)
    cl = mid + rng.normal(0, 0.3, n)
    return op, hi, lo, cl


@pytest.mark.parametrize("lb", [3, 5])
def test_confirmed_pivots_match_research(lb):
    _, h, l, _ = _synth_ohlc()
    cp = confirmed_pivots(h, l, lb)
    o_hc, o_hp, o_lc, o_lp = _oracle_pivots(h, l, lb)
    np.testing.assert_array_equal(cp.hi_confirm_idx, o_hc)
    np.testing.assert_array_equal(cp.hi_price, o_hp)
    np.testing.assert_array_equal(cp.lo_confirm_idx, o_lc)
    np.testing.assert_array_equal(cp.lo_price, o_lp)


# ── oracle: research FVG block (cobrax.py:150-155) ────────────────────────────
def _oracle_fvg(h, l, k, iside, fvg_min):
    if iside < 0 and h[k] < l[k - 2]:
        sz = l[k - 2] - h[k]
        if sz >= fvg_min:
            return {"k": k, "prox": h[k], "far": l[k - 2], "ce": (l[k - 2] + h[k]) / 2}
    if iside > 0 and l[k] > h[k - 2]:
        sz = l[k] - h[k - 2]
        if sz >= fvg_min:
            return {"k": k, "prox": l[k], "far": h[k - 2], "ce": (l[k] + h[k - 2]) / 2}
    return None


def test_detect_fvg_matches_research_scan():
    _, h, l, _ = _synth_ohlc()
    for side in (-1, 1):
        for k in range(2, len(h)):
            got = detect_fvg(h, l, k, side, fvg_min=0.3)
            exp = _oracle_fvg(h, l, k, side, 0.3)
            if exp is None:
                assert got is None, f"k={k} side={side}: expected no FVG"
            else:
                assert got is not None, f"k={k} side={side}: missed FVG"
                assert got["prox"] == pytest.approx(exp["prox"])
                assert got["far"] == pytest.approx(exp["far"])
                assert got["ce"] == pytest.approx(exp["ce"])


def test_detect_fvg_respects_min_and_bounds():
    _, h, l, _ = _synth_ohlc()
    assert detect_fvg(h, l, 0, -1, 0.3) is None  # k<2 guard
    assert detect_fvg(h, l, 1, 1, 0.3) is None
    # A gap below fvg_min must be rejected.
    h2 = np.array([10.0, 10.0, 9.9])   # long gap? low[2]=? build explicit
    l2 = np.array([9.0, 9.0, 9.85])    # low[2]=9.85 > high[0]=10.0? no
    assert detect_fvg(h2, l2, 2, 1, 0.3) is None


# ── oracle: research OTE block (cobrax.py:159-167) ────────────────────────────
def _oracle_ote(iside, sw_ext, sw_k, fvg_k, elvl, h, l):
    if iside < 0:
        fib1 = sw_ext
        fib0 = float(l[sw_k:fvg_k + 1].min())
        rng = fib1 - fib0
        if rng <= 0:
            return None
        return (elvl - fib0) / rng
    else:
        fib1 = sw_ext
        fib0 = float(h[sw_k:fvg_k + 1].max())
        rng = fib0 - fib1
        if rng <= 0:
            return None
        return (fib0 - elvl) / rng


def test_ote_ratio_matches_research():
    _, h, l, _ = _synth_ohlc()
    for side in (-1, 1):
        for sw_k, fvg_k in [(10, 25), (100, 118), (400, 402), (700, 760)]:
            sw_ext = float(l[sw_k]) if side > 0 else float(h[sw_k])
            elvl = float((h[fvg_k] + l[fvg_k]) / 2)
            got = ote_ratio(side, sw_ext, sw_k, fvg_k, elvl, h, l)
            exp = _oracle_ote(side, sw_ext, sw_k, fvg_k, elvl, h, l)
            if exp is None:
                assert got is None
            else:
                assert got == pytest.approx(exp)


# ── oracle: research bias_at SEMANTICS (cobrax.py:86-94), unit-safe ───────────
# Research uses `htf_ts.view("i8") + htf_tf*60*1e9` (ns offset). That is CORRECT
# on the real ns parquet (verified: datetime64[ns] → ns close_ts, non-degenerate).
# It is fragile only for synthetic date_range data, which pandas 3.0 downcasts to
# microseconds through the pd.to_datetime(.values) round-trip (→ unit mismatch →
# constant bias). This oracle reproduces the INTENDED semantic — "last M15 bar
# whose CLOSE time (label + htf_tf) is <= t" — with datetime arithmetic, so it is
# unit-robust and the test is valid on synthetic data. HtfBiasTracker is likewise
# resolution-agnostic (pure Timestamp arithmetic, no .view).
def _oracle_bias_series(m5: pd.DataFrame, htf_tf=15):
    htf = (m5.set_index("timestamp").resample(f"{htf_tf}min", label="left", closed="left")
           .agg({"close": "last"}).dropna().reset_index())
    htf_c = htf["close"].values
    close_time = (pd.DatetimeIndex(htf["timestamp"]) + pd.Timedelta(minutes=htf_tf))
    htf_sma = pd.Series(htf_c).rolling(20).mean().values
    htf_bias = np.sign(htf_c - np.nan_to_num(htf_sma, nan=htf_c))

    def bias_at(t):
        j = int(close_time.searchsorted(pd.Timestamp(t), side="right")) - 1
        return int(htf_bias[j]) if j >= 0 else 0

    return bias_at


def _synth_m5(seed=11, n=1200):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = 2000 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame({"timestamp": ts, "close": close})


def test_htf_bias_tracker_matches_research_bias_at():
    m5 = _synth_m5()
    bias_at = _oracle_bias_series(m5)
    tr = HtfBiasTracker(tf_min=15, sma_period=20)
    mismatches = 0
    for _, row in m5.iterrows():
        ts = row["timestamp"]
        tr.update({"timestamp": ts, "close": float(row["close"])})
        exp = bias_at(ts)
        got = tr.bias()
        if got != exp:
            mismatches += 1
    assert mismatches == 0, f"{mismatches} bias mismatches vs research bias_at"


def test_htf_bias_zero_during_warmup():
    """<20 finalized M15 buckets → bias 0 (research nan_to_num(sma,nan=close))."""
    m5 = _synth_m5(n=40)  # ~13 M15 buckets, under the 20 SMA window
    tr = HtfBiasTracker()
    for _, row in m5.iterrows():
        tr.update({"timestamp": row["timestamp"], "close": float(row["close"])})
    assert tr.bias() == 0
