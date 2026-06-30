"""Quantitative Formalization XAUUSD (PDF1) — causal port.

Strategy A — XAU Confluence Long:
  1. Temporal: NY-London overlap UTC 13:00-17:00 (post-London open, pre-NY close
     stamp; range 13:00-17:00 UTC). Use 13:00 UTC NY open as the ORB anchor.
  2. ORB15: high/low over [13:00, 13:15) UTC. Only valid AFTER 13:15 UTC closes.
  3. Long trigger (M5):
       close_t > ORH
       AND close_t > VWAP_session (VWAP from 00:00 UTC up to PRIOR M5 close)
       AND close_t > VAH_prev_day (computed from prior CLOSED UTC day)
       AND close_t - open_t > 1/5 * sum(high_{t-i} - low_{t-i}, i=1..5)  (momentum)
       AND vol_t > 1/3 * sum(vol_{t-i}, i=1..3)
  4. Short = mirror (close < ORL & close < VWAP & close < VAL_prev_day & ...).
  5. SL = ORH - 0.5 * ORwidth (long) / ORL + 0.5 * ORwidth (short). 1R bracket.
  6. TP at 1.5R (per Phase plan partial 1R + final 1.5R; simplify to 1.5R single).
  7. Time horizon: until end of 17:00 UTC NY-London overlap (12 M5 bars = 60 min
     bar count by close at 17:00). Actually allow 24h horizon clamped to tp_mult.

Causality rules:
  - ORH/ORL fixed at 13:15 UTC; entries strictly after.
  - VWAP_session = cumsum(volume * typical) / cumsum(volume) over CLOSED M5
    bars only (prior, not current). At M5 bar k, use VWAP through bar k-1.
  - VAH/VAL = prior CLOSED UTC day's value-area-high/low (from M5 volume profile).
  - Momentum condition uses bars t-1..t-5 (already closed).
  - Volume condition uses bars t-1..t-3.

Output: trades parquet + headline JSON. Persists via shared harness.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import (  # noqa: E402
    load_data, simulate, headline, persist, print_headline, gate
)


def compute_session_vwap(m5: pd.DataFrame) -> pd.Series:
    """Session VWAP per UTC day, lagged by 1 bar so current bar can use it."""
    typ = (m5["high"] + m5["low"] + m5["close"]) / 3.0
    pv = typ * m5["volume"]
    utc_date = m5["timestamp"].dt.tz_convert("UTC").dt.date.astype(str)
    pv_cum = pv.groupby(utc_date).cumsum()
    v_cum = m5["volume"].groupby(utc_date).cumsum()
    vwap_now = pv_cum / v_cum.replace(0, np.nan)
    return vwap_now.groupby(utc_date).shift(1)


def compute_orb15(m5: pd.DataFrame) -> pd.DataFrame:
    """ORH/ORL per UTC day from 13:00-13:14 UTC inclusive (three M5 bars).
    Available from 13:15 UTC onward.
    """
    utc_date = m5["timestamp"].dt.tz_convert("UTC").dt.date.astype(str)
    utc_hr = m5["timestamp"].dt.tz_convert("UTC").dt.hour
    utc_min = m5["timestamp"].dt.tz_convert("UTC").dt.minute
    in_orb = (utc_hr == 13) & (utc_min < 15)
    orb = m5.loc[in_orb].groupby(utc_date).agg(
        ORH=("high", "max"), ORL=("low", "min")
    ).reset_index()
    orb.columns = ["utc_date", "ORH", "ORL"]
    return orb


def compute_value_area_per_day(m5: pd.DataFrame, tick: float = 0.1) -> pd.DataFrame:
    """Prior UTC day's Value Area High/Low using M5 volume profile, 70% area."""
    utc_date = m5["timestamp"].dt.tz_convert("UTC").dt.date.astype(str)
    out_rows = []
    for d, g in m5.groupby(utc_date):
        if len(g) < 5:
            out_rows.append({"utc_date": d, "VAH": np.nan, "VAL": np.nan, "POC": np.nan})
            continue
        lo = float(g["low"].min())
        hi = float(g["high"].max())
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            out_rows.append({"utc_date": d, "VAH": np.nan, "VAL": np.nan, "POC": np.nan})
            continue
        nbins = max(10, int(np.ceil((hi - lo) / tick)))
        edges = np.linspace(lo, hi, nbins + 1)
        centers = 0.5 * (edges[:-1] + edges[1:])
        typ = (g["high"] + g["low"] + g["close"]).values / 3.0
        vol = g["volume"].values
        hist, _ = np.histogram(typ, bins=edges, weights=vol)
        total = hist.sum()
        if total <= 0:
            out_rows.append({"utc_date": d, "VAH": np.nan, "VAL": np.nan, "POC": np.nan})
            continue
        poc_i = int(hist.argmax())
        poc = centers[poc_i]
        target = 0.70 * total
        included = hist[poc_i]
        lo_i, hi_i = poc_i, poc_i
        while included < target and (lo_i > 0 or hi_i < nbins - 1):
            up_sum = hist[hi_i + 1] + (hist[hi_i + 2] if hi_i + 2 < nbins else 0) if hi_i < nbins - 1 else 0
            dn_sum = hist[lo_i - 1] + (hist[lo_i - 2] if lo_i - 2 >= 0 else 0) if lo_i > 0 else 0
            if up_sum >= dn_sum and hi_i < nbins - 1:
                hi_i += 1
                included += hist[hi_i]
                if hi_i < nbins - 1 and included < target:
                    hi_i += 1
                    included += hist[hi_i]
            elif lo_i > 0:
                lo_i -= 1
                included += hist[lo_i]
                if lo_i > 0 and included < target:
                    lo_i -= 1
                    included += hist[lo_i]
            else:
                break
        vah = centers[hi_i]
        val = centers[lo_i]
        out_rows.append({"utc_date": d, "VAH": vah, "VAL": val, "POC": poc})
    out = pd.DataFrame(out_rows)
    out["utc_date"] = pd.to_datetime(out["utc_date"]).dt.date.astype(str)
    return out


def build_features(m5: pd.DataFrame) -> pd.DataFrame:
    """Add session VWAP_lag, ORH/ORL of the day, VAH/VAL of PRIOR day, momentum & vol filters."""
    df = m5.copy()
    df["utc_date"] = df["timestamp"].dt.tz_convert("UTC").dt.date.astype(str)
    df["utc_hr"] = df["timestamp"].dt.tz_convert("UTC").dt.hour
    df["utc_min"] = df["timestamp"].dt.tz_convert("UTC").dt.minute

    df["vwap_lag"] = compute_session_vwap(df)

    orb = compute_orb15(df)
    df = df.merge(orb, on="utc_date", how="left")

    va_per_day = compute_value_area_per_day(df)
    va_per_day["utc_date_dt"] = pd.to_datetime(va_per_day["utc_date"])
    va_per_day = va_per_day.sort_values("utc_date_dt").reset_index(drop=True)
    # prior_day map
    va_per_day["VAH_prev"] = va_per_day["VAH"].shift(1)
    va_per_day["VAL_prev"] = va_per_day["VAL"].shift(1)
    va_per_day["POC_prev"] = va_per_day["POC"].shift(1)
    df = df.merge(
        va_per_day[["utc_date", "VAH_prev", "VAL_prev", "POC_prev"]],
        on="utc_date", how="left",
    )

    # Momentum: close - open vs mean of last-5 H-L ranges (bars t-1..t-5)
    hl = (df["high"] - df["low"])
    df["mean_hl5_lag"] = hl.shift(1).rolling(5).mean()
    df["body_t"] = df["close"] - df["open"]

    # Volume surge: vol_t > mean(vol_{t-1..t-3})
    df["mean_vol3_lag"] = df["volume"].shift(1).rolling(3).mean()

    return df


def generate_signals(df: pd.DataFrame, *, direction: str) -> pd.DataFrame:
    """direction = 'long' or 'short'. Returns DataFrame ready for simulate()."""
    in_window = (df["utc_hr"] >= 13) & (df["utc_hr"] < 17)
    after_orb = ~((df["utc_hr"] == 13) & (df["utc_min"] < 15))
    has_orb = df["ORH"].notna() & df["ORL"].notna()
    has_vwap = df["vwap_lag"].notna()
    has_va = df["VAH_prev"].notna() & df["VAL_prev"].notna()
    has_momo = df["mean_hl5_lag"].notna()
    has_vol = df["mean_vol3_lag"].notna()

    base = in_window & after_orb & has_orb & has_vwap & has_va & has_momo & has_vol

    if direction == "long":
        breakout = df["close"] > df["ORH"]
        vwap_ok = df["close"] > df["vwap_lag"]
        va_ok = df["close"] > df["VAH_prev"]
        momo_ok = df["body_t"] > df["mean_hl5_lag"]
        vol_ok = df["volume"] > df["mean_vol3_lag"]
        sig_mask = base & breakout & vwap_ok & va_ok & momo_ok & vol_ok
        side = 1
    else:
        breakdown = df["close"] < df["ORL"]
        vwap_ok = df["close"] < df["vwap_lag"]
        va_ok = df["close"] < df["VAL_prev"]
        momo_ok = df["body_t"] < -df["mean_hl5_lag"]
        vol_ok = df["volume"] > df["mean_vol3_lag"]
        sig_mask = base & breakdown & vwap_ok & va_ok & momo_ok & vol_ok
        side = -1

    sig_idx = np.flatnonzero(sig_mask.values)
    # first signal per UTC day to avoid stacking
    if len(sig_idx) == 0:
        return pd.DataFrame(columns=["entry_index", "side", "risk_units"])
    rows = df.iloc[sig_idx].copy()
    rows["sig_idx"] = sig_idx
    rows = rows.groupby("utc_date").first().reset_index()
    # entry on NEXT M5 open (t+1)
    rows["entry_index"] = rows["sig_idx"] + 1
    # Risk: 0.5 * ORwidth from breakout level
    or_width = (rows["ORH"] - rows["ORL"]).abs()
    rows["risk_units"] = (0.5 * or_width).where(or_width > 0, np.nan)
    rows = rows.dropna(subset=["risk_units"])
    rows = rows[rows["risk_units"] > 0]
    rows["side"] = side
    return rows[["entry_index", "side", "risk_units"]].astype(
        {"entry_index": int, "side": int, "risk_units": float}
    )


def main():
    print("[load] Loading m5/m15 cached frames...")
    _, m5, _ = load_data()
    print(f"  m5 rows: {len(m5):,}")

    print("[features] Building VWAP + ORB15 + ValueArea per UTC day...")
    df = build_features(m5)
    print(f"  feature rows: {len(df):,}")

    print("\n=== STRATEGY A — Confluence (PDF1) ===\n")
    for direction in ["long", "short"]:
        print(f"\n[{direction}] generating signals...")
        sigs = generate_signals(df, direction=direction)
        print(f"  signals: {len(sigs):,}")
        for tp in [1.5, 2.0, 3.0]:
            trades = simulate(sigs, df, tp_mult=tp)
            h = headline(trades)
            label = f"confluence_{direction}_TP={tp}R"
            print_headline(label, h)
            persist("confluence_xau", label, trades, notes=f"PDF1 {direction} VWAP+VAH+ORB+momo TP={tp}R")


if __name__ == "__main__":
    main()
