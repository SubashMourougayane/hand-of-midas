# XAU-SDR-001

**XAU Supply Demand Reclaim**

This is the clean strategy package for the base we chose: **Sleeve 1 only**.

It is not the older YouTube-to-the-dot demand-only base. It is the newer XAUUSD clean top-3 supply/demand reclaim candidate that survived the first stress pack.

## Current Base

`XAU-SDR-001` trades XAUUSD reclaim reactions around quantified supply/demand zones.

The base is:

- XAUUSD only
- Supply and demand reclaim events
- Clean top-3 candidate set
- No cross-asset add-on
- No Brent add-on
- No top-10 stretch
- No experimental hour/day/retail-style filters
- Results measured in `R`

## Headline Numbers

Full sample, 2019-2026:

| Metric | Value |
|---|---:|
| Trades | 1,032 |
| Net R | +256.11R |
| Win Rate | 63.86% |
| Profit Factor | 1.68 |
| Max Drawdown | -12.69R |
| Positive Years | 8/8 |

OOS-style 2022-2026 slice:

| Metric | Value |
|---|---:|
| Trades | 818 |
| Net R | +216.97R |
| Avg R / Year | +43.39R |
| Win Rate | 64.67% |
| Profit Factor | 1.75 |
| Max Drawdown | -12.69R |
| Positive Years | 5/5 |

At user-selected fixed risk:

| 1R Risk | Approx OOS Avg / Year |
|---:|---:|
| $1,000 | $43,393 |
| $2,000 | $86,786 |
| $2,500 | $108,483 |

## Plain-English Edge

The strategy is trying to capture this behavior:

1. Gold moves away from a price zone with force.
2. That zone later gets retested.
3. If price reclaims/rejects the zone with the right confirmation, enter.
4. The trade usually aims for a relatively small but repeatable `R` outcome.
5. The edge comes from many controlled reactions, not from a few huge trades.

The stress pack says the edge is not just one lucky year or one monster winner. It still needs live/paper monitoring because 2023 was weak.

## Folder Map

- `config/` - frozen strategy metadata and headline numbers.
- `code/src/` - source snapshot from the SupplyDemand project.
- `code/scripts/` - runnable research/report scripts.
- `code/tests/` - copied test files relevant to data quality and causality.
- `data/raw/` - XAUUSD raw minute data used by the project.
- `docs/` - human-readable reports and rulebooks.
- `results/base/` - frozen base trades, yearly, monthly, direction, session, and summary files.
- `results/stress/` - cost, Monte Carlo, bootstrap, drawdown, clustering, and fragility stress files.
- `research_evidence/` - discovery and walk-forward evidence that led to this base.
- `trade_journals/` - Excel/CSV journals where available.
- `archive/source_notes/` - copied old notes so we remember what was promoted and what was superseded.

## Run

From this folder:

```bash
python3 code/scripts/run_xau_sdr_report.py
```

That regenerates the summary files and report from the frozen trade ledger.

For the original full test suite, run from the parent SupplyDemand project:

```bash
cd /Users/subash/Documents/QUANT/SupplyDemand
python3 -m pytest tests
```

## Production Warning

This is a research base, not a live deployment package yet.

Before live execution, do one final pass on:

- exact broker contract sizing
- spread and slippage model
- live order fill behavior
- timezone handling
- duplicate-signal handling
- paper-forward tracking

