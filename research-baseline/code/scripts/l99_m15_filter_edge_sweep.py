from __future__ import annotations

import json
from itertools import combinations, product
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/Users/subash/Documents/QUANT/SupplyDemand")
RAW = ROOT / "data" / "raw" / "XAUUSD.ecn_M1_201601040000_202606181903.csv"
CONFLUENCE_EVENTS = ROOT / "research" / "l99_multitimeframe_sd_confluence" / "multitimeframe_sd_confluence_events.csv"
OB_ZONES = ROOT / "research" / "standalone_order_block" / "standalone_ob_zones.csv"
OUT = ROOT / "research" / "l99_m15_filter_edge_sweep"

START = pd.Timestamp("2019-01-01", tz="UTC")
END = pd.Timestamp("2026-06-19", tz="UTC")
NY_TZ = "America/New_York"
ORACLE_R = 6279.211314445981
SEED = 29062026 + 4101
VP_BIN = 0.50


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    feature_path = OUT / "m15_2c_1atr_feature_matrix.csv"
    if feature_path.exists():
        features = pd.read_csv(feature_path)
        for col in ["created_timestamp", "touch_timestamp", "entry_timestamp", "base_timestamp", "impulse_start_timestamp", "impulse_end_timestamp"]:
            if col in features.columns:
                features[col] = pd.to_datetime(features[col], utc=True)
    else:
        raw = load_raw()
        m15 = prep_context(resample_ohlcv(raw, "15min"))
        events = load_events()
        features = build_feature_matrix(events, raw, m15)
        features.to_csv(feature_path, index=False)

    candidates = sweep_candidates(features)
    candidates.to_csv(OUT / "m15_filter_candidate_sweep.csv", index=False)

    best = select_best(candidates)
    quality = select_quality_candidate(candidates)
    best_trades = apply_rule(features, best)
    best_trades.to_csv(OUT / "best_candidate_trades.csv", index=False)
    quality_trades = apply_rule(features, quality)
    quality_trades.to_csv(OUT / "quality_candidate_trades.csv", index=False)

    yearly = yearly_summary(best_trades)
    monthly = monthly_summary(best_trades)
    stress = stress_tests(best_trades)
    random = random_benchmark(features, best)
    walk = rolling_walk_forward(features)
    neighborhood = parameter_neighborhood(features, best)
    mc = monte_carlo(best_trades)
    quality_yearly = yearly_summary(quality_trades)
    quality_monthly = monthly_summary(quality_trades)
    quality_stress = stress_tests(quality_trades)
    quality_random = random_benchmark(features, quality)
    quality_neighborhood = parameter_neighborhood(features, quality)
    quality_mc = monte_carlo(quality_trades)

    yearly.to_csv(OUT / "best_candidate_yearly.csv", index=False)
    monthly.to_csv(OUT / "best_candidate_monthly.csv", index=False)
    stress.to_csv(OUT / "best_candidate_cost_stress.csv", index=False)
    random.to_csv(OUT / "best_candidate_random_benchmark.csv", index=False)
    walk.to_csv(OUT / "rolling_walk_forward.csv", index=False)
    neighborhood.to_csv(OUT / "parameter_neighborhood.csv", index=False)
    mc.to_csv(OUT / "monte_carlo.csv", index=False)
    quality_yearly.to_csv(OUT / "quality_candidate_yearly.csv", index=False)
    quality_monthly.to_csv(OUT / "quality_candidate_monthly.csv", index=False)
    quality_stress.to_csv(OUT / "quality_candidate_cost_stress.csv", index=False)
    quality_random.to_csv(OUT / "quality_candidate_random_benchmark.csv", index=False)
    quality_neighborhood.to_csv(OUT / "quality_candidate_parameter_neighborhood.csv", index=False)
    quality_mc.to_csv(OUT / "quality_candidate_monte_carlo.csv", index=False)

    payload = {
        "best_rule": best.to_dict(),
        "best_metrics": evaluate(best_trades),
        "quality_rule": quality.to_dict(),
        "quality_metrics": evaluate(quality_trades),
        "oracle_r": ORACLE_R,
        "oracle_capture_pct": float(evaluate(best_trades)["net_r"] / ORACLE_R),
        "deliverables": [
            "m15_2c_1atr_feature_matrix.csv",
            "m15_filter_candidate_sweep.csv",
            "best_candidate_trades.csv",
            "best_candidate_yearly.csv",
            "best_candidate_monthly.csv",
            "best_candidate_cost_stress.csv",
            "best_candidate_random_benchmark.csv",
            "rolling_walk_forward.csv",
            "parameter_neighborhood.csv",
            "monte_carlo.csv",
            "quality_candidate_trades.csv",
            "quality_candidate_yearly.csv",
            "quality_candidate_monthly.csv",
            "quality_candidate_cost_stress.csv",
            "quality_candidate_random_benchmark.csv",
            "quality_candidate_parameter_neighborhood.csv",
            "quality_candidate_monte_carlo.csv",
        ],
    }
    (OUT / "m15_filter_edge_summary.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    write_report(
        features,
        candidates,
        best,
        best_trades,
        yearly,
        monthly,
        stress,
        random,
        walk,
        neighborhood,
        mc,
        quality,
        quality_trades,
        quality_yearly,
        quality_monthly,
        quality_stress,
        quality_random,
        quality_neighborhood,
        quality_mc,
    )
    print(f"Wrote {OUT}")


def load_raw() -> pd.DataFrame:
    raw = pd.read_csv(RAW, sep="\t")
    ts = pd.to_datetime(raw["<DATE>"].astype(str) + " " + raw["<TIME>"].astype(str), format="%Y.%m.%d %H:%M:%S", utc=True)
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": pd.to_numeric(raw["<OPEN>"], errors="coerce"),
            "high": pd.to_numeric(raw["<HIGH>"], errors="coerce"),
            "low": pd.to_numeric(raw["<LOW>"], errors="coerce"),
            "close": pd.to_numeric(raw["<CLOSE>"], errors="coerce"),
            "volume": pd.to_numeric(raw["<TICKVOL>"], errors="coerce").fillna(0),
        }
    )
    return df[(df["timestamp"] >= START - pd.Timedelta(days=35)) & (df["timestamp"] < END)].dropna().sort_values("timestamp").reset_index(drop=True)


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return (
        df.set_index("timestamp")
        .resample(rule)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def prep_context(m15: pd.DataFrame) -> pd.DataFrame:
    out = m15.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out["atr"] = atr(out, 14)
    out["ema8"] = out["close"].ewm(span=8, adjust=False).mean()
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema50"] = out["close"].ewm(span=50, adjust=False).mean()
    out["ema200"] = out["close"].ewm(span=200, adjust=False).mean()
    out["trend_ema50_200"] = np.where(out["ema50"] > out["ema200"], "bull", "bear")
    out["atr_pct_rank_500"] = out["atr"].rolling(500, min_periods=100).rank(pct=True)
    out["vol_regime"] = pd.cut(out["atr_pct_rank_500"], [-np.inf, 0.33, 0.66, np.inf], labels=["low", "mid", "high"]).astype(str)
    ny = out["timestamp"].dt.tz_convert(NY_TZ)
    out["ny_date"] = ny.dt.date.astype(str)
    out["ny_hour"] = ny.dt.hour
    out["weekday"] = ny.dt.day_name()
    out["session"] = pd.cut(
        out["ny_hour"],
        bins=[-1, 2, 7, 11, 16, 23],
        labels=["post_close", "asia_late", "london_ny_overlap", "ny_main", "after_hours"],
    ).astype(str)
    out["range"] = (out["high"] - out["low"]).replace(0, np.nan)
    out["body"] = (out["close"] - out["open"]).abs()
    out["body_ratio"] = out["body"] / out["range"]
    out["close_location"] = (out["close"] - out["low"]) / out["range"]
    out["bull_fvg"] = out["low"] > out["high"].shift(2)
    out["bull_fvg_lower"] = out["high"].shift(2)
    out["bull_fvg_upper"] = out["low"]
    out["bear_fvg"] = out["high"] < out["low"].shift(2)
    out["bear_fvg_lower"] = out["high"]
    out["bear_fvg_upper"] = out["low"].shift(2)
    return add_orb_context(out)


def add_orb_context(m15: pd.DataFrame) -> pd.DataFrame:
    out = m15.copy()
    out["orb30_high"] = np.nan
    out["orb30_low"] = np.nan
    out["orb30_width"] = np.nan
    out["orb30_state"] = "missing"
    out["orb15_high"] = np.nan
    out["orb15_low"] = np.nan
    out["orb15_state"] = "missing"
    for _, idx in out.groupby("ny_date").groups.items():
        day = out.loc[idx]
        first_hour = day[(day["ny_hour"] == 9) & (day["timestamp"].dt.tz_convert(NY_TZ).dt.minute < 60)]
        orb30 = first_hour.head(2)
        orb15 = first_hour.head(1)
        if len(orb30) >= 2:
            high = float(orb30["high"].max())
            low = float(orb30["low"].min())
            out.loc[idx, "orb30_high"] = high
            out.loc[idx, "orb30_low"] = low
            out.loc[idx, "orb30_width"] = high - low
            close = out.loc[idx, "close"].astype(float)
            out.loc[idx, "orb30_state"] = np.where(close > high, "above", np.where(close < low, "below", "inside"))
        if len(orb15) >= 1:
            high = float(orb15["high"].max())
            low = float(orb15["low"].min())
            out.loc[idx, "orb15_high"] = high
            out.loc[idx, "orb15_low"] = low
            close = out.loc[idx, "close"].astype(float)
            out.loc[idx, "orb15_state"] = np.where(close > high, "above", np.where(close < low, "below", "inside"))
    return out


def load_events() -> pd.DataFrame:
    df = pd.read_csv(CONFLUENCE_EVENTS)
    df = df[df["spec_name"].eq("m15_2c_1atr")].copy()
    for col in ["created_timestamp", "touch_timestamp", "entry_timestamp", "base_timestamp", "impulse_start_timestamp", "impulse_end_timestamp"]:
        df[col] = pd.to_datetime(df[col], utc=True)
    df["year"] = df["entry_timestamp"].dt.year
    df["month"] = df["entry_timestamp"].dt.strftime("%Y-%m")
    df["date"] = df["entry_timestamp"].dt.date.astype(str)
    df["winner"] = df["net_1r_after_cost"].astype(float) > 0
    return df.sort_values(["entry_timestamp", "zone_id"]).reset_index(drop=True)


def build_feature_matrix(events: pd.DataFrame, raw: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    ctx = lookup_context(out, m15)
    out = pd.concat([out.reset_index(drop=True), ctx.reset_index(drop=True)], axis=1)
    out = add_volume_profile(out, raw)
    out = add_order_block_overlap(out)
    out = add_fvg_features(out, m15)
    out = add_derived_features(out)
    return out


def lookup_context(events: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    ts = m15["timestamp"].dt.tz_convert(None).astype("datetime64[ns]").astype("int64").to_numpy()
    rows = []
    for ev in events.itertuples(index=False):
        entry_ns = pd.Timestamp(ev.entry_timestamp).tz_convert(None).value
        i = int(np.searchsorted(ts, entry_ns, side="right") - 1)
        i = max(0, min(i, len(m15) - 1))
        row = m15.iloc[i]
        rows.append(
            {
                "entry_ny_hour": int(row["ny_hour"]),
                "entry_weekday": str(row["weekday"]),
                "entry_session": str(row["session"]),
                "trend_ema50_200": str(row["trend_ema50_200"]),
                "atr_pct_rank_500": float(row["atr_pct_rank_500"]) if pd.notna(row["atr_pct_rank_500"]) else np.nan,
                "vol_regime": str(row["vol_regime"]),
                "orb30_state": str(row["orb30_state"]),
                "orb15_state": str(row["orb15_state"]),
                "orb30_width_atr": safe_div(float(row["orb30_width"]), float(row["atr"])),
                "entry_close_location": float(row["close_location"]) if pd.notna(row["close_location"]) else np.nan,
                "entry_ema8_distance_atr": safe_div(float(row["close"] - row["ema8"]), float(row["atr"])),
                "entry_ema20_distance_atr": safe_div(float(row["close"] - row["ema20"]), float(row["atr"])),
            }
        )
    return pd.DataFrame(rows)


def add_volume_profile(events: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    m1 = raw.copy()
    m1["typical"] = (m1["high"] + m1["low"] + m1["close"]) / 3.0
    ts = m1["timestamp"].dt.tz_convert(None).astype("datetime64[ns]").astype("int64").to_numpy()
    prices = m1["typical"].to_numpy(float)
    vols = m1["volume"].to_numpy(float)
    rows = []
    for ev in out.itertuples(index=False):
        end_ns = pd.Timestamp(ev.entry_timestamp).tz_convert(None).value
        start_ns = (pd.Timestamp(ev.entry_timestamp) - pd.Timedelta(hours=24)).tz_convert(None).value
        s = int(np.searchsorted(ts, start_ns, side="left"))
        e = int(np.searchsorted(ts, end_ns, side="left"))
        rows.append(profile_stats(prices[s:e], vols[s:e], float(ev.upper), float(ev.lower), float(ev.entry_price), float(ev.risk_units)))
    prof = pd.DataFrame(rows)
    return pd.concat([out.reset_index(drop=True), prof.reset_index(drop=True)], axis=1)


def profile_stats(prices: np.ndarray, vols: np.ndarray, upper: float, lower: float, entry: float, risk_units: float) -> dict[str, object]:
    empty = {
        "profile_complete": False,
        "profile_location": "unknown",
        "volume_node": "unknown",
        "zone_contains_poc": False,
        "zone_overlaps_value": False,
        "poc_distance_r": np.nan,
        "zone_volume_percentile": np.nan,
    }
    if len(prices) < 60 or np.nansum(vols) <= 0:
        return empty
    lo = np.floor(np.nanmin(prices) / VP_BIN) * VP_BIN
    hi = np.ceil(np.nanmax(prices) / VP_BIN) * VP_BIN + VP_BIN
    bins = np.arange(lo, hi + VP_BIN, VP_BIN)
    if len(bins) < 4:
        return empty
    hist, edges = np.histogram(prices, bins=bins, weights=vols)
    if hist.sum() <= 0:
        return empty
    centers = (edges[:-1] + edges[1:]) / 2
    poc_i = int(np.argmax(hist))
    included = {poc_i}
    left = poc_i - 1
    right = poc_i + 1
    acc = float(hist[poc_i])
    target = 0.70 * float(hist.sum())
    while acc < target and (left >= 0 or right < len(hist)):
        lv = hist[left] if left >= 0 else -1
        rv = hist[right] if right < len(hist) else -1
        if rv >= lv:
            included.add(right)
            acc += float(rv)
            right += 1
        else:
            included.add(left)
            acc += float(lv)
            left -= 1
    idx = sorted(included)
    val = float(edges[min(idx)])
    vah = float(edges[max(idx) + 1])
    zone_mid = (upper + lower) / 2
    zone_i = int(np.clip(np.searchsorted(edges, zone_mid, side="right") - 1, 0, len(hist) - 1))
    pct = float((hist <= hist[zone_i]).mean())
    if zone_mid > vah:
        loc = "above_value"
    elif zone_mid < val:
        loc = "below_value"
    elif zone_mid <= centers[poc_i]:
        loc = "value_low_half"
    else:
        loc = "value_high_half"
    node = "lvn" if pct <= 0.25 else "hvn" if pct >= 0.75 else "mid_volume"
    poc = float(centers[poc_i])
    return {
        "profile_complete": True,
        "profile_location": loc,
        "volume_node": node,
        "zone_contains_poc": bool(lower <= poc <= upper),
        "zone_overlaps_value": bool(upper >= val and lower <= vah),
        "poc_distance_r": safe_div(zone_mid - poc, risk_units),
        "zone_volume_percentile": pct,
    }


def add_order_block_overlap(events: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    if not OB_ZONES.exists():
        out["ob_overlap"] = False
        out["ob_fvg_bos_overlap"] = False
        return out
    ob = pd.read_csv(OB_ZONES)
    ob["created_timestamp"] = pd.to_datetime(ob["created_timestamp"], utc=True)
    ob = ob.sort_values("created_timestamp")
    arrays = {}
    for d, g in ob.groupby("direction"):
        arrays[d] = {
            "ts": g["created_timestamp"].dt.tz_convert(None).astype("datetime64[ns]").astype("int64").to_numpy(),
            "upper": g["upper"].to_numpy(float),
            "lower": g["lower"].to_numpy(float),
            "has_fvg": g["has_fvg"].astype(bool).to_numpy(),
            "has_bos": g["has_bos"].astype(bool).to_numpy(),
            "discount_position": g["discount_position"].to_numpy(float),
        }
    overlaps = []
    fvg_bos = []
    discount = []
    for ev in out.itertuples(index=False):
        arr = arrays.get(ev.direction)
        if arr is None:
            overlaps.append(False)
            fvg_bos.append(False)
            discount.append(np.nan)
            continue
        end_ns = pd.Timestamp(ev.entry_timestamp).tz_convert(None).value
        start_ns = (pd.Timestamp(ev.entry_timestamp) - pd.Timedelta(days=30)).tz_convert(None).value
        s = int(np.searchsorted(arr["ts"], start_ns, side="left"))
        e = int(np.searchsorted(arr["ts"], end_ns, side="right"))
        mask = (arr["lower"][s:e] <= float(ev.upper)) & (arr["upper"][s:e] >= float(ev.lower))
        overlaps.append(bool(mask.any()))
        if mask.any():
            loc = np.where(mask)[0]
            fvg_bos.append(bool((arr["has_fvg"][s:e][loc] & arr["has_bos"][s:e][loc]).any()))
            discount.append(float(np.nanmin(arr["discount_position"][s:e][loc])))
        else:
            fvg_bos.append(False)
            discount.append(np.nan)
    out["ob_overlap_30d"] = overlaps
    out["ob_fvg_bos_overlap_30d"] = fvg_bos
    out["ob_min_discount_position_30d"] = discount
    return out


def add_fvg_features(events: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    ts = m15["timestamp"].dt.tz_convert(None).astype("datetime64[ns]").astype("int64").to_numpy()
    rows = []
    for ev in out.itertuples(index=False):
        end_ns = pd.Timestamp(ev.entry_timestamp).tz_convert(None).value
        i = int(np.searchsorted(ts, end_ns, side="left"))
        start20 = max(0, i - 20)
        start100 = max(0, i - 100)
        w20 = m15.iloc[start20:i]
        w100 = m15.iloc[start100:i]
        side_long = ev.direction == "demand"
        if side_long:
            recent = bool(w20["bull_fvg"].fillna(False).any())
            overlap = fvg_zone_overlap(w100[w100["bull_fvg"].fillna(False)], "bull_fvg_lower", "bull_fvg_upper", float(ev.lower), float(ev.upper))
            opp_recent = bool(w20["bear_fvg"].fillna(False).any())
        else:
            recent = bool(w20["bear_fvg"].fillna(False).any())
            overlap = fvg_zone_overlap(w100[w100["bear_fvg"].fillna(False)], "bear_fvg_lower", "bear_fvg_upper", float(ev.lower), float(ev.upper))
            opp_recent = bool(w20["bull_fvg"].fillna(False).any())
        rows.append({"recent_fvg_20": recent, "zone_fvg_overlap_100": overlap, "opposite_fvg_20": opp_recent})
    return pd.concat([out.reset_index(drop=True), pd.DataFrame(rows).reset_index(drop=True)], axis=1)


def fvg_zone_overlap(gaps: pd.DataFrame, lower_col: str, upper_col: str, zone_lower: float, zone_upper: float) -> bool:
    for gap in gaps.itertuples(index=False):
        lower = float(getattr(gap, lower_col))
        upper = float(getattr(gap, upper_col))
        if lower <= zone_upper and upper >= zone_lower:
            return True
    return False


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
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
    out["h1_stack_96"] = out["same_dir_h1_overlap_96h"].ge(1)
    out["h1_stack_30d"] = out["same_dir_h1_overlap_30d"].ge(1)
    out["intraday_stack_24h"] = out["same_dir_intraday_overlap_24h"].ge(1)
    out["intraday_stack_7d"] = out["same_dir_intraday_overlap_7d"].ge(1)
    out["stack_score3"] = out["stack_score_capped"].ge(3)
    out["stack_7d30d_score3"] = out["stack_score_7d_30d_capped"].ge(3)
    out["trend_aligned"] = (out["direction"].eq("demand") & out["trend_ema50_200"].eq("bull")) | (out["direction"].eq("supply") & out["trend_ema50_200"].eq("bear"))
    out["orb_continuation"] = (out["direction"].eq("demand") & out["orb30_state"].eq("above")) | (out["direction"].eq("supply") & out["orb30_state"].eq("below"))
    out["orb_reversal"] = (out["direction"].eq("demand") & out["orb30_state"].eq("below")) | (out["direction"].eq("supply") & out["orb30_state"].eq("above"))
    out["orb_inside"] = out["orb30_state"].eq("inside")
    out["vp_lvn"] = out["volume_node"].eq("lvn")
    out["vp_hvn"] = out["volume_node"].eq("hvn")
    out["vp_value_low"] = out["profile_location"].eq("value_low_half")
    out["vp_value_high"] = out["profile_location"].eq("value_high_half")
    out["vp_below_value"] = out["profile_location"].eq("below_value")
    out["vp_above_value"] = out["profile_location"].eq("above_value")
    out["ob_quality"] = out["ob_fvg_bos_overlap_30d"].fillna(False).astype(bool)
    out["tight_zone"] = out["zone_width_atr"].le(1.0)
    out["wide_zone"] = out["zone_width_atr"].ge(2.0)
    out["impulse_ge_1p5"] = out["impulse_atr"].ge(1.5)
    out["impulse_ge_2"] = out["impulse_atr"].ge(2.0)
    out["base_body_low"] = out["base_body_ratio"].le(0.35)
    out["base_body_high"] = out["base_body_ratio"].ge(0.65)
    out["ny_main_or_overlap"] = out["entry_session"].isin(["london_ny_overlap", "ny_main"])
    out["avoid_after_hours"] = ~out["entry_session"].eq("after_hours")
    out["ema8_aligned"] = (out["direction"].eq("demand") & out["entry_ema8_distance_atr"].gt(0)) | (out["direction"].eq("supply") & out["entry_ema8_distance_atr"].lt(0))
    return out


def sweep_candidates(df: pd.DataFrame) -> pd.DataFrame:
    base_flags = [
        "dir_demand",
        "dir_supply",
        "cost_le_0p03",
        "cost_le_0p05",
        "risk_ge_10",
        "risk_ge_15",
        "fast_confirm_1",
        "fast_confirm_2",
        "fast_confirm_3",
        "body_ge_45",
        "body_ge_60",
        "body_ge_70",
        "h1_stack_96",
        "h1_stack_30d",
        "intraday_stack_24h",
        "intraday_stack_7d",
        "stack_score3",
        "stack_7d30d_score3",
        "trend_aligned",
        "orb_continuation",
        "orb_reversal",
        "orb_inside",
        "vp_lvn",
        "vp_hvn",
        "zone_contains_poc",
        "zone_overlaps_value",
        "ob_overlap_30d",
        "ob_quality",
        "recent_fvg_20",
        "zone_fvg_overlap_100",
        "opposite_fvg_20",
        "tight_zone",
        "wide_zone",
        "impulse_ge_1p5",
        "impulse_ge_2",
        "base_body_low",
        "base_body_high",
        "ny_main_or_overlap",
        "avoid_after_hours",
        "ema8_aligned",
    ]
    required_sets = [
        ("cost_le_0p03",),
        ("cost_le_0p05",),
        ("cost_le_0p05", "body_ge_45"),
        ("cost_le_0p05", "body_ge_60"),
        ("cost_le_0p05", "fast_confirm_2"),
        ("cost_le_0p05", "fast_confirm_3"),
    ]
    combos = set()
    for req in required_sets:
        combos.add(tuple(sorted(req)))
        remaining = [f for f in base_flags if f not in req]
        for k in range(1, 4):
            for extra in combinations(remaining, k):
                combo = tuple(sorted(req + extra))
                # Avoid impossible direction pair.
                if "dir_demand" in combo and "dir_supply" in combo:
                    continue
                combos.add(combo)
    rows = []
    flag_arrays = {flag: df[flag].fillna(False).astype(bool).to_numpy() for flag in base_flags}
    r = df["net_1r_after_cost"].astype(float).to_numpy()
    winner = df["winner"].astype(bool).to_numpy()
    years = df["year"].astype(int).to_numpy()
    dates = df["date"].astype(str).to_numpy()
    total_winners = max(1, int(winner.sum()))
    total_losers = max(1, int((~winner).sum()))
    for combo in sorted(combos):
        mask = np.ones(len(df), dtype=bool)
        for flag in combo:
            mask &= flag_arrays[flag]
        events = int(mask.sum())
        if events < 80:
            continue
        row = {"rule": "+".join(combo), "filters": len(combo), **evaluate_arrays(r, winner, dates, mask)}
        train_mask = mask & (years <= 2022)
        oos_mask = mask & (years > 2022)
        row.update(prefix_metrics("train", evaluate_arrays(r, winner, dates, train_mask)))
        row.update(prefix_metrics("oos", evaluate_arrays(r, winner, dates, oos_mask)))
        yearly = pd.Series(r[mask]).groupby(years[mask]).sum()
        row["positive_years"] = int((yearly > 0).sum())
        row["negative_years"] = int((yearly < 0).sum())
        row["max_year_profit_share"] = max_year_share(yearly)
        row["winner_keep_pct"] = float(winner[mask].sum() / total_winners)
        row["loser_removed_pct"] = float(1.0 - ((~winner[mask]).sum() / total_losers))
        row["oracle_capture_pct"] = float(row["net_r"] / ORACLE_R)
        row["passes_primary_gate"] = bool(
            row["train_net_r"] > 0
            and row["oos_net_r"] > 0
            and row["oos_profit_factor"] >= 1.25
            and row["positive_years"] >= 6
            and row["max_year_profit_share"] <= 0.35
            and row["events"] >= 150
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["passes_primary_gate", "oos_profit_factor", "net_r"], ascending=[False, False, False])


def evaluate_arrays(r: np.ndarray, winner: np.ndarray, dates: np.ndarray, mask: np.ndarray) -> dict[str, float | int]:
    vals = r[mask]
    if len(vals) == 0:
        return {
            "events": 0,
            "unique_days": 0,
            "winners": 0,
            "losers": 0,
            "net_r": 0.0,
            "avg_r": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_dd_r": 0.0,
            "expectancy_r": 0.0,
        }
    wins = vals[vals > 0]
    losses = vals[vals < 0]
    eq = np.cumsum(vals)
    dd = eq - np.maximum.accumulate(eq)
    return {
        "events": int(len(vals)),
        "unique_days": int(pd.Series(dates[mask]).nunique()),
        "winners": int(winner[mask].sum()),
        "losers": int((~winner[mask]).sum()),
        "net_r": float(vals.sum()),
        "avg_r": float(vals.mean()),
        "expectancy_r": float(vals.mean()),
        "win_rate": float((vals > 0).mean()),
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) else (np.inf if wins.sum() > 0 else 0.0),
        "max_dd_r": float(dd.min()) if len(dd) else 0.0,
    }


def apply_rule(df: pd.DataFrame, rule_row: pd.Series) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for flag in str(rule_row["rule"]).split("+"):
        if flag:
            mask &= df[flag].fillna(False).astype(bool)
    return df[mask].sort_values(["entry_timestamp", "zone_id"]).reset_index(drop=True)


def select_best(candidates: pd.DataFrame) -> pd.Series:
    passed = candidates[candidates["passes_primary_gate"]].copy()
    balanced = passed[
        (passed["events"] >= 300)
        & (passed["positive_years"] >= 7)
        & (passed["oos_profit_factor"] >= 1.50)
        & (passed["max_year_profit_share"] <= 0.35)
    ].copy()
    if not balanced.empty:
        return balanced.sort_values(["net_r", "oos_profit_factor", "events"], ascending=[False, False, False]).iloc[0]
    if not passed.empty:
        return passed.sort_values(["net_r", "oos_profit_factor", "events"], ascending=[False, False, False]).iloc[0]
    return candidates.sort_values(["oos_profit_factor", "net_r", "events"], ascending=[False, False, False]).iloc[0]


def select_quality_candidate(candidates: pd.DataFrame) -> pd.Series:
    passed = candidates[candidates["passes_primary_gate"]].copy()
    if not passed.empty:
        return passed.sort_values(["oos_profit_factor", "net_r", "events"], ascending=[False, False, False]).iloc[0]
    return candidates.sort_values(["oos_profit_factor", "net_r", "events"], ascending=[False, False, False]).iloc[0]


def evaluate(group: pd.DataFrame) -> dict[str, float | int]:
    if group.empty:
        return {
            "events": 0,
            "unique_days": 0,
            "winners": 0,
            "losers": 0,
            "net_r": 0.0,
            "avg_r": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_dd_r": 0.0,
            "expectancy_r": 0.0,
        }
    r = group["net_1r_after_cost"].astype(float)
    wins = r[r > 0]
    losses = r[r < 0]
    eq = r.cumsum()
    dd = eq - eq.cummax()
    return {
        "events": int(len(group)),
        "unique_days": int(group["date"].nunique()),
        "winners": int((r > 0).sum()),
        "losers": int((r < 0).sum()),
        "net_r": float(r.sum()),
        "avg_r": float(r.mean()),
        "expectancy_r": float(r.mean()),
        "win_rate": float((r > 0).mean()),
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) else (np.inf if wins.sum() > 0 else 0.0),
        "max_dd_r": float(dd.min()) if len(dd) else 0.0,
    }


def prefix_metrics(prefix: str, metrics: dict[str, float | int]) -> dict[str, float | int]:
    return {f"{prefix}_{k}": v for k, v in metrics.items()}


def max_year_share(yearly: pd.Series) -> float:
    total = float(yearly.sum())
    if total <= 0:
        return 1.0
    return float(yearly.max() / total)


def yearly_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, group in trades.groupby("year"):
        rows.append({"year": int(year), **evaluate(group)})
    return pd.DataFrame(rows)


def monthly_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for month, group in trades.groupby("month"):
        rows.append({"month": month, **evaluate(group)})
    return pd.DataFrame(rows)


def stress_tests(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for extra_cost in [0.0, 0.01, 0.02, 0.03, 0.05]:
        tmp = trades.copy()
        tmp["net_1r_after_cost"] = tmp["net_1r_after_cost"].astype(float) - extra_cost
        rows.append({"extra_cost_r": extra_cost, **evaluate(tmp)})
    return pd.DataFrame(rows)


def random_benchmark(df: pd.DataFrame, best: pd.Series) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    selected = apply_rule(df, best)
    n = len(selected)
    # Universe respects direction/cost base if present; this is stricter than random from all events.
    universe = df.copy()
    for flag in ["dir_demand", "dir_supply", "cost_le_0p03", "cost_le_0p05"]:
        if flag in str(best["rule"]).split("+"):
            universe = universe[universe[flag].fillna(False).astype(bool)]
    values = universe["net_1r_after_cost"].astype(float).to_numpy()
    samples = np.array([rng.choice(values, size=n, replace=False).sum() for _ in range(5000)])
    return pd.DataFrame(
        [
            {
                "rule": best["rule"],
                "events": n,
                "rule_net_r": float(selected["net_1r_after_cost"].sum()),
                "random_p05": float(np.quantile(samples, 0.05)),
                "random_p50": float(np.quantile(samples, 0.50)),
                "random_p95": float(np.quantile(samples, 0.95)),
                "prob_random_ge_rule": float((samples >= float(selected["net_1r_after_cost"].sum())).mean()),
            }
        ]
    )


def rolling_walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    years = sorted(df["year"].unique())
    for test_year in years:
        train = df[df["year"] < test_year]
        test = df[df["year"] == test_year]
        if len(train) < 500 or len(test) < 50:
            continue
        cand = sweep_candidates(train)
        if cand.empty:
            continue
        best = select_best(cand)
        test_trades = apply_rule(test, best)
        rows.append({"test_year": int(test_year), "selected_rule": best["rule"], **evaluate(test_trades)})
    return pd.DataFrame(rows)


def parameter_neighborhood(df: pd.DataFrame, best: pd.Series) -> pd.DataFrame:
    flags = str(best["rule"]).split("+")
    rows = []
    for drop in ["", *flags]:
        mutated = [f for f in flags if f != drop]
        if not mutated:
            continue
        fake = pd.Series({"rule": "+".join(mutated)})
        trades = apply_rule(df, fake)
        if len(trades) < 80:
            continue
        row = {"mutation": "base" if not drop else f"drop_{drop}", "rule": fake["rule"], **evaluate(trades)}
        yearly = trades.groupby("year")["net_1r_after_cost"].sum()
        row["positive_years"] = int((yearly > 0).sum())
        row["max_year_profit_share"] = max_year_share(yearly)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["net_r", "profit_factor"], ascending=[False, False])


def monte_carlo(trades: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    r = trades["net_1r_after_cost"].astype(float).to_numpy()
    rows = []
    for i in range(3000):
        sample = rng.choice(r, size=len(r), replace=True)
        eq = np.cumsum(sample)
        dd = eq - np.maximum.accumulate(eq)
        rows.append({"run": i, "net_r": float(eq[-1]), "max_dd_r": float(dd.min())})
    out = pd.DataFrame(rows)
    summary = out.quantile([0.01, 0.05, 0.5, 0.95, 0.99]).reset_index(names="quantile")
    return summary


def safe_div(a: float, b: float) -> float:
    if not np.isfinite(a) or not np.isfinite(b) or b == 0:
        return np.nan
    return a / b


def table(df: pd.DataFrame, n: int = 25) -> str:
    if df.empty:
        return "_No rows._"
    shown = df.head(n).copy()
    for col in shown.columns:
        if pd.api.types.is_float_dtype(shown[col]):
            shown[col] = shown[col].map(lambda x: "inf" if np.isinf(x) else f"{x:.4f}")
    headers = list(shown.columns)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, row in shown.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in headers) + " |")
    return "\n".join(lines)


def write_report(
    features: pd.DataFrame,
    candidates: pd.DataFrame,
    best: pd.Series,
    trades: pd.DataFrame,
    yearly: pd.DataFrame,
    monthly: pd.DataFrame,
    stress: pd.DataFrame,
    random: pd.DataFrame,
    walk: pd.DataFrame,
    neighborhood: pd.DataFrame,
    mc: pd.DataFrame,
    quality: pd.Series,
    quality_trades: pd.DataFrame,
    quality_yearly: pd.DataFrame,
    quality_monthly: pd.DataFrame,
    quality_stress: pd.DataFrame,
    quality_random: pd.DataFrame,
    quality_neighborhood: pd.DataFrame,
    quality_mc: pd.DataFrame,
) -> None:
    best_metrics = evaluate(trades)
    quality_metrics = evaluate(quality_trades)
    passed = candidates[candidates["passes_primary_gate"]]
    positive_months = int((monthly["net_r"] > 0).sum()) if not monthly.empty else 0
    quality_positive_months = int((quality_monthly["net_r"] > 0).sum()) if not quality_monthly.empty else 0
    failed_walk_rows = walk[walk["net_r"] <= 0] if not walk.empty and "net_r" in walk.columns else pd.DataFrame()
    verdict = (
        "Research-only. The fixed balanced candidate passes the static train/OOS, yearly, "
        "random, Monte Carlo, cost-stress, and neighborhood checks, but the automatic rolling "
        "walk-forward selector still produced negative test years. That means the edge is promising, "
        "but the selection process itself is not robust enough to promote as a live base yet."
    )
    body = f"""# L99 M15 Filter Edge Sweep

## Status

{verdict}

Universe: `m15_2c_1atr` supply/demand reclaim entries.

| Metric | Value |
|---|---:|
| Universe trades | `{len(features)}` |
| Universe winners | `{int(features['winner'].sum())}` |
| Universe losers | `{int((~features['winner']).sum())}` |
| Universe net R | `{features['net_1r_after_cost'].sum():.2f}` |
| Oracle positive-only R | `{ORACLE_R:.2f}` |

## Selection Policy

The main candidate is selected for balanced revenue, not just headline PF:

- primary gate pass
- `events >= 300`
- `positive_years >= 7`
- `oos_profit_factor >= 1.50`
- `max_year_profit_share <= 0.35`
- then highest total net R

The quality candidate is kept separately as the highest-OOS-PF passing candidate.

## Balanced Candidate

Rule:

`{best['rule']}`

| Metric | Value |
|---|---:|
| Trades retained | `{best_metrics['events']}` |
| Winners kept | `{best_metrics['winners']}` |
| Losers kept | `{best_metrics['losers']}` |
| Net R | `{best_metrics['net_r']:.2f}` |
| PF | `{best_metrics['profit_factor']:.2f}` |
| WR | `{best_metrics['win_rate']:.2%}` |
| Expectancy | `{best_metrics['expectancy_r']:.4f}R` |
| Max DD | `{best_metrics['max_dd_r']:.2f}R` |
| Oracle capture | `{best_metrics['net_r'] / ORACLE_R:.2%}` |
| Positive months | `{positive_months} / {len(monthly)}` |

## Quality Candidate

Rule:

`{quality['rule']}`

| Metric | Value |
|---|---:|
| Trades retained | `{quality_metrics['events']}` |
| Winners kept | `{quality_metrics['winners']}` |
| Losers kept | `{quality_metrics['losers']}` |
| Net R | `{quality_metrics['net_r']:.2f}` |
| PF | `{quality_metrics['profit_factor']:.2f}` |
| WR | `{quality_metrics['win_rate']:.2%}` |
| Expectancy | `{quality_metrics['expectancy_r']:.4f}R` |
| Max DD | `{quality_metrics['max_dd_r']:.2f}R` |
| Oracle capture | `{quality_metrics['net_r'] / ORACLE_R:.2%}` |
| Positive months | `{quality_positive_months} / {len(quality_monthly)}` |

## Primary Gate Passes

{table(passed, 30)}

## Top Candidates

{table(candidates, 40)}

## Yearly

{table(yearly, 12)}

## Monthly

{table(monthly, 30)}

## Cost Stress

{table(stress, 10)}

## Quality Candidate Cost Stress

{table(quality_stress, 10)}

## Random Benchmark

{table(random, 5)}

## Quality Candidate Random Benchmark

{table(quality_random, 5)}

## Rolling Walk-Forward

{table(walk, 20)}

Negative rolling years:

{table(failed_walk_rows, 10)}

## Parameter Neighborhood

{table(neighborhood, 20)}

## Quality Candidate Parameter Neighborhood

{table(quality_neighborhood, 20)}

## Monte Carlo

{table(mc, 10)}

## Quality Candidate Monte Carlo

{table(quality_mc, 10)}

## Verdict

{verdict}

The fixed balanced candidate is the better answer to "more PnL and more trades." The quality candidate is the better answer to "highest PF." Neither should be promoted until the walk-forward selection problem is solved.

## Files

- `m15_2c_1atr_feature_matrix.csv`
- `m15_filter_candidate_sweep.csv`
- `best_candidate_trades.csv`
- `best_candidate_yearly.csv`
- `best_candidate_monthly.csv`
- `best_candidate_cost_stress.csv`
- `best_candidate_random_benchmark.csv`
- `rolling_walk_forward.csv`
- `parameter_neighborhood.csv`
- `monte_carlo.csv`
- `quality_candidate_trades.csv`
- `quality_candidate_yearly.csv`
- `quality_candidate_monthly.csv`
- `quality_candidate_cost_stress.csv`
- `quality_candidate_random_benchmark.csv`
- `quality_candidate_parameter_neighborhood.csv`
- `quality_candidate_monte_carlo.csv`
"""
    (OUT / "L99_M15_FILTER_EDGE_SWEEP.md").write_text(body, encoding="utf-8")


if __name__ == "__main__":
    main()
