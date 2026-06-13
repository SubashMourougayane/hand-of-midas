# Filter #5 — Break-even trigger 50% → 35%

**Status:** ✅ SHIPPED selectively (Gold Micro, Oil Macro, Oil Micro). Gold Macro EXCLUDED.

**Branch:** `filter-05-be-pct` → merged into `midas-deploy` 2026-06-13

## Hypothesis

When a winning trade gets halfway to its TP, the live system moves SL to entry+1c
(break-even). Earlier this trigger fires → more reversals get scratched at BE
instead of going to full SL. Trade-off: some trades that would have hit TP get cut
at BE, sacrificing wins.

Question: does the math work out? Filter #5 tests `be_trigger_pct=0.35` (fires at
35% to TP) vs production `0.50` (fires at 50% to TP).

## Implementation

Per-system `be_trigger_pct` config knob. The config dict in each system already
had this key (set to 0.50 across the board). Filter ships by changing the value.

| Path | Edit |
|---|---|
| `backend-micro/config.py` | `MICRO_ALPHA_SWEEP["be_trigger_pct"]: 0.50 → 0.35` |
| `backend-oil/config.py` | `ALPHA_SWEEP["be_trigger_pct"]: 0.50 → 0.35` |
| `backend-oil-micro/config.py` | `MICRO_ALPHA_SWEEP["be_trigger_pct"]: 0.50 → 0.35` |
| `backend/config.py` | **unchanged** — Gold Macro stays 0.50 |
| `backend-micro/backtest/engine.py` | Reads `MICRO_ALPHA_SWEEP["be_trigger_pct"]` as default |
| `backend-oil/backtest/engine.py` | Reads `ALPHA_SWEEP["be_trigger_pct"]` as default |
| `backend-oil-micro/backtest/engine.py` | Reads `MICRO_ALPHA_SWEEP["be_trigger_pct"]` as default |
| `backend/backtest/engine.py` | **unchanged** — Gold Macro keeps hardcoded `0.5` default |
| `backend-oil/scanner/live_engine.py` | Hardcoded `* 0.5` → `* ALPHA_SWEEP["be_trigger_pct"]` (lines 401, 426) |
| `backend/scanner/live_engine.py` | **unchanged** — Gold Macro live keeps `* 0.5` |

Gold Micro and Oil Micro live engines already read from config (no live patch needed).
Gold Macro live + BT both stay at 0.5 — fully excluded from ship.

## BT 21-yr pre/post — full

| System | Baseline (0.50) | Filter (0.35) | Δ Trades | Δ WR | Δ PF | Δ P&L | $ Δ |
|---|---|---|---:|---:|---:|---:|---:|
| Gold Macro | N=2242, WR 65.4%, PF 2.56, $346,196 | N=2258, WR 69.6%, PF 2.78, $341,274 | +16 | +4.2pp | +0.22 | -1.4% | -$4,922 |
| Gold Micro | N=1855, WR 68.2%, PF 2.42, $240,254 | N=1911, WR 74.1%, PF 2.77, $252,265 | +56 | +5.9pp | +0.35 | +5.0% | +$12,011 |
| Oil Macro | N=1609, WR 54.2%, PF 2.66, $645,588 | N=1653, WR 60.4%, PF 2.94, $697,995 | +44 | +6.2pp | +0.28 | +8.1% | +$52,407 |
| Oil Micro | N=4425, WR 69.9%, PF 2.69, $2,010,717 | N=4601, WR 77.1%, PF 3.10, $2,125,672 | +176 | +7.2pp | +0.41 | +5.7% | +$114,955 |

**All 4 systems pass `Δ PF > 0` and `Δ WR > 0` thresholds.** Gold Macro is the only one
where total P&L drops slightly (−$4.9k, −1.4%). User decision: exclude Gold Macro from
the ship to keep its proven $346k baseline intact.

## Live signal-gen impact

**N/A** — this is a fill-side filter. The signal-generation logic is unchanged.
Same signals fire pre and post; only the SL movement during the trade differs.

The parity audit run earlier today already validated 100% direction agreement
between live and BT signal-gen on all 4 systems across 8 regimes. So:

- Live signals: identical
- BT signals: identical
- Trade outcomes: change because the fill model evaluates BE earlier

## Recommendation

**Ship to 3 systems, exclude Gold Macro.** Aggregate impact across the 3 ship
systems: **+$179,373 / 21 years (+$8.5k/yr).**

## Risks

- **Test coverage:** the existing `tests/harness/test_22_parity.py` baselines may
  shift slightly post-ship since BT now uses 0.35 by default. Will need to update
  baselines if any of the 3 systems' parity drifts >5pp.
- **Asymmetric across systems:** Gold Macro stays at 0.5 while the other 3 use 0.35.
  Future contributors editing the BE logic need to check both values. Mitigation:
  the per-system `be_trigger_pct` config key + comment lineage in commit messages.

## Files changed

- `backend-micro/config.py`
- `backend-oil/config.py`
- `backend-oil-micro/config.py`
- `backend-micro/backtest/engine.py`
- `backend-oil/backtest/engine.py`
- `backend-oil-micro/backtest/engine.py`
- `backend-oil/scanner/live_engine.py`
- `backend/execution/fill_model.py` (added `be_trigger_pct` kwarg, default 0.5)
- `backend-oil/execution/fill_model.py` (same)

## Related artifacts

- `scripts/run_filter_05.py` — the pre/post benchmark
- `scripts/validate_filter_05.py` — selective-ship validation
- `scripts/output/filter_05_results.json` — raw pre/post numbers
- `scripts/output/filter_05_validation.json` — selective ship verification
