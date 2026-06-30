from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .causality import prepare_intraday_frame, validate_market_data
from .confirmation_engine import add_confirmation_features
from .supply_demand_ema_retest import _remove_pyramids
from .trade_manager import empty_trades, summarize_trades
from .zone_detector import YouTubeSupplyDemandConfig, atr, confirmed_swings, resample_ohlcv


STRATEGY_ID = "SND_FIB_CONFLUENCE_2Z_NQBUNHEO_V1"


@dataclass(frozen=True)
class SndFibConfig:
    ltf_rule: str = "15min"
    htf_rule: str = "1h"
    htf_atr_length: int = 14
    ltf_atr_length: int = 14
    min_momentum_candles: int = 3
    momentum_body_atr_multiple: float = 1.0
    consolidation_bars: int = 6
    consolidation_max_range_atr: float = 1.2
    breakout_body_atr_multiple: float = 1.0
    wick_cluster_bars: int = 6
    wick_cluster_min_touches: int = 3
    wick_min_pct_range: float = 0.55
    wick_cluster_tolerance_atr: float = 0.45
    fib_levels: tuple[float, ...] = (0.50, 0.618)
    fib_overlap_tolerance_atr: float = 0.20
    fib_extension: float = 0.27
    zone_expiry_hours: float = 72.0
    confirmation_max_wait_hours: float = 24.0
    stop_mode: str = "conservative_zone"
    stop_atr_buffer: float = 0.10
    min_target_r: float = 0.50
    remove_pyramids: bool = True


@dataclass
class FibZone:
    zone_id: int
    direction: str
    upper: float
    lower: float
    created_bar: int
    created_timestamp: pd.Timestamp
    base_timestamp: pd.Timestamp
    impulse_start_timestamp: pd.Timestamp
    impulse_end_timestamp: pd.Timestamp
    fib_low: float
    fib_high: float
    fib_level: float
    fib_price: float
    source: str
    retested: bool = False
    traded: bool = False
    archived: bool = False


@dataclass(frozen=True)
class FibConfirmation:
    zone: FibZone
    retest_index: int
    decision_index: int
    entry_index: int
    decision_timestamp: pd.Timestamp
    confirmation: str


def generate_snd_fib_confluence_trades(
    raw: pd.DataFrame,
    config: SndFibConfig = SndFibConfig(),
) -> pd.DataFrame:
    frame = prepare_intraday_frame(raw)
    validate_market_data(frame)
    ltf = resample_ohlcv(frame, config.ltf_rule).reset_index(drop=True)
    if len(ltf) < max(config.ltf_atr_length, config.htf_atr_length) + 2:
        return empty_snd_fib_trades()

    base_config = YouTubeSupplyDemandConfig(
        ltf_rule=config.ltf_rule,
        htf_rule=config.htf_rule,
        htf_atr_length=config.htf_atr_length,
        ltf_atr_length=config.ltf_atr_length,
        zone_expiry_bars=None,
        zone_expiry_hours=config.zone_expiry_hours,
        confirmation_mode="both",
    )
    ltf = add_confirmation_features(ltf, base_config)
    htf = resample_ohlcv(ltf, config.htf_rule).reset_index(drop=True)
    htf["atr"] = atr(htf, config.htf_atr_length)
    swings = confirmed_swings(ltf, 2, 2)
    zones = detect_snd_fib_zones(htf, config)

    candidates: list[dict[str, object]] = []
    for zone in zones:
        confirmation = find_fib_confirmation(ltf, zone, config)
        if confirmation is None:
            continue
        trade = build_fib_trade(ltf, confirmation, config, swings)
        if trade is not None:
            candidates.append(trade)

    if not candidates:
        return empty_snd_fib_trades()

    trades = pd.DataFrame(candidates).sort_values(["entry_timestamp", "zone_id"]).reset_index(drop=True)
    if config.remove_pyramids:
        trades = _remove_pyramids(trades)
    return trades.reset_index(drop=True)


def empty_snd_fib_trades() -> pd.DataFrame:
    base = empty_trades()
    for col in [
        "source",
        "fib_level",
        "fib_price",
        "fib_low",
        "fib_high",
        "target_r",
        "final_r_multiple",
        "final_pnl_units",
        "held_hours",
    ]:
        base[col] = pd.Series(dtype="float64")
    return base


def detect_snd_fib_zones(htf: pd.DataFrame, config: SndFibConfig) -> list[FibZone]:
    zones: list[FibZone] = []
    seen: set[tuple[str, int, str]] = set()

    def add_zone(candidate: FibZone | None) -> None:
        if candidate is None:
            return
        key = (candidate.direction, candidate.created_bar, candidate.source)
        if key in seen:
            return
        seen.add(key)
        candidate.zone_id = len(zones) + 1
        zones.append(candidate)

    for i in range(config.htf_atr_length, len(htf)):
        add_zone(momentum_zone(htf, i, config))
        add_zone(consolidation_zone(htf, i, config))
        add_zone(wick_rejection_zone(htf, i, config))

    return zones


def momentum_zone(htf: pd.DataFrame, end_i: int, config: SndFibConfig) -> FibZone | None:
    atr_value = float(htf["atr"].iloc[end_i])
    if not np.isfinite(atr_value) or atr_value <= 0:
        return None
    open_ = htf["open"].astype(float)
    close = htf["close"].astype(float)
    body = (close - open_).abs()

    start_i = end_i
    while start_i >= 0 and close.iloc[start_i] > open_.iloc[start_i] and body.iloc[start_i] >= config.momentum_body_atr_multiple * atr_value:
        start_i -= 1
    bull_start = start_i + 1
    if end_i - bull_start + 1 >= config.min_momentum_candles and bull_start > 0:
        return base_candle_zone(htf, bull_start - 1, bull_start, end_i, "demand", "momentum_3_candle", config)

    start_i = end_i
    while start_i >= 0 and close.iloc[start_i] < open_.iloc[start_i] and body.iloc[start_i] >= config.momentum_body_atr_multiple * atr_value:
        start_i -= 1
    bear_start = start_i + 1
    if end_i - bear_start + 1 >= config.min_momentum_candles and bear_start > 0:
        return base_candle_zone(htf, bear_start - 1, bear_start, end_i, "supply", "momentum_3_candle", config)

    return None


def consolidation_zone(htf: pd.DataFrame, breakout_i: int, config: SndFibConfig) -> FibZone | None:
    start_i = breakout_i - config.consolidation_bars
    if start_i < 0:
        return None
    atr_value = float(htf["atr"].iloc[breakout_i])
    if not np.isfinite(atr_value) or atr_value <= 0:
        return None
    block = htf.iloc[start_i:breakout_i]
    upper = float(block["high"].max())
    lower = float(block["low"].min())
    if upper - lower > config.consolidation_max_range_atr * atr_value:
        return None
    row = htf.iloc[breakout_i]
    breakout_body = abs(float(row["close"] - row["open"]))
    if breakout_body < config.breakout_body_atr_multiple * atr_value:
        return None
    if float(row["close"]) > upper:
        return zone_from_bounds(htf, start_i, breakout_i, "demand", upper, lower, "consolidation_breakout", config)
    if float(row["close"]) < lower:
        return zone_from_bounds(htf, start_i, breakout_i, "supply", upper, lower, "consolidation_breakout", config)
    return None


def wick_rejection_zone(htf: pd.DataFrame, end_i: int, config: SndFibConfig) -> FibZone | None:
    start_i = end_i - config.wick_cluster_bars + 1
    if start_i < 0:
        return None
    atr_value = float(htf["atr"].iloc[end_i])
    if not np.isfinite(atr_value) or atr_value <= 0:
        return None
    block = htf.iloc[start_i : end_i + 1]
    candle_range = (block["high"] - block["low"]).astype(float)
    valid_range = candle_range > 0
    lower_wick = (np.minimum(block["open"], block["close"]) - block["low"]).astype(float)
    upper_wick = (block["high"] - np.maximum(block["open"], block["close"])).astype(float)

    lower_hits = block[valid_range & (lower_wick / candle_range >= config.wick_min_pct_range)]
    if len(lower_hits) >= config.wick_cluster_min_touches and float(lower_hits["low"].max() - lower_hits["low"].min()) <= config.wick_cluster_tolerance_atr * atr_value:
        return zone_from_bounds(
            htf,
            int(lower_hits.index[0]),
            end_i,
            "demand",
            float(lower_hits[["open", "close"]].min(axis=1).max()),
            float(lower_hits["low"].min()),
            "multi_wick_rejection",
            config,
        )

    upper_hits = block[valid_range & (upper_wick / candle_range >= config.wick_min_pct_range)]
    if len(upper_hits) >= config.wick_cluster_min_touches and float(upper_hits["high"].max() - upper_hits["high"].min()) <= config.wick_cluster_tolerance_atr * atr_value:
        return zone_from_bounds(
            htf,
            int(upper_hits.index[0]),
            end_i,
            "supply",
            float(upper_hits["high"].max()),
            float(upper_hits[["open", "close"]].max(axis=1).min()),
            "multi_wick_rejection",
            config,
        )
    return None


def base_candle_zone(
    htf: pd.DataFrame,
    base_i: int,
    start_i: int,
    end_i: int,
    direction: str,
    source: str,
    config: SndFibConfig,
) -> FibZone | None:
    return zone_from_bounds(
        htf,
        start_i,
        end_i,
        direction,
        float(htf["high"].iloc[base_i]),
        float(htf["low"].iloc[base_i]),
        source,
        config,
        base_i=base_i,
    )


def zone_from_bounds(
    htf: pd.DataFrame,
    start_i: int,
    end_i: int,
    direction: str,
    upper: float,
    lower: float,
    source: str,
    config: SndFibConfig,
    base_i: int | None = None,
) -> FibZone | None:
    if upper <= lower:
        return None
    fib_low = float(htf["low"].iloc[start_i : end_i + 1].min())
    fib_high = float(htf["high"].iloc[start_i : end_i + 1].max())
    if fib_high <= fib_low:
        return None
    atr_value = float(htf["atr"].iloc[end_i])
    fib = best_fib_overlap(direction, upper, lower, fib_low, fib_high, atr_value, config)
    if fib is None:
        return None
    fib_level, fib_price = fib
    offset = pd.tseries.frequencies.to_offset(config.htf_rule)
    base_index = start_i if base_i is None else base_i
    return FibZone(
        zone_id=0,
        direction=direction,
        upper=upper,
        lower=lower,
        created_bar=end_i,
        created_timestamp=htf["timestamp"].iloc[end_i] + offset,
        base_timestamp=htf["timestamp"].iloc[base_index],
        impulse_start_timestamp=htf["timestamp"].iloc[start_i],
        impulse_end_timestamp=htf["timestamp"].iloc[end_i],
        fib_low=fib_low,
        fib_high=fib_high,
        fib_level=fib_level,
        fib_price=fib_price,
        source=source,
    )


def best_fib_overlap(
    direction: str,
    upper: float,
    lower: float,
    fib_low: float,
    fib_high: float,
    atr_value: float,
    config: SndFibConfig,
) -> tuple[float, float] | None:
    tolerance = config.fib_overlap_tolerance_atr * atr_value
    best: tuple[float, float, float] | None = None
    for level in config.fib_levels:
        if direction == "demand":
            price = fib_high - level * (fib_high - fib_low)
        else:
            price = fib_low + level * (fib_high - fib_low)
        distance = 0.0 if lower - tolerance <= price <= upper + tolerance else min(abs(price - lower), abs(price - upper))
        if distance <= tolerance and (best is None or distance < best[2]):
            best = (level, price, distance)
    if best is None:
        return None
    return best[0], best[1]


def find_fib_confirmation(ltf: pd.DataFrame, zone: FibZone, config: SndFibConfig) -> FibConfirmation | None:
    start_i = int(ltf["timestamp"].searchsorted(zone.created_timestamp, side="left"))
    expiry_ts = zone.created_timestamp + pd.Timedelta(hours=config.zone_expiry_hours)
    expiry_i = min(len(ltf), int(ltf["timestamp"].searchsorted(expiry_ts, side="left")))
    retest_i: int | None = None
    for i in range(start_i, expiry_i):
        row = ltf.iloc[i]
        if zone_failed(row, zone):
            zone.archived = True
            return None
        if zone_touched(row, zone):
            zone.retested = True
            retest_i = i
            break
    if retest_i is None:
        return None

    confirm_cutoff = min(
        expiry_i,
        int(ltf["timestamp"].searchsorted(ltf["timestamp"].iloc[retest_i] + pd.Timedelta(hours=config.confirmation_max_wait_hours), side="left")),
        len(ltf) - 1,
    )
    for i in range(retest_i + 1, confirm_cutoff):
        row = ltf.iloc[i]
        prev = ltf.iloc[i - 1]
        if zone_failed(row, zone):
            zone.archived = True
            return None
        if zone.direction == "demand":
            ok, label = bullish_rejection_confirmation(row, prev)
        else:
            ok, label = bearish_rejection_confirmation(row, prev)
        if ok:
            return FibConfirmation(zone, retest_i, i, i, row["timestamp"], label)
    return None


def zone_touched(row: pd.Series, zone: FibZone) -> bool:
    return bool(row["high"] >= zone.lower and row["low"] <= zone.upper)


def zone_failed(row: pd.Series, zone: FibZone) -> bool:
    if zone.direction == "demand":
        return bool(row["close"] < zone.lower)
    return bool(row["close"] > zone.upper)


def bullish_rejection_confirmation(row: pd.Series, prev: pd.Series) -> tuple[bool, str]:
    engulfing = row["close"] > row["open"] and prev["close"] < prev["open"] and row["open"] < prev["close"] and row["close"] > prev["open"]
    if engulfing:
        return True, "bullish_engulfing"
    candle_range = float(row["high"] - row["low"])
    if candle_range <= 0:
        return False, ""
    lower_wick = float(min(row["open"], row["close"]) - row["low"])
    body = abs(float(row["close"] - row["open"]))
    doji_pin = lower_wick / candle_range >= 0.55 and body / candle_range <= 0.35 and row["close"] >= row["open"]
    return bool(doji_pin), "bullish_pin_doji_rejection" if doji_pin else ""


def bearish_rejection_confirmation(row: pd.Series, prev: pd.Series) -> tuple[bool, str]:
    engulfing = row["close"] < row["open"] and prev["close"] > prev["open"] and row["open"] > prev["close"] and row["close"] < prev["open"]
    if engulfing:
        return True, "bearish_engulfing"
    candle_range = float(row["high"] - row["low"])
    if candle_range <= 0:
        return False, ""
    upper_wick = float(row["high"] - max(row["open"], row["close"]))
    body = abs(float(row["close"] - row["open"]))
    doji_pin = upper_wick / candle_range >= 0.55 and body / candle_range <= 0.35 and row["close"] <= row["open"]
    return bool(doji_pin), "bearish_pin_doji_rejection" if doji_pin else ""


def build_fib_trade(
    ltf: pd.DataFrame,
    confirmation: FibConfirmation,
    config: SndFibConfig,
    swings: pd.DataFrame,
) -> dict[str, object] | None:
    zone = confirmation.zone
    entry_i = confirmation.entry_index
    row = ltf.iloc[entry_i]
    atr_value = float(row["atr"])
    if not np.isfinite(atr_value) or atr_value <= 0:
        return None
    side = 1 if zone.direction == "demand" else -1
    entry_price = float(row["close"])
    if zone.direction == "demand":
        stop_price = min(zone.lower, float(ltf["low"].iloc[confirmation.decision_index])) - config.stop_atr_buffer * atr_value
        take_profit = zone.fib_high + config.fib_extension * (zone.fib_high - zone.fib_low)
    else:
        stop_price = max(zone.upper, float(ltf["high"].iloc[confirmation.decision_index])) + config.stop_atr_buffer * atr_value
        take_profit = zone.fib_low - config.fib_extension * (zone.fib_high - zone.fib_low)

    risk = (entry_price - stop_price) if side > 0 else (stop_price - entry_price)
    reward = (take_profit - entry_price) if side > 0 else (entry_price - take_profit)
    if risk <= 0 or reward / risk < config.min_target_r:
        return None

    outcome = simulate_close_exit(ltf, entry_i, side, entry_price, stop_price, take_profit, risk)
    zone.traded = True
    zone.archived = True
    final_pnl_units = outcome["r_multiple"] * risk
    return {
        "zone_id": zone.zone_id,
        "zone_direction": zone.direction,
        "decision_timestamp": confirmation.decision_timestamp,
        "entry_timestamp": ltf["timestamp"].iloc[entry_i],
        "exit_timestamp": outcome["exit_timestamp"],
        "side": side,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "take_profit": take_profit,
        "exit_price": outcome["exit_price"],
        "exit_reason": outcome["exit_reason"],
        "risk_units": risk,
        "pnl_units": final_pnl_units,
        "r_multiple": outcome["r_multiple"],
        "confirmation": confirmation.confirmation,
        "zone_upper": zone.upper,
        "zone_lower": zone.lower,
        "zone_created_timestamp": zone.created_timestamp,
        "zone_retested": zone.retested,
        "zone_traded": zone.traded,
        "source": zone.source,
        "fib_level": zone.fib_level,
        "fib_price": zone.fib_price,
        "fib_low": zone.fib_low,
        "fib_high": zone.fib_high,
        "target_r": reward / risk,
        "final_r_multiple": outcome["r_multiple"],
        "final_pnl_units": final_pnl_units,
        "held_hours": held_hours(ltf, entry_i, int(outcome["exit_index"])),
    }


def simulate_close_exit(
    ltf: pd.DataFrame,
    entry_i: int,
    side: int,
    entry_price: float,
    stop_price: float,
    take_profit: float,
    risk: float,
) -> dict[str, object]:
    for i in range(entry_i, len(ltf)):
        close = float(ltf["close"].iloc[i])
        if side > 0:
            if close <= stop_price:
                return exit_result(ltf, i, close, (close - entry_price) / risk, "close_stop")
            if close >= take_profit:
                return exit_result(ltf, i, close, (close - entry_price) / risk, "close_take_profit")
        else:
            if close >= stop_price:
                return exit_result(ltf, i, close, (entry_price - close) / risk, "close_stop")
            if close <= take_profit:
                return exit_result(ltf, i, close, (entry_price - close) / risk, "close_take_profit")
    final_i = len(ltf) - 1
    close = float(ltf["close"].iloc[final_i])
    return exit_result(ltf, final_i, close, (close - entry_price) * side / risk, "end_of_data")


def exit_result(ltf: pd.DataFrame, exit_i: int, exit_price: float, r: float, reason: str) -> dict[str, object]:
    return {
        "exit_index": exit_i,
        "exit_timestamp": ltf["timestamp"].iloc[exit_i],
        "exit_price": exit_price,
        "r_multiple": r,
        "exit_reason": reason,
    }


def held_hours(ltf: pd.DataFrame, entry_i: int, exit_i: int) -> float:
    return float((pd.Timestamp(ltf["timestamp"].iloc[exit_i]) - pd.Timestamp(ltf["timestamp"].iloc[entry_i])).total_seconds() / 3600.0)


def summarize_snd_fib_trades(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_r": 0.0}
    normalized = trades.copy()
    normalized["pnl_units"] = normalized["final_pnl_units"]
    normalized["r_multiple"] = normalized["final_r_multiple"]
    return summarize_trades(normalized)


__all__ = [
    "STRATEGY_ID",
    "SndFibConfig",
    "detect_snd_fib_zones",
    "generate_snd_fib_confluence_trades",
    "summarize_snd_fib_trades",
]
