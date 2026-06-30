from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/Users/subash/Documents/QUANT/SupplyDemand")
INTRADAY_DIR = ROOT / "research" / "l99_intraday_sd_zone_research"
H1_DIR = ROOT / "research" / "edge_discovery_l99"
OUT = ROOT / "research" / "l99_multitimeframe_sd_confluence"
SEED = 42


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    events = load_events()
    intraday_zones = load_intraday_zones()
    h1_zones = load_h1_zones()

    scored = score_confluence(events, intraday_zones, h1_zones)
    scored.to_csv(OUT / "multitimeframe_sd_confluence_events.csv", index=False)

    feature_tables = feature_summary(scored)
    rules = validate_rules(scored)
    random = random_benchmark(scored, rules)

    feature_tables.to_csv(OUT / "multitimeframe_sd_confluence_feature_tables.csv", index=False)
    rules.to_csv(OUT / "multitimeframe_sd_confluence_rule_validation.csv", index=False)
    random.to_csv(OUT / "multitimeframe_sd_confluence_random_benchmark.csv", index=False)

    summary = {
        "events": int(len(scored)),
        "unique_days": int(scored["date"].nunique()),
        "best_rules_by_net_r": rules.sort_values("net_r", ascending=False).head(10).to_dict("records"),
        "robust_passes": rules[rules["robust_pass"]].to_dict("records"),
    }
    (OUT / "multitimeframe_sd_confluence_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(feature_tables, rules, random)
    print(f"Wrote {OUT}")


def load_events() -> pd.DataFrame:
    path = INTRADAY_DIR / "intraday_sd_reclaim_events.csv"
    df = pd.read_csv(path)
    for col in ["created_timestamp", "touch_timestamp", "entry_timestamp"]:
        df[col] = pd.to_datetime(df[col], utc=True)
    df["year"] = df["entry_timestamp"].dt.year
    df["date"] = df["entry_timestamp"].dt.date.astype(str)
    df["month"] = df["entry_timestamp"].dt.to_period("M").astype(str)
    return df


def load_intraday_zones() -> pd.DataFrame:
    path = INTRADAY_DIR / "intraday_sd_zones.csv"
    df = pd.read_csv(path)
    df["created_timestamp"] = pd.to_datetime(df["created_timestamp"], utc=True)
    df = df.rename(columns={"zone_id": "src_zone_id"})
    return df


def load_h1_zones() -> pd.DataFrame:
    path = H1_DIR / "sd_zone_universe.csv"
    df = pd.read_csv(path)
    df["created_timestamp"] = pd.to_datetime(df["created_timestamp"], utc=True)
    df = df.rename(columns={"zone_id": "src_zone_id"})
    df["zone_tf"] = "h1"
    return df


def score_confluence(events: pd.DataFrame, intraday_zones: pd.DataFrame, h1_zones: pd.DataFrame) -> pd.DataFrame:
    rows = []
    intraday_by_dir = prep_zone_arrays(intraday_zones)
    h1_by_dir = prep_zone_arrays(h1_zones)

    for idx, ev in events.iterrows():
        if idx and idx % 5000 == 0:
            print(f"scored {idx:,}/{len(events):,}")
        entry_ts = ev["entry_timestamp"]

        intra = count_overlaps(
            intraday_by_dir[ev["direction"]],
            event_upper=float(ev["upper"]),
            event_lower=float(ev["lower"]),
            entry_ts=entry_ts,
            lookback_hours=24,
            event_zone_id=int(ev["zone_id"]),
            event_spec=str(ev["spec_name"]),
        )
        intra_7d = count_overlaps(
            intraday_by_dir[ev["direction"]],
            event_upper=float(ev["upper"]),
            event_lower=float(ev["lower"]),
            entry_ts=entry_ts,
            lookback_hours=168,
            event_zone_id=int(ev["zone_id"]),
            event_spec=str(ev["spec_name"]),
        )
        h1 = count_overlaps(
            h1_by_dir[ev["direction"]],
            event_upper=float(ev["upper"]),
            event_lower=float(ev["lower"]),
            entry_ts=entry_ts,
            lookback_hours=96,
            event_zone_id=None,
            event_spec=None,
        )
        h1_30d = count_overlaps(
            h1_by_dir[ev["direction"]],
            event_upper=float(ev["upper"]),
            event_lower=float(ev["lower"]),
            entry_ts=entry_ts,
            lookback_hours=720,
            event_zone_id=None,
            event_spec=None,
        )

        row = ev.to_dict()
        row.update(
            {
                "same_dir_intraday_overlap_24h": intra["overlap_count"],
                "same_dir_intraday_distinct_specs_24h": intra["distinct_specs"],
                "same_dir_intraday_distinct_tfs_24h": intra["distinct_tfs"],
                "same_dir_intraday_max_overlap_ratio_24h": intra["max_overlap_ratio"],
                "same_dir_intraday_overlap_7d": intra_7d["overlap_count"],
                "same_dir_intraday_distinct_specs_7d": intra_7d["distinct_specs"],
                "same_dir_intraday_distinct_tfs_7d": intra_7d["distinct_tfs"],
                "same_dir_intraday_max_overlap_ratio_7d": intra_7d["max_overlap_ratio"],
                "same_dir_h1_overlap_96h": h1["overlap_count"],
                "same_dir_h1_distinct_specs_96h": h1["distinct_specs"],
                "same_dir_h1_max_overlap_ratio_96h": h1["max_overlap_ratio"],
                "same_dir_h1_overlap_30d": h1_30d["overlap_count"],
                "same_dir_h1_distinct_specs_30d": h1_30d["distinct_specs"],
                "same_dir_h1_max_overlap_ratio_30d": h1_30d["max_overlap_ratio"],
                "has_intraday_stack": intra["overlap_count"] >= 1,
                "has_intraday_stack_7d": intra_7d["overlap_count"] >= 1,
                "has_cross_tf_intraday_stack": intra["distinct_tfs"] >= 1,
                "has_h1_stack": h1["overlap_count"] >= 1,
                "has_h1_stack_30d": h1_30d["overlap_count"] >= 1,
                "stack_score": intra["overlap_count"] + 2 * h1["overlap_count"],
                "stack_score_capped": min(intra["overlap_count"], 3) + 2 * min(h1["overlap_count"], 2),
                "stack_score_7d_30d": intra_7d["overlap_count"] + 2 * h1_30d["overlap_count"],
                "stack_score_7d_30d_capped": min(intra_7d["overlap_count"], 3) + 2 * min(h1_30d["overlap_count"], 2),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def prep_zone_arrays(zones: pd.DataFrame) -> dict[str, dict[str, np.ndarray]]:
    out = {}
    for direction, grp in zones.sort_values("created_timestamp").groupby("direction"):
        ts_ns = grp["created_timestamp"].dt.tz_convert(None).astype("datetime64[ns]").astype("int64").to_numpy()
        out[direction] = {
            "ts": ts_ns,
            "upper": grp["upper"].astype(float).to_numpy(),
            "lower": grp["lower"].astype(float).to_numpy(),
            "zone_id": grp["src_zone_id"].astype(int).to_numpy(),
            "spec": grp["spec_name"].astype(str).to_numpy(),
            "tf": grp.get("zone_tf", pd.Series(["h1"] * len(grp))).astype(str).to_numpy(),
        }
    return out


def count_overlaps(
    arr: dict[str, np.ndarray],
    event_upper: float,
    event_lower: float,
    entry_ts: pd.Timestamp,
    lookback_hours: int,
    event_zone_id: int | None,
    event_spec: str | None,
) -> dict[str, float | int]:
    entry_ns = entry_ts.value
    start_ns = (entry_ts - pd.Timedelta(hours=lookback_hours)).value
    left = np.searchsorted(arr["ts"], start_ns, side="left")
    right = np.searchsorted(arr["ts"], entry_ns, side="right")
    if right <= left:
        return empty_overlap()

    upper = arr["upper"][left:right]
    lower = arr["lower"][left:right]
    mask = (lower <= event_upper) & (upper >= event_lower)
    if event_zone_id is not None:
        zone_ids = arr["zone_id"][left:right]
        specs = arr["spec"][left:right]
        mask &= ~((zone_ids == event_zone_id) & (specs == event_spec))

    if not mask.any():
        return empty_overlap()

    upper_m = upper[mask]
    lower_m = lower[mask]
    overlap = np.minimum(upper_m, event_upper) - np.maximum(lower_m, event_lower)
    event_width = max(event_upper - event_lower, 1e-9)
    ratios = np.maximum(overlap, 0) / event_width
    specs_m = arr["spec"][left:right][mask]
    tf_m = arr["tf"][left:right][mask]
    return {
        "overlap_count": int(mask.sum()),
        "distinct_specs": int(pd.Series(specs_m).nunique()),
        "distinct_tfs": int(pd.Series(tf_m).nunique()),
        "max_overlap_ratio": float(np.max(ratios)),
    }


def empty_overlap() -> dict[str, float | int]:
    return {"overlap_count": 0, "distinct_specs": 0, "distinct_tfs": 0, "max_overlap_ratio": 0.0}


def metrics(df: pd.DataFrame) -> dict[str, float | int]:
    r = df["net_1r_after_cost"].astype(float)
    wins = r[r > 0]
    losses = r[r < 0]
    return {
        "events": int(len(df)),
        "unique_days": int(df["date"].nunique()) if len(df) else 0,
        "net_r": float(r.sum()) if len(df) else 0.0,
        "avg_r": float(r.mean()) if len(df) else 0.0,
        "win_rate": float((r > 0).mean()) if len(df) else 0.0,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) else (np.inf if wins.sum() > 0 else 0.0),
        "avg_cost_r": float(df["cost_r"].mean()) if len(df) else 0.0,
        "median_risk_units": float(df["risk_units"].median()) if len(df) else 0.0,
    }


def feature_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    bins = [
        ("stack_score", [-1, 0, 1, 2, 3, 5, 999], ["0", "1", "2", "3", "4-5", "6+"]),
        ("stack_score_7d_30d_capped", [-1, 0, 1, 2, 3, 5, 999], ["0", "1", "2", "3", "4-5", "6+"]),
        ("same_dir_intraday_overlap_24h", [-1, 0, 1, 2, 3, 5, 999], ["0", "1", "2", "3", "4-5", "6+"]),
        ("same_dir_intraday_overlap_7d", [-1, 0, 1, 2, 3, 5, 999], ["0", "1", "2", "3", "4-5", "6+"]),
        ("same_dir_h1_overlap_96h", [-1, 0, 1, 2, 999], ["0", "1", "2", "3+"]),
        ("same_dir_h1_overlap_30d", [-1, 0, 1, 2, 999], ["0", "1", "2", "3+"]),
    ]
    for col, edges, labels in bins:
        tmp = df.copy()
        tmp["_bucket"] = pd.cut(tmp[col], bins=edges, labels=labels)
        for bucket, group in tmp.groupby("_bucket", observed=False):
            if len(group) == 0:
                continue
            row = {"feature": col, "value": str(bucket)}
            row.update(metrics(group))
            rows.append(row)
    for col in ["direction", "spec_name", "cost_bucket", "has_h1_stack", "has_h1_stack_30d", "has_intraday_stack", "has_intraday_stack_7d"]:
        for value, group in df.groupby(col):
            row = {"feature": col, "value": str(value)}
            row.update(metrics(group))
            rows.append(row)
    return pd.DataFrame(rows).sort_values(["net_r", "profit_factor"], ascending=[False, False])


def validate_rules(df: pd.DataFrame) -> pd.DataFrame:
    rule_defs = {
        "all": lambda x: np.ones(len(x), dtype=bool),
        "intraday_stack": lambda x: x["same_dir_intraday_overlap_24h"] >= 1,
        "intraday_stack_2plus": lambda x: x["same_dir_intraday_overlap_24h"] >= 2,
        "intraday_stack_4plus": lambda x: x["same_dir_intraday_overlap_24h"] >= 4,
        "h1_stack": lambda x: x["same_dir_h1_overlap_96h"] >= 1,
        "h1_stack_2plus": lambda x: x["same_dir_h1_overlap_96h"] >= 2,
        "intraday_and_h1_stack": lambda x: (x["same_dir_intraday_overlap_24h"] >= 1) & (x["same_dir_h1_overlap_96h"] >= 1),
        "stack_score_3plus": lambda x: x["stack_score_capped"] >= 3,
        "stack_score_5plus": lambda x: x["stack_score_capped"] >= 5,
        "stack_score_3plus_cost_le_0p03": lambda x: (x["stack_score_capped"] >= 3) & (x["cost_r"] <= 0.03),
        "h1_stack_cost_le_0p03": lambda x: (x["same_dir_h1_overlap_96h"] >= 1) & (x["cost_r"] <= 0.03),
        "intraday_stack_cost_le_0p03": lambda x: (x["same_dir_intraday_overlap_24h"] >= 1) & (x["cost_r"] <= 0.03),
        "intraday_stack_7d": lambda x: x["same_dir_intraday_overlap_7d"] >= 1,
        "intraday_stack_7d_2plus": lambda x: x["same_dir_intraday_overlap_7d"] >= 2,
        "h1_stack_30d": lambda x: x["same_dir_h1_overlap_30d"] >= 1,
        "h1_stack_30d_2plus": lambda x: x["same_dir_h1_overlap_30d"] >= 2,
        "intraday_7d_and_h1_30d": lambda x: (x["same_dir_intraday_overlap_7d"] >= 1) & (x["same_dir_h1_overlap_30d"] >= 1),
        "stack_7d_30d_score_3plus": lambda x: x["stack_score_7d_30d_capped"] >= 3,
        "stack_7d_30d_score_5plus": lambda x: x["stack_score_7d_30d_capped"] >= 5,
        "stack_7d_30d_score_3plus_cost_le_0p03": lambda x: (x["stack_score_7d_30d_capped"] >= 3) & (x["cost_r"] <= 0.03),
    }
    universes = [("all_specs", df)]
    for spec in sorted(df["spec_name"].unique()):
        universes.append((spec, df[df["spec_name"] == spec]))

    rows = []
    for universe_name, universe in universes:
        for direction in ["all", "demand", "supply"]:
            base = universe if direction == "all" else universe[universe["direction"] == direction]
            if len(base) == 0:
                continue
            for rule_name, rule_fn in rule_defs.items():
                group = base[rule_fn(base)]
                if len(group) < 50:
                    continue
                row = {"universe": universe_name, "direction": direction, "rule": rule_name}
                row.update(metrics(group))
                train = group[group["year"] <= 2022]
                oos = group[group["year"] > 2022]
                yearly = group.groupby("year")["net_1r_after_cost"].sum()
                row.update(
                    {
                        "train_net_r": float(train["net_1r_after_cost"].sum()),
                        "oos_net_r": float(oos["net_1r_after_cost"].sum()),
                        "positive_years": int((yearly > 0).sum()),
                        "negative_years": int((yearly < 0).sum()),
                    }
                )
                row["robust_pass"] = bool(
                    row["events"] >= 150
                    and row["train_net_r"] > 0
                    and row["oos_net_r"] > 0
                    and row["profit_factor"] >= 1.15
                    and row["positive_years"] >= 6
                )
                rows.append(row)
    return pd.DataFrame(rows).sort_values(["robust_pass", "net_r", "profit_factor"], ascending=[False, False, False])


def random_benchmark(df: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows = []
    for _, rule in rules.head(25).iterrows():
        universe = df.copy()
        if rule["universe"] != "all_specs":
            universe = universe[universe["spec_name"] == rule["universe"]]
        if rule["direction"] != "all":
            universe = universe[universe["direction"] == rule["direction"]]
        n = int(rule["events"])
        if n <= 0 or len(universe) < n:
            continue
        values = universe["net_1r_after_cost"].astype(float).to_numpy()
        samples = np.array([rng.choice(values, size=n, replace=False).sum() for _ in range(3000)])
        rows.append(
            {
                "universe": rule["universe"],
                "direction": rule["direction"],
                "rule": rule["rule"],
                "events": n,
                "rule_net_r": float(rule["net_r"]),
                "random_p05": float(np.quantile(samples, 0.05)),
                "random_p50": float(np.quantile(samples, 0.50)),
                "random_p95": float(np.quantile(samples, 0.95)),
                "prob_random_ge_rule": float((samples >= float(rule["net_r"])).mean()),
            }
        )
    return pd.DataFrame(rows)


def table(df: pd.DataFrame, n: int = 20) -> str:
    if df.empty:
        return "_No rows._"
    shown = df.head(n).copy()
    for col in shown.columns:
        if pd.api.types.is_float_dtype(shown[col]):
            shown[col] = shown[col].map(lambda x: "inf" if np.isinf(x) else f"{x:.4f}")
    headers = list(shown.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in shown.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in headers) + " |")
    return "\n".join(lines)


def write_report(feature_tables: pd.DataFrame, rules: pd.DataFrame, random: pd.DataFrame) -> None:
    robust = rules[rules["robust_pass"]]
    text = f"""# L99 Multi-Timeframe Supply/Demand Confluence Research

## Status

Research-only. Frozen base unchanged.

This branch tests whether the real supply/demand edge is not simply a single zone, but a **stacked price area**:

- M15/M30 intraday zone reclaim event.
- Same-direction intraday zones overlapping the event's zone during the prior 24h.
- Same-direction H1 zones overlapping the event's zone during the prior 96h.
- Outcome remains the existing 1R bracket after estimated XAUUSD cost.

## Feature Tables

{table(feature_tables, 35)}

## Rule Validation

{table(rules, 35)}

## Random Benchmark

{table(random, 25)}

## Robust Passes

{table(robust, 20)}

## Interpretation

A confluence rule is promotable only if it is positive in train and OOS, clears PF 1.15, has at least 150 trades, and is positive in at least 6 years.

If the best confluence rows are still thin, then the conclusion is severe but useful: price-area stacking is not enough by itself. The next research step should model path behavior after the tap: rejection speed, volume/ATR expansion after reclaim, and whether the zone becomes accepted or rejected after 15-60 minutes.

## Files

- `multitimeframe_sd_confluence_events.csv`
- `multitimeframe_sd_confluence_feature_tables.csv`
- `multitimeframe_sd_confluence_rule_validation.csv`
- `multitimeframe_sd_confluence_random_benchmark.csv`
- `multitimeframe_sd_confluence_summary.json`
"""
    (OUT / "L99_MULTITIMEFRAME_SD_CONFLUENCE.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
