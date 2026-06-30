from __future__ import annotations

import pandas as pd

from .causality import prepare_intraday_frame, validate_market_data
from .confirmation_engine import add_confirmation_features, find_confirmation
from .retest_engine import find_retest
from .trade_manager import empty_trades, execute_trade, summarize_trades
from .zone_detector import YouTubeSupplyDemandConfig, Zone, confirmed_swings, detect_zones, resample_ohlcv


SupplyDemandEmaRetestConfig = YouTubeSupplyDemandConfig
SupplyDemandZone = Zone
detect_supply_demand_zones = detect_zones


def generate_supply_demand_ema_retest_trades(
    raw: pd.DataFrame,
    config: SupplyDemandEmaRetestConfig = SupplyDemandEmaRetestConfig(),
) -> pd.DataFrame:
    frame = prepare_intraday_frame(raw)
    validate_market_data(frame)
    ltf = resample_ohlcv(frame, config.ltf_rule)
    if len(ltf) < max(config.ltf_atr_length, config.ema_length) + 2:
        return empty_trades()

    ltf = add_confirmation_features(ltf, config)
    zones = detect_zones(ltf, config)
    swings = confirmed_swings(ltf, config.swing_left, config.swing_right)
    candidates: list[dict[str, object]] = []

    for zone in zones:
        retest = find_retest(ltf, zone, config)
        if retest is None:
            continue
        confirmation = find_confirmation(ltf, zone, retest.retest_index, config)
        if confirmation is None:
            continue
        trade = execute_trade(ltf, confirmation, config, swings)
        if trade is not None:
            candidates.append(trade)

    if not candidates:
        return empty_trades()

    trades = pd.DataFrame(candidates).sort_values(["entry_timestamp", "zone_id"]).reset_index(drop=True)
    return _remove_pyramids(trades)


def _remove_pyramids(trades: pd.DataFrame) -> pd.DataFrame:
    accepted_rows: list[pd.Series] = []
    active_until = pd.Timestamp.min.tz_localize("UTC")
    for _, trade in trades.iterrows():
        if trade["entry_timestamp"] < active_until:
            continue
        accepted_rows.append(trade)
        active_until = trade["exit_timestamp"]
    if not accepted_rows:
        return empty_trades()
    return pd.DataFrame(accepted_rows).reset_index(drop=True)


__all__ = [
    "SupplyDemandEmaRetestConfig",
    "SupplyDemandZone",
    "detect_supply_demand_zones",
    "empty_trades",
    "generate_supply_demand_ema_retest_trades",
    "resample_ohlcv",
    "summarize_trades",
]
