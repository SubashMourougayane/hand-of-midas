# R&D Lab — Hand of Midas Strategy Re-derivation

> **Locked: 2026-06-20.** The contract below is the rule book for everything that happens inside this folder. It cannot be changed without the user's explicit written approval.

---

## Why this lab exists

The production Oil Micro strategy was running on a backtest with intra-bar lookahead. With the lookahead removed, every full year of the 7-year JustMarkets BCO_USD backtest loses money (PF 0.89, 40% WR, every full year red).

This lab is for honestly re-deriving the strategy from first principles, not for tuning the broken implementation.

The user has committed to:
- 8 weeks of research, possibly more
- 20-30% probability of finding real edge
- No live trading until Phase 4
- Validation/holdout discipline (one-shot tests)

The assistant has committed to:
- Working ONLY in this folder (no production code changes during R&D)
- All 6 safeguards in `CONTRACT_AND_SAFEGUARDS.md`
- No commits / no pushes without explicit user approval
- Failure-honest reporting at every phase

---

## Folder layout

```
R&D/
├── README.md                          ← this file (the contract)
├── CONTRACT_AND_SAFEGUARDS.md         ← the 6 safeguards (the rule book)
├── HYPOTHESES.md                      ← every hypothesis written BEFORE testing
├── DECISIONS.md                       ← every "I chose X over Y because Z" recorded
├── data_split.py                      ← sealed data access (the only way to read CSVs from R&D)
├── safeguards/
│   ├── test_no_lookahead.py           ← automated lookahead audit
│   └── test_random_strategy_baseline.py  ← "too good to be true" check
├── phase_0_observations/              ← Phase 0: manual chart studies
├── phase_1_detection/                 ← Phase 1: rewritten signal-gen
├── phase_2_validation/                ← LOCKED until Phase 1 passes
├── phase_3_stress/                    ← LOCKED until Phase 2 passes
├── phase_4_paper/                     ← LOCKED until Phase 3 passes
└── results/
    ├── phase_1_devset.md              ← results on dev (2019-2023)
    ├── phase_2_validation.md          ← ONE TIME ONLY (2024)
    └── phase_3_holdout.md             ← ONE TIME ONLY (2025-2026)
```

---

## The data split (LOCKED — do not change)

| Phase | Date range | Allowed access |
|---|---|---|
| Development (Phase 0+1) | 2019-09-26 → 2023-12-31 | Read freely, iterate |
| Validation (Phase 2) | 2024-01-01 → 2024-12-31 | One-shot only |
| Holdout (Phase 3) | 2025-01-01 → 2026-06-19 | One-shot only after Phase 2 passes |
| Live (Phase 4) | 2026-06-21 onwards | 1% sizing only |

Boundary dates are calendar UTC. Once `data_split.py` is written, the split is hash-locked. Any attempt to change the boundaries will require regenerating the hash and an explicit user note in `DECISIONS.md`.

---

## The phase gates

Each phase has a **pre-registered pass criterion** written into `HYPOTHESES.md` BEFORE the test runs. The phase passes only if the criterion is met. No re-tuning after seeing results. No moving goalposts.

| Phase | Goal | Gate to pass |
|---|---|---|
| 0 | Understand what real stop-runs look like | User-signed-off list of 20 hand-marked setups + written description |
| 1 | Re-derive detection rules on dev data | Each rule individually catches ≥80% of hand-marked setups |
| 2 | Validate on 2024 (unseen) | PF ≥ 1.3, max DD < 30%, year P&L positive |
| 3 | Stress + holdout on 2025-2026 | PF ≥ 1.2 with 2x slippage, holdout positive |
| 4 | 1% live deployment | 30 trades with BT-vs-live parity ≥ 80% |

Failure at ANY phase ends the project. There is no "try again after one more tweak."

---

## What lives in this folder

ONLY this:
- The contract + safeguards
- Pre-registered hypotheses
- The data-split gateway
- Phase work files (notebooks, code, results)
- Test files for the safeguards

What does NOT live here:
- Imports from `backend/`, `backend-micro/`, `backend-oil-micro/`, or any other production package
- Trading code that places real orders
- Anything that touches the live database
- "Quick experiments" outside the phase structure
- The legacy strategy parameters (every value starts from observation)

---

## Sign-offs

| Date | Phase | Signed by | Outcome |
|---|---|---|---|
| 2026-06-20 | Lab construction | (pending user signoff to enter Phase 0) | Lab walls + safeguards in place |

---

## Status

**2026-06-20 evening:** Lab skeleton created. Safeguards pending. Phase 0 not yet started. No strategy code exists yet.
