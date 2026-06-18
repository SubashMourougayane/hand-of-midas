# Decision — Drop Both Macros, Keep Only Micros

**Date:** 2026-06-19
**Owner:** Subash
**Status:** LOCKED

---

## Decision

1. **Refactor scope (ongoing)**: Gold Micro + Oil Micro only. Drop Gold Macro + Oil Macro from refactor plan.
2. **Live ops**: disable Gold Macro + Oil Macro scheduler scans. No more live signals from either Macro.
3. **Future**: Macro code paths to be scrapped (deletion deferred — not blocking refactor).

---

## Reasoning

**Day 1 disaster (2026-06-18):**
- Oil Macro live: 2 LONG entries → both SL → −$1,151
- Oil Micro live: 2 TTL_EXPIRED + 1 SL + 1 BE-bug scratch → −$364
- Gold Macro live: 0 signals fired
- Gold Micro live: 1 TTL_EXPIRED + 1 BE-bug scratch → ~$0

**Master RCA Jun 19:** parity drift across all 4 systems, parallel-implementation root cause. Refactor estimated 14h for all 4.

**Trade-off considered:**
- Oil Micro alone (7yr JM BT, neutral): 2,462 trades, 80% WR, PF 7.28, $2.86M P&L
- Oil Macro alone (7yr JM BT, neutral): 827 trades, 60% WR, PF 4.97, $704K P&L
- Overlap analysis (2026 Jan-Jun): Macro 45% overlap with Micro. 62 unique Macro winners worth $78K/yr (58% WR).

**Why drop Macros anyway:**
- Macros = additional surface for parity drift (Master RCA D1 TP-formula on Oil Macro was Day 1 killer; Gold Macro D3 cross-strategy lock latent risk for 20+ days).
- Refactoring Macros = ~5.5h work for $78K/yr extra edge that ALSO depends on refactor restoring parity.
- Micros alone deliver the dominant P&L (~$3M/yr potential vs $0.7M Macros).
- Operational simplicity: 2 systems instead of 4. Fewer code paths, fewer log streams, fewer deploy targets.
- Cross-strategy locks (D3, D4) become moot when Macros don't fire.
- Gold Macro hasn't fired live since week start anyway. Cross-market data path silently broken since Jun 18 JM ingest. Low signal-of-life.

---

## Numbers (for the record)

| System | 7yr BT P&L (JM, neutral) | Status |
|---|---|---|
| Gold Macro | (not measured — cross_market data path break) | DROP |
| Oil Macro | $704,571 | DROP |
| Gold Micro | (pending walk) | KEEP + REFACTOR |
| Oil Micro | $2,859,551 | KEEP + REFACTOR |

**Macro edge sacrificed:** ~$78K/yr unique-to-Macro Oil signals (per overlap analysis). Accepted as cost of operational simplicity + freezing the parity-drift bleeders.

---

## Refactor scope (revised)

Per `REFACTOR_PLAN_LIVE_BT_UNIFY.md`, but only:

| Phase | Original | Revised |
|---|---|---|
| 0 — parity baseline | 4 systems | **2 systems** (Gold Micro + Oil Micro) |
| 1 — adapter | shared | unchanged |
| 2 — Oil Macro | 2.5h | **DROPPED** |
| 3 — Gold Macro | 2h | **DROPPED** |
| 4 — Gold Micro | 2.5h | unchanged |
| 5 — Oil Micro | 3h | unchanged |
| 6 — cross-system | 1h | reduced (no cross-strategy interlock to evaluate; Macros gone) |
| 7-8 — smoke + flip | unchanged | unchanged |
| **Total** | **~14h** | **~6.5h** |

---

## Live ops (immediate next session)

- Disable Gold Macro scheduler (`backend/scanner/scheduler.py` — disable scan loop or set `scan_enabled=False`).
- Disable Oil Macro scheduler (`backend-oil/scanner/scheduler.py` — same).
- Verify no open Macro positions before disabling. Close any if present.
- Document disable mechanism in handoff.
- Frontend dashboard: Macros remain visible (read-only) for historical trades. Disable "active scan" badge if present.

---

## What's NOT changing

- Gold Macro / Oil Macro code stays on disk (not deleted yet).
- Macro DB tables (`gd_trades` strategy=`alpha_sweep` for Gold Macro, `OIL-AS-%` for Oil Macro) stay for history.
- Frontend `/gold-macro` and `/oil-macro` routes stay readable.
- BT engine code stays runnable for historical analysis if needed.

**Deletion is future work.** Goal of this decision: stop bleeding + simplify ops + focus refactor.

---

## Reversibility

If Macros need to come back:
1. Re-enable schedulers (toggle the disable flag back on).
2. Verify cross-strategy locks still work (D3 Gold Macro, D4 Oil Micro account-wide).
3. Run BT on current JM data to confirm signals still match.

No data destruction. Fully reversible until code deletion.
