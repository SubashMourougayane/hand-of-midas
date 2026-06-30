from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .causality import prepare_intraday_frame, validate_market_data
from .confirmation_engine import add_confirmation_features
from .retest_engine import find_retest, zone_failed
from .supply_demand_ema_retest import _remove_pyramids
from .trade_manager import _last_swing, _nearest_prior_target, empty_trades, summarize_trades
from .zone_detector import YouTubeSupplyDemandConfig, Zone, confirmed_swings, detect_zones, resample_ohlcv


STRATEGY_ID = "YOUTUBE_AY7FWME1CBK_TO_DOT_V1"


@dataclass(frozen=True)
class YouTubeToDotConfig:
    base: YouTubeSupplyDemandConfig = field(
        default_factory=lambda: YouTubeSupplyDemandConfig(
            confirmation_mode="both",
            zone_expiry_bars=None,
            zone_expiry_hours=48.0,
            enforce_h1_trend=False,
            max_impulse_pullback_pct=0.50,
            min_target_r=0.0,
            close_based_exits=True,
            close_fill_at_level=False,
        )
    )
    huge_body_atr_multiple: float = 1.0
    fixed_fallback_target_r: float = 2.5
    near_target_progress: float = 0.80
    reversal_body_ratio: float = 0.60
    reversal_close_location: float = 0.60
    remove_pyramids: bool = True


@dataclass(frozen=True)
class ToDotConfirmation:
    zone: Zone
    decision_index: int
    entry_index: int
    decision_timestamp: pd.Timestamp
    confirmation: str


def generate_youtube_to_dot_trades(
    raw: pd.DataFrame,
    config: YouTubeToDotConfig = YouTubeToDotConfig(),
) -> pd.DataFrame:
    frame = prepare_intraday_frame(raw)
    validate_market_data(frame)
    ltf = resample_ohlcv(frame, config.base.ltf_rule).reset_index(drop=True)
    if len(ltf) < max(config.base.ltf_atr_length, config.base.ema_length) + 2:
        return empty_youtube_to_dot_trades()

    ltf = add_confirmation_features(ltf, config.base)
    zones = detect_zones(ltf, config.base)
    swings = confirmed_swings(ltf, config.base.swing_left, config.base.swing_right)
    candidates: list[dict[str, object]] = []

    for zone in zones:
        retest = find_retest(ltf, zone, config.base)
        if retest is None:
            continue
        confirmation = find_to_dot_confirmation(ltf, zone, retest.retest_index, config)
        if confirmation is None:
            continue
        trade = build_to_dot_trade(ltf, confirmation, config, swings)
        if trade is not None:
            candidates.append(trade)

    if not candidates:
        return empty_youtube_to_dot_trades()

    trades = pd.DataFrame(candidates).sort_values(["entry_timestamp", "zone_id"]).reset_index(drop=True)
    if config.remove_pyramids:
        trades = _remove_pyramids(trades)
    return trades.reset_index(drop=True)


def empty_youtube_to_dot_trades() -> pd.DataFrame:
    base = empty_trades()
    for column in [
        "target_rule",
        "target_r",
        "near_target_progress",
        "final_r_multiple",
        "final_pnl_units",
        "held_hours",
    ]:
        base[column] = pd.Series(dtype="float64")
    return base


def summarize_youtube_to_dot_trades(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_r": 0.0}
    normalized = trades.copy()
    normalized["pnl_units"] = normalized["final_pnl_units"]
    normalized["r_multiple"] = normalized["final_r_multiple"]
    return summarize_trades(normalized)


def find_to_dot_confirmation(
    ltf: pd.DataFrame,
    zone: Zone,
    retest_index: int,
    config: YouTubeToDotConfig,
) -> ToDotConfirmation | None:
    start_i = int(ltf["timestamp"].searchsorted(zone.created_timestamp, side="left"))
    expiry_i = _zone_expiry_index(ltf, start_i, zone.created_timestamp, config.base)
    for i in range(retest_index + 1, min(expiry_i, len(ltf) - 1)):
        row = ltf.iloc[i]
        prev = ltf.iloc[i - 1]
        if zone_failed(row, zone):
            zone.archived = True
            return None
        if pd.isna(row["ema"]) or pd.isna(prev["ema"]) or pd.isna(row["atr"]):
            continue

        if zone.direction == "demand":
            ema_ok = prev["close"] < prev["ema"] and row["close"] > row["ema"]
            candle_ok, label = bullish_to_dot_candle(row, prev, config)
        else:
            ema_ok = prev["close"] > prev["ema"] and row["close"] < row["ema"]
            candle_ok, label = bearish_to_dot_candle(row, prev, config)

        if ema_ok and candle_ok:
            return ToDotConfirmation(
                zone=zone,
                decision_index=i,
                entry_index=i + 1,
                decision_timestamp=row["timestamp"],
                confirmation=label,
            )
    return None


def bullish_to_dot_candle(
    row: pd.Series,
    prev: pd.Series,
    config: YouTubeToDotConfig,
) -> tuple[bool, str]:
    engulfing = (
        row["close"] > row["open"]
        and prev["close"] < prev["open"]
        and row["open"] < prev["close"]
        and row["close"] > prev["open"]
    )
    if engulfing:
        return True, "bullish_engulfing"

    candle_range = float(row["high"] - row["low"])
    body = float(row["close"] - row["open"])
    if candle_range <= 0 or body <= 0:
        return False, ""
    close_location = float((row["close"] - row["low"]) / candle_range)
    strong = (
        body >= config.base.confirmation_body_ratio * candle_range
        and close_location >= 1.0 - config.base.confirmation_close_extreme_pct
        and body >= config.huge_body_atr_multiple * float(row["atr"])
    )
    return bool(strong), "bullish_huge_candle" if strong else ""


def bearish_to_dot_candle(
    row: pd.Series,
    prev: pd.Series,
    config: YouTubeToDotConfig,
) -> tuple[bool, str]:
    engulfing = (
        row["close"] < row["open"]
        and prev["close"] > prev["open"]
        and row["open"] > prev["close"]
        and row["close"] < prev["open"]
    )
    if engulfing:
        return True, "bearish_engulfing"

    candle_range = float(row["high"] - row["low"])
    body = float(row["open"] - row["close"])
    if candle_range <= 0 or body <= 0:
        return False, ""
    close_location = float((row["close"] - row["low"]) / candle_range)
    strong = (
        body >= config.base.confirmation_body_ratio * candle_range
        and close_location <= config.base.confirmation_close_extreme_pct
        and body >= config.huge_body_atr_multiple * float(row["atr"])
    )
    return bool(strong), "bearish_huge_candle" if strong else ""


def build_to_dot_trade(
    ltf: pd.DataFrame,
    confirmation: ToDotConfirmation,
    config: YouTubeToDotConfig,
    swings: pd.DataFrame,
) -> dict[str, object] | None:
    zone = confirmation.zone
    entry_i = confirmation.entry_index
    if entry_i >= len(ltf):
        return None

    entry_price = float(ltf["open"].iloc[entry_i])
    atr_value = ltf["atr"].iloc[confirmation.decision_index]
    if pd.isna(atr_value) or atr_value <= 0:
        return None

    if zone.direction == "demand":
        side = 1
        last_swing = _last_swing(swings["swing_low"], confirmation.decision_index)
        stop_reference = min(zone.lower, last_swing) if last_swing is not None else zone.lower
        stop_price = stop_reference - config.base.stop_atr_buffer * float(atr_value)
        take_profit = _nearest_prior_target(
            swings["swing_high"], ltf, entry_i, entry_price, config.base.key_level_lookback, side
        )
    else:
        side = -1
        last_swing = _last_swing(swings["swing_high"], confirmation.decision_index)
        stop_reference = max(zone.upper, last_swing) if last_swing is not None else zone.upper
        stop_price = stop_reference + config.base.stop_atr_buffer * float(atr_value)
        take_profit = _nearest_prior_target(
            swings["swing_low"], ltf, entry_i, entry_price, config.base.key_level_lookback, side
        )

    risk = (entry_price - stop_price) if side > 0 else (stop_price - entry_price)
    if risk <= 0:
        zone.archived = True
        return None

    target_rule = "nearest_prior_swing"
    if take_profit is None:
        take_profit = entry_price + side * config.fixed_fallback_target_r * risk
        target_rule = "fallback_2p5r"

    reward = (float(take_profit) - entry_price) if side > 0 else (entry_price - float(take_profit))
    if reward <= 0:
        take_profit = entry_price + side * config.fixed_fallback_target_r * risk
        reward = config.fixed_fallback_target_r * risk
        target_rule = "fallback_2p5r_invalid_swing"

    outcome = simulate_to_dot_exit(
        ltf=ltf,
        entry_i=entry_i,
        side=side,
        entry_price=entry_price,
        stop_price=stop_price,
        take_profit=float(take_profit),
        risk=risk,
        config=config,
    )
    zone.traded = True
    zone.archived = True
    final_pnl_units = outcome["r_multiple"] * risk
    target_r = reward / risk
    return {
        "zone_id": zone.zone_id,
        "zone_direction": zone.direction,
        "decision_timestamp": confirmation.decision_timestamp,
        "entry_timestamp": ltf["timestamp"].iloc[entry_i],
        "exit_timestamp": outcome["exit_timestamp"],
        "side": side,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "take_profit": float(take_profit),
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
        "target_rule": target_rule,
        "target_r": target_r,
        "near_target_progress": outcome["near_target_progress"],
        "final_r_multiple": outcome["r_multiple"],
        "final_pnl_units": final_pnl_units,
        "held_hours": _held_hours(ltf, entry_i, int(outcome["exit_index"])),
    }


def simulate_to_dot_exit(
    *,
    ltf: pd.DataFrame,
    entry_i: int,
    side: int,
    entry_price: float,
    stop_price: float,
    take_profit: float,
    risk: float,
    config: YouTubeToDotConfig,
) -> dict[str, object]:
    planned_distance = abs(take_profit - entry_price)
    for i in range(entry_i, len(ltf)):
        row = ltf.iloc[i]
        close = float(row["close"])
        progress = ((close - entry_price) * side) / planned_distance if planned_distance > 0 else 0.0

        if side > 0:
            if close <= stop_price:
                return _exit_result(ltf, i, close, (close - entry_price) / risk, "close_stop", progress)
            if close >= take_profit:
                return _exit_result(ltf, i, close, (close - entry_price) / risk, "close_take_profit", progress)
            if progress >= config.near_target_progress and bearish_reversal(row, config):
                return _exit_result(ltf, i, close, (close - entry_price) / risk, "near_target_bearish_reversal", progress)
        else:
            if close >= stop_price:
                return _exit_result(ltf, i, close, (entry_price - close) / risk, "close_stop", progress)
            if close <= take_profit:
                return _exit_result(ltf, i, close, (entry_price - close) / risk, "close_take_profit", progress)
            if progress >= config.near_target_progress and bullish_reversal(row, config):
                return _exit_result(ltf, i, close, (entry_price - close) / risk, "near_target_bullish_reversal", progress)

    final_i = len(ltf) - 1
    close = float(ltf["close"].iloc[final_i])
    r = (close - entry_price) * side / risk
    return _exit_result(ltf, final_i, close, r, "end_of_data", 0.0)


def bullish_reversal(row: pd.Series, config: YouTubeToDotConfig) -> bool:
    candle_range = float(row["high"] - row["low"])
    if candle_range <= 0 or row["close"] <= row["open"]:
        return False
    body = float(row["close"] - row["open"])
    close_location = float((row["close"] - row["low"]) / candle_range)
    return body >= config.reversal_body_ratio * candle_range and close_location >= config.reversal_close_location


def bearish_reversal(row: pd.Series, config: YouTubeToDotConfig) -> bool:
    candle_range = float(row["high"] - row["low"])
    if candle_range <= 0 or row["close"] >= row["open"]:
        return False
    body = float(row["open"] - row["close"])
    close_location = float((row["close"] - row["low"]) / candle_range)
    return body >= config.reversal_body_ratio * candle_range and close_location <= 1.0 - config.reversal_close_location


def _exit_result(
    ltf: pd.DataFrame,
    exit_i: int,
    exit_price: float,
    r: float,
    reason: str,
    progress: float,
) -> dict[str, object]:
    return {
        "exit_index": exit_i,
        "exit_timestamp": ltf["timestamp"].iloc[exit_i],
        "exit_price": exit_price,
        "r_multiple": r,
        "exit_reason": reason,
        "near_target_progress": progress,
    }


def _zone_expiry_index(
    ltf: pd.DataFrame,
    start_i: int,
    created_timestamp: pd.Timestamp,
    config: YouTubeSupplyDemandConfig,
) -> int:
    if config.zone_expiry_hours is not None:
        expiry_timestamp = created_timestamp + pd.Timedelta(hours=float(config.zone_expiry_hours))
        return int(ltf["timestamp"].searchsorted(expiry_timestamp, side="right"))
    if config.zone_expiry_bars is not None:
        return start_i + int(config.zone_expiry_bars)
    return len(ltf)


def _held_hours(ltf: pd.DataFrame, entry_i: int, exit_i: int) -> float:
    return float((pd.Timestamp(ltf["timestamp"].iloc[exit_i]) - pd.Timestamp(ltf["timestamp"].iloc[entry_i])).total_seconds() / 3600.0)


__all__ = [
    "STRATEGY_ID",
    "YouTubeToDotConfig",
    "generate_youtube_to_dot_trades",
    "summarize_youtube_to_dot_trades",
]
