"""Shared CAUSAL feature library for overnight research.

BIBLE RULES (non-negotiable, enforced here so every harness inherits them):
  1. NO LOOK-AHEAD. Every feature for a trade with entry_ts T must be derivable
     ONLY from bars whose CLOSE timestamp is <= T. A bar labeled at open-time O
     with timeframe TF closes at O+TF; it's usable only if O+TF <= T.
  2. TIME-AWARE CANDLE CLOSE. HTF features (H1/H4/D1) use the LAST bar whose
     close (bar_open + tf_delta) <= entry_ts. Never the bar still forming.
  3. NO CAUSALITY BUG. Rolling windows are backward-looking. Session/ORB features
     only valid AFTER the window has fully closed.

All post-hoc: reads existing bt_trades + raw M5 parquet. Zero strategy/BT/live
code touched. This module is IMPORT-ONLY — it defines builders, runs nothing.

Usage:
    from _causal_lib import (
        load_trades, load_m5, resample_causal, attach_htf_feature_causal,
        session_levels_causal, prior_day_levels_causal, rolling_feature_causal,
        bootstrap_p_neg, permutation_p, quintile_table, headline,
    )
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


DB_URL = os.environ.get("BT_ENGINE_DB_URL",
                        "postgresql+psycopg2://subash@localhost:5432/golddigger_bt")
BASELINE_RUN = "b6604240-14f4-464f-86b4-0d0e32755838"
M5_PATH = Path("/tmp/oanda_xau_m5.parquet")


# ─────────────────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────────────────

def load_trades(run_id: str = BASELINE_RUN) -> pd.DataFrame:
    """Load closed trades with fib geometry from a BT run."""
    eng = create_engine(DB_URL)
    q = text("""
        SELECT trade_id::text, entry_timestamp, exit_timestamp, side, leg,
               direction, entry_price, stop_price, take_profit_price,
               risk_units, net_r, gross_r, bars_held, exit_reason,
               partial_taken,
               (raw_features->>'fib_L')::numeric  AS fib_l,
               (raw_features->>'fib_H')::numeric  AS fib_h,
               (raw_features->>'fib_diff')::numeric AS fib_diff,
               (raw_features->>'setup_confirm_ts') AS setup_confirm_ts,
               (raw_features->>'ny_hr')::int AS ny_hr,
               (raw_features->>'pnl_usd')::numeric AS pnl_usd
        FROM bt_trades
        WHERE run_id = :rid AND net_r IS NOT NULL AND raw_features ? 'fib_L'
        ORDER BY entry_timestamp
    """)
    with eng.connect() as c:
        df = pd.read_sql(q, c, params={"rid": run_id})
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], utc=True)
    df["exit_timestamp"] = pd.to_datetime(df["exit_timestamp"], utc=True)
    df["setup_confirm_ts"] = pd.to_datetime(df["setup_confirm_ts"], utc=True)
    df["year"] = df["entry_timestamp"].dt.year
    for c in ["entry_price", "stop_price", "take_profit_price", "risk_units",
              "net_r", "gross_r", "fib_l", "fib_h", "fib_diff", "pnl_usd"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["win"] = (df["net_r"] > 0).astype(int)
    # overnight = crosses UTC calendar day
    df["overnight"] = (df["entry_timestamp"].dt.date != df["exit_timestamp"].dt.date).astype(int)
    return df


def load_m5() -> pd.DataFrame:
    m5 = pd.read_parquet(M5_PATH)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    return m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────
# Causal resampling + HTF feature attach
# ─────────────────────────────────────────────────────────────────────────

_TF_DELTA = {
    "5min": pd.Timedelta("5min"), "15min": pd.Timedelta("15min"),
    "30min": pd.Timedelta("30min"), "1h": pd.Timedelta("1h"),
    "4h": pd.Timedelta("4h"), "1D": pd.Timedelta("1D"),
}


def resample_causal(m5: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample M5 to tf. Returns frame with bar_open_ts + close_ts (= open+tf).

    A bar is only USABLE for a trade whose entry_ts >= close_ts. We attach both
    so downstream masks compare against close_ts, NEVER open_ts (the look-ahead trap).
    """
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    r = (m5.set_index("timestamp").resample(tf, label="left", closed="left")
         .agg(agg).dropna().reset_index())
    r = r.rename(columns={"timestamp": "bar_open_ts"})
    if r["bar_open_ts"].dt.tz is None:
        r["bar_open_ts"] = r["bar_open_ts"].dt.tz_localize("UTC")
    r["close_ts"] = r["bar_open_ts"] + _TF_DELTA[tf]
    return r


def attach_htf_feature_causal(trades: pd.DataFrame, htf: pd.DataFrame,
                              feature_col: str, out_col: str) -> pd.DataFrame:
    """For each trade, pick htf[feature_col] from the LAST htf bar whose
    close_ts <= entry_ts. Provably causal — uses close_ts, not open.
    """
    ct = htf["close_ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    vals = htf[feature_col].to_numpy()
    ent = trades["entry_timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    out = np.full(len(trades), np.nan)
    idx = np.searchsorted(ct, ent, side="right") - 1  # last bar with close <= entry
    valid = idx >= 0
    out[valid] = vals[idx[valid]]
    trades = trades.copy()
    trades[out_col] = out
    return trades


def rolling_feature_causal(htf: pd.DataFrame, col: str, window: int, fn: str = "mean",
                           out_col: str | None = None) -> pd.DataFrame:
    """Backward-looking rolling feature on an HTF frame. min_periods=window so no
    partial-window leakage. Result at bar i uses bars [i-window+1 .. i], all closed.
    """
    out_col = out_col or f"{col}_{fn}{window}"
    htf = htf.copy()
    roll = htf[col].rolling(window, min_periods=window)
    htf[out_col] = getattr(roll, fn)()
    return htf


def prior_day_levels_causal(m5: pd.DataFrame) -> pd.DataFrame:
    """PDH/PDL/PDC per D1 bar — usable only AFTER that day closes.
    Returns D1 frame w/ pdh/pdl/pdc columns representing the PRIOR completed day,
    and close_ts = day_open + 1D (when the level becomes known).
    """
    d1 = resample_causal(m5, "1D")
    d1["pdh"] = d1["high"].shift(1)   # prior day high — known at THIS day's open
    d1["pdl"] = d1["low"].shift(1)
    d1["pdc"] = d1["close"].shift(1)
    # These prior-day levels are known at d1 bar_open (start of current day), so
    # they're usable for any entry_ts >= bar_open_ts. Set close_ts = bar_open_ts.
    d1 = d1.copy()
    d1["close_ts"] = d1["bar_open_ts"]  # available from day start
    return d1.dropna(subset=["pdh"]).reset_index(drop=True)


def session_levels_causal(m5: pd.DataFrame, start_hr: int, end_hr: int,
                          label: str) -> pd.DataFrame:
    """Session high/low (e.g. Asia 0-7 UTC, London 7-13 UTC), usable only AFTER
    the session window closes each day. Returns per-day frame with
    {label}_high/{label}_low and close_ts = that day's session end.
    Causal: the level is only known once end_hr passes.
    """
    m = m5.copy()
    m["date"] = m["timestamp"].dt.date
    m["hr"] = m["timestamp"].dt.hour
    win = m[(m["hr"] >= start_hr) & (m["hr"] < end_hr)]
    grp = win.groupby("date").agg(hi=("high", "max"), lo=("low", "min")).reset_index()
    # close_ts = date at end_hr:00 UTC (session window fully closed)
    grp["close_ts"] = pd.to_datetime(grp["date"].astype(str)).dt.tz_localize("UTC") + pd.Timedelta(hours=end_hr)
    grp = grp.rename(columns={"hi": f"{label}_high", "lo": f"{label}_low"})
    return grp[["close_ts", f"{label}_high", f"{label}_low"]].reset_index(drop=True)


def vwap_causal(m5: pd.DataFrame, anchor: str = "1D") -> pd.DataFrame:
    """Session-anchored VWAP per M5 bar (resets each anchor period). Causal by
    construction — cumulative within the period up to and including each bar.
    Returns M5 frame with 'vwap' col (value AT each bar's close).
    """
    m = m5.copy()
    m["tp"] = (m["high"] + m["low"] + m["close"]) / 3.0
    m["pv"] = m["tp"] * m["volume"].clip(lower=1)
    m["grp"] = m["timestamp"].dt.floor(anchor)
    m["cum_pv"] = m.groupby("grp")["pv"].cumsum()
    m["cum_v"] = m.groupby("grp")["volume"].clip(lower=1).cumsum()
    m["vwap"] = m["cum_pv"] / m["cum_v"]
    return m[["timestamp", "vwap"]]


def attach_m5_value_at_or_before(trades: pd.DataFrame, m5v: pd.DataFrame,
                                 col: str, out_col: str,
                                 ts_col: str = "timestamp") -> pd.DataFrame:
    """Attach an M5-level value (e.g. vwap) as of the last M5 bar whose close
    <= entry_ts. M5 bar labeled at open O closes at O+5min. Usable if O+5min<=entry.
    """
    tcl = (m5v[ts_col].dt.tz_convert("UTC").dt.tz_localize(None) + pd.Timedelta("5min")).to_numpy()
    vals = m5v[col].to_numpy()
    ent = trades["entry_timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    out = np.full(len(trades), np.nan)
    idx = np.searchsorted(tcl, ent, side="right") - 1
    valid = idx >= 0
    out[valid] = vals[idx[valid]]
    trades = trades.copy()
    trades[out_col] = out
    return trades


# ─────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────

def headline(df: pd.DataFrame, label: str = "") -> dict:
    n = len(df)
    if n == 0:
        return {"label": label, "n": 0}
    wr = 100.0 * (df["net_r"] > 0).mean()
    prof = df.loc[df.net_r > 0, "net_r"].sum()
    loss = -df.loc[df.net_r <= 0, "net_r"].sum()
    pf = prof / loss if loss > 0 else float("inf")
    return {"label": label, "n": n, "wr": round(wr, 2),
            "sum_r": round(float(df.net_r.sum()), 1), "pf": round(float(pf), 3)}


def quintile_table(df: pd.DataFrame, feat: str) -> list[dict]:
    d = df.dropna(subset=[feat]).copy()
    if len(d) < 100:
        return []
    try:
        d["q"] = pd.qcut(d[feat], 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
    except Exception:
        return []
    rows = []
    for q in sorted(d["q"].dropna().unique()):
        s = d[d["q"] == q]
        rows.append({**headline(s, f"Q{q}"),
                     "range": [round(float(s[feat].min()), 4), round(float(s[feat].max()), 4)]})
    return rows


def bootstrap_p_neg(net_r: np.ndarray, n_iter: int = 5000, seed: int = 42) -> float:
    rng = np.random.default_rng(seed)
    n = len(net_r)
    if n == 0:
        return 1.0
    neg = 0
    for _ in range(n_iter):
        if net_r[rng.integers(0, n, n)].sum() < 0:
            neg += 1
    return neg / n_iter


def permutation_p(net_r: np.ndarray, n_iter: int = 1000, seed: int = 42) -> float:
    rng = np.random.default_rng(seed)
    absr = np.abs(net_r)
    obs = net_r.sum()
    ge = 0
    for _ in range(n_iter):
        if (rng.choice([-1, 1], len(absr)) * absr).sum() >= obs:
            ge += 1
    return ge / n_iter


def yearly_positive(df: pd.DataFrame) -> tuple[int, int]:
    """Return (positive_years, total_years) by net_r sum."""
    g = df.groupby("year")["net_r"].sum()
    return int((g > 0).sum()), int(len(g))
