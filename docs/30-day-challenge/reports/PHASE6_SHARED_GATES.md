# Phase 6 — Shared Production Gates + BT Realism Layer

**Date:** 2026-06-19
**Owner:** Subash
**Driver:** Phase 4-5 closed signal-gen parity (100%). Trade-level parity remained
gappy because gates differed between BT and live. This phase makes BT and live
use the SAME gate code, with documented live-only exceptions for things that
physically only exist on the live side (broker rejections, cross-account state).

---

## Goal

**100% parity at trade-list level** between BT and live, given:
- Same input data (JM CSVs)
- Same gate state (cooldown, dd_state, blacklist) starting clean
- Same `BIAS_MODE` env var
- Same signal-gen output (already verified Phase 4-5)

Gates that physically can't be reproduced (broker rejections, real-broker MT5
state) are explicitly **opt-out** — BT passes a no-op callback.

---

## Parity contract — what's tested

| Component | Parity guarantee |
|---|---|
| Signal generation | **100% byte-identical** (Phase 4-5, already done) |
| Production gate decisions | **100% byte-identical** when same state + callbacks |
| Trade execution (entry/SL/TP/BE/MAX_HOLD/partial) | **100% byte-identical** when same data |
| Risk sizing | **100% byte-identical** with same equity + state |
| Commission/swap accounting (BT) | **NEW** — BT applies, live actual broker |
| Broker rejections | **Live-only** — BT can't simulate. Documented exception. |
| Cron tick latency | **Live-only** — BT walks deterministic. Documented exception. |
| Tick-resolution fills (intra-M3) | **Live-only** — BT M3 OHLC. Documented exception. |

---

## Gates to move/add (12 items)

| # | Gate | Where today | After Phase 6 | Effort |
|---|---|---|---|---|
| 1 | One-at-a-time blocker | Both — different code | Shared `apply_gates` | 15min |
| 2 | Daily cap (max 3 FILLED/day) | Both — different code | Shared | 15min |
| 3 | Persistent sweep blacklist | Both — different storage (set vs DB) | Shared with callback for DB | 30min |
| 4 | DD pause (5 consecutive losses → skip 2) | BT only | Shared, **ADD to live** | 30min |
| 5 | Risk reduction (×0.5 after losses) | BT only | Shared, **ADD to live** | 30min |
| 6 | Equity-MA risk reduction | BT only | Shared, **ADD to live** | 30min |
| 7 | 5-min cooldown after signal attempt | Live only | Shared, **ADD to BT** + audit live works | 1h |
| 8 | Startup cooldown (45min post-restart) | Live only | Pluggable callback (BT no-op) | 15min |
| 9 | Daily max loss circuit-breaker | Live (dead code) | **DELETE** | 15min |
| 10 | Commission + Swap | Neither | **NEW — BT applies, live actual** | 1h |
| 11 | Cross-account MT5 lock (`get_open_trades`) | Live only | Pluggable callback (BT no-op) | 15min |
| 12 | Broker rejections (5004, 522) | Live only | **STAYS live-only** (physics) | 0min |

**Total gate work: ~5h**

## Infrastructure (5h)

| Step | Task | Effort |
|---|---|---|
| F1 | Build `backend/scanner/production_gates.py` + `GateState` + `apply_gates` + unit tests | 1.5h |
| F2 | Audit live cooldown on both Micros (verify exists, fires correctly) | 30min |
| F3 | Wire BT engines (Gold + Oil Micro) to call shared module | 1h |
| F4 | Wire Live schedulers (Gold + Oil Micro) with callbacks | 1h |
| F5 | Run 7yr BT regression (numbers will drop — honest projection) | 30min |
| F6 | Build trade-list parity test (extends current signal parity) | 1h |
| F7 | Run smoke test: 2-day live↔BT trade list parity | 30min |
| F8 | Commit + push | 30min |

**Total: ~10h**

---

## Order of work

Each step is one commit. Each commit re-runs full parity suite.

1. **Plan doc** (this file) — committed first
2. **F1** Build `production_gates.py` module + tests (no integration)
3. **F2** Audit live cooldown (separate diagnostic, no code change unless bug found)
4. **#9** Delete dead daily_max_loss (cleanup before refactor)
5. **#1, #2, #3** Move strategy-level gates to shared (no behavior change for BT or live)
6. **#7** Move 5-min cooldown to shared + add to BT
7. **#4, #5, #6** Move DD/risk-reduction to shared + add to live
8. **#8, #11** Pluggable callbacks for live-only gates
9. **F3** BT integration — first regression run
10. **F4** Live integration — verify dry_run still produces same signals
11. **#10** Commission + swap added to BT
12. **F5** Final 7yr BT regression
13. **F6** Build trade-list parity test
14. **F7** Smoke test — 2 days, both Micros, byte-level trade match
15. Commit + verify

---

## Projected impact

| Metric | Pre-Phase-6 | Post-Phase-6 (projected) |
|---|---|---|
| BT Oil Micro 7yr P&L | $2.82M | $2.4-2.6M (5min cooldown -5%, commission -1.5%) |
| BT Gold Micro 7yr P&L | $763K | $650-700K |
| Combined 7yr | $3.58M | $3.0-3.3M honest |
| Live capture ratio | ~30-50% (drift bugs) | **~70-90%** (only physics gap) |
| Live ↔ BT signal parity | 100% | 100% (unchanged) |
| Live ↔ BT trade-list parity | not measured | **100% with documented exceptions** |

---

## Decisions locked

| Decision | Value |
|---|---|
| Commission rate Oil (BCO) | $7/lot round-trip (JustMarkets ECN, conservative) |
| Commission rate Gold (XAU) | $6/lot round-trip |
| Lot size | 100 units = 1 lot |
| Swap | INCLUDE for overnight trades |
| BT slippage formula | KEEP deterministic (Filter #11) — no tail |
| Daily max loss | DELETE (dead code) |
| Startup cooldown in BT | NO-OP callback (BT has no restart concept) |
| Cross-account MT5 lock in BT | NO-OP callback (BT has no broker) |
| Broker rejections in BT | NO simulation (too noisy, varies by hour) |

---

## Live-only gates — explicit exception list

These exist on live, BT does NOT simulate them. Documented as known gaps:

1. **Broker rejections** (5004 timeout, 522 connection error) — random, transient. BT never has them.
2. **Cron tick latency** — BT walks bar boundaries deterministically. Live polls every 3min, may catch sweep at slightly different M3 bar.
3. **Tick-resolution fills** — BT uses M3 OHLC; broker tick could fill mid-bar at extremum.
4. **Startup cooldown** — BT runs single-process, no restart simulation.
5. **Cross-account MT5 lock** — BT has no broker / no other accounts.
6. **DWX EA failures** — file-system race conditions, EA crashes.

These are physics, not drift. Expected in live capture ratio.

---

## Test strategy

### Unit tests (`tests/test_production_gates.py`)
- Each gate isolated. Pure function tested with synthetic state.
- Mock callbacks for live-only gates.

### Existing parity tests
- `tests/harness/parity/test_oil_micro_parity.py` — signal-gen parity (already passing)
- `tests/harness/parity/test_gold_micro_parity.py` — signal-gen parity (already passing)

### NEW — Trade-list parity test
- `tests/harness/parity/test_oil_micro_trade_parity.py`
- `tests/harness/parity/test_gold_micro_trade_parity.py`
- Asserts: BT trade list ≡ Live dry_run trade list (with same starting state, no broker rejections simulated)

### Smoke test (manual)
- `scripts/phase6_smoke_test.py` — runs 2-day window through both BT and live dry_run
- Compares trade-by-trade
- Reports any divergence

---

## Files created / modified

### NEW
- `backend/scanner/production_gates.py` — shared module
- `tests/test_production_gates.py` — unit tests
- `tests/harness/parity/test_oil_micro_trade_parity.py`
- `tests/harness/parity/test_gold_micro_trade_parity.py`
- `scripts/phase6_smoke_test.py` — 2-day trade-list smoke test
- `docs/30-day-challenge/reports/PHASE6_SHARED_GATES.md` — this doc

### MODIFIED
- `backend/backtest/engine.py` — wire `apply_gates` (or stays out if Macros dropped)
- `backend-micro/backtest/engine.py` — wire
- `backend-oil-micro/backtest/engine.py` — wire + commission + swap
- `backend-micro/scanner/scheduler.py` — wire with callbacks
- `backend-oil-micro/scanner/scheduler.py` — wire with callbacks
- `backend/strategies/micro_alpha_sweep.py` — gate logic moved out (signal-gen stays pure)
- `backend-oil-micro/strategies/micro_alpha_sweep_oil.py` — same
- `backend-micro/config.py` — DELETE `DD_PROTECTION` (or strip dead key)
- `backend-oil-micro/config.py` — same

### DELETED
- Dead `daily_max_loss` references

---

## Done criteria

1. `pytest tests/test_production_gates.py` — all green
2. `pytest tests/harness/parity/` — all green (2 signal + 2 trade parity)
3. `scripts/phase6_smoke_test.py --window 2026-06-17:2026-06-18` — Oil Micro & Gold Micro produce IDENTICAL trade lists in BT and live dry_run
4. 7yr BT regression run — numbers documented as new baseline
5. Commit + memory updated
