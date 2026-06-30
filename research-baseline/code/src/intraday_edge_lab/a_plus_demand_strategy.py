from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .causality import prepare_intraday_frame, validate_market_data
from .confirmation_engine import add_confirmation_features
from .supply_demand_ema_retest import _remove_pyramids
from .trade_manager import _last_swing, _nearest_prior_target, empty_trades, summarize_trades
from .zone_detector import YouTubeSupplyDemandConfig, atr, confirmed_swings, resample_ohlcv


STRATEGY_ID = "A_PLUS_DEMAND_FVG_DISCOUNT_NKMZAQQPFBW_V1"


@dataclass(frozen=True)
class APlusDemandConfig:
    ltf_rule: str = "15min"
    trail_rule: str = "5min"
    htf_rule: str = "1h"
    htf_atr_length: int = 14
    ltf_atr_length: int = 14
    ema_length: int = 8
    min_impulse_candles: int = 3
    max_impulse_candles: int = 5
    impulse_total_atr_multiple: float = 2.0
    body_zone_small_body_pct: float = 0.35
    fvg_required: bool = True
    discount_max_zone_top_pct: float = 0.50
    bos_lookback: int = 30
    ema_separation_atr: float = 0.25
    ema_chop_lookback: int = 8
    ema_min_closes_above: int = 6
    zone_expiry_hours: float = 72.0
    confirmation_max_wait_hours: float = 24.0
    pullback_min_bars: int = 3
    pullback_max_bear_body_atr: float = 1.20
    stop_atr_buffer: float = 0.10
    min_target_r: float = 1.50
    key_level_lookback: int = 100
    exit_mode: str = "fixed_target"
    trail_atr_length: int = 14
    trail_atr_multiple: float = 2.0
    confirmation_min_body_pct: float = 0.50
    confirmation_min_close_location: float = 0.65
    remove_pyramids: bool = True


@dataclass
class APlusDemandZone:
    zone_id: int
    upper: float
    lower: float
    created_bar: int
    created_timestamp: pd.Timestamp
    base_timestamp: pd.Timestamp
    impulse_start_timestamp: pd.Timestamp
    impulse_end_timestamp: pd.Timestamp
    swing_low: float
    swing_high: float
    fvg_upper: float
    fvg_lower: float
    zone_rule: str
    retested: bool = False
    traded: bool = False
    archived: bool = False


@dataclass(frozen=True)
class APlusConfirmation:
    zone: APlusDemandZone
    retest_index: int
    decision_index: int
    entry_index: int
    decision_timestamp: pd.Timestamp
    confirmation: str


def generate_a_plus_demand_trades(
    raw: pd.DataFrame,
    config: APlusDemandConfig = APlusDemandConfig(),
) -> pd.DataFrame:
    frame = prepare_intraday_frame(raw)
    validate_market_data(frame)
    ltf = resample_ohlcv(frame, config.ltf_rule).reset_index(drop=True)
    trail = resample_ohlcv(frame, config.trail_rule).reset_index(drop=True)
    if len(ltf) < max(config.ltf_atr_length, config.ema_length) + 2:
        return empty_a_plus_trades()

    base_config = YouTubeSupplyDemandConfig(
        ltf_rule=config.ltf_rule,
        htf_rule=config.htf_rule,
        htf_atr_length=config.htf_atr_length,
        ltf_atr_length=config.ltf_atr_length,
        ema_length=config.ema_length,
        zone_expiry_bars=None,
        zone_expiry_hours=config.zone_expiry_hours,
    )
    ltf = add_confirmation_features(ltf, base_config)
    htf = resample_ohlcv(ltf, config.htf_rule).reset_index(drop=True)
    htf["atr"] = atr(htf, config.htf_atr_length)
    trail["atr"] = atr(trail, config.trail_atr_length)
    swings = confirmed_swings(ltf, 2, 2)
    zones = detect_a_plus_demand_zones(htf, config)

    candidates: list[dict[str, object]] = []
    for zone in zones:
        confirmation = find_a_plus_confirmation(ltf, zone, config)
        if confirmation is None:
            continue
        trade = build_a_plus_trade(ltf, trail, confirmation, config, swings)
        if trade is not None:
            candidates.append(trade)

    if not candidates:
        return empty_a_plus_trades()
    trades = pd.DataFrame(candidates).sort_values(["entry_timestamp", "zone_id"]).reset_index(drop=True)
    if config.remove_pyramids:
        trades = _remove_pyramids(trades)
    return trades.reset_index(drop=True)


def empty_a_plus_trades() -> pd.DataFrame:
    base = empty_trades()
    for col in [
        "fvg_upper",
        "fvg_lower",
        "discount_position",
        "target_r",
        "zone_rule",
        "entry_rule",
        "exit_mode",
        "final_r_multiple",
        "final_pnl_units",
        "held_hours",
    ]:
        base[col] = pd.Series(dtype="float64")
    return base


def detect_a_plus_demand_zones(htf: pd.DataFrame, config: APlusDemandConfig) -> list[APlusDemandZone]:
    zones: list[APlusDemandZone] = []
    offset = pd.tseries.frequencies.to_offset(config.htf_rule)
    open_ = htf["open"].astype(float)
    high = htf["high"].astype(float)
    low = htf["low"].astype(float)
    close = htf["close"].astype(float)

    previous_end = -1
    for end_i in range(config.htf_atr_length, len(htf)):
        atr_value = float(htf["atr"].iloc[end_i])
        if not np.isfinite(atr_value) or atr_value <= 0:
            continue
        start_i = end_i
        while start_i >= 0 and close.iloc[start_i] > open_.iloc[start_i]:
            start_i -= 1
        start_i += 1
        candles = end_i - start_i + 1
        if candles < config.min_impulse_candles or candles > config.max_impulse_candles:
            continue
        if end_i == previous_end or start_i <= 0:
            continue
        total_move = float(close.iloc[end_i] - open_.iloc[start_i])
        if total_move < config.impulse_total_atr_multiple * atr_value:
            continue
        if config.fvg_required and not bullish_fvg(htf, start_i):
            continue
        prior_high = float(high.iloc[max(0, start_i - config.bos_lookback) : start_i].max())
        if not np.isfinite(prior_high) or float(high.iloc[start_i : end_i + 1].max()) <= prior_high:
            continue

        base_i = start_i - 1
        body_low = min(float(open_.iloc[base_i]), float(close.iloc[base_i]))
        body_high = max(float(open_.iloc[base_i]), float(close.iloc[base_i]))
        candle_range = float(high.iloc[base_i] - low.iloc[base_i])
        body = body_high - body_low
        if candle_range <= 0:
            continue
        if body / candle_range <= config.body_zone_small_body_pct:
            lower = float(low.iloc[base_i])
            upper = float(high.iloc[base_i])
            zone_rule = "small_base_wick_to_wick"
        else:
            lower = body_low
            upper = body_high
            zone_rule = "body_close_zone"

        swing_low = float(low.iloc[start_i : end_i + 1].min())
        swing_high = float(high.iloc[start_i : end_i + 1].max())
        if swing_high <= swing_low:
            continue
        discount_position = (upper - swing_low) / (swing_high - swing_low)
        if discount_position > config.discount_max_zone_top_pct:
            continue

        zones.append(
            APlusDemandZone(
                zone_id=len(zones) + 1,
                upper=upper,
                lower=lower,
                created_bar=end_i,
                created_timestamp=htf["timestamp"].iloc[end_i] + offset,
                base_timestamp=htf["timestamp"].iloc[base_i],
                impulse_start_timestamp=htf["timestamp"].iloc[start_i],
                impulse_end_timestamp=htf["timestamp"].iloc[end_i],
                swing_low=swing_low,
                swing_high=swing_high,
                fvg_upper=float(low.iloc[start_i + 2]),
                fvg_lower=float(high.iloc[start_i]),
                zone_rule=zone_rule,
            )
        )
        previous_end = end_i
    return zones


def bullish_fvg(htf: pd.DataFrame, start_i: int) -> bool:
    if start_i + 2 >= len(htf):
        return False
    candle1_high = float(htf["high"].iloc[start_i])
    candle3_low = float(htf["low"].iloc[start_i + 2])
    return candle3_low > candle1_high


def find_a_plus_confirmation(
    ltf: pd.DataFrame,
    zone: APlusDemandZone,
    config: APlusDemandConfig,
) -> APlusConfirmation | None:
    start_i = int(ltf["timestamp"].searchsorted(zone.created_timestamp, side="left"))
    expiry_ts = zone.created_timestamp + pd.Timedelta(hours=config.zone_expiry_hours)
    expiry_i = min(len(ltf), int(ltf["timestamp"].searchsorted(expiry_ts, side="left")))
    retest_i: int | None = None
    for i in range(start_i, expiry_i):
        row = ltf.iloc[i]
        if float(row["close"]) < zone.lower:
            zone.archived = True
            return None
        if float(row["high"]) >= zone.lower and float(row["low"]) <= zone.upper:
            if not slow_pullback_ok(ltf, start_i, i, config):
                zone.archived = True
                return None
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
    for i in range(retest_i, confirm_cutoff):
        row = ltf.iloc[i]
        if float(row["close"]) < zone.lower:
            zone.archived = True
            return None
        if not ema_structure_ok(ltf, i, config):
            continue
        ok, label = bullish_trigger(row, config)
        if ok:
            return APlusConfirmation(zone, retest_i, i, i + 1, row["timestamp"], label)
    return None


def slow_pullback_ok(ltf: pd.DataFrame, start_i: int, retest_i: int, config: APlusDemandConfig) -> bool:
    if retest_i - start_i + 1 < config.pullback_min_bars:
        return False
    window = ltf.iloc[start_i : retest_i + 1]
    atr_values = window["atr"].astype(float)
    bearish_body = (window["open"] - window["close"]).astype(float)
    massive_bear = (window["close"] < window["open"]) & (bearish_body >= config.pullback_max_bear_body_atr * atr_values)
    return not bool(massive_bear.any())


def ema_structure_ok(ltf: pd.DataFrame, i: int, config: APlusDemandConfig) -> bool:
    if i + 1 < config.ema_chop_lookback:
        return False
    row = ltf.iloc[i]
    if pd.isna(row["ema"]) or pd.isna(row["atr"]):
        return False
    if float(row["close"] - row["ema"]) < config.ema_separation_atr * float(row["atr"]):
        return False
    window = ltf.iloc[i - config.ema_chop_lookback + 1 : i + 1]
    closes_above = (window["close"] > window["ema"]).sum()
    return int(closes_above) >= config.ema_min_closes_above


def bullish_trigger(row: pd.Series, config: APlusDemandConfig = APlusDemandConfig()) -> tuple[bool, str]:
    if float(row["close"]) <= float(row["open"]):
        return False, ""
    candle_range = float(row["high"] - row["low"])
    if candle_range <= 0:
        return False, ""
    body = float(row["close"] - row["open"])
    close_location = float((row["close"] - row["low"]) / candle_range)
    if body / candle_range >= config.confirmation_min_body_pct and close_location >= config.confirmation_min_close_location:
        return True, "bullish_confirmation_close"
    return False, ""


def build_a_plus_trade(
    ltf: pd.DataFrame,
    trail: pd.DataFrame,
    confirmation: APlusConfirmation,
    config: APlusDemandConfig,
    swings: pd.DataFrame,
) -> dict[str, object] | None:
    zone = confirmation.zone
    decision_i = confirmation.decision_index
    if confirmation.entry_index >= len(ltf):
        return None
    decision = ltf.iloc[decision_i]
    entry_price = float(decision["close"])
    atr_value = float(decision["atr"])
    last_swing = _last_swing(swings["swing_low"], decision_i)
    swing_stop = min(zone.lower, last_swing) if last_swing is not None else zone.lower
    ema_stop = float(decision["ema"]) if pd.notna(decision["ema"]) else swing_stop
    stop_price = min(swing_stop, ema_stop) - config.stop_atr_buffer * atr_value
    risk = entry_price - stop_price
    if risk <= 0:
        return None

    take_profit = _nearest_prior_target(swings["swing_high"], ltf, decision_i, entry_price, config.key_level_lookback, 1)
    target_rule = "nearest_structural_swing_high"
    if take_profit is None or float(take_profit) <= entry_price or (float(take_profit) - entry_price) / risk < config.min_target_r:
        take_profit = entry_price + config.min_target_r * risk
        target_rule = "fixed_min_1p5r"
    reward = float(take_profit) - entry_price

    if config.exit_mode == "m5_trailing":
        outcome = simulate_m5_trailing_exit(ltf, trail, confirmation.entry_index, entry_price, stop_price, risk, config)
    else:
        outcome = simulate_fixed_exit(ltf, confirmation.entry_index, entry_price, stop_price, float(take_profit), risk)

    zone.traded = True
    zone.archived = True
    final_pnl_units = outcome["r_multiple"] * risk
    return {
        "zone_id": zone.zone_id,
        "zone_direction": "demand",
        "decision_timestamp": confirmation.decision_timestamp,
        "entry_timestamp": pd.Timestamp(decision["timestamp"]) + pd.tseries.frequencies.to_offset(config.ltf_rule),
        "exit_timestamp": outcome["exit_timestamp"],
        "side": 1,
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
        "fvg_upper": zone.fvg_upper,
        "fvg_lower": zone.fvg_lower,
        "discount_position": (zone.upper - zone.swing_low) / (zone.swing_high - zone.swing_low),
        "target_r": reward / risk,
        "zone_rule": zone.zone_rule,
        "target_rule": target_rule,
        "entry_rule": "m15_green_confirmation_close_after_first_zone_tap",
        "exit_mode": config.exit_mode,
        "final_r_multiple": outcome["r_multiple"],
        "final_pnl_units": final_pnl_units,
        "held_hours": held_hours(pd.Timestamp(decision["timestamp"]) + pd.tseries.frequencies.to_offset(config.ltf_rule), outcome["exit_timestamp"]),
    }


def simulate_fixed_exit(
    ltf: pd.DataFrame,
    entry_i: int,
    entry_price: float,
    stop_price: float,
    take_profit: float,
    risk: float,
) -> dict[str, object]:
    for i in range(entry_i, len(ltf)):
        close = float(ltf["close"].iloc[i])
        if close <= stop_price:
            return exit_result(ltf["timestamp"].iloc[i], close, (close - entry_price) / risk, "close_stop")
        if close >= take_profit:
            return exit_result(ltf["timestamp"].iloc[i], close, (close - entry_price) / risk, "close_take_profit")
    close = float(ltf["close"].iloc[-1])
    return exit_result(ltf["timestamp"].iloc[-1], close, (close - entry_price) / risk, "end_of_data")


def simulate_m5_trailing_exit(
    ltf: pd.DataFrame,
    trail: pd.DataFrame,
    entry_i: int,
    entry_price: float,
    stop_price: float,
    risk: float,
    config: APlusDemandConfig,
) -> dict[str, object]:
    entry_ts = pd.Timestamp(ltf["timestamp"].iloc[entry_i - 1]) + pd.tseries.frequencies.to_offset(config.ltf_rule)
    start_i = int(trail["timestamp"].searchsorted(entry_ts, side="left"))
    active = False
    highest = entry_price
    trail_stop = stop_price
    for i in range(start_i, len(trail)):
        row = trail.iloc[i]
        close = float(row["close"])
        if close <= stop_price:
            return exit_result(row["timestamp"], close, (close - entry_price) / risk, "m5_initial_stop")
        if close > entry_price:
            active = True
        if active and pd.notna(row["atr"]):
            highest = max(highest, float(row["high"]))
            trail_stop = max(trail_stop, highest - config.trail_atr_multiple * float(row["atr"]))
            if close < trail_stop:
                return exit_result(row["timestamp"], close, (close - entry_price) / risk, "m5_trailing_close")
    close = float(trail["close"].iloc[-1])
    return exit_result(trail["timestamp"].iloc[-1], close, (close - entry_price) / risk, "end_of_data")


def exit_result(timestamp: pd.Timestamp, exit_price: float, r: float, reason: str) -> dict[str, object]:
    return {
        "exit_timestamp": timestamp,
        "exit_price": exit_price,
        "r_multiple": r,
        "exit_reason": reason,
    }


def held_hours(start: pd.Timestamp, end: pd.Timestamp) -> float:
    return float((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() / 3600.0)


def summarize_a_plus_trades(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_r": 0.0}
    normalized = trades.copy()
    normalized["pnl_units"] = normalized["final_pnl_units"]
    normalized["r_multiple"] = normalized["final_r_multiple"]
    return summarize_trades(normalized)


__all__ = [
    "STRATEGY_ID",
    "APlusDemandConfig",
    "bullish_fvg",
    "detect_a_plus_demand_zones",
    "generate_a_plus_demand_trades",
    "summarize_a_plus_trades",
]
