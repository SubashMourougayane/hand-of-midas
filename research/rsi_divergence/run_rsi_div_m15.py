"""RSI Divergence on M15 + H1 zone filter (literal PDF: 1H/4H zones).

Higher-TF div + H1 S/R zone + M5 confirm + 4R target.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import (
    load_data, simulate, headline, persist, print_headline, COST_USD
)
from research.rsi_divergence.run_rsi_div import rsi, find_pivots


def build_m15_features(m1: pd.DataFrame) -> pd.DataFrame:
    m15 = m1.set_index("timestamp").resample("15min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    m15["rsi14"] = rsi(m15["close"], 14)
    m15["rsi14_lag"] = m15["rsi14"].shift(1)
    tr = pd.concat([
        (m15["high"] - m15["low"]),
        (m15["high"] - m15["close"].shift(1)).abs(),
        (m15["low"] - m15["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    m15["atr14"] = tr.rolling(14).mean()
    m15["atr14_lag"] = m15["atr14"].shift(1)
    ph, pl = find_pivots(m15["high"].values, m15["low"].values, right=2, left=2)
    m15["piv_high"] = ph
    m15["piv_low"] = pl
    m15["year"] = m15["timestamp"].dt.year
    return m15


def build_h1_zones(m1: pd.DataFrame) -> pd.DataFrame:
    h1 = m1.set_index("timestamp").resample("1h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    ph, pl = find_pivots(h1["high"].values, h1["low"].values, right=2, left=2)
    h1["piv_high"] = ph
    h1["piv_low"] = pl
    # zone = confirmed pivot, available at confirmation bar = i+2
    return h1


def get_support_levels(h1_piv_low: pd.DataFrame, h1_confirm_ts: np.ndarray,
                       before_ts: np.datetime64) -> np.ndarray:
    """h1_piv_low: DataFrame pre-filtered to piv_low==True with 'low' column.
    h1_confirm_ts: matching confirm_ts array (datetime64[ns]).
    """
    mask = h1_confirm_ts <= before_ts
    avail = h1_piv_low.loc[mask, "low"].values
    return avail[-20:] if len(avail) else np.array([])


def get_resistance_levels(h1_piv_high: pd.DataFrame, h1_confirm_ts: np.ndarray,
                          before_ts: np.datetime64) -> np.ndarray:
    mask = h1_confirm_ts <= before_ts
    avail = h1_piv_high.loc[mask, "high"].values
    return avail[-20:] if len(avail) else np.array([])


def generate_long_m15_h1(m15: pd.DataFrame, h1: pd.DataFrame) -> pd.DataFrame:
    n = len(m15)
    lows = m15["low"].values
    closes = m15["close"].values
    opens = m15["open"].values
    rsi_lag = m15["rsi14_lag"].values
    atr_lag = m15["atr14_lag"].values
    pl = m15["piv_low"].values
    ts = m15["timestamp"].values

    h1_pl = h1[h1["piv_low"]].copy().reset_index(drop=True)
    h1_pl_confirm = (h1_pl["timestamp"] + pd.Timedelta(hours=2)).values

    rows = []
    last_idx = -1
    last_price = np.nan
    last_rsi = np.nan

    for i in range(5, n - 4):
        j = i + 2  # confirmation bar
        if j >= n - 1:
            break
        if not pl[i]:
            continue
        new_price = lows[i]
        new_rsi = rsi_lag[i + 1] if not np.isnan(rsi_lag[i + 1]) else rsi_lag[i]
        if last_idx < 0 or np.isnan(last_rsi):
            last_idx, last_price, last_rsi = i, new_price, new_rsi
            continue
        if not (new_price < last_price and new_rsi > last_rsi):
            last_idx, last_price, last_rsi = i, new_price, new_rsi
            continue

        # H1 zone check
        atr_now = atr_lag[j]
        if not np.isfinite(atr_now) or atr_now <= 0:
            last_idx, last_price, last_rsi = i, new_price, new_rsi
            continue
        tol = 0.5 * atr_now
        sup = get_support_levels(h1_pl, h1_pl_confirm, ts[j])
        if len(sup) == 0:
            zone_hit = False
        else:
            zone_hit = bool((np.abs(new_price - sup) <= tol).any())
        if not zone_hit:
            last_idx, last_price, last_rsi = i, new_price, new_rsi
            continue

        # Confirm candle = first bullish M15 close > prior close after j
        confirm = -1
        for k in range(j, min(j + 5, n - 1)):
            if closes[k] > opens[k] and closes[k] > closes[k - 1]:
                confirm = k
                break
        if confirm < 0:
            last_idx, last_price, last_rsi = i, new_price, new_rsi
            continue
        entry_idx = confirm + 1
        entry_price = opens[entry_idx]
        stop = new_price - 0.01
        risk = entry_price - stop
        if risk <= 0:
            last_idx, last_price, last_rsi = i, new_price, new_rsi
            continue
        rows.append({"entry_index": int(entry_idx), "side": 1, "risk_units": float(risk)})
        last_idx, last_price, last_rsi = i, new_price, new_rsi
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["entry_index", "side", "risk_units"])


def main():
    print("[load] m1 cache...")
    m1, _, _ = load_data()
    print(f"  m1 rows: {len(m1):,}")
    print("[features] M15 RSI + pivots, H1 pivots...")
    m15 = build_m15_features(m1)
    h1 = build_h1_zones(m1)
    print(f"  m15 rows: {len(m15):,}, h1 rows: {len(h1):,}")

    print("\n=== RSI DIV M15 + H1 zones ===\n")
    sigs = generate_long_m15_h1(m15, h1)
    print(f"  long signals: {len(sigs):,}")
    for tp in [1.0, 2.0, 3.0, 4.0]:
        trades = simulate(sigs, m15, tp_mult=tp)
        h = headline(trades)
        print_headline(f"rsidiv_m15_h1zone_long_TP={tp}R", h)
        persist("rsi_divergence", f"rsidiv_m15_h1zone_long_TP={tp}R", trades,
                notes=f"PDF2 long M15+H1zone TP={tp}R")


if __name__ == "__main__":
    main()
