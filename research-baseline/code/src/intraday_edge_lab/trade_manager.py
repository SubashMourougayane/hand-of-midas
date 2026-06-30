from __future__ import annotations

import numpy as np
import pandas as pd

from .confirmation_engine import ConfirmationResult
from .zone_detector import YouTubeSupplyDemandConfig, confirmed_swings


def execute_trade(
    ltf: pd.DataFrame,
    confirmation: ConfirmationResult,
    config: YouTubeSupplyDemandConfig,
    swings: pd.DataFrame | None = None,
) -> dict[str, object] | None:
    zone = confirmation.zone
    entry_i = confirmation.entry_index
    if entry_i >= len(ltf):
        return None

    entry_price = float(ltf["open"].iloc[entry_i])
    atr_value = ltf["atr"].iloc[confirmation.decision_index]
    if pd.isna(atr_value) or atr_value <= 0:
        return None

    if swings is None:
        swings = confirmed_swings(ltf, config.swing_left, config.swing_right)
    if zone.direction == "demand":
        side = 1
        last_swing = _last_swing(swings["swing_low"], confirmation.decision_index)
        stop_reference = min(zone.lower, last_swing) if last_swing is not None else zone.lower
        stop_price = stop_reference - config.stop_atr_buffer * float(atr_value)
        take_profit = _nearest_prior_target(
            swings["swing_high"],
            ltf,
            entry_i,
            entry_price,
            config.key_level_lookback,
            side,
        )
    else:
        side = -1
        last_swing = _last_swing(swings["swing_high"], confirmation.decision_index)
        stop_reference = max(zone.upper, last_swing) if last_swing is not None else zone.upper
        stop_price = stop_reference + config.stop_atr_buffer * float(atr_value)
        take_profit = _nearest_prior_target(
            swings["swing_low"],
            ltf,
            entry_i,
            entry_price,
            config.key_level_lookback,
            side,
        )

    if take_profit is None:
        zone.archived = True
        return None

    risk = (entry_price - stop_price) if side > 0 else (stop_price - entry_price)
    reward = (take_profit - entry_price) if side > 0 else (entry_price - take_profit)
    if risk <= 0 or reward <= 0:
        zone.archived = True
        return None
    if reward / risk < config.min_target_r:
        zone.archived = True
        return None

    outcome = _simulate_bracket(ltf, entry_i, side, stop_price, take_profit, config)
    zone.traded = True
    zone.archived = True
    pnl_units = (outcome["exit_price"] - entry_price) * side
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
        "pnl_units": pnl_units,
        "r_multiple": pnl_units / risk,
        "confirmation": confirmation.confirmation,
        "zone_upper": zone.upper,
        "zone_lower": zone.lower,
        "zone_created_timestamp": zone.created_timestamp,
        "zone_retested": zone.retested,
        "zone_traded": zone.traded,
    }


def empty_trades() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "zone_id",
            "zone_direction",
            "decision_timestamp",
            "entry_timestamp",
            "exit_timestamp",
            "side",
            "entry_price",
            "stop_price",
            "take_profit",
            "exit_price",
            "exit_reason",
            "risk_units",
            "pnl_units",
            "r_multiple",
            "confirmation",
            "zone_upper",
            "zone_lower",
            "zone_created_timestamp",
            "zone_retested",
            "zone_traded",
        ]
    )


def summarize_trades(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_r": 0.0}
    wins = trades.loc[trades["pnl_units"] > 0, "pnl_units"]
    losses = -trades.loc[trades["pnl_units"] < 0, "pnl_units"]
    gross_win = float(wins.sum())
    gross_loss = float(losses.sum())
    profit_factor = np.inf if gross_loss == 0 and gross_win > 0 else (gross_win / gross_loss if gross_loss else 0.0)
    return {
        "trades": int(len(trades)),
        "win_rate": float((trades["pnl_units"] > 0).mean()),
        "profit_factor": float(profit_factor),
        "expectancy_r": float(trades["r_multiple"].mean()),
    }


def _last_swing(series: pd.Series, before_i: int) -> float | None:
    prior = series.iloc[: before_i + 1].dropna()
    if prior.empty:
        return None
    return float(prior.iloc[-1])


def _nearest_prior_target(
    series: pd.Series,
    ltf: pd.DataFrame,
    entry_i: int,
    entry_price: float,
    lookback: int,
    side: int,
) -> float | None:
    start_i = max(0, entry_i - lookback)
    candidates = series.iloc[start_i:entry_i].dropna().astype(float)
    if side > 0:
        candidates = candidates[candidates > entry_price]
        if candidates.empty:
            return None
        return float(candidates.min())

    candidates = candidates[candidates < entry_price]
    if candidates.empty:
        return None
    return float(candidates.max())


def _simulate_bracket(
    ltf: pd.DataFrame,
    entry_i: int,
    side: int,
    stop_price: float,
    take_profit: float,
    config: YouTubeSupplyDemandConfig,
) -> dict[str, object]:
    if config.close_based_exits:
        return _simulate_close_based_bracket(ltf, entry_i, side, stop_price, take_profit, config)

    for i in range(entry_i, len(ltf)):
        row = ltf.iloc[i]
        if side > 0:
            stop_hit = row["low"] <= stop_price
            target_hit = row["high"] >= take_profit
            if stop_hit and target_hit:
                exit_price = stop_price if config.conservative_intrabar else take_profit
                return {"exit_timestamp": row["timestamp"], "exit_price": exit_price, "exit_reason": "ambiguous_stop_first"}
            if stop_hit:
                return {"exit_timestamp": row["timestamp"], "exit_price": stop_price, "exit_reason": "stop"}
            if target_hit:
                return {"exit_timestamp": row["timestamp"], "exit_price": take_profit, "exit_reason": "take_profit"}
        else:
            stop_hit = row["high"] >= stop_price
            target_hit = row["low"] <= take_profit
            if stop_hit and target_hit:
                exit_price = stop_price if config.conservative_intrabar else take_profit
                return {"exit_timestamp": row["timestamp"], "exit_price": exit_price, "exit_reason": "ambiguous_stop_first"}
            if stop_hit:
                return {"exit_timestamp": row["timestamp"], "exit_price": stop_price, "exit_reason": "stop"}
            if target_hit:
                return {"exit_timestamp": row["timestamp"], "exit_price": take_profit, "exit_reason": "take_profit"}

    final = ltf.iloc[-1]
    return {"exit_timestamp": final["timestamp"], "exit_price": float(final["close"]), "exit_reason": "end_of_data"}


def _simulate_close_based_bracket(
    ltf: pd.DataFrame,
    entry_i: int,
    side: int,
    stop_price: float,
    take_profit: float,
    config: YouTubeSupplyDemandConfig,
) -> dict[str, object]:
    for i in range(entry_i, len(ltf)):
        row = ltf.iloc[i]
        close = float(row["close"])
        if side > 0:
            if close <= stop_price:
                exit_price = stop_price if config.close_fill_at_level else close
                return {"exit_timestamp": row["timestamp"], "exit_price": exit_price, "exit_reason": "close_stop"}
            if close >= take_profit:
                exit_price = take_profit if config.close_fill_at_level else close
                return {"exit_timestamp": row["timestamp"], "exit_price": exit_price, "exit_reason": "close_take_profit"}
        else:
            if close >= stop_price:
                exit_price = stop_price if config.close_fill_at_level else close
                return {"exit_timestamp": row["timestamp"], "exit_price": exit_price, "exit_reason": "close_stop"}
            if close <= take_profit:
                exit_price = take_profit if config.close_fill_at_level else close
                return {"exit_timestamp": row["timestamp"], "exit_price": exit_price, "exit_reason": "close_take_profit"}

    final = ltf.iloc[-1]
    return {"exit_timestamp": final["timestamp"], "exit_price": float(final["close"]), "exit_reason": "end_of_data"}
