from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from intraday_edge_lab.confirmation_engine import add_confirmation_features, bearish_confirmation, bullish_confirmation
from intraday_edge_lab.mt_loader import load_mt_export
from intraday_edge_lab.supply_demand_ema_retest import _remove_pyramids
from intraday_edge_lab.trade_manager import _nearest_prior_target, _simulate_close_based_bracket
from intraday_edge_lab.zone_detector import YouTubeSupplyDemandConfig, atr, confirmed_swings, resample_ohlcv


RAW = ROOT / "data" / "raw" / "XAUUSD.ecn_M1_201601040000_202606181903.csv"
OUT = ROOT / "research" / "standalone_order_block"
MINUTE_DATA_START = pd.Timestamp("2019-06-03 15:00:00+00:00")
RISK_USD = 50.0


@dataclass(frozen=True)
class OrderBlockConfig:
    htf_rule: str = "1h"
    ltf_rule: str = "15min"
    atr_length: int = 14
    impulse_window: int = 3
    min_impulse_atr: float = 2.0
    zone_mode: str = "body"
    direction_mode: str = "both"
    fvg_required: bool = True
    bos_required: bool = True
    discount_required: bool = True
    discount_pct: float = 0.50
    bos_lookback: int = 48
    expiry_hours: float = 72.0
    confirmation_wait_hours: float = 24.0
    pullback_min_bars: int = 3
    pullback_max_opposing_body_atr: float = 1.20
    stop_atr_buffer: float = 0.20
    key_level_lookback: int = 100
    target_mode: str = "swing_target"
    target_floor_r: float = 0.0
    entry_trigger: str = "ema_cross"
    confirmation_mode: str = "both"
    swing_left: int = 2
    swing_right: int = 2


@dataclass(frozen=True)
class OrderBlockZone:
    zone_id: int
    direction: str
    upper: float
    lower: float
    created_timestamp: pd.Timestamp
    base_timestamp: pd.Timestamp
    impulse_start_timestamp: pd.Timestamp
    impulse_end_timestamp: pd.Timestamp
    base_index: int
    impulse_end_index: int
    impulse_atr: float
    has_fvg: bool
    has_bos: bool
    discount_position: float
    zone_mode: str


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw, meta = load_mt_export(RAW, drop_zero_spread=False)
    raw = raw[pd.to_datetime(raw["timestamp"], utc=True) >= MINUTE_DATA_START].reset_index(drop=True)

    ltf = build_ltf(raw)
    htf = resample_ohlcv(raw, "1h").reset_index(drop=True)
    htf["atr"] = atr(htf, 14)
    htf_swings = confirmed_swings(htf, 2, 2)

    rows: list[dict[str, object]] = []
    yearly_frames: list[pd.DataFrame] = []
    all_trade_frames: list[pd.DataFrame] = []
    all_zone_frames: list[pd.DataFrame] = []
    saved_ledgers: dict[str, pd.DataFrame] = {}
    zone_cache: dict[tuple[object, ...], list[OrderBlockZone]] = {}

    variants = build_variants()
    for idx, (variant, config) in enumerate(variants, start=1):
        key = zone_cache_key(config)
        if key not in zone_cache:
            zone_cache[key] = detect_order_block_zones(htf, htf_swings, config)
            zone_frame = pd.DataFrame([z.__dict__ | {"zone_cache_key": str(key)} for z in zone_cache[key]])
            if not zone_frame.empty:
                all_zone_frames.append(zone_frame)
        zones = zone_cache[key]
        trades = generate_trades(ltf, zones, config)
        if not trades.empty:
            trades.insert(0, "variant", variant)
            trades["pnl_usd"] = trades["r_multiple"].astype(float) * RISK_USD
            trades["entry_year"] = pd.to_datetime(trades["entry_timestamp"], utc=True).dt.year
            trades = _remove_pyramids(trades.sort_values(["entry_timestamp", "zone_id"]).reset_index(drop=True))
            all_trade_frames.append(trades)
            saved_ledgers[variant] = trades
            yearly = summarize_yearly(trades, variant)
            if not yearly.empty:
                yearly_frames.append(yearly)
        rows.append({"variant": variant, **variant_knobs(config), "zones": len(zones), **metrics(trades), **drawdown(trades)})
        if idx % 50 == 0:
            print(f"Completed {idx}/{len(variants)} variants", flush=True)

    summary = pd.DataFrame(rows).sort_values(["net_pnl_usd", "profit_factor", "trades"], ascending=[False, False, False])
    yearly_all = pd.concat(yearly_frames, ignore_index=True) if yearly_frames else pd.DataFrame()
    trades_all = pd.concat(all_trade_frames, ignore_index=True) if all_trade_frames else pd.DataFrame()
    zones_all = pd.concat(all_zone_frames, ignore_index=True) if all_zone_frames else pd.DataFrame()

    summary.to_csv(OUT / "standalone_ob_summary.csv", index=False)
    yearly_all.to_csv(OUT / "standalone_ob_yearly.csv", index=False)
    trades_all.to_csv(OUT / "standalone_ob_trades.csv", index=False)
    zones_all.to_csv(OUT / "standalone_ob_zones.csv", index=False)
    save_top_ledgers(summary, saved_ledgers)

    payload = {
        "status": "research_only_base_unchanged",
        "source_videos": [
            "https://www.youtube.com/watch?v=AY7fWmE1CBk",
            "https://youtu.be/nkMzaQqpFbw",
        ],
        "method": "Standalone H1 order-block detector with body/wick zones, optional FVG, BOS, discount/premium, first-tap freshness, slow pullback, EMA/confirmation triggers, and swing/opposing-zone targets.",
        "data_scope_start": str(MINUTE_DATA_START),
        "risk_usd": RISK_USD,
        "data_source": meta.__dict__,
        "variant_count": len(variants),
        "top_rows": summary.head(25).to_dict("records"),
    }
    (OUT / "standalone_ob_summary.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    write_report(summary, yearly_all, zones_all, trades_all, payload)
    print(summary.head(30).to_string(index=False))


def build_ltf(raw: pd.DataFrame) -> pd.DataFrame:
    base = YouTubeSupplyDemandConfig(zone_expiry_bars=None, zone_expiry_hours=72.0, confirmation_mode="both")
    ltf = resample_ohlcv(raw, "15min").reset_index(drop=True)
    ltf = add_confirmation_features(ltf, base)
    ltf["atr"] = atr(ltf, 14)
    return ltf


def build_variants() -> list[tuple[str, OrderBlockConfig]]:
    variants = []
    base = OrderBlockConfig()
    quality_profiles = {
        "strict": (True, True, True),
        "no_fvg": (False, True, True),
        "no_bos": (True, False, True),
        "no_discount": (True, True, False),
    }
    grid = product(
        ("body", "wick"),
        ("demand_only", "both"),
        quality_profiles.items(),
        (1.5, 2.0),
        ("ema_cross", "confirmation_close"),
    )
    for values in grid:
        zone_mode, direction_mode, quality, impulse, entry_trigger = values
        quality_name, (fvg_required, bos_required, discount_required) = quality
        target_mode = "swing_target"
        target_floor = 0.0
        config = OrderBlockConfig(
            **{
                **base.__dict__,
                "zone_mode": zone_mode,
                "direction_mode": direction_mode,
                "fvg_required": fvg_required,
                "bos_required": bos_required,
                "discount_required": discount_required,
                "min_impulse_atr": impulse,
                "entry_trigger": entry_trigger,
                "target_mode": target_mode,
                "target_floor_r": target_floor,
            }
        )
        variant = (
            f"ob_{zone_mode}_{direction_mode}_imp{impulse:g}_"
            f"{quality_name}_"
            f"{entry_trigger}_{target_mode}_floor{target_floor:g}r"
        ).replace(".", "p")
        variants.append((variant, config))
    return variants


def zone_cache_key(config: OrderBlockConfig) -> tuple[object, ...]:
    return (
        config.zone_mode,
        config.direction_mode,
        config.fvg_required,
        config.bos_required,
        config.discount_required,
        config.min_impulse_atr,
    )


def detect_order_block_zones(htf: pd.DataFrame, swings: pd.DataFrame, config: OrderBlockConfig) -> list[OrderBlockZone]:
    zones: list[OrderBlockZone] = []
    offset = pd.tseries.frequencies.to_offset(config.htf_rule)
    open_ = htf["open"].to_numpy(dtype=float)
    high = htf["high"].to_numpy(dtype=float)
    low = htf["low"].to_numpy(dtype=float)
    close = htf["close"].to_numpy(dtype=float)
    timestamps = htf["timestamp"].to_numpy()
    is_bull = close > open_
    is_bear = close < open_
    atr_values = htf["atr"].to_numpy(dtype=float)
    for base_i in range(config.atr_length, len(htf) - config.impulse_window - 1):
        atr_value = float(atr_values[base_i])
        if not np.isfinite(atr_value) or atr_value <= 0:
            continue
        for direction in ("demand", "supply"):
            if config.direction_mode == "demand_only" and direction != "demand":
                continue
            if direction == "demand" and close[base_i] >= open_[base_i]:
                continue
            if direction == "supply" and close[base_i] <= open_[base_i]:
                continue
            start_i = base_i + 1
            end_i = base_i + config.impulse_window
            if direction == "demand":
                impulse_candles = int(is_bull[start_i : end_i + 1].sum())
                impulse = float(np.nanmax(close[start_i : end_i + 1]) - open_[start_i])
            else:
                impulse_candles = int(is_bear[start_i : end_i + 1].sum())
                impulse = float(open_[start_i] - np.nanmin(close[start_i : end_i + 1]))
            if impulse_candles < config.impulse_window or impulse < config.min_impulse_atr * atr_value:
                continue
            has_fvg = fvg_exists_arrays(high, low, start_i, end_i, direction)
            if config.fvg_required and not has_fvg:
                continue
            has_bos = bos_exists_arrays(high, low, swings, base_i, start_i, end_i, direction, config)
            if config.bos_required and not has_bos:
                continue

            lower, upper = zone_bounds_arrays(open_, high, low, close, base_i, config.zone_mode)
            swing_low = float(np.nanmin(low[base_i : end_i + 1]))
            swing_high = float(np.nanmax(high[base_i : end_i + 1]))
            if swing_high <= swing_low or upper <= lower:
                continue
            if direction == "demand":
                discount_position = (upper - swing_low) / (swing_high - swing_low)
                discount_ok = discount_position <= config.discount_pct
            else:
                discount_position = (swing_high - lower) / (swing_high - swing_low)
                discount_ok = discount_position <= config.discount_pct
            if config.discount_required and not discount_ok:
                continue

            zones.append(
                OrderBlockZone(
                    zone_id=len(zones) + 1,
                    direction=direction,
                    upper=upper,
                    lower=lower,
                    created_timestamp=pd.Timestamp(timestamps[end_i]) + offset,
                    base_timestamp=pd.Timestamp(timestamps[base_i]),
                    impulse_start_timestamp=pd.Timestamp(timestamps[start_i]),
                    impulse_end_timestamp=pd.Timestamp(timestamps[end_i]),
                    base_index=base_i,
                    impulse_end_index=end_i,
                    impulse_atr=impulse / atr_value,
                    has_fvg=has_fvg,
                    has_bos=has_bos,
                    discount_position=discount_position,
                    zone_mode=config.zone_mode,
                )
            )
    return zones


def fvg_exists_arrays(high: np.ndarray, low: np.ndarray, start_i: int, end_i: int, direction: str) -> bool:
    for i in range(start_i, max(start_i, end_i - 1)):
        if i + 2 > end_i:
            break
        if direction == "demand" and float(low[i + 2]) > float(high[i]):
            return True
        if direction == "supply" and float(high[i + 2]) < float(low[i]):
            return True
    return False


def bos_exists_arrays(
    high: np.ndarray,
    low: np.ndarray,
    swings: pd.DataFrame,
    base_i: int,
    start_i: int,
    end_i: int,
    direction: str,
    config: OrderBlockConfig,
) -> bool:
    lookback_start = max(0, base_i - config.bos_lookback)
    if direction == "demand":
        prior = swings["swing_high"].iloc[lookback_start:base_i].dropna()
        if prior.empty:
            return False
        return float(np.nanmax(high[start_i : end_i + 1])) > float(prior.iloc[-1])
    prior = swings["swing_low"].iloc[lookback_start:base_i].dropna()
    if prior.empty:
        return False
    return float(np.nanmin(low[start_i : end_i + 1])) < float(prior.iloc[-1])


def zone_bounds_arrays(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, i: int, zone_mode: str) -> tuple[float, float]:
    if zone_mode == "body":
        lower = min(float(open_[i]), float(close[i]))
        upper = max(float(open_[i]), float(close[i]))
    else:
        lower = float(low[i])
        upper = float(high[i])
    return lower, upper


def generate_trades(ltf: pd.DataFrame, zones: list[OrderBlockZone], config: OrderBlockConfig) -> pd.DataFrame:
    rows = []
    swings = confirmed_swings(ltf, config.swing_left, config.swing_right)
    yt_config = YouTubeSupplyDemandConfig(
        zone_expiry_bars=None,
        zone_expiry_hours=config.expiry_hours,
        confirmation_mode=config.confirmation_mode,
        stop_atr_buffer=config.stop_atr_buffer,
        key_level_lookback=config.key_level_lookback,
        close_based_exits=True,
        close_fill_at_level=False,
    )
    for zone in zones:
        trade = maybe_trade_zone(ltf, swings, zone, zones, config, yt_config)
        if trade is not None:
            rows.append(trade)
    return pd.DataFrame(rows)


def maybe_trade_zone(
    ltf: pd.DataFrame,
    swings: pd.DataFrame,
    zone: OrderBlockZone,
    all_zones: list[OrderBlockZone],
    config: OrderBlockConfig,
    yt_config: YouTubeSupplyDemandConfig,
) -> dict[str, object] | None:
    start_i = int(ltf["timestamp"].searchsorted(zone.created_timestamp, side="left"))
    expiry_ts = zone.created_timestamp + pd.Timedelta(hours=config.expiry_hours)
    expiry_i = min(len(ltf) - 1, int(ltf["timestamp"].searchsorted(expiry_ts, side="left")))
    retest_i = None
    for i in range(start_i, expiry_i):
        row = ltf.iloc[i]
        if failed_zone(row, zone):
            return None
        if float(row["high"]) >= zone.lower and float(row["low"]) <= zone.upper:
            if not slow_pullback_ok(ltf, start_i, i, zone.direction, config):
                return None
            retest_i = i
            break
    if retest_i is None:
        return None

    confirm_cutoff = min(
        expiry_i,
        int(ltf["timestamp"].searchsorted(ltf["timestamp"].iloc[retest_i] + pd.Timedelta(hours=config.confirmation_wait_hours), side="left")),
        len(ltf) - 2,
    )
    for i in range(retest_i, confirm_cutoff + 1):
        row = ltf.iloc[i]
        prev = ltf.iloc[i - 1] if i > 0 else None
        if failed_zone(row, zone):
            return None
        if prev is None or pd.isna(row["ema"]) or pd.isna(prev["ema"]):
            continue
        ok, label = entry_ok(row, prev, zone.direction, config, yt_config)
        if ok:
            return build_trade(ltf, swings, all_zones, zone, i, i + 1, label, config, yt_config)
    return None


def failed_zone(row: pd.Series, zone: OrderBlockZone) -> bool:
    if zone.direction == "demand":
        return float(row["close"]) < zone.lower
    return float(row["close"]) > zone.upper


def slow_pullback_ok(ltf: pd.DataFrame, start_i: int, retest_i: int, direction: str, config: OrderBlockConfig) -> bool:
    if retest_i - start_i + 1 < config.pullback_min_bars:
        return False
    window = ltf.iloc[start_i : retest_i + 1]
    if direction == "demand":
        body = (window["open"] - window["close"]).astype(float)
        toxic = (window["close"] < window["open"]) & (body >= config.pullback_max_opposing_body_atr * window["atr"].astype(float))
    else:
        body = (window["close"] - window["open"]).astype(float)
        toxic = (window["close"] > window["open"]) & (body >= config.pullback_max_opposing_body_atr * window["atr"].astype(float))
    return not bool(toxic.any())


def entry_ok(
    row: pd.Series,
    prev: pd.Series,
    direction: str,
    config: OrderBlockConfig,
    yt_config: YouTubeSupplyDemandConfig,
) -> tuple[bool, str]:
    if config.entry_trigger == "ema_cross":
        if direction == "demand":
            ema_ok = bool(float(prev["close"]) < float(prev["ema"]) and float(row["close"]) > float(row["ema"]))
            candle_ok, label = bullish_confirmation(row, prev, yt_config)
        else:
            ema_ok = bool(float(prev["close"]) > float(prev["ema"]) and float(row["close"]) < float(row["ema"]))
            candle_ok, label = bearish_confirmation(row, prev, yt_config)
        return bool(ema_ok and candle_ok), label
    candle_range = float(row["high"] - row["low"])
    if candle_range <= 0:
        return False, ""
    if direction == "demand":
        body = float(row["close"] - row["open"])
        close_location = float((row["close"] - row["low"]) / candle_range)
        return bool(body > 0 and body / candle_range >= 0.50 and close_location >= 0.65), "bullish_confirmation_close"
    body = float(row["open"] - row["close"])
    close_location = float((row["high"] - row["close"]) / candle_range)
    return bool(body > 0 and body / candle_range >= 0.50 and close_location >= 0.65), "bearish_confirmation_close"


def build_trade(
    ltf: pd.DataFrame,
    swings: pd.DataFrame,
    all_zones: list[OrderBlockZone],
    zone: OrderBlockZone,
    decision_i: int,
    entry_i: int,
    label: str,
    config: OrderBlockConfig,
    yt_config: YouTubeSupplyDemandConfig,
) -> dict[str, object] | None:
    if entry_i >= len(ltf):
        return None
    side = 1 if zone.direction == "demand" else -1
    entry_price = float(ltf["open"].iloc[entry_i])
    atr_value = float(ltf["atr"].iloc[decision_i])
    if not np.isfinite(atr_value) or atr_value <= 0:
        return None
    if side == 1:
        last_swing = last_swing_value(swings["swing_low"], decision_i)
        stop_ref = min(zone.lower, last_swing) if last_swing is not None else zone.lower
        stop_price = stop_ref - config.stop_atr_buffer * atr_value
    else:
        last_swing = last_swing_value(swings["swing_high"], decision_i)
        stop_ref = max(zone.upper, last_swing) if last_swing is not None else zone.upper
        stop_price = stop_ref + config.stop_atr_buffer * atr_value
    risk = entry_price - stop_price if side == 1 else stop_price - entry_price
    if risk <= 0:
        return None
    take_profit = find_target(ltf, swings, all_zones, zone, entry_i, entry_price, side, config, yt_config)
    if take_profit is None:
        return None
    reward = take_profit - entry_price if side == 1 else entry_price - take_profit
    if reward <= 0:
        return None
    if reward / risk < config.target_floor_r:
        take_profit = entry_price + side * config.target_floor_r * risk
        reward = config.target_floor_r * risk
    outcome = _simulate_close_based_bracket(ltf, entry_i, side, stop_price, float(take_profit), yt_config)
    pnl_units = (float(outcome["exit_price"]) - entry_price) * side
    return {
        "zone_id": zone.zone_id,
        "zone_direction": zone.direction,
        "decision_timestamp": ltf["timestamp"].iloc[decision_i],
        "entry_timestamp": ltf["timestamp"].iloc[entry_i],
        "exit_timestamp": outcome["exit_timestamp"],
        "side": side,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "take_profit": float(take_profit),
        "exit_price": outcome["exit_price"],
        "exit_reason": outcome["exit_reason"],
        "risk_units": risk,
        "target_r": reward / risk,
        "pnl_units": pnl_units,
        "r_multiple": pnl_units / risk,
        "confirmation": label,
        "zone_upper": zone.upper,
        "zone_lower": zone.lower,
        "zone_created_timestamp": zone.created_timestamp,
        "base_timestamp": zone.base_timestamp,
        "impulse_atr": zone.impulse_atr,
        "has_fvg": zone.has_fvg,
        "has_bos": zone.has_bos,
        "discount_position": zone.discount_position,
        "zone_mode": zone.zone_mode,
        "entry_trigger": config.entry_trigger,
        "target_mode": config.target_mode,
    }


def last_swing_value(series: pd.Series, before_i: int) -> float | None:
    values = series.iloc[: before_i + 1].dropna()
    return None if values.empty else float(values.iloc[-1])


def find_target(
    ltf: pd.DataFrame,
    swings: pd.DataFrame,
    all_zones: list[OrderBlockZone],
    zone: OrderBlockZone,
    entry_i: int,
    entry_price: float,
    side: int,
    config: OrderBlockConfig,
    yt_config: YouTubeSupplyDemandConfig,
) -> float | None:
    if config.target_mode == "swing_target":
        series = swings["swing_high"] if side == 1 else swings["swing_low"]
        return _nearest_prior_target(series, ltf, entry_i, entry_price, yt_config.key_level_lookback, side)
    entry_ts = ltf["timestamp"].iloc[entry_i]
    if side == 1:
        candidates = [z.lower for z in all_zones if z.direction == "supply" and z.created_timestamp < entry_ts and z.lower > entry_price]
        return float(min(candidates)) if candidates else None
    candidates = [z.upper for z in all_zones if z.direction == "demand" and z.created_timestamp < entry_ts and z.upper < entry_price]
    return float(max(candidates)) if candidates else None


def variant_knobs(config: OrderBlockConfig) -> dict[str, object]:
    return {
        "zone_mode": config.zone_mode,
        "direction_mode": config.direction_mode,
        "min_impulse_atr": config.min_impulse_atr,
        "fvg_required": config.fvg_required,
        "bos_required": config.bos_required,
        "discount_required": config.discount_required,
        "entry_trigger": config.entry_trigger,
        "target_mode": config.target_mode,
        "target_floor_r": config.target_floor_r,
    }


def metrics(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {
            "trades": 0,
            "net_pnl_usd": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "avg_target_r": 0.0,
            "median_target_r": 0.0,
            "positive_years": 0,
            "negative_years": 0,
        }
    pnl = trades["pnl_usd"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    yearly = summarize_yearly(trades, str(trades["variant"].iloc[0]) if "variant" in trades else "variant")
    return {
        "trades": int(len(trades)),
        "net_pnl_usd": float(pnl.sum()),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": gross_profit / gross_loss if gross_loss else np.inf if gross_profit > 0 else 0.0,
        "expectancy_r": float(trades["r_multiple"].astype(float).mean()),
        "avg_target_r": float(trades["target_r"].astype(float).mean()),
        "median_target_r": float(trades["target_r"].astype(float).median()),
        "positive_years": int((yearly["net_pnl_usd"] > 0).sum()) if not yearly.empty else 0,
        "negative_years": int((yearly["net_pnl_usd"] < 0).sum()) if not yearly.empty else 0,
    }


def drawdown(trades: pd.DataFrame, start_equity: float = 5000.0) -> dict[str, float]:
    if trades.empty:
        return {"ending_equity": start_equity, "max_drawdown_usd": 0.0, "max_drawdown_pct": 0.0}
    ordered = trades.sort_values("entry_timestamp")
    equity = start_equity + ordered["pnl_usd"].astype(float).cumsum()
    peak = equity.cummax()
    dd = equity - peak
    return {
        "ending_equity": float(equity.iloc[-1]),
        "max_drawdown_usd": float(dd.min()),
        "max_drawdown_pct": float((dd / peak).min()),
    }


def summarize_yearly(trades: pd.DataFrame, variant: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for year, group in trades.groupby(pd.to_datetime(trades["entry_timestamp"], utc=True).dt.year):
        rows.append({"variant": variant, "year": int(year), **metrics_no_year(group)})
    return pd.DataFrame(rows)


def metrics_no_year(group: pd.DataFrame) -> dict[str, float | int]:
    pnl = group["pnl_usd"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gp = float(wins.sum())
    gl = float(-losses.sum())
    return {
        "trades": int(len(group)),
        "net_pnl_usd": float(pnl.sum()),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": gp / gl if gl else np.inf if gp > 0 else 0.0,
        "expectancy_r": float(group["r_multiple"].astype(float).mean()),
    }


def save_top_ledgers(summary: pd.DataFrame, ledgers: dict[str, pd.DataFrame], count: int = 12) -> None:
    for variant in summary.head(count)["variant"].tolist():
        ledger = ledgers.get(variant)
        if ledger is not None:
            ledger.to_csv(OUT / f"{variant}_trades.csv", index=False)


def write_report(summary: pd.DataFrame, yearly: pd.DataFrame, zones: pd.DataFrame, trades: pd.DataFrame, payload: dict[str, object]) -> None:
    top_read = build_top_read(summary)
    report = f"""# Standalone Order-Block Research

## Scope

Research-only. The frozen Supply/Demand base is untouched.

This tests the missing pure order-block branch: last opposite H1 candle before a strong displacement, with body/wick zones, optional FVG, BOS, discount/premium, first-tap freshness, slow-pullback rejection, and either EMA-cross or confirmation-close entries.

## Top Read

{top_read}

## Zone / Trade Counts

- Variants tested: `{int(payload["variant_count"])}`
- Total detected zone rows across variants: `{len(zones)}`
- Total trade rows across variants: `{len(trades)}`

## Top Variant Summary

{markdown_table(format_table(summary.head(30)))}

## Yearly For Top 5

{markdown_table(format_table(yearly[yearly["variant"].isin(summary.head(5)["variant"])] if not yearly.empty else yearly))}

## Read

This is the pure OB answer to the earlier audit gap. If the best rows do not beat the active base on sample size, PF, drawdown, and yearly spread, OB should remain a tag inside the stronger ORB/A+ stack rather than become a standalone strategy.

## Files

- `standalone_ob_summary.csv`
- `standalone_ob_yearly.csv`
- `standalone_ob_trades.csv`
- `standalone_ob_zones.csv`
- `standalone_ob_summary.json`
- top `*_trades.csv` ledgers
"""
    (OUT / "STANDALONE_ORDER_BLOCK_RESEARCH.md").write_text(report, encoding="utf-8")


def build_top_read(summary: pd.DataFrame) -> str:
    if summary.empty:
        return "_No rows generated._"
    best = summary.iloc[0]
    active_base = "Active demand base reference: `211` trades, `$2,186.91`, PF `2.38`, WR `69.19%`, max DD about `-4.36%`."
    lines = [
        f"- Best standalone OB row: `{best['variant']}` with `{int(best['trades'])}` trades, `${float(best['net_pnl_usd']):,.2f}` PnL, PF `{format_factor(float(best['profit_factor']))}`, WR `{float(best['win_rate']):.2%}`, DD `{float(best['max_drawdown_pct']):.2%}`.",
        f"- {active_base}",
    ]
    if int(best["trades"]) < 50:
        lines.append("- Read: too few trades for promotion even if headline PnL looks attractive.")
    elif float(best["net_pnl_usd"]) > 2186.91 and float(best["profit_factor"]) >= 2.38:
        lines.append("- Read: this deserves follow-up validation against costs, Monte Carlo, and walk-forward.")
    else:
        lines.append("- Read: standalone OB does not beat the current base; keep OB as confluence/tag unless follow-up validation says otherwise.")
    return "\n".join(lines)


def format_factor(value: float) -> str:
    return "inf" if np.isinf(value) else f"{value:.2f}"


def format_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    money_cols = {"net_pnl_usd", "ending_equity", "max_drawdown_usd"}
    pct_cols = {"win_rate", "max_drawdown_pct"}
    factor_cols = {"profit_factor", "expectancy_r", "avg_target_r", "median_target_r"}
    for col in out.columns:
        if col in money_cols:
            out[col] = out[col].map(lambda x: f"${float(x):,.2f}")
        elif col in pct_cols:
            out[col] = out[col].map(lambda x: f"{float(x):.2%}")
        elif col in factor_cols:
            out[col] = out[col].map(lambda x: format_factor(float(x)))
    return out


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    cols = list(frame.columns)
    lines = [
        "| " + " | ".join(str(col) for col in cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in cols) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
