"""RSI Divergence (PDF2) — causal quantisation on XAUUSD.

Strategy B rules (literal port of PDF):
  - Indicator: RSI(14) on M5 closes (cached, lagged by 1).
  - Pivot detection: right=2 lookback. A swing high at bar i is confirmed
    at bar i+2 when high[i] > high[i-1..i-2] and high[i] > high[i+1..i+2].
    Use right=2 so confirmation lands at bar i+2; we will then only act
    from bar i+3 (next M5 OPEN after the confirmation bar closes).
  - Support/Resistance zones: PRIOR confirmed pivots. A pivot is a "zone"
    if it lies in the lowest/highest 30% of last-60-pivot range AND no closer
    pivot exists within 50 bars (~4h) of price - tunable.
  - Bullish setup (LONG):
      price makes new LL vs previous confirmed pivot low
      AND RSI at that pivot > RSI at prior pivot (Higher Low)
      AND that pivot low is within +0.5*ATR14 of nearest support zone
      AND wait for confirm candle: bullish close > confirm-bar high?
        Simpler causal trigger: first M5 bar AFTER confirmed pivot whose
        close > prior_M5_close AND close > prior_M5_open (bullish body).
  - Entry: NEXT M5 OPEN after confirmation candle closes.
  - SL: pivot low - 1 tick (long); pivot high + 1 tick (short).
  - TP: 4R.
  - Bearish mirror.

Causality:
  - RSI lagged 1 (use prior closed M5).
  - Pivots only acted upon after right-bars complete (lag = right+1 = 3).
  - Zones from PRIOR pivots only (chronologically earlier than current).
  - No future bars touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import (  # noqa: E402
    load_data, simulate, headline, persist, print_headline, gate, COST_USD
)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    dn = (-delta).clip(lower=0.0)
    roll_up = up.ewm(alpha=1.0 / period, adjust=False).mean()
    roll_dn = dn.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = roll_up / roll_dn.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def find_pivots(highs: np.ndarray, lows: np.ndarray, right: int = 2, left: int = 2):
    """Return (pivot_high_idx_arr, pivot_low_idx_arr) where each idx is the
    BAR of the pivot itself; CONFIRMATION lands at idx + right.
    """
    n = len(highs)
    ph = np.zeros(n, dtype=bool)
    pl = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        if highs[i] == highs[i - left:i + right + 1].max() and highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            ph[i] = True
        if lows[i] == lows[i - left:i + right + 1].min() and lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            pl[i] = True
    return ph, pl


def build_features(m5: pd.DataFrame) -> pd.DataFrame:
    df = m5.copy()
    df["rsi14"] = rsi(df["close"], 14)
    df["rsi14_lag"] = df["rsi14"].shift(1)
    # ATR M5 14
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14_m5"] = tr.rolling(14).mean()
    df["atr14_m5_lag"] = df["atr14_m5"].shift(1)
    # pivots right=2, left=2
    ph, pl = find_pivots(df["high"].values, df["low"].values, right=2, left=2)
    df["piv_high"] = ph
    df["piv_low"] = pl
    return df


def generate_signals_long(df: pd.DataFrame, *, require_zone: bool = True) -> pd.DataFrame:
    """Long: confirmed price LL + RSI HL at confirmed low pivot, then bullish confirm candle."""
    n = len(df)
    lows = df["low"].values
    highs = df["high"].values
    closes = df["close"].values
    opens = df["open"].values
    rsi_lag = df["rsi14_lag"].values
    atr_lag = df["atr14_m5_lag"].values
    pl = df["piv_low"].values
    years = df["year"].values

    rows = []
    last_piv_low_idx = -1
    last_piv_low_price = np.nan
    last_piv_low_rsi = np.nan
    prior_pivot_lows = []  # for zone definition

    for i in range(5, n - 3):
        # pivot confirmed when bar i has piv_low True and we've passed i+2
        # We process pivot at confirmation time = i+2; i.e. at bar j=i+2 we know
        # bar i was a pivot low.
        j = i + 2  # confirmation bar index
        if j >= n - 1:
            break
        if not pl[i]:
            continue

        new_pivot_price = lows[i]
        new_pivot_rsi = rsi_lag[i + 1] if not np.isnan(rsi_lag[i + 1]) else rsi_lag[i]
        # divergence requires PRIOR pivot low to compare
        if last_piv_low_idx < 0 or np.isnan(last_piv_low_rsi):
            last_piv_low_idx = i
            last_piv_low_price = new_pivot_price
            last_piv_low_rsi = new_pivot_rsi
            prior_pivot_lows.append((i, new_pivot_price))
            continue

        price_ll = new_pivot_price < last_piv_low_price
        rsi_hl = new_pivot_rsi > last_piv_low_rsi
        if not (price_ll and rsi_hl):
            # update tracker but do not signal
            last_piv_low_idx = i
            last_piv_low_price = new_pivot_price
            last_piv_low_rsi = new_pivot_rsi
            prior_pivot_lows.append((i, new_pivot_price))
            continue

        # Zone filter: this pivot must be within +0.5*atr_lag of an OLDER pivot
        # low (a support zone). prior_pivot_lows excludes current.
        if require_zone:
            atr_now = atr_lag[j]
            if not np.isfinite(atr_now) or atr_now <= 0:
                last_piv_low_idx = i
                last_piv_low_price = new_pivot_price
                last_piv_low_rsi = new_pivot_rsi
                prior_pivot_lows.append((i, new_pivot_price))
                continue
            tol = 0.5 * atr_now
            zone_hit = any(
                abs(new_pivot_price - p) <= tol
                for (idx, p) in prior_pivot_lows[-30:-1]  # window
            )
            if not zone_hit:
                last_piv_low_idx = i
                last_piv_low_price = new_pivot_price
                last_piv_low_rsi = new_pivot_rsi
                prior_pivot_lows.append((i, new_pivot_price))
                continue

        # Look for bullish CONFIRMATION candle: first bar k >= j where close > open
        # AND close > prior close. Entry at k+1 open.
        confirmation_idx = -1
        for k in range(j, min(j + 10, n - 1)):
            if closes[k] > opens[k] and closes[k] > closes[k - 1]:
                confirmation_idx = k
                break
        if confirmation_idx < 0:
            last_piv_low_idx = i
            last_piv_low_price = new_pivot_price
            last_piv_low_rsi = new_pivot_rsi
            prior_pivot_lows.append((i, new_pivot_price))
            continue
        entry_idx = confirmation_idx + 1
        if entry_idx >= n - 2:
            continue
        entry_price = df["open"].values[entry_idx]
        # SL = pivot low - 1 tick
        stop_price = new_pivot_price - 0.01
        risk = entry_price - stop_price
        if risk <= 0:
            last_piv_low_idx = i
            last_piv_low_price = new_pivot_price
            last_piv_low_rsi = new_pivot_rsi
            prior_pivot_lows.append((i, new_pivot_price))
            continue
        rows.append({"entry_index": int(entry_idx), "side": 1, "risk_units": float(risk),
                     "pivot_idx": int(i), "confirm_idx": int(confirmation_idx)})

        last_piv_low_idx = i
        last_piv_low_price = new_pivot_price
        last_piv_low_rsi = new_pivot_rsi
        prior_pivot_lows.append((i, new_pivot_price))

    if not rows:
        return pd.DataFrame(columns=["entry_index", "side", "risk_units"])
    return pd.DataFrame(rows)


def generate_signals_short(df: pd.DataFrame, *, require_zone: bool = True) -> pd.DataFrame:
    n = len(df)
    highs = df["high"].values
    closes = df["close"].values
    opens = df["open"].values
    rsi_lag = df["rsi14_lag"].values
    atr_lag = df["atr14_m5_lag"].values
    ph = df["piv_high"].values

    rows = []
    last_idx = -1
    last_price = np.nan
    last_rsi = np.nan
    prior_highs = []

    for i in range(5, n - 3):
        j = i + 2
        if j >= n - 1:
            break
        if not ph[i]:
            continue
        new_price = highs[i]
        new_rsi = rsi_lag[i + 1] if not np.isnan(rsi_lag[i + 1]) else rsi_lag[i]
        if last_idx < 0 or np.isnan(last_rsi):
            last_idx = i; last_price = new_price; last_rsi = new_rsi
            prior_highs.append((i, new_price)); continue
        price_hh = new_price > last_price
        rsi_lh = new_rsi < last_rsi
        if not (price_hh and rsi_lh):
            last_idx = i; last_price = new_price; last_rsi = new_rsi
            prior_highs.append((i, new_price)); continue
        if require_zone:
            atr_now = atr_lag[j]
            if not np.isfinite(atr_now) or atr_now <= 0:
                last_idx = i; last_price = new_price; last_rsi = new_rsi
                prior_highs.append((i, new_price)); continue
            tol = 0.5 * atr_now
            zone_hit = any(
                abs(new_price - p) <= tol for (idx, p) in prior_highs[-30:-1]
            )
            if not zone_hit:
                last_idx = i; last_price = new_price; last_rsi = new_rsi
                prior_highs.append((i, new_price)); continue
        confirmation_idx = -1
        for k in range(j, min(j + 10, n - 1)):
            if closes[k] < opens[k] and closes[k] < closes[k - 1]:
                confirmation_idx = k
                break
        if confirmation_idx < 0:
            last_idx = i; last_price = new_price; last_rsi = new_rsi
            prior_highs.append((i, new_price)); continue
        entry_idx = confirmation_idx + 1
        if entry_idx >= n - 2:
            continue
        entry_price = df["open"].values[entry_idx]
        stop_price = new_price + 0.01
        risk = stop_price - entry_price
        if risk <= 0:
            last_idx = i; last_price = new_price; last_rsi = new_rsi
            prior_highs.append((i, new_price)); continue
        rows.append({"entry_index": int(entry_idx), "side": -1, "risk_units": float(risk),
                     "pivot_idx": int(i), "confirm_idx": int(confirmation_idx)})
        last_idx = i; last_price = new_price; last_rsi = new_rsi
        prior_highs.append((i, new_price))

    if not rows:
        return pd.DataFrame(columns=["entry_index", "side", "risk_units"])
    return pd.DataFrame(rows)


def main():
    print("[load] m5 cache...")
    _, m5, _ = load_data()
    print(f"  m5 rows: {len(m5):,}")
    print("[features] RSI14 + ATR14 + pivots(right=2)...")
    df = build_features(m5)
    print("\n=== STRATEGY B — RSI Divergence (PDF2) ===\n")

    print("\n[long, zone_filter=True]")
    sigs_l = generate_signals_long(df, require_zone=True)
    print(f"  signals: {len(sigs_l):,}")
    for tp in [1.0, 2.0, 4.0]:
        trades = simulate(sigs_l[["entry_index", "side", "risk_units"]], df, tp_mult=tp)
        h = headline(trades); print_headline(f"rsidiv_long_zone_TP={tp}R", h)
        persist("rsi_divergence", f"rsidiv_long_zone_TP={tp}R", trades, notes=f"PDF2 long zone TP={tp}R")

    print("\n[long, zone_filter=False]")
    sigs_l2 = generate_signals_long(df, require_zone=False)
    print(f"  signals: {len(sigs_l2):,}")
    for tp in [1.0, 2.0, 4.0]:
        trades = simulate(sigs_l2[["entry_index", "side", "risk_units"]], df, tp_mult=tp)
        h = headline(trades); print_headline(f"rsidiv_long_nozone_TP={tp}R", h)
        persist("rsi_divergence", f"rsidiv_long_nozone_TP={tp}R", trades, notes=f"PDF2 long nozone TP={tp}R")

    print("\n[short, zone_filter=True]")
    sigs_s = generate_signals_short(df, require_zone=True)
    print(f"  signals: {len(sigs_s):,}")
    for tp in [1.0, 2.0, 4.0]:
        trades = simulate(sigs_s[["entry_index", "side", "risk_units"]], df, tp_mult=tp)
        h = headline(trades); print_headline(f"rsidiv_short_zone_TP={tp}R", h)
        persist("rsi_divergence", f"rsidiv_short_zone_TP={tp}R", trades, notes=f"PDF2 short zone TP={tp}R")


if __name__ == "__main__":
    main()
