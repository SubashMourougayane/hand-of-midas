from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class YouTubeSupplyDemandConfig:
    ltf_rule: str = "15min"
    htf_rule: str = "1h"
    htf_atr_length: int = 14
    ltf_atr_length: int = 14
    min_impulse_candles: int = 3
    impulse_atr_multiple: float = 2.0
    max_impulse_pullback_pct: float = 0.50
    ema_length: int = 8
    confirmation_body_ratio: float = 0.70
    confirmation_close_extreme_pct: float = 0.20
    confirmation_mode: str = "engulfing"
    stop_atr_buffer: float = 0.20
    min_target_r: float = 0.0
    swing_left: int = 2
    swing_right: int = 2
    key_level_lookback: int = 100
    base_lookback: int = 10
    zone_expiry_bars: int | None = 288
    zone_expiry_hours: float | None = None
    enforce_h1_trend: bool = False
    close_based_exits: bool = True
    close_fill_at_level: bool = False
    conservative_intrabar: bool = True

    def __post_init__(self) -> None:
        if self.swing_right < 1:
            raise ValueError("swing_right must be >= 1 to avoid same-bar swing confirmation.")
        if self.zone_expiry_hours is not None and self.zone_expiry_hours <= 0:
            raise ValueError("zone_expiry_hours must be positive when set.")


@dataclass
class Zone:
    zone_id: int
    direction: str
    upper: float
    lower: float
    created_bar: int
    created_timestamp: pd.Timestamp
    base_timestamp: pd.Timestamp
    impulse_start_timestamp: pd.Timestamp
    retested: bool = False
    traded: bool = False
    archived: bool = False


def atr(frame: pd.DataFrame, length: int) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    true_range = pd.concat(
        [(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(length, min_periods=length).mean()


def resample_ohlcv(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    indexed = frame.set_index("timestamp")
    aggregations: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    for optional in ("session", "symbol", "timeframe"):
        if optional in indexed.columns:
            aggregations[optional] = "first"

    out = indexed.resample(rule, label="left", closed="left").agg(aggregations)
    return out.dropna(subset=["open", "high", "low", "close"]).reset_index()


def confirmed_swings(frame: pd.DataFrame, left: int, right: int) -> pd.DataFrame:
    if right < 1:
        raise ValueError("swing_right must be >= 1 to avoid same-bar swing confirmation.")
    swings = pd.DataFrame(
        {
            "swing_high": float("nan"),
            "swing_low": float("nan"),
        },
        index=frame.index,
        dtype="float64",
    )
    high = frame["high"].astype(float).to_numpy()
    low = frame["low"].astype(float).to_numpy()
    for pivot_i in range(left, len(frame) - right):
        high_window = high[pivot_i - left : pivot_i + right + 1]
        low_window = low[pivot_i - left : pivot_i + right + 1]
        confirm_i = pivot_i + right
        if high[pivot_i] == high_window.max() and (high_window == high[pivot_i]).sum() == 1:
            swings.loc[confirm_i, "swing_high"] = high[pivot_i]
        if low[pivot_i] == low_window.min() and (low_window == low[pivot_i]).sum() == 1:
            swings.loc[confirm_i, "swing_low"] = low[pivot_i]
    return swings


def h1_trend_series(htf: pd.DataFrame, config: YouTubeSupplyDemandConfig) -> pd.Series:
    swings = confirmed_swings(htf, config.swing_left, config.swing_right)
    last_highs: list[float] = []
    last_lows: list[float] = []
    trends: list[str] = []

    for i in range(len(htf)):
        swing_high = swings["swing_high"].iloc[i]
        swing_low = swings["swing_low"].iloc[i]
        if pd.notna(swing_high):
            last_highs.append(float(swing_high))
            last_highs = last_highs[-2:]
        if pd.notna(swing_low):
            last_lows.append(float(swing_low))
            last_lows = last_lows[-2:]

        if len(last_highs) == 2 and len(last_lows) == 2:
            if last_highs[-1] > last_highs[-2] and last_lows[-1] > last_lows[-2]:
                trends.append("bullish")
            elif last_highs[-1] < last_highs[-2] and last_lows[-1] < last_lows[-2]:
                trends.append("bearish")
            else:
                trends.append("range")
        else:
            trends.append("range")

    return pd.Series(trends, index=htf.index, dtype="string")


def detect_zones(
    ltf_frame: pd.DataFrame,
    config: YouTubeSupplyDemandConfig = YouTubeSupplyDemandConfig(),
) -> list[Zone]:
    htf = resample_ohlcv(ltf_frame, config.htf_rule)
    htf["atr"] = atr(htf, config.htf_atr_length)
    trend = h1_trend_series(htf, config)
    htf_offset = pd.tseries.frequencies.to_offset(config.htf_rule)
    zones: list[Zone] = []
    previous_qualifying_direction = ""

    for i in range(config.min_impulse_candles - 1, len(htf)):
        atr_value = htf["atr"].iloc[i]
        if pd.isna(atr_value) or atr_value <= 0:
            previous_qualifying_direction = ""
            continue

        direction, start_i = _current_impulse(htf, i, config)
        if not direction:
            previous_qualifying_direction = ""
            continue
        if previous_qualifying_direction == direction:
            continue

        trend_value = trend.iloc[i]
        if config.enforce_h1_trend and (
            (direction == "demand" and trend_value != "bullish")
            or (direction == "supply" and trend_value != "bearish")
        ):
            previous_qualifying_direction = direction
            continue

        base_i = _find_base_index(htf, start_i, direction, config.base_lookback)
        if base_i is None:
            previous_qualifying_direction = direction
            continue

        zones.append(
            Zone(
                zone_id=len(zones) + 1,
                direction=direction,
                upper=float(htf["high"].iloc[base_i]),
                lower=float(htf["low"].iloc[base_i]),
                created_bar=i,
                created_timestamp=htf["timestamp"].iloc[i] + htf_offset,
                base_timestamp=htf["timestamp"].iloc[base_i],
                impulse_start_timestamp=htf["timestamp"].iloc[start_i],
            )
        )
        previous_qualifying_direction = direction

    return zones


def _current_impulse(
    htf: pd.DataFrame,
    end_i: int,
    config: YouTubeSupplyDemandConfig,
) -> tuple[str, int | None]:
    open_ = htf["open"].astype(float)
    close = htf["close"].astype(float)
    start_i = end_i
    while start_i >= 0 and close.iloc[start_i] > open_.iloc[start_i]:
        start_i -= 1
    bullish_start = start_i + 1

    start_i = end_i
    while start_i >= 0 and close.iloc[start_i] < open_.iloc[start_i]:
        start_i -= 1
    bearish_start = start_i + 1

    if end_i - bullish_start + 1 >= config.min_impulse_candles:
        total_move = close.iloc[end_i] - open_.iloc[bullish_start]
        threshold = config.impulse_atr_multiple * htf["atr"].iloc[end_i]
        if total_move >= threshold and _pullback_ok(htf, bullish_start, end_i, "demand", total_move, config):
            return "demand", bullish_start

    if end_i - bearish_start + 1 >= config.min_impulse_candles:
        total_move = open_.iloc[bearish_start] - close.iloc[end_i]
        threshold = config.impulse_atr_multiple * htf["atr"].iloc[end_i]
        if total_move >= threshold and _pullback_ok(htf, bearish_start, end_i, "supply", total_move, config):
            return "supply", bearish_start

    return "", None


def _pullback_ok(
    htf: pd.DataFrame,
    start_i: int,
    end_i: int,
    direction: str,
    total_move: float,
    config: YouTubeSupplyDemandConfig,
) -> bool:
    if total_move <= 0:
        return False
    if direction == "demand":
        running_high = float(htf["high"].iloc[start_i])
        max_pullback = 0.0
        for i in range(start_i + 1, end_i + 1):
            max_pullback = max(max_pullback, running_high - float(htf["low"].iloc[i]))
            running_high = max(running_high, float(htf["high"].iloc[i]))
    else:
        running_low = float(htf["low"].iloc[start_i])
        max_pullback = 0.0
        for i in range(start_i + 1, end_i + 1):
            max_pullback = max(max_pullback, float(htf["high"].iloc[i]) - running_low)
            running_low = min(running_low, float(htf["low"].iloc[i]))
    return max_pullback / total_move <= config.max_impulse_pullback_pct


def _find_base_index(
    htf: pd.DataFrame,
    impulse_start_i: int | None,
    direction: str,
    lookback: int,
) -> int | None:
    if impulse_start_i is None:
        return None
    first_i = max(0, impulse_start_i - lookback)
    for i in range(impulse_start_i - 1, first_i - 1, -1):
        open_ = float(htf["open"].iloc[i])
        close = float(htf["close"].iloc[i])
        if direction == "demand" and close < open_:
            return i
        if direction == "supply" and close > open_:
            return i
    return None
