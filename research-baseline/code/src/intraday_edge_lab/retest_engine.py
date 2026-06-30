from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .zone_detector import YouTubeSupplyDemandConfig, Zone


@dataclass(frozen=True)
class RetestResult:
    zone: Zone
    retest_index: int
    retest_timestamp: pd.Timestamp


def find_retest(
    ltf: pd.DataFrame,
    zone: Zone,
    config: YouTubeSupplyDemandConfig = YouTubeSupplyDemandConfig(),
) -> RetestResult | None:
    start_i = int(ltf["timestamp"].searchsorted(zone.created_timestamp, side="left"))
    expiry_i = zone_expiry_index(ltf, start_i, zone.created_timestamp, config)
    for i in range(start_i, expiry_i):
        row = ltf.iloc[i]
        if zone_failed(row, zone):
            zone.archived = True
            return None
        if zone_touched(row, zone):
            zone.retested = True
            return RetestResult(zone=zone, retest_index=i, retest_timestamp=row["timestamp"])
    return None


def zone_touched(row: pd.Series, zone: Zone) -> bool:
    return bool(row["high"] >= zone.lower and row["low"] <= zone.upper)


def zone_failed(row: pd.Series, zone: Zone) -> bool:
    if zone.direction == "demand":
        return bool(row["close"] < zone.lower)
    return bool(row["close"] > zone.upper)


def zone_expiry_index(
    ltf: pd.DataFrame,
    start_i: int,
    created_timestamp: pd.Timestamp,
    config: YouTubeSupplyDemandConfig,
) -> int:
    if config.zone_expiry_hours is not None:
        cutoff = pd.Timestamp(created_timestamp) + pd.Timedelta(hours=config.zone_expiry_hours)
        return int(ltf["timestamp"].searchsorted(cutoff, side="left"))
    if config.zone_expiry_bars is not None:
        return min(len(ltf), start_i + config.zone_expiry_bars)
    return len(ltf)
