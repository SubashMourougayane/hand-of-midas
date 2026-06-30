from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .causality import prepare_intraday_frame, validate_market_data
from .confirmation_engine import add_confirmation_features, find_confirmation
from .retest_engine import find_retest
from .supply_demand_ema_retest import _remove_pyramids
from .trade_manager import _last_swing, _nearest_prior_target, empty_trades, summarize_trades
from .zone_detector import YouTubeSupplyDemandConfig, confirmed_swings, detect_zones, resample_ohlcv


@dataclass(frozen=True)
class SupplyDemandConceptConfig:
    """Demand-only concept strategy promoted after the direction OOS pass."""

    base: YouTubeSupplyDemandConfig = field(
        default_factory=lambda: YouTubeSupplyDemandConfig(
            confirmation_mode="engulfing",
            zone_expiry_bars=None,
            zone_expiry_hours=48.0,
            enforce_h1_trend=False,
            max_impulse_pullback_pct=0.50,
            min_target_r=0.0,
            close_based_exits=True,
            close_fill_at_level=False,
        )
    )
    t1_fraction: float = 0.50
    runner_max_hold_hours: float = 24.0
    runner_stop: str = "breakeven_after_t1"
    runner_target_r: float | None = None
    fill_at_level: bool = False
    remove_pyramids: bool = True
    allowed_directions: tuple[str, ...] = ("demand",)


def generate_supply_demand_concept_trades(
    raw: pd.DataFrame,
    config: SupplyDemandConceptConfig = SupplyDemandConceptConfig(),
) -> pd.DataFrame:
    frame = prepare_intraday_frame(raw)
    validate_market_data(frame)
    ltf = resample_ohlcv(frame, config.base.ltf_rule).reset_index(drop=True)
    if len(ltf) < max(config.base.ltf_atr_length, config.base.ema_length) + 2:
        return empty_concept_trades()

    ltf["_timestamp_ns"] = pd.to_datetime(ltf["timestamp"], utc=True).array.asi8
    ltf = add_confirmation_features(ltf, config.base)
    zones = detect_zones(ltf, config.base)
    swings = confirmed_swings(ltf, config.base.swing_left, config.base.swing_right)
    candidates: list[dict[str, object]] = []

    for zone in zones:
        retest = find_retest(ltf, zone, config.base)
        if retest is None:
            continue
        confirmation = find_confirmation(ltf, zone, retest.retest_index, config.base)
        if confirmation is None:
            continue
        trade = _build_concept_trade(ltf, confirmation, config, swings)
        if trade is not None:
            candidates.append(trade)

    if not candidates:
        return empty_concept_trades()

    trades = pd.DataFrame(candidates).sort_values(["entry_timestamp", "zone_id"]).reset_index(drop=True)
    if config.remove_pyramids:
        trades = _remove_pyramids(trades)
    trades = trades[trades["zone_direction"].isin(config.allowed_directions)]
    return trades.reset_index(drop=True)


def empty_concept_trades() -> pd.DataFrame:
    base = empty_trades()
    for column in [
        "t1_price",
        "t1_fraction",
        "t1_timestamp",
        "t1_r",
        "runner_fraction",
        "runner_stop_price",
        "runner_exit_timestamp",
        "runner_exit_price",
        "runner_r",
        "runner_exit_reason",
        "final_r_multiple",
        "final_pnl_units",
        "held_hours",
    ]:
        base[column] = pd.Series(dtype="float64")
    return base


def summarize_concept_trades(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_r": 0.0}
    normalized = trades.copy()
    normalized["pnl_units"] = normalized["final_pnl_units"]
    normalized["r_multiple"] = normalized["final_r_multiple"]
    return summarize_trades(normalized)


def _build_concept_trade(
    ltf: pd.DataFrame,
    confirmation,
    config: SupplyDemandConceptConfig,
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
        t1_price = _nearest_prior_target(
            swings["swing_high"], ltf, entry_i, entry_price, config.base.key_level_lookback, side
        )
    else:
        side = -1
        last_swing = _last_swing(swings["swing_high"], confirmation.decision_index)
        stop_reference = max(zone.upper, last_swing) if last_swing is not None else zone.upper
        stop_price = stop_reference + config.base.stop_atr_buffer * float(atr_value)
        t1_price = _nearest_prior_target(
            swings["swing_low"], ltf, entry_i, entry_price, config.base.key_level_lookback, side
        )

    if t1_price is None:
        zone.archived = True
        return None

    risk = (entry_price - stop_price) if side > 0 else (stop_price - entry_price)
    reward = (t1_price - entry_price) if side > 0 else (entry_price - t1_price)
    if risk <= 0 or reward <= 0:
        zone.archived = True
        return None
    if reward / risk < config.base.min_target_r:
        zone.archived = True
        return None

    outcome = _simulate_partial_runner(
        ltf=ltf,
        entry_i=entry_i,
        side=side,
        entry_price=entry_price,
        stop_price=stop_price,
        t1_price=float(t1_price),
        risk=risk,
        config=config,
    )
    zone.traded = True
    zone.archived = True
    final_pnl_units = outcome["final_r_multiple"] * risk
    return {
        "zone_id": zone.zone_id,
        "zone_direction": zone.direction,
        "decision_timestamp": confirmation.decision_timestamp,
        "entry_timestamp": ltf["timestamp"].iloc[entry_i],
        "exit_timestamp": outcome["final_exit_timestamp"],
        "side": side,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "take_profit": float(t1_price),
        "exit_price": outcome["final_exit_price"],
        "exit_reason": outcome["final_exit_reason"],
        "risk_units": risk,
        "pnl_units": final_pnl_units,
        "r_multiple": outcome["final_r_multiple"],
        "confirmation": confirmation.confirmation,
        "zone_upper": zone.upper,
        "zone_lower": zone.lower,
        "zone_created_timestamp": zone.created_timestamp,
        "zone_retested": zone.retested,
        "zone_traded": zone.traded,
        "t1_price": float(t1_price),
        "t1_fraction": config.t1_fraction,
        "t1_timestamp": outcome["t1_timestamp"],
        "t1_r": outcome["t1_r"],
        "runner_fraction": 1.0 - config.t1_fraction,
        "runner_stop_price": entry_price,
        "runner_exit_timestamp": outcome["runner_exit_timestamp"],
        "runner_exit_price": outcome["runner_exit_price"],
        "runner_r": outcome["runner_r"],
        "runner_exit_reason": outcome["runner_exit_reason"],
        "final_r_multiple": outcome["final_r_multiple"],
        "final_pnl_units": final_pnl_units,
        "held_hours": outcome["held_hours"],
    }


def _simulate_partial_runner(
    *,
    ltf: pd.DataFrame,
    entry_i: int,
    side: int,
    entry_price: float,
    stop_price: float,
    t1_price: float,
    risk: float,
    config: SupplyDemandConceptConfig,
) -> dict[str, object]:
    max_i = _max_exit_index_by_time(ltf, entry_i, config.runner_max_hold_hours)
    t1_fraction = config.t1_fraction
    runner_fraction = 1.0 - t1_fraction

    for i in range(entry_i, max_i + 1):
        close = float(ltf["close"].iloc[i])
        if _stop_hit(close, side, stop_price):
            stop_r = _r_multiple(stop_price if config.fill_at_level else close, entry_price, side, risk)
            return _single_leg_result(ltf, entry_i, i, stop_price if config.fill_at_level else close, stop_r, "pre_t1_stop")
        if _target_hit(close, side, t1_price):
            t1_fill = t1_price if config.fill_at_level else close
            t1_r = _r_multiple(t1_fill, entry_price, side, risk)
            runner = _simulate_runner(ltf, i, max_i, side, entry_price, risk, config)
            final_r = t1_fraction * t1_r + runner_fraction * float(runner["runner_r"])
            return {
                "final_r_multiple": final_r,
                "final_pnl_units": final_r * risk,
                "final_exit_timestamp": runner["runner_exit_timestamp"],
                "final_exit_price": runner["runner_exit_price"],
                "final_exit_reason": runner["runner_exit_reason"],
                "t1_timestamp": ltf["timestamp"].iloc[i],
                "t1_r": t1_r,
                **runner,
                "held_hours": _held_hours(ltf, entry_i, int(runner["runner_exit_index"])),
            }

    close = float(ltf["close"].iloc[max_i])
    r = _r_multiple(close, entry_price, side, risk)
    return _single_leg_result(ltf, entry_i, max_i, close, r, "pre_t1_time_stop")


def _simulate_runner(
    ltf: pd.DataFrame,
    t1_i: int,
    max_i: int,
    side: int,
    entry_price: float,
    risk: float,
    config: SupplyDemandConceptConfig,
) -> dict[str, object]:
    start_i = min(max_i, t1_i + 1)
    target_price = None if config.runner_target_r is None else entry_price + side * config.runner_target_r * risk

    for i in range(start_i, max_i + 1):
        close = float(ltf["close"].iloc[i])
        if target_price is not None and _target_hit(close, side, target_price):
            fill = target_price if config.fill_at_level else close
            return _runner_result(ltf, i, fill, _r_multiple(fill, entry_price, side, risk), "runner_target")
        if _breakeven_hit(close, side, entry_price):
            fill = entry_price if config.fill_at_level else close
            return _runner_result(ltf, i, fill, _r_multiple(fill, entry_price, side, risk), "runner_breakeven")

    close = float(ltf["close"].iloc[max_i])
    return _runner_result(ltf, max_i, close, _r_multiple(close, entry_price, side, risk), "runner_time_stop")


def _single_leg_result(
    ltf: pd.DataFrame,
    entry_i: int,
    exit_i: int,
    exit_price: float,
    r: float,
    reason: str,
) -> dict[str, object]:
    return {
        "final_r_multiple": r,
        "final_pnl_units": np.nan,
        "final_exit_timestamp": ltf["timestamp"].iloc[exit_i],
        "final_exit_price": exit_price,
        "final_exit_reason": reason,
        "t1_timestamp": pd.NaT,
        "t1_r": np.nan,
        "runner_exit_index": exit_i,
        "runner_exit_timestamp": ltf["timestamp"].iloc[exit_i],
        "runner_exit_price": exit_price,
        "runner_r": r,
        "runner_exit_reason": reason,
        "held_hours": _held_hours(ltf, entry_i, exit_i),
    }


def _runner_result(
    ltf: pd.DataFrame,
    exit_i: int,
    exit_price: float,
    r: float,
    reason: str,
) -> dict[str, object]:
    return {
        "runner_exit_index": exit_i,
        "runner_exit_timestamp": ltf["timestamp"].iloc[exit_i],
        "runner_exit_price": exit_price,
        "runner_r": r,
        "runner_exit_reason": reason,
    }


def _max_exit_index_by_time(ltf: pd.DataFrame, entry_i: int, max_hold_hours: float) -> int:
    cutoff = pd.Timestamp(ltf["timestamp"].iloc[entry_i]) + pd.Timedelta(hours=max_hold_hours)
    if "_timestamp_ns" in ltf.columns:
        ns = ltf["_timestamp_ns"].to_numpy(dtype=np.int64)
    else:
        ns = pd.to_datetime(ltf["timestamp"], utc=True).array.asi8
    cutoff_value = cutoff.value
    while len(ns) and ns[entry_i] and abs(cutoff_value) > abs(ns[entry_i]) * 10:
        cutoff_value //= 1000
    exit_i = int(np.searchsorted(ns, cutoff_value, side="right") - 1)
    return max(entry_i, min(len(ltf) - 1, exit_i))


def _held_hours(ltf: pd.DataFrame, entry_i: int, exit_i: int) -> float:
    return float((pd.Timestamp(ltf["timestamp"].iloc[exit_i]) - pd.Timestamp(ltf["timestamp"].iloc[entry_i])).total_seconds() / 3600.0)


def _stop_hit(close: float, side: int, stop: float) -> bool:
    return close <= stop if side > 0 else close >= stop


def _target_hit(close: float, side: int, target: float) -> bool:
    return close >= target if side > 0 else close <= target


def _breakeven_hit(close: float, side: int, entry: float) -> bool:
    return close <= entry if side > 0 else close >= entry


def _r_multiple(fill: float, entry: float, side: int, risk: float) -> float:
    return (fill - entry) * side / risk


__all__ = [
    "SupplyDemandConceptConfig",
    "generate_supply_demand_concept_trades",
    "summarize_concept_trades",
]
