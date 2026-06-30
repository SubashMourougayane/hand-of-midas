from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .retest_engine import zone_expiry_index, zone_failed
from .zone_detector import YouTubeSupplyDemandConfig, Zone, atr


@dataclass(frozen=True)
class ConfirmationResult:
    zone: Zone
    decision_index: int
    entry_index: int
    decision_timestamp: pd.Timestamp
    confirmation: str


def add_confirmation_features(ltf: pd.DataFrame, config: YouTubeSupplyDemandConfig) -> pd.DataFrame:
    out = ltf.copy()
    out["atr"] = atr(out, config.ltf_atr_length)
    out["ema"] = out["close"].ewm(span=config.ema_length, adjust=False, min_periods=config.ema_length).mean()
    return out


def find_confirmation(
    ltf: pd.DataFrame,
    zone: Zone,
    retest_index: int,
    config: YouTubeSupplyDemandConfig,
) -> ConfirmationResult | None:
    start_i = int(ltf["timestamp"].searchsorted(zone.created_timestamp, side="left"))
    expiry_i = zone_expiry_index(ltf, start_i, zone.created_timestamp, config)
    for i in range(retest_index + 1, min(expiry_i, len(ltf) - 1)):
        row = ltf.iloc[i]
        prev = ltf.iloc[i - 1]
        if zone_failed(row, zone):
            zone.archived = True
            return None
        if pd.isna(row["ema"]) or pd.isna(prev["ema"]):
            continue

        if zone.direction == "demand":
            ema_ok = prev["close"] < prev["ema"] and row["close"] > row["ema"]
            candle_ok, label = bullish_confirmation(row, prev, config)
        else:
            ema_ok = prev["close"] > prev["ema"] and row["close"] < row["ema"]
            candle_ok, label = bearish_confirmation(row, prev, config)

        if ema_ok and candle_ok:
            return ConfirmationResult(
                zone=zone,
                decision_index=i,
                entry_index=i + 1,
                decision_timestamp=row["timestamp"],
                confirmation=label,
            )
    return None


def bullish_confirmation(
    row: pd.Series,
    prev: pd.Series,
    config: YouTubeSupplyDemandConfig,
) -> tuple[bool, str]:
    if config.confirmation_mode in {"both", "engulfing"}:
        engulfing = (
            row["close"] > row["open"]
            and prev["close"] < prev["open"]
            and row["open"] < prev["close"]
            and row["close"] > prev["open"]
        )
        if engulfing:
            return True, "bullish_engulfing"

    if config.confirmation_mode not in {"both", "strong_body"}:
        return False, ""
    candle_range = row["high"] - row["low"]
    if candle_range <= 0:
        return False, ""
    body = row["close"] - row["open"]
    strong_body = (
        body > 0
        and body / candle_range >= config.confirmation_body_ratio
        and (row["high"] - row["close"]) / candle_range <= config.confirmation_close_extreme_pct
    )
    return (bool(strong_body), "bullish_strong_body" if strong_body else "")


def bearish_confirmation(
    row: pd.Series,
    prev: pd.Series,
    config: YouTubeSupplyDemandConfig,
) -> tuple[bool, str]:
    if config.confirmation_mode in {"both", "engulfing"}:
        engulfing = (
            row["close"] < row["open"]
            and prev["close"] > prev["open"]
            and row["open"] > prev["close"]
            and row["close"] < prev["open"]
        )
        if engulfing:
            return True, "bearish_engulfing"

    if config.confirmation_mode not in {"both", "strong_body"}:
        return False, ""
    candle_range = row["high"] - row["low"]
    if candle_range <= 0:
        return False, ""
    body = row["open"] - row["close"]
    strong_body = (
        body > 0
        and body / candle_range >= config.confirmation_body_ratio
        and (row["close"] - row["low"]) / candle_range <= config.confirmation_close_extreme_pct
    )
    return (bool(strong_body), "bearish_strong_body" if strong_body else "")
