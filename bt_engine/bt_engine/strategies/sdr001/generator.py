"""SDR-001 event generator ported from `l99_intraday_sd_zone_research.py`.

Generates supply/demand zones + retest/confirm events from raw M1 bars.
Logic is verbatim from the canonical research script — same numbers, same
order, same cost_r formula.

This is the strategy logic. Runs causally bar-by-bar within the bounds of
its lookback windows (no future peeking).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


XAU_COST_USD = 0.30  # per-trade spread cost in USD price units
CONFIRM_BARS = 8
EXPIRY_HOURS = 24
ATR_BUFFER = 0.2  # stop buffer in ATR units

# m15_2c_1atr only (matches sleeve1 spec_name)
SPEC_NAME = "m15_2c_1atr"
SPEC_TF = "15min"
SPEC_MIN_CANDLES = 2
SPEC_ATR_MULT = 1.0
NY_TZ = "America/New_York"
STACK_SPECS: tuple[tuple[str, str, int, float], ...] = (
    ("m15_2c_1atr", "15min", 2, 1.0),
    ("m15_3c_1p5atr", "15min", 3, 1.5),
    ("m30_2c_1atr", "30min", 2, 1.0),
    ("m30_3c_1p5atr", "30min", 3, 1.5),
)
SDR002_CLEAN_RULE: tuple[str, ...] = (
    "closed_m15_ema8_aligned",
    "intraday_stack_24h",
    "ny_main_or_overlap",
    "cost_le_0p05",
    "body_ge_45",
    "base_body_low",
)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    true_range = pd.concat(
        [(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(n, min_periods=n).mean()


def resample_ohlcv(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    indexed = frame.set_index("timestamp")
    aggregations: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    for optional in ("spread", "symbol", "timeframe"):
        if optional in indexed.columns:
            aggregations[optional] = "last" if optional == "spread" else "first"
    return (
        indexed.resample(rule, label="left", closed="left")
        .agg(aggregations)
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )


@dataclass(frozen=True)
class Zone:
    zone_id: int
    zone_tf: str
    spec_name: str
    direction: str
    upper: float
    lower: float
    created_timestamp: pd.Timestamp
    base_timestamp: pd.Timestamp
    impulse_start_timestamp: pd.Timestamp
    impulse_end_timestamp: pd.Timestamp
    impulse_candles: int
    impulse_atr: float
    zone_width_atr: float
    base_body_ratio: float


def prep_ltf(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out["atr"] = atr(out, 14)
    out["ema8"] = out["close"].ewm(span=8, adjust=False).mean()
    out["range"] = (out["high"] - out["low"]).replace(0, np.nan)
    out["body"] = (out["close"] - out["open"]).abs()
    out["body_ratio"] = out["body"] / out["range"]
    out["close_location"] = (out["close"] - out["low"]) / out["range"]
    out = add_orb_context(out)
    return out.reset_index(drop=True)


def add_orb_context(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    ny = out["timestamp"].dt.tz_convert(NY_TZ)
    out["ny_date"] = ny.dt.date.astype(str)
    out["ny_hour"] = ny.dt.hour
    out["ny_minute"] = ny.dt.minute
    out["orb30_high"] = np.nan
    out["orb30_low"] = np.nan
    out["orb30_width"] = np.nan
    out["orb30_state"] = "missing"
    out["orb15_high"] = np.nan
    out["orb15_low"] = np.nan
    out["orb15_state"] = "missing"
    for _, idx in out.groupby("ny_date").groups.items():
        day = out.loc[idx]
        first_hour = day[(day["ny_hour"] == 9) & (day["ny_minute"] < 60)]
        bar_minutes = _median_minutes(day)
        bars_per_15m = max(1, int(round(15 / _median_minutes(day))))
        orb30 = first_hour.head(bars_per_15m * 2)
        orb15 = first_hour.head(bars_per_15m)
        if len(orb30) >= bars_per_15m * 2:
            high = float(orb30["high"].max())
            low = float(orb30["low"].min())
            available_from = pd.Timestamp(orb30["timestamp"].iloc[-1]) + pd.Timedelta(minutes=bar_minutes)
            eligible = day["timestamp"] >= available_from
            eligible_idx = day.index[eligible]
            out.loc[eligible_idx, "orb30_high"] = high
            out.loc[eligible_idx, "orb30_low"] = low
            out.loc[eligible_idx, "orb30_width"] = high - low
            close = out.loc[eligible_idx, "close"].astype(float)
            out.loc[eligible_idx, "orb30_state"] = np.where(close > high, "above", np.where(close < low, "below", "inside"))
        if len(orb15) >= bars_per_15m:
            high = float(orb15["high"].max())
            low = float(orb15["low"].min())
            available_from = pd.Timestamp(orb15["timestamp"].iloc[-1]) + pd.Timedelta(minutes=bar_minutes)
            eligible = day["timestamp"] >= available_from
            eligible_idx = day.index[eligible]
            out.loc[eligible_idx, "orb15_high"] = high
            out.loc[eligible_idx, "orb15_low"] = low
            close = out.loc[eligible_idx, "close"].astype(float)
            out.loc[eligible_idx, "orb15_state"] = np.where(close > high, "above", np.where(close < low, "below", "inside"))
    return out


def _median_minutes(frame: pd.DataFrame) -> float:
    diffs = frame["timestamp"].sort_values().diff().dropna()
    if diffs.empty:
        return 15.0
    return max(1.0, float(diffs.dt.total_seconds().median() / 60.0))


def _add_closed_m15_context(out: pd.DataFrame, m15: pd.DataFrame | None) -> pd.DataFrame:
    """Attach strictly previous closed-M15 EMA context.

    M15 bars are left-labelled, so a row stamped 10:15 represents the candle
    starting at 10:15. At a 10:15 entry that candle is not closed yet. This
    helper therefore uses `timestamp < entry_timestamp`, never `<=`.
    """
    out["closed_m15_timestamp"] = pd.NaT
    out["closed_m15_close"] = np.nan
    out["closed_m15_ema8"] = np.nan
    out["closed_m15_atr"] = np.nan
    out["closed_m15_ema8_distance_atr"] = np.nan
    out["closed_m15_ema8_aligned"] = False
    out["m15_boundary_entry"] = out["entry_timestamp"].dt.minute.mod(15).eq(0)
    if m15 is None or m15.empty:
        return out

    m15_ctx = m15[["timestamp", "atr", "ema8", "close"]].copy()
    m15_ctx["timestamp"] = pd.to_datetime(m15_ctx["timestamp"], utc=True)
    ts = m15_ctx["timestamp"].dt.tz_convert(None).astype("datetime64[ns]").astype("int64").to_numpy()
    entries = out["entry_timestamp"].dt.tz_convert(None).astype("datetime64[ns]").astype("int64").to_numpy()
    idx = np.searchsorted(ts, entries, side="left") - 1
    valid = idx >= 0
    idx = np.clip(idx, 0, len(m15_ctx) - 1)
    closes = m15_ctx["close"].to_numpy(float)[idx]
    emas = m15_ctx["ema8"].to_numpy(float)[idx]
    atrs = m15_ctx["atr"].to_numpy(float)[idx]
    with np.errstate(divide="ignore", invalid="ignore"):
        dist = (closes - emas) / atrs
    dist[~valid] = np.nan
    out["closed_m15_timestamp"] = pd.Series(m15_ctx["timestamp"].iloc[idx].to_numpy(), index=out.index).where(valid, pd.NaT)
    out["closed_m15_close"] = np.where(valid, closes, np.nan)
    out["closed_m15_ema8"] = np.where(valid, emas, np.nan)
    out["closed_m15_atr"] = np.where(valid, atrs, np.nan)
    out["closed_m15_ema8_distance_atr"] = dist
    out["closed_m15_ema8_aligned"] = (
        out["direction"].eq("demand") & out["closed_m15_ema8_distance_atr"].gt(0)
    ) | (
        out["direction"].eq("supply") & out["closed_m15_ema8_distance_atr"].lt(0)
    )
    return out


def build_intraday_stack_zones(m15: pd.DataFrame, m30: pd.DataFrame) -> list[Zone]:
    """Build the intraday zone universe used only as a causal stack filter."""
    frames = {"15min": m15, "30min": m30}
    zones: list[Zone] = []
    for spec_name, tf, min_candles, atr_mult in STACK_SPECS:
        zones.extend(
            detect_zones(
                frames[tf],
                spec_name=spec_name,
                tf=tf,
                min_candles=min_candles,
                atr_mult=atr_mult,
            )
        )
    return zones


def _add_intraday_stack_context(out: pd.DataFrame, stack_zones: list[Zone] | None) -> pd.DataFrame:
    """Count known same-direction overlapping intraday zones from the prior 24h."""
    out["same_dir_intraday_overlap_24h"] = 0
    out["same_dir_intraday_distinct_specs_24h"] = 0
    out["same_dir_intraday_distinct_tfs_24h"] = 0
    out["intraday_stack_24h"] = False
    if not stack_zones:
        return out

    zones = pd.DataFrame([z.__dict__ for z in stack_zones])
    zones["created_timestamp"] = pd.to_datetime(zones["created_timestamp"], utc=True)
    grouped: dict[str, dict[str, Any]] = {}
    for direction, frame in zones.groupby("direction"):
        frame = frame.sort_values("created_timestamp").reset_index(drop=True)
        grouped[str(direction)] = {
            "created": frame["created_timestamp"].dt.tz_convert(None).astype("datetime64[ns]").astype("int64").to_numpy(),
            "upper": frame["upper"].to_numpy(float),
            "lower": frame["lower"].to_numpy(float),
            "zone_id": frame["zone_id"].to_numpy(int),
            "spec_name": frame["spec_name"].astype(str).to_numpy(),
            "zone_tf": frame["zone_tf"].astype(str).to_numpy(),
        }
    counts: list[int] = []
    spec_counts: list[int] = []
    tf_counts: list[int] = []
    for ev in out.itertuples(index=False):
        arr = grouped.get(str(ev.direction))
        if arr is None:
            counts.append(0)
            spec_counts.append(0)
            tf_counts.append(0)
            continue
        entry_ns = pd.Timestamp(ev.entry_timestamp).value
        start_ns = (pd.Timestamp(ev.entry_timestamp) - pd.Timedelta(hours=24)).value
        s = int(np.searchsorted(arr["created"], start_ns, side="left"))
        e = int(np.searchsorted(arr["created"], entry_ns, side="right"))
        if e <= s:
            counts.append(0)
            spec_counts.append(0)
            tf_counts.append(0)
            continue
        mask = (arr["lower"][s:e] <= float(ev.upper)) & (arr["upper"][s:e] >= float(ev.lower))
        if "zone_id" in out.columns and "spec_name" in out.columns:
            own = (arr["zone_id"][s:e] == int(ev.zone_id)) & (arr["spec_name"][s:e] == str(ev.spec_name))
            mask &= ~own
        count = int(mask.sum())
        counts.append(count)
        if count:
            spec_counts.append(int(len(set(arr["spec_name"][s:e][mask]))))
            tf_counts.append(int(len(set(arr["zone_tf"][s:e][mask]))))
        else:
            spec_counts.append(0)
            tf_counts.append(0)
    out["same_dir_intraday_overlap_24h"] = counts
    out["same_dir_intraday_distinct_specs_24h"] = spec_counts
    out["same_dir_intraday_distinct_tfs_24h"] = tf_counts
    out["intraday_stack_24h"] = out["same_dir_intraday_overlap_24h"].ge(1)
    return out


def add_event_rule_features(
    events: pd.DataFrame,
    m5: pd.DataFrame,
    *,
    m15: pd.DataFrame | None = None,
    stack_zones: list[Zone] | None = None,
) -> pd.DataFrame:
    """Add forward-live selection flags used by SDR-001.

    These are causal predicates computed from event fields and data available
    through the entry bar. More expensive research-only features remain absent
    until promoted explicitly.
    """
    if events.empty:
        return events
    out = events.copy()
    out["entry_timestamp"] = pd.to_datetime(out["entry_timestamp"], utc=True)
    out["_event_order"] = np.arange(len(out))
    m5_ctx = m5[["timestamp", "atr", "ema8", "close", "close_location"]].copy()
    for optional in ("orb30_state", "orb15_state", "orb30_width"):
        if optional in m5.columns:
            m5_ctx[optional] = m5[optional]
    m5_ctx["timestamp"] = pd.to_datetime(m5_ctx["timestamp"], utc=True)
    context = m5_ctx.rename(
        columns={
            "timestamp": "entry_context_timestamp",
            "atr": "entry_atr",
            "ema8": "entry_ema8",
            "close": "entry_close",
            "close_location": "entry_close_location",
        }
    )
    out = pd.merge_asof(
        out.sort_values("entry_timestamp"),
        context.sort_values("entry_context_timestamp"),
        left_on="entry_timestamp",
        right_on="entry_context_timestamp",
        direction="backward",
        allow_exact_matches=False,
    ).sort_values("_event_order").drop(columns=["_event_order"]).reset_index(drop=True)
    ny = out["entry_timestamp"].dt.tz_convert(NY_TZ)
    out["entry_ny_hour"] = ny.dt.hour
    out["entry_weekday"] = ny.dt.day_name()
    out["entry_session"] = pd.cut(
        out["entry_ny_hour"],
        bins=[-1, 2, 7, 11, 16, 23],
        labels=["post_close", "asia_late", "london_ny_overlap", "ny_main", "after_hours"],
    ).astype(str)
    out["entry_ema8_distance_atr"] = (out["entry_price"] - out["entry_ema8"]) / out["entry_atr"]
    if "orb30_width" in out:
        out["orb30_width_atr"] = out["orb30_width"] / out["entry_atr"]
    out["dir_demand"] = out["direction"].eq("demand")
    out["dir_supply"] = out["direction"].eq("supply")
    out["cost_le_0p03"] = out["cost_r"].le(0.03)
    out["cost_le_0p05"] = out["cost_r"].le(0.05)
    out["risk_ge_10"] = out["risk_units"].ge(10)
    out["risk_ge_15"] = out["risk_units"].ge(15)
    out["fast_confirm_1"] = out["bars_to_confirm"].le(1)
    out["fast_confirm_2"] = out["bars_to_confirm"].le(2)
    out["fast_confirm_3"] = out["bars_to_confirm"].le(3)
    out["body_ge_45"] = out["confirm_body_ratio"].ge(0.45)
    out["body_ge_60"] = out["confirm_body_ratio"].ge(0.60)
    out["body_ge_70"] = out["confirm_body_ratio"].ge(0.70)
    out["tight_zone"] = out["zone_width_atr"].le(1.0)
    out["wide_zone"] = out["zone_width_atr"].ge(2.0)
    out["impulse_ge_1p5"] = out["impulse_atr"].ge(1.5)
    out["impulse_ge_2"] = out["impulse_atr"].ge(2.0)
    out["base_body_low"] = out["base_body_ratio"].le(0.35)
    out["base_body_high"] = out["base_body_ratio"].ge(0.65)
    out["ny_main_or_overlap"] = out["entry_session"].isin(["london_ny_overlap", "ny_main"])
    out["avoid_after_hours"] = ~out["entry_session"].eq("after_hours")
    out["ema8_aligned"] = (
        out["direction"].eq("demand") & out["entry_ema8_distance_atr"].gt(0)
    ) | (
        out["direction"].eq("supply") & out["entry_ema8_distance_atr"].lt(0)
    )
    out = _add_closed_m15_context(out, m15)
    out = _add_intraday_stack_context(out, stack_zones)
    out["xau_sdr_002_clean"] = True
    for flag in SDR002_CLEAN_RULE:
        out["xau_sdr_002_clean"] &= out[flag].fillna(False).astype(bool)
    out["orb_continuation"] = (
        out["direction"].eq("demand") & out["orb30_state"].eq("above")
    ) | (
        out["direction"].eq("supply") & out["orb30_state"].eq("below")
    )
    out["orb_reversal"] = (
        out["direction"].eq("demand") & out["orb30_state"].eq("below")
    ) | (
        out["direction"].eq("supply") & out["orb30_state"].eq("above")
    )
    out["orb_inside"] = out["orb30_state"].eq("inside")
    out["trade_key"] = (
        out["entry_timestamp"].astype(str)
        + "|"
        + out["direction"].astype(str)
        + "|"
        + out["entry_price"].astype(str)
    )
    return out


def detect_zones(
    df: pd.DataFrame,
    *,
    spec_name: str = SPEC_NAME,
    tf: str = SPEC_TF,
    min_candles: int = SPEC_MIN_CANDLES,
    atr_mult: float = SPEC_ATR_MULT,
) -> list[Zone]:
    zones: list[Zone] = []
    last_key: tuple[str, int] | None = None
    opens = df["open"].to_numpy(float)
    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    closes = df["close"].to_numpy(float)
    atrs = df["atr"].to_numpy(float)
    for end_i in range(20, len(df)):
        atr_v = atrs[end_i]
        if not np.isfinite(atr_v) or atr_v <= 0:
            continue
        direction = ""
        start_i = end_i
        while start_i >= 0 and closes[start_i] > opens[start_i]:
            start_i -= 1
        bull_start = start_i + 1
        if end_i - bull_start + 1 >= min_candles:
            move = closes[end_i] - opens[bull_start]
            if move >= atr_mult * atr_v:
                direction = "demand"
                start_i = bull_start
        if not direction:
            start_i = end_i
            while start_i >= 0 and closes[start_i] < opens[start_i]:
                start_i -= 1
            bear_start = start_i + 1
            if end_i - bear_start + 1 >= min_candles:
                move = opens[bear_start] - closes[end_i]
                if move >= atr_mult * atr_v:
                    direction = "supply"
                    start_i = bear_start
        if not direction:
            continue
        key = (direction, start_i)
        if key == last_key:
            continue
        last_key = key
        base_i = start_i - 1
        if base_i < 0:
            continue
        # Prefer opposite-colour base, otherwise immediately prior candle.
        for j in range(start_i - 1, max(-1, start_i - 6), -1):
            if direction == "demand" and closes[j] < opens[j]:
                base_i = j
                break
            if direction == "supply" and closes[j] > opens[j]:
                base_i = j
                break
        width = highs[base_i] - lows[base_i]
        if width <= 0:
            continue
        zones.append(
            Zone(
                zone_id=len(zones) + 1,
                zone_tf=tf,
                spec_name=spec_name,
                direction=direction,
                upper=float(highs[base_i]),
                lower=float(lows[base_i]),
                created_timestamp=pd.Timestamp(df["timestamp"].iloc[end_i]) + pd.Timedelta(tf),
                base_timestamp=pd.Timestamp(df["timestamp"].iloc[base_i]),
                impulse_start_timestamp=pd.Timestamp(df["timestamp"].iloc[start_i]),
                impulse_end_timestamp=pd.Timestamp(df["timestamp"].iloc[end_i]),
                impulse_candles=end_i - start_i + 1,
                impulse_atr=float(abs(closes[end_i] - opens[start_i]) / atr_v),
                zone_width_atr=float(width / atr_v),
                base_body_ratio=float(abs(closes[base_i] - opens[base_i]) / width),
            )
        )
    return zones


def confirm_reclaim(m5: pd.DataFrame, z: Zone, touch_i: int) -> dict[str, Any]:
    end_i = min(len(m5) - 2, touch_i + CONFIRM_BARS)
    for i in range(touch_i, end_i + 1):
        close = float(m5["close"].iloc[i])
        if z.direction == "demand":
            if close < z.lower:
                return {"confirmed": False}
            if close > z.upper and close > float(m5["ema8"].iloc[i]):
                return {
                    "confirmed": True,
                    "confirm_i": i,
                    "entry_i": i + 1,
                    "bars_to_confirm": i - touch_i,
                    "confirm_close": close,
                    "confirm_body_ratio": float(m5["body_ratio"].iloc[i]) if pd.notna(m5["body_ratio"].iloc[i]) else np.nan,
                }
        else:
            if close > z.upper:
                return {"confirmed": False}
            if close < z.lower and close < float(m5["ema8"].iloc[i]):
                return {
                    "confirmed": True,
                    "confirm_i": i,
                    "entry_i": i + 1,
                    "bars_to_confirm": i - touch_i,
                    "confirm_close": close,
                    "confirm_body_ratio": float(m5["body_ratio"].iloc[i]) if pd.notna(m5["body_ratio"].iloc[i]) else np.nan,
                }
    return {"confirmed": False}


def forward_path(m5: pd.DataFrame, entry_i: int, side: int, entry: float, stop: float, risk: float) -> dict[str, Any]:
    end_i = min(len(m5) - 1, entry_i + 12 * 24)
    hit_1 = False
    hit_stop = False
    first = "time"
    mfe = 0.0
    mae = 0.0
    for i in range(entry_i, end_i + 1):
        hi = float(m5["high"].iloc[i])
        lo = float(m5["low"].iloc[i])
        if side > 0:
            fav = (hi - entry) / risk
            adv = (entry - lo) / risk
            stop_hit = lo <= stop
        else:
            fav = (entry - lo) / risk
            adv = (hi - entry) / risk
            stop_hit = hi >= stop
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        if fav >= 1.0 and first == "time":
            hit_1 = True
            first = "tp1"
        if stop_hit:
            hit_stop = True
            if first == "time":
                first = "stop"
            break
    close_r = side * (float(m5["close"].iloc[end_i]) - entry) / risk
    outcome = 1.0 if hit_1 and first != "stop" else (-1.0 if hit_stop else float(np.clip(close_r, -1, 1)))
    return {
        "mfe_24h_r": float(mfe),
        "mae_24h_r": float(mae),
        "close_24h_r": float(close_r),
        "bracket_1r_outcome_r": float(outcome),
        "first_event_24h": first,
    }


def label_events(m5: pd.DataFrame, zones: list[Zone]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ts = m5["timestamp"].astype("int64").to_numpy()
    unit_divisor = 1000 if m5["timestamp"].dtype.name.startswith("datetime64[us") else 1
    highs = m5["high"].to_numpy(float)
    lows = m5["low"].to_numpy(float)
    for z in zones:
        start_v = pd.Timestamp(z.created_timestamp).value // unit_divisor
        end_v = (pd.Timestamp(z.created_timestamp) + pd.Timedelta(hours=EXPIRY_HOURS)).value // unit_divisor
        start_i = int(np.searchsorted(ts, start_v, side="left"))
        end_i = int(np.searchsorted(ts, end_v, side="right"))
        if start_i >= len(m5) - 2:
            continue
        touched = np.where((highs[start_i:end_i] >= z.lower) & (lows[start_i:end_i] <= z.upper))[0]
        if len(touched) == 0:
            continue
        touch_i = start_i + int(touched[0])
        confirm = confirm_reclaim(m5, z, touch_i)
        if not confirm["confirmed"]:
            continue
        entry_i = int(confirm["entry_i"])
        if entry_i >= len(m5):
            continue
        entry = float(m5["open"].iloc[entry_i])
        atr_v = float(m5["atr"].iloc[entry_i])
        if not np.isfinite(atr_v) or atr_v <= 0:
            continue
        buffer = ATR_BUFFER * atr_v
        if z.direction == "demand":
            side = 1
            stop = z.lower - buffer
            risk = entry - stop
        else:
            side = -1
            stop = z.upper + buffer
            risk = stop - entry
        if risk <= 0:
            continue
        path = forward_path(m5, entry_i, side, entry, stop, risk)
        rows.append(
            {
                **z.__dict__,
                "touch_timestamp": m5["timestamp"].iloc[touch_i],
                "entry_timestamp": m5["timestamp"].iloc[entry_i],
                "entry_price": entry,
                "stop_price": stop,
                "risk_units": risk,
                "touch_delay_hours": (pd.Timestamp(m5["timestamp"].iloc[touch_i]) - z.created_timestamp).total_seconds() / 3600,
                **confirm,
                **path,
            }
        )
    return rows


def generate_events_from_raw(
    raw: pd.DataFrame,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Master pipeline. Returns the m15_2c_1atr event DataFrame.

    Columns match `intraday_sd_reclaim_events.csv` (sleeve1 schema):
        zone_id, zone_tf, spec_name, direction, upper, lower,
        created_timestamp, base_timestamp, impulse_*, touch_timestamp,
        entry_timestamp, entry_price, stop_price, risk_units,
        touch_delay_hours, confirmed, confirm_i, entry_i, bars_to_confirm,
        confirm_close, confirm_body_ratio, mfe_24h_r, mae_24h_r, close_24h_r,
        bracket_1r_outcome_r, first_event_24h,
        year, month, date, cost_r, net_1r_after_cost, cost_bucket
    """
    raw = raw.copy()
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)

    def _utc(t):
        ts = pd.Timestamp(t)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    if start is not None:
        raw = raw[raw["timestamp"] >= _utc(start)]
    if end is not None:
        raw = raw[raw["timestamp"] < _utc(end)]
    raw = raw.dropna().sort_values("timestamp").reset_index(drop=True)

    m5 = prep_ltf(resample_ohlcv(raw, "5min"))
    m15 = prep_ltf(resample_ohlcv(raw, "15min"))
    m30 = prep_ltf(resample_ohlcv(raw, "30min"))

    zones = detect_zones(m15)
    stack_zones = build_intraday_stack_zones(m15, m30)
    events = label_events(m5, zones)
    df = pd.DataFrame(events)
    if df.empty:
        return df
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], utc=True)
    df["year"] = df["entry_timestamp"].dt.year
    df["month"] = df["entry_timestamp"].dt.strftime("%Y-%m")
    df["date"] = df["entry_timestamp"].dt.date.astype(str)
    df["cost_r"] = XAU_COST_USD / df["risk_units"]
    df["net_1r_after_cost"] = df["bracket_1r_outcome_r"] - df["cost_r"]
    df["cost_bucket"] = pd.cut(
        df["cost_r"],
        bins=[0, 0.03, 0.05, 0.10, 0.20, np.inf],
        labels=["<=0.03R", "0.03-0.05R", "0.05-0.10R", "0.10-0.20R", ">0.20R"],
        include_lowest=True,
    ).astype(str)
    df = add_event_rule_features(df, m5, m15=m15, stack_zones=stack_zones)
    return df
