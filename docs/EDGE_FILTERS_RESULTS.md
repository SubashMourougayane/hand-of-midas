# EDGE_FILTERS — Results Log

One row per filter that has been measured. **No filter ships to live without numbers in this file.** No fake numbers, no phantom fills, no assumptions.

For the candidate catalog see [EDGE_FILTERS.md](EDGE_FILTERS.md). For the 6-step gate see [EDGE_FILTERS_IMPLEMENTATION.md](EDGE_FILTERS_IMPLEMENTATION.md).

---

## Filter #17 — Oil Macro live `risk<0.01` → `risk<0.3` (Phase 0 drift fix)

**Status:** ✅ Shipped (commit `a5dc3e1`, 2026-06-12). Local-only — not pushed to VPS yet.

**Type:** Drift fix, not alpha filter. Live was diverging from backtest's risk floor; this aligns them.

### What changed

`backend-oil/scanner/scheduler.py:285,299`:
```diff
-if risk < 0.01 or risk > asia_range * 0.8:
+if risk < 0.3  or risk > asia_range * 0.8:
```

Backtest at `backend/strategies/alpha_sweep.py:111,135` was already `risk<0.3` — the fix brings live into agreement.

### Backtest impact

**N/A by construction.** The backtest already used `risk<0.3`, so running it before/after the live-side fix produces identical numbers. There is no backtest delta to measure.

### Production data measurement (substitute for backtest)

Pulled all `ENTRY_FILLED` and `EXIT_FILLED` events from `/api/oil/journal/events` (alpha_sweep_oil only, deduped by trade_ref) on 2026-06-12. 10 entries, 8 closed:

| trade_ref | entry | sl | risk | exit | pnl_usd | post-#17? |
|---|---|---|---|---|---|---|
| OIL-AS-f5e9710a | 92.95 | 90.96 | 1.99 | (open) | (open) | takes |
| OIL-AS-59a94823 | 91.51 | 91.08 | 0.43 | (stuck) | (stuck) | takes |
| OIL-AS-5434644d | 92.14 | 93.15 | 1.01 | SL | -1054.44 | takes |
| **OIL-AS-f557abc0** | **92.15** | **91.91** | **0.24** | **SL** | **-513.12** | **🚫 BLOCK** |
| OIL-AS-cbc736f8 | 95.87 | 96.55 | 0.68 | TP | +409.06 | takes |
| OIL-AS-86b4293c | 96.15 | 96.98 | 0.83 | SL | -312.08 | takes |
| OIL-AS-e6e64a02 | 95.92 | 95.21 | 0.71 | SL | -338.67 | takes |
| OIL-AS-7a5c0377 | 95.61 | 95.20 | 0.41 | SL | -375.56 | takes |
| OIL-AS-fd4282e5 | 96.87 | 97.29 | 0.42 | SL | -223.86 | takes |
| OIL-AS-8924ef1b | 93.63 | 92.88 | 0.75 | TP | +1377.76 | takes |

**Filter #17 would have skipped 1 of 10 entries** — the one with `risk = 0.24`, just below the 0.30 floor.

### Pre/Post P&L

| Metric | Pre-fix (8 closed trades) | Post-fix (7 closed, skipping f557abc0) | Δ |
|---|---|---|---|
| Trades | 8 | 7 | -1 |
| Wins | 2 | 2 | 0 |
| Losses | 6 | 5 | -1 |
| Win rate | 25.0% | 28.6% | +3.6pp |
| Gross win | $1,786.82 | $1,786.82 | 0 |
| Gross loss | $2,817.73 | $2,304.61 | -$513.12 |
| **Profit Factor** | **0.63** | **0.78** | **+0.14** |
| **Net P&L** | **-$1,030.91** | **-$517.79** | **+$513.12** |

### Parity harness impact

| Window | Pre-fix parity | Post-fix parity | Δ |
|---|---|---|---|
| 7-day | 57.4% (BT=1, Live=6, in_both=1) | 59.0% (BT=1, Live=5, in_both=1) | +1.6pp, Live -1 |
| 30-day | 64.0% (BT=13, Live=24, in_both=7) | 64.6% (BT=13, Live=23, in_both=7) | +0.6pp, Live -1 |

Direction agreement remained 100% on overlaps both pre and post.

### Caveats

- **N is small (8 closed trades).** One trade dominates the delta. Statistical significance: low. The direction (positive) is unambiguous; the magnitude is suggestive, not proven.
- **One-at-a-time gate means we can't claim "the saved capital would have been deployed elsewhere"** — Oil Macro doesn't queue trades, so blocking f557abc0 just keeps the slot empty until the next valid signal.
- **Backtest delta is zero by construction** because the backtest already enforced `risk<0.3`. We cannot run "backtest with bug" because the bug was live-only. This is what made the bug a parity-violation in the first place.

### Verdict

✅ **Keep the fix.** Production data shows it would have saved $513 over the past 9 days (1 of 10 entries skipped, that 1 happened to lose by SL). It also closes a documented live↔backtest drift bug, which is its primary purpose. The P&L improvement is a bonus, not the justification.

### Next action

Push `a5dc3e1` to VPS. Future Oil Macro entries with risk in [0.01, 0.30) will be skipped server-side.

---

## Filter #11 — Deterministic slippage (deferred from Phase 0)

**Status:** ⏭️ Deferred to Phase 1.

**Reason:** Empirical run-to-run noise on parity_pct measured at ~0.07pp across three back-to-back gold_micro runs (parity = 0.599078, 0.599364, 0.599710). The "1-3pp noise" claim from `PARITY_HARNESS_EXPLAINED.md` was overstated. At the harness's current 1-decimal display granularity, the noise is invisible. Will be needed when Phase 1 alpha filters require backtest-PF comparison runs.

No action taken; no code change.

---

## Template for future filter results

For each filter measured (whether shipped or rejected):

```markdown
## Filter #N — Title

**Status:** ✅ Shipped / ❌ Rejected / ⏭️ Deferred (commit, date)

**Type:** Drift fix / Alpha filter / Calibration

### What changed
(diff or description)

### Backtest impact
| System | Trades | WR | PF | Net P&L | Max DD | Δ vs baseline |
|---|---|---|---|---|---|---|
| (system) | ... | ... | ... | ... | ... | ... |

### Parity harness impact
| Window | Pre parity | Post parity | Δ |

### Production data (if applicable)
(N trades, P&L delta from real broker outcomes)

### Caveats
(small N, one-at-a-time gate, missing measurement, anything not quantified)

### Verdict
✅ Keep / ❌ Revert / ⏭️ Recalibrate

### Next action
```

