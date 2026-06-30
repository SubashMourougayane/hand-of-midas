# XAU-SDR-001 Manifest

## Canonical Files

- Config: `config/xau_sdr_001_config.json`
- Rulebook: `docs/STRATEGY_RULEBOOK.md`
- Edge summary: `docs/EDGE_SUMMARY.md`
- Runbook: `docs/RUNBOOK.md`
- Frozen trades: `results/base/base_sleeve1_trades.csv`
- Frozen summary: `results/base/base_sleeve1_summary.csv`
- Stress report: `docs/XAU_SDR_001_BASE_STRESS_TEST.md`

## Folder Responsibilities

- `results/base/` contains only frozen base outputs.
- `results/stress/` contains stress tests against that base.
- `research_evidence/` contains evidence that led to the promotion.
- `code/` contains runnable/reporting code and source snapshots.
- `archive/` contains superseded notes copied for memory.

## Base Integrity Rule

Any change to base signal rules, filters, data, cost model, sizing model, or execution model must create a new candidate ID.

Use:

- `XAU-SDR-002` for a promoted strategy successor.
- `XAU-SDR-001-EXP-*` for experiments.

