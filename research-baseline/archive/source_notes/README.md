# SupplyDemand

Self-contained XAUUSD supply/demand strategy project.

## Active New Base

`SUPPLY_DEMAND_DEMAND_ONLY_EDGE_V1`

This is the corrected demand-only concept base promoted from the direction OOS pass:

- H1 supply/demand zones
- Demand zones only / long side only
- M15 EMA8 + engulfing confirmation
- `confirmation_mode = engulfing`
- `zone_expiry_bars = None`
- `zone_expiry_hours = 48`
- `enforce_h1_trend = False`
- `max_impulse_pullback_pct = 0.50`
- `min_target_r = 0.0`
- First target: current nearest prior swing target
- Exit `50%` at T1
- Remaining `50%` becomes a runner
- Runner stop moves to breakeven after T1
- Runner has no fixed target
- Runner max hold is `24h` wall-clock
- Execution: M15 close trigger + close fill
- Direction handling: keep the original both-side no-overlap arbitration, then execute only demand rows. This preserves the exact 211-trade OOS-validated result.
- Active reporting starts at `2019-06-03 15:00:00+00:00` to exclude the daily-only source segment
- `swing_right = 2`; configs with `swing_right < 1` are rejected

## Latest Active Baseline Run

Using `$50` fixed risk for reporting:

- Data scope: from `2019-06-03 15:00:00+00:00`
- Trades: `211`
- Net PnL: `$2,186.91`
- Win rate: `69.19%`
- Profit factor: `2.38`
- Expectancy: `0.2073R/trade`

Output:

- `outputs/new_base/SUPPLY_DEMAND_CONCEPT_NEW_BASE.md`
- `outputs/new_base/supply_demand_concept_trades.csv`
- `outputs/new_base/supply_demand_concept_summary.json`

## Folder Layout

- `src/`: strategy and loader code
- `scripts/`: runnable research and report scripts
- `tests/`: strategy tests
- `data/raw/`: local XAUUSD input data
- `outputs/new_base/`: active new-base output
- `research/`: rerunnable research variants
- `reports/`: regenerated audit reports
- `archive/f28_supply_demand_review/`: old frozen base, audits, sweeps, and historical research

## Run

From this folder:

```bash
python3 -m pytest tests
PYTHONPATH=src python3 scripts/run_supply_demand_concept.py
```

Optional research reruns:

```bash
PYTHONPATH=src python3 scripts/f28_working_baseline_trade_journal.py
PYTHONPATH=src python3 scripts/f28_partial_tp_research.py
PYTHONPATH=src python3 scripts/f28_trailing_base_filter_research.py
```

Current research audit suite:

```bash
python3 scripts/run_research_audit_suite.py
```

This regenerates the raw-data audit, market-data quality audit, import contract, missing-market source scout, onboarding manifest report, external source map, research atlas, combination/stack/parameter coverage audits, market coverage, candidate hierarchy, paper/live gate, goal scorecard, and then runs the test suite. Output:

- `research/research_audit_suite/RESEARCH_AUDIT_SUITE.md`
- `research/research_audit_suite/research_audit_suite_results.json`

Missing-market source plan:

- `research/market_data_source_scout/MARKET_DATA_SOURCE_SCOUT.md`

Normalize non-native M1 data into the project contract:

```bash
PYTHONPATH=src python3 scripts/normalize_market_data.py /path/to/source.csv --symbol EURUSD --format auto --spread-points 3
```

For multiple market files, use the onboarding manifest:

```bash
PYTHONPATH=src python3 scripts/market_data_onboarding.py
```

Then edit `research/market_data_onboarding/market_data_onboarding_manifest.csv`, enable rows with real source paths, and rerun the command.

Onboarding only marks a file `NORMALIZED_READY` when it has at least `100000` rows and covers `2019-06-03 15:00:00+00:00`; shorter converted files are kept as `NORMALIZED_NEEDS_HISTORY`.

## Important Note

The old frozen base is preserved in `archive/`. The prior both-side concept base is preserved in `outputs/proof_pack/07_direction_oos/` as the promotion evidence. The active new base is demand-only because supply-only failed OOS and acted as persistent drag.
