from __future__ import annotations

import numpy as np
import pandas as pd

from .causality import assert_feature_timestamps


def add_synthetic_quotes(frame: pd.DataFrame, spread_bps: float = 2.0) -> pd.DataFrame:
    """Attach conservative bid/ask quotes when raw quotes are unavailable."""
    out = frame.copy()
    if {"bid", "ask"}.issubset(out.columns):
        return out
    half_spread = out["close"] * (spread_bps / 10000.0) / 2.0
    out["bid"] = out["close"] - half_spread
    out["ask"] = out["close"] + half_spread
    return out


def build_causal_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Build bar-close features using only information known by each timestamp."""
    out = pd.DataFrame({"timestamp": frame["timestamp"]})
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)

    returns = close.pct_change()
    true_range = pd.concat(
        [(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)

    out["ret_1"] = returns
    out["log_ret_1"] = np.log(close).diff()
    out["rv_5"] = returns.rolling(5, min_periods=5).std()
    out["rv_20"] = returns.rolling(20, min_periods=20).std()
    out["atr_14"] = true_range.rolling(14, min_periods=14).mean()
    atr_baseline = out["atr_14"].shift(1).rolling(100, min_periods=50).mean()
    out["atr_pct_100"] = (out["atr_14"] >= atr_baseline).astype(float)
    out["volume_z_20"] = (volume - volume.rolling(20, min_periods=20).mean()) / volume.rolling(
        20, min_periods=20
    ).std()
    out["rvol_20"] = volume / volume.rolling(20, min_periods=20).mean()
    out["range_pct"] = (high - low) / close
    out["close_location"] = ((close - low) / (high - low).replace(0, np.nan)).clip(0, 1)
    out["spread_bps"] = ((frame["ask"] - frame["bid"]) / close) * 10000.0

    for length in (9, 20, 21, 34, 50, 100, 200):
        ema = close.ewm(span=length, adjust=False, min_periods=length).mean()
        out[f"ema_{length}"] = ema
        out[f"ema_{length}_slope_5"] = ema.diff(5) / ema.shift(5)
        out[f"close_to_ema_{length}_atr"] = (close - ema) / out["atr_14"].replace(0, np.nan)

    for length in (20, 50, 100, 200):
        sma = close.rolling(length, min_periods=length).mean()
        out[f"sma_{length}"] = sma
        out[f"sma_{length}_slope_5"] = sma.diff(5) / sma.shift(5)

    gain = close.diff().clip(lower=0)
    loss = -close.diff().clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["rsi_14"] = 100 - (100 / (1 + rs))
    out["rsi_14_slope_5"] = out["rsi_14"].diff(5)

    typical = (high + low + close) / 3.0
    if "session" in frame.columns:
        session = frame["session"].astype(str)
    else:
        session = frame["timestamp"].dt.date.astype(str)
    dollar_volume = typical * volume
    vwap = dollar_volume.groupby(session).cumsum() / volume.groupby(session).cumsum()
    out["session_vwap"] = vwap
    out["close_to_vwap_atr"] = (close - vwap) / out["atr_14"].replace(0, np.nan)

    assert_feature_timestamps(out, frame)
    return out


def previous_session_extremes(frame: pd.DataFrame) -> pd.DataFrame:
    """Map each row to the prior session high and low without crossing the boundary."""
    if "session" in frame.columns:
        session = frame["session"].astype(str)
    else:
        session = frame["timestamp"].dt.date.astype(str)

    session_stats = (
        frame.assign(_session=session)
        .groupby("_session", sort=True)
        .agg(prev_high=("high", "max"), prev_low=("low", "min"))
        .shift(1)
    )
    mapped = session.map(session_stats["prev_high"]).to_frame("prev_session_high")
    mapped["prev_session_low"] = session.map(session_stats["prev_low"])
    return mapped.reset_index(drop=True)
