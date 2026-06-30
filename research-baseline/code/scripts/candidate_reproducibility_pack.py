from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research" / "candidate_reproducibility"

HIERARCHY = ROOT / "research" / "strategy_candidate_hierarchy" / "strategy_candidate_hierarchy.csv"
META = ROOT / "research" / "meta_stack_candidate_comparison" / "candidate_comparison_summary.csv"


COMMANDS = {
    "SUPPLY_DEMAND_DEMAND_ONLY_EDGE_V1": [
        "PYTHONPATH=src python3 scripts/run_supply_demand_concept.py",
        "python3 scripts/strategy_candidate_hierarchy.py",
    ],
    "orb_aplus_capped_only__risk_1p25%__uncapped__unit_cost_model": [
        "python3 scripts/meta_stack_risk_calibration.py",
        "python3 scripts/meta_stack_candidate_comparison.py",
        "python3 scripts/strategy_candidate_hierarchy.py",
    ],
    "orb_aplus_capped_only__risk_1p00%__dd5_half_recover2__unit_cost_model": [
        "python3 scripts/meta_stack_risk_calibration.py",
        "python3 scripts/meta_stack_candidate_comparison.py",
        "python3 scripts/paper_live_readiness_gate.py",
        "python3 scripts/paper_live_journal_runner.py",
    ],
    "additive_allow_overlap__risk_1p25%__tiered_dd_3_6__unit_cost_model": [
        "python3 scripts/meta_stack_risk_calibration.py",
        "python3 scripts/meta_stack_candidate_comparison.py",
    ],
    "non_overlap_orb_priority__risk_2p00%__dd3_half_recover1__unit_cost_model": [
        "python3 scripts/meta_stack_risk_calibration.py",
        "python3 scripts/meta_stack_candidate_comparison.py",
    ],
}

SOURCE_FILES = {
    "SUPPLY_DEMAND_DEMAND_ONLY_EDGE_V1": [
        "outputs/new_base/SUPPLY_DEMAND_CONCEPT_NEW_BASE.md",
        "outputs/new_base/supply_demand_concept_summary.json",
        "outputs/new_base/supply_demand_concept_trades.csv",
        "outputs/new_base/supply_demand_concept_yearly.csv",
    ],
    "orb_aplus_capped_only__risk_1p25%__uncapped__unit_cost_model": [
        "research/meta_stack_candidate_comparison/META_STACK_CANDIDATE_COMPARISON.md",
        "research/meta_stack_candidate_comparison/candidate_comparison_summary.csv",
        "research/meta_stack_candidate_comparison/candidate_comparison_yearly.csv",
        "research/meta_stack_risk_calibration/meta_stack_risk_calibration_summary.csv",
        "research/meta_stack_risk_calibration/meta_stack_risk_calibration_selector.csv",
    ],
    "orb_aplus_capped_only__risk_1p00%__dd5_half_recover2__unit_cost_model": [
        "research/meta_stack_candidate_comparison/META_STACK_CANDIDATE_COMPARISON.md",
        "research/paper_live_readiness/PAPER_LIVE_READINESS_GATE.md",
        "research/paper_live_journal/PAPER_LIVE_JOURNAL_RUNNER.md",
        "research/meta_stack_candidate_comparison/candidate_comparison_summary.csv",
        "research/meta_stack_candidate_comparison/candidate_comparison_yearly.csv",
    ],
    "additive_allow_overlap__risk_1p25%__tiered_dd_3_6__unit_cost_model": [
        "research/meta_stack_candidate_comparison/META_STACK_CANDIDATE_COMPARISON.md",
        "research/meta_stack_candidate_comparison/candidate_comparison_summary.csv",
    ],
    "non_overlap_orb_priority__risk_2p00%__dd3_half_recover1__unit_cost_model": [
        "research/meta_stack_candidate_comparison/META_STACK_CANDIDATE_COMPARISON.md",
        "research/meta_stack_candidate_comparison/candidate_comparison_summary.csv",
    ],
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    hierarchy = pd.read_csv(HIERARCHY)
    meta = pd.read_csv(META)
    rows = build_rows(hierarchy, meta)
    summary = build_summary(rows)

    rows.to_csv(OUT / "candidate_reproducibility_matrix.csv", index=False)
    (OUT / "candidate_reproducibility_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    write_report(rows, summary)
    print(markdown_table(display(rows[["candidate", "status", "role", "net_pnl_usd", "profit_factor", "reproducibility_status"]])))


def build_rows(hierarchy: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    selected_statuses = {
        "PROMOTED_BASE",
        "RESEARCH_CANDIDATE",
        "PAPER_CANDIDATE",
        "REJECT_TAIL_RISK",
    }
    selected = hierarchy[hierarchy["status"].astype(str).isin(selected_statuses)].copy()
    meta_lookup = meta.set_index("portfolio_variant").to_dict("index") if not meta.empty else {}
    rows = []
    for row in selected.to_dict("records"):
        candidate = str(row["candidate"])
        files = SOURCE_FILES.get(candidate, [str(row.get("source_report", ""))])
        commands = COMMANDS.get(candidate, ["python3 scripts/run_research_audit_suite.py"])
        missing_files = [path for path in files if path and not (ROOT / path).exists()]
        meta_row = meta_lookup.get(candidate, {})
        rows.append(
            {
                "candidate": candidate,
                "role": row["role"],
                "status": row["status"],
                "scope": row["scope"],
                "trades": int(row["trades"]),
                "net_pnl_usd": float(row["net_pnl_usd"]),
                "win_rate": safe_float(row.get("win_rate")),
                "profit_factor": safe_float(row.get("profit_factor")),
                "max_drawdown_pct": safe_float(row.get("max_drawdown_pct")),
                "positive_years": safe_float(row.get("positive_years")),
                "negative_years": safe_float(row.get("negative_years")),
                "gross_pnl_usd": safe_float(meta_row.get("gross_pnl_usd")),
                "execution_cost_usd": safe_float(meta_row.get("execution_cost_usd")),
                "mc_selector_pass": meta_row.get("mc_selector_pass", ""),
                "trade_net_p05": safe_float(meta_row.get("trade_net_p05")),
                "trade_prob_dd_worse_15pct": safe_float(meta_row.get("trade_prob_dd_worse_15pct")),
                "source_files": "; ".join(files),
                "missing_source_files": "; ".join(missing_files),
                "rerun_commands": " && ".join(commands),
                "promotion_read": row["promotion_read"],
                "reproducibility_status": "PASS" if not missing_files else "MISSING_FILES",
            }
        )
    return pd.DataFrame(rows)


def build_summary(rows: pd.DataFrame) -> dict[str, object]:
    status_counts = rows["reproducibility_status"].value_counts().to_dict() if not rows.empty else {}
    best = rows[rows["status"].eq("RESEARCH_CANDIDATE")].sort_values("net_pnl_usd", ascending=False).head(1)
    paper = rows[rows["status"].eq("PAPER_CANDIDATE")].head(1)
    return {
        "status": "candidate_reproducibility_audited",
        "candidates_checked": int(len(rows)),
        "status_counts": status_counts,
        "best_research_candidate": best.iloc[0].to_dict() if not best.empty else {},
        "paper_candidate": paper.iloc[0].to_dict() if not paper.empty else {},
    }


def write_report(rows: pd.DataFrame, summary: dict[str, object]) -> None:
    best = summary.get("best_research_candidate", {})
    paper = summary.get("paper_candidate", {})
    body = f"""# Candidate Reproducibility Pack

## Status

Research-only. Frozen base unchanged.

This pack records the exact current candidate metrics, source files, and rerun commands for the promoted base, winning research candidate, safer paper/live candidate, more-trades branch, and rejected high-revenue branch.

## Main Read

- Candidates checked: `{summary["candidates_checked"]}`
- Reproducibility status counts: `{summary["status_counts"]}`
- Winning research candidate: `{best.get("candidate", "none")}`
- Winning research candidate net PnL: `${float(best.get("net_pnl_usd", 0.0)):,.2f}`
- Safer paper/live candidate: `{paper.get("candidate", "none")}`
- Safer paper/live candidate net PnL: `${float(paper.get("net_pnl_usd", 0.0)):,.2f}`

## Candidate Matrix

{markdown_table(display(rows))}

## Reproduction Order

For the full current-state proof:

```bash
python3 scripts/run_research_audit_suite.py
```

For individual candidate evidence, use the `rerun_commands` column. These commands regenerate the current report chain; they do not promote research candidates or mutate the frozen base.

## Files

- `candidate_reproducibility_matrix.csv`
- `candidate_reproducibility_summary.json`
"""
    (OUT / "CANDIDATE_REPRODUCIBILITY_PACK.md").write_text(body, encoding="utf-8")


def safe_float(value: object) -> float:
    try:
        if pd.isna(value):
            return float("nan")
        return float(value)
    except Exception:
        return float("nan")


def display(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in ["net_pnl_usd", "gross_pnl_usd", "execution_cost_usd", "trade_net_p05"]:
        if column in out:
            out[column] = out[column].map(lambda value: "" if pd.isna(value) else f"${float(value):,.2f}")
    for column in ["win_rate", "max_drawdown_pct", "trade_prob_dd_worse_15pct"]:
        if column in out:
            out[column] = out[column].map(lambda value: "" if pd.isna(value) else f"{float(value):.2%}")
    for column in ["profit_factor"]:
        if column in out:
            out[column] = out[column].map(lambda value: "" if pd.isna(value) else f"{float(value):.4f}")
    return out


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    rows = [list(frame.columns)] + frame.fillna("").astype(str).values.tolist()
    widths = [max(len(str(row[index])) for row in rows) for index in range(len(rows[0]))]
    header = "| " + " | ".join(str(rows[0][index]).ljust(widths[index]) for index in range(len(widths))) + " |"
    sep = "| " + " | ".join("-" * widths[index] for index in range(len(widths))) + " |"
    body = [
        "| " + " | ".join(str(row[index]).ljust(widths[index]) for index in range(len(widths))) + " |"
        for row in rows[1:]
    ]
    return "\n".join([header, sep, *body])


if __name__ == "__main__":
    main()
