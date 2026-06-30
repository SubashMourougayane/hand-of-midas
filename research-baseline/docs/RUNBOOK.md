# XAU-SDR-001 Runbook

## Regenerate Base Report

From this folder:

```bash
python3 code/scripts/run_xau_sdr_report.py
```

Outputs are written to:

- `results/base/`
- `results/stress/`
- `docs/XAU_SDR_001_REGENERATED_REPORT.md`

## Original Research Scripts

The copied research scripts are in:

- `code/scripts/l99_m15_filter_edge_sweep.py`
- `code/scripts/l99_multitimeframe_sd_confluence.py`
- `code/scripts/standalone_order_block_research.py`

Some historical scripts were originally written against the parent `SupplyDemand` project layout. The frozen base files are therefore the canonical source for `XAU-SDR-001` unless a script is explicitly adapted and rerun.

## Tests

For full historical tests:

```bash
cd /Users/subash/Documents/QUANT/SupplyDemand
python3 -m pytest tests
```

## What Not To Do

Do not silently add:

- cross-asset confirmation,
- ORB filters,
- order-block filters,
- volume profile filters,
- top-10 stretch,
- direction-only overrides,
- hour/day filters.

Those create a new candidate, not `XAU-SDR-001`.

