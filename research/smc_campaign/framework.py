"""Shared framework for the SMC/ICT 12-strategy mega-campaign.

Provides:
  - multi-timeframe XAU loader (M1/M5/M15/H1/H4/D1), cached, tz-aware UTC
  - heavy logger (_log with timestamps, flush)
  - close-based price bracket sim (fixed TP/SL prices OR R-multiple)
  - headline + gate + adversarial helpers (re-exported from causal_sim where possible)
  - sweep runner scaffold with live progress + running-best + leaderboard persist

CAUSALITY CONTRACT (enforced everywhere downstream):
  - Every feature/zone derives from bars whose CLOSE ts is STRICTLY before entry ts.
  - HTF bars resampled label='left', closed='left'; a bar's data is "known" only at
    its close = timestamp + tf_minutes.
  - Entries on M5 grid (or the strategy's stated TF), armed at a confirmation-close ts.
  - Cost $0.30/risk_units (XAU), matches all prior work.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import (  # noqa: E402
    load_data as _load_m5m15, _load_raw_m1, headline, gate, print_headline, COST_USD,
)

TF_MIN = {"5min": 5, "15min": 15, "30min": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}
CACHE = Path("/tmp")


def _log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    """OHLCV resample with EMA/ATR + shift(1)-lagged copies. label/closed left.
    A row's *_lag columns are the values known at that bar's OPEN (prior bar closed).
    """
    df = m1.set_index("timestamp").resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema100"] = df["close"].ewm(span=100, adjust=False).mean()
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14).mean()
    # RSI(14) Wilder
    delta = df["close"].diff()
    up = delta.clip(lower=0.0)
    dn = (-delta).clip(lower=0.0)
    roll_up = up.ewm(alpha=1/14, adjust=False).mean()
    roll_dn = dn.ewm(alpha=1/14, adjust=False).mean()
    rs = roll_up / roll_dn.replace(0, np.nan)
    df["rsi14"] = 100 - 100 / (1 + rs)
    return df


class MTF:
    """Multi-timeframe bundle. m5 is the execution frame (has atr14_lag + year etc
    from causal_sim). Higher TFs carry EMA/ATR/RSI. All tz-aware UTC."""

    def __init__(self):
        _log("Loading base M1/M5/M15 (causal_sim) …")
        self.m1, self.m5, self.m15 = _load_m5m15()
        _log(f"  m1={len(self.m1):,} m5={len(self.m5):,} m15={len(self.m15):,}")
        self._cache: dict[str, pd.DataFrame] = {"15min": None}

    def tf(self, rule: str) -> pd.DataFrame:
        if rule not in self._cache or self._cache.get(rule) is None:
            _log(f"  resampling {rule} …")
            self._cache[rule] = resample(self.m1, rule)
            _log(f"    {rule}: {len(self._cache[rule]):,} bars")
        return self._cache[rule]


def sim_price_bracket(signals: pd.DataFrame, m5: pd.DataFrame, *, horizon: int = 288,
                      cost_usd: float = COST_USD) -> pd.DataFrame:
    """Vectorised close-based bracket. signals need fill_index/side/entry_price/
    tp_price/sl_price/risk_units. First TP-or-SL close touch within horizon wins
    (tie: SL first, conservative); else time-exit at horizon close. R vs risk_units."""
    if len(signals) == 0:
        return pd.DataFrame(columns=["entry_ts", "side", "net_r", "bracket_r", "rr", "year"])
    cl = m5["close"].values
    ts = m5["timestamp"].values
    yr = m5["year"].values
    n = len(m5)

    fi = signals["fill_index"].to_numpy(dtype=np.int64)
    side = signals["side"].to_numpy(dtype=np.float64)
    entry = signals["entry_price"].to_numpy(dtype=np.float64)
    tp = signals["tp_price"].to_numpy(dtype=np.float64)
    sl = signals["sl_price"].to_numpy(dtype=np.float64)
    risk = signals["risk_units"].to_numpy(dtype=np.float64)

    valid = (risk > 0) & (fi < n - 2) & (fi >= 0)
    fi, side, entry, tp, sl, risk = fi[valid], side[valid], entry[valid], tp[valid], sl[valid], risk[valid]
    m = len(fi)
    if m == 0:
        return pd.DataFrame(columns=["entry_ts", "side", "net_r", "bracket_r", "rr", "year"])

    # Build a [m, horizon+1] window of closes (clipped at n-1). Row k = closes fi[k]..fi[k]+H
    H = horizon
    offs = np.arange(H + 1)
    idx = np.minimum(fi[:, None] + offs[None, :], n - 1)   # [m, H+1]
    win = cl[idx]                                           # [m, H+1] closes

    long = side > 0
    # touch masks
    tp_hit = np.where(long[:, None], win >= tp[:, None], win <= tp[:, None])
    sl_hit = np.where(long[:, None], win <= sl[:, None], win >= sl[:, None])

    def first_true(mask):
        any_ = mask.any(axis=1)
        first = np.where(any_, mask.argmax(axis=1), H + 1)  # H+1 = "never"
        return first, any_

    tp_i, _ = first_true(tp_hit)
    sl_i, _ = first_true(sl_hit)

    bracket = np.empty(m, dtype=np.float64)
    exit_i = np.empty(m, dtype=np.int64)
    # SL strictly-before-or-equal TP => SL (conservative on ties)
    sl_wins = sl_i <= tp_i
    both_never = (sl_i > H) & (tp_i > H)
    # SL outcome
    r_sl = np.where(long, (sl - entry) / risk, (entry - sl) / risk)
    r_tp = np.where(long, (tp - entry) / risk, (entry - tp) / risk)
    bracket = np.where(sl_wins, r_sl, r_tp)
    exit_off = np.where(sl_wins, sl_i, tp_i)
    # time-exit for those that never touched
    time_close = win[np.arange(m), np.minimum(H, np.full(m, H))]  # close at horizon end
    r_time = side * (time_close - entry) / risk
    bracket = np.where(both_never, r_time, bracket)
    exit_off = np.where(both_never, H, exit_off)
    exit_i = np.minimum(fi + exit_off, n - 1)

    out = pd.DataFrame({
        "entry_ts": ts[fi], "side": side, "entry_price": entry,
        "tp_price": tp, "sl_price": sl, "risk_units": risk,
        "exit_index": exit_i, "bracket_r": bracket,
        "cost_r": cost_usd / risk, "net_r": bracket - cost_usd / risk,
        "rr": np.abs(tp - entry) / risk, "year": yr[fi],
    })
    return out


def assert_causal(signals: pd.DataFrame, m5: pd.DataFrame, arm_col: str = "arm_ts"):
    """Hard self-test: every fill sits at/after its arm_ts (fully-confirmed setup time)."""
    if arm_col not in signals.columns or len(signals) == 0:
        return
    arm = pd.to_datetime(signals[arm_col]).values
    fill_ts = m5["timestamp"].values[signals["fill_index"].astype(int).values]
    bad = (fill_ts < arm).sum()
    assert bad == 0, f"LEAK: {bad} fills precede their arm_ts"


def full_audit(sig_builder, m5, *, label: str, delay_reprice=True):
    """Run base + delay + cost-stress + bootstrap + IS/OOS + year table. sig_builder()
    returns a signals df (with fill_index/entry_price/side/tp/sl/risk_units)."""
    sig = sig_builder()
    _log(f"AUDIT [{label}]: {len(sig)} signals")
    if len(sig) < 30:
        _log("  too few signals — skip audit")
        return None
    base = sim_price_bracket(sig, m5)
    print_headline(f"{label} base", headline(base))

    if delay_reprice:
        op = m5["open"].values
        n = len(m5)
        for d in (1, 2, 3):
            s = sig.copy()
            s["fill_index"] = s["fill_index"].astype(int) + d
            s = s[s["fill_index"] < n - 2].reset_index(drop=True)
            s["entry_price"] = op[s["fill_index"].values]
            s["risk_units"] = (s["entry_price"] - s["sl_price"]).abs()
            s = s[s["risk_units"] > 0]
            print_headline(f"{label} delay+{d}", headline(sim_price_bracket(s, m5)))

    for c in (0.30, 0.50, 0.80):
        print_headline(f"{label} cost${c}", headline(sim_price_bracket(sig, m5, cost_usd=c)))

    r = base["net_r"].values
    rng = np.random.default_rng(13)
    boots = np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(1500)])
    _log(f"  bootstrap net={r.sum():+.1f}R P(net<=0)={(boots <= 0).mean():.4f}")
    print_headline(f"{label} IS19-23", headline(base[base.year <= 2023]))
    print_headline(f"{label} OOS24-26", headline(base[base.year >= 2024]))
    yt = base.groupby("year")["net_r"].agg(["sum", "count"]).round(1)
    _log("  year-by-year:\n" + yt.to_string())
    return base
