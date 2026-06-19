# Unified Oil Micro Engine — Architecture

> **Status:** Design approved 2026-06-20 IST after 12hr parity-bug session.
> **Branch:** `feature/tape-replay-server`.
> **Plan source:** `~/.claude/plans/piped-hopping-biscuit.md` (canonical version).
> **Implementation tracked in:** task list (Phase 0 → Phase 7).

---

## Why this exists

Five parity bugs shipped in one day:

| Bug | What it was | What broke it |
|---|---|---|
| BT-LOOKAHEAD | BT walked F27 limit fills from engulfing M3 bar; live could only know about the signal at the H1 bar that triggered emit. ~30–60 min reverse lookahead in BT. | Two parallel implementations of fill-anchor logic. |
| A1 (sweep blacklist) | Live persisted `gd_traded_sweeps` rows; BT had no equivalent state. Blacklist polluted across deploy boundary blocked post-deploy live trades. | Live had inter-call state BT didn't model. |
| A9 (H6/F27 anchor) | Live computed limit price from current tick; BT computed from bar close. Different prices, different fills. | Two implementations of the same formula. |
| A10 (cron vs sequential) | BT walked signals chronologically; live emitted on cron schedule. Same wick, different fire times. | Different control flows. |
| F-LOOKAHEAD.4 | Even after BT-LOOKAHEAD fix, BT walks fill from `emit_h1+1` M3 bar; live places via cron-tick at `emit_h1+3-15` min. ~3-15 min residual gap. | Cron cadence in live, no equivalent abstraction in BT. |

All five root-cause to the same disease: **Oil Micro runs as two parallel implementations** (BT engine + live scheduler/engine). Plus a third hack (`replay/runner.py` sys.modules surgery to shove live code through tape data).

Cure: write a unified engine where BT, Replay, and Live are the same code path with swappable I/O adapters.

---

## Hard constraints

- **No DB schema changes.** Engine reads/writes existing `gd_*` tables.
- **No live trading risk.** Cutover happens during weekend close, with rehearsed rollback.
- **No scope creep.** Same behavior, cleaner architecture. New filters / strategies / sizing are out.
- **No solo cutover.** User signs off Phase 5 explicitly before flip.

Outcome: collapse 2,603 lines of parallel implementation into one `oil_micro/` package; eliminate the parity-bug class by construction.

---

## The five interfaces

All in `oil_micro/core/`.

### `Clock` — `oil_micro/core/clock.py`

`WallClock` (live) + `TapeClock` (BT/Replay). One method `now() -> datetime`. `TapeClock` adds `advance_to(ts)` (monotonic-only, raises on backward).

### `TickSource` — `oil_micro/core/tick_source.py`

Returns BT-canonical DataFrames (`bid_*`, `ask_*`, `mid_*`, UTC index) at any clock time. Three implementations:

- `CsvTickSource` (BT): full-history CSV slicing
- `DwxTickSource` (live): wraps `backend.execution.get_candles` / `get_current_price`
- `ReplayTickSource` (replay): wraps `replay/tape/server.py:TapeServer`

Methods: `get_h1_window(now, count=24)`, `get_m3_window(now, count=50)`, `get_daily_window(now, count=2)`, `get_current_price(now) -> dict | None`.

### `Executor` — `oil_micro/core/executor.py`

`OrderRef` dataclass; methods `place_market`, `place_limit`, `cancel_pending`, `modify_sl`, `close`, `close_partial`, `get_open_orders`, `get_order_details`, `get_account_summary`, `advance(now)`.

- `SimulatedExecutor` (BT/Replay): reuses `backend/execution/fill_model.py:execute_trade` byte-for-byte for fill physics — no reimplementation
- `DwxExecutor` (live): thin adapter over `backend/execution/mt5_executor.py`. `advance()` is a no-op (broker advances asynchronously).

### `StateStore` — `oil_micro/core/state_store.py`

**One method `snapshot(now) -> GateSnapshot`** does a single round-trip read of everything gates need (cooldown, sweep blacklist, dd_state, open positions, trades_today, last_20_pnls, startup_cooldown). Eliminates the TOCTOU class of parity bugs.

- `InMemoryStateStore` (BT, Python dicts)
- `PostgresStateStore` (Live/Replay; **single CTE** against `gd_trades` / `gd_signals` / `gd_journal` / `gd_traded_sweeps` / `gd_dd_state` row id=4)

Same Protocol on both sides → engine doesn't know which it's talking to.

### `Notifier` — `oil_micro/core/notifier.py`

`TelegramNotifier` (wraps `backend/notify.py`), `NullNotifier` (BT), `LogNotifier` (replay debug). All methods swallow exceptions.

---

## Single engine, three drivers

`oil_micro/engine.py:OilMicroEngine.run_until(end)` is one main loop:

```
loop every 1 minute of clock:
  1. h1 = tick_source.get_h1_window(now, 24); m3 = (now, 50); daily = (now, 2)
  2. bias = compute_bias(daily) → apply F28 override (neutral mode env var)
  3. signals = generate_signals(h1, m3, bias_dict)         # SHARED — backend-oil-micro/strategies/micro_alpha_sweep_oil.py
  4. gates = state_store.snapshot(now)                      # SINGLE round-trip
  5. for sig in signals (only on minute % 3 == 0):
       decision = apply_gates(sig, gates, now)              # wraps backend/scanner/production_gates.py
       if decision.skip: state_store.log_signal(...skip_reason); continue
       order_ref = self._place_order(sig, gates)            # market or limit per cfg
       state_store.mark_sweep_consumed(...)
       if order_ref.state in ("OPEN", "PENDING"): state_store.insert_*_trade(...)
       break    # ONE trade per cycle (Master RCA D5)
  6. for evt in executor.advance(now): handle (BT/Replay only; live no-op)
  7. position_manager.update(now)                            # BE arm + partial TP + MAX_HOLD
  8. pending_manager.update(now)                             # F27 TTL reconcile
  9. orphan_reconciler.update(now)                           # live-only
 10. clock.sleep_until(now + 1min)
```

Drivers in `oil_micro/drivers/{bt,replay,live}.py` wire the protocols differently. **Same engine code in all three modes.**

---

## Cutover plan

| Phase | Days | Description |
|---|---:|---|
| 0 | 0.5 | Persist this design + initial docs |
| 1a | 2 | `core/{clock,tick_source(Csv),state_store(InMem),executor(Sim)}` + engine skeleton |
| 1b | 1.5 | Live driver + `DwxExecutor` + `PostgresStateStore` (CTE) (parallelizable with Phase 2) |
| 2 | 1.5 | BT-mode parity to existing `backend-oil-micro/backtest/engine.py` — exact match |
| 3 | 1 | Replay-mode parity to BT — same trade list, same fills |
| 4 | 2.5 | **Live SHADOW DRY-RUN** alongside production for 48hr; ZERO divergence required |
| 5 | 0.5 | Atomic cutover during JustMarkets weekend close (Sat 21:00 UTC). `OIL_MICRO_ENGINE=legacy/unified` env var rollback, rehearsed on staging first |
| 6 | 7 (wall) | Bake week — no active dev, monitoring only |
| 7 | 0.5 | Delete old code (`backend-oil-micro/{backtest/engine,scanner/scheduler,scanner/live_engine,scanner/price_stream}.py` + `replay/runner.py` sys.modules surgery) |

**Total: 8.5 dev days + 7-day bake = ~3 calendar weeks; +50% buffer = ~5 weeks.**

Hard ship gate: Phase 4 shadow comparison must show **zero signal/order divergence over 48hr**.

---

## What's kept / dropped

**KEEP unchanged:**
- `backend-oil-micro/strategies/micro_alpha_sweep_oil.py` — `generate_signals` (Phase 5.5 unified)
- `backend/execution/fill_model.py` — `execute_trade`, `_sl_slip` (canonical fill physics)
- `backend/execution/limit_price.py` — `compute_limit_price`
- `backend/scanner/production_gates.py` — wrap, don't replace
- `backend/scanner/broker_to_dataframe.py`
- DB schema (`gd_trades`, `gd_signals`, `gd_journal`, `gd_traded_sweeps`, `gd_dd_state`)
- DWX EA + commands.json/last_response.json wire protocol

**KEEP-AS-LIB (wrapped by adapters, not changed):**
- `backend/execution/mt5_executor.py` (DwxExecutor wraps it)
- `backend/notify.py` (TelegramNotifier wraps it)
- `backend/db.py:execute, safe_json_dumps` (PostgresStateStore uses it)

**DROP (after Phase 7 cutover bake):**
- `backend-oil-micro/backtest/engine.py` (599 lines)
- `backend-oil-micro/scanner/scheduler.py` (537 lines)
- `backend-oil-micro/scanner/live_engine.py` (1467 lines)
- `replay/runner.py` sys.modules surgery (replaced by clean `oil_micro/drivers/replay.py`)

---

## Risks (top 3)

1. **Subtle BT regression invisible to test harness, breaks live.**
   Mitigation: 7yr backtest must match existing BT (after BT-LOOKAHEAD anchor fix is on both sides) within 0 trades / $0 pnl_sized. Plus 48hr live shadow with zero divergence as ship gate.
2. **Live trading interruption during cutover.**
   Mitigation: cutover during JustMarkets weekend close with no open positions; rollback via env var rehearsed on staging; user signs off in writing.
3. **Author exhaustion → cutover at the wrong time.**
   Mitigation: Phase 5 requires user-signed checklist. No solo cutover. 5-week realistic timeline includes buffer.

---

## Locked-in design decisions

- **Package location:** new top-level `oil_micro/` package, parallel to `backend-oil-micro/`. Old code stays in tree until Phase 7 deletes it.
- **DB read pattern:** single CTE round-trip in `StateStore.snapshot()`. Eliminates TOCTOU class of parity bugs structurally.
- **Gold Micro:** oil-first ship. After Oil bakes 7+ days clean, port the same pattern to Gold (~2 days extra). Two separate cutovers, both rollback-able.

---

## Standards (apply to every line written under this plan)

See:
- [STYLE.md](./STYLE.md) — code quality (module structure, function size, type hints, error handling, logging)
- [TESTING.md](./TESTING.md) — coverage gates, Protocol-level shared tests, property tests, real-DB tests
- [PERFORMANCE.md](./PERFORMANCE.md) — cycle latency budgets, BT/replay speed targets, profiling discipline

Every phase's PR includes both the code AND its docs. PRs that ship code without docs are returned for changes.

---

## Documentation deliverables (per phase)

| Phase | Required doc artifacts |
|---|---|
| 0 | `docs/oil_micro/README.md`, `ARCHITECTURE.md` (this), `STYLE.md`, `TESTING.md`, `PERFORMANCE.md` |
| 1a | `docs/oil_micro/{clock,tick_source,executor,state_store,notifier,engine}.md` |
| 1b | `docs/oil_micro/{dwx_executor,postgres_state_store,dwx_tick_source}.md` |
| 2 | BT-parity recipe added to `TESTING.md` |
| 3 | `docs/oil_micro/REPLAY.md` (replay-mode harness usage) |
| 4 | `docs/oil_micro/SHADOW.md` (shadow-mode SOP) |
| 5 | `docs/oil_micro/RUNBOOK.md` (cutover + rollback procedure) |
| 6 | `docs/oil_micro/MONITORING.md` (bake-week queries, alerts) |
| 7 | `docs/oil_micro/MIGRATION_LOG.md` (what was deleted, where to find it in git history) |

---

## Verification (end-to-end)

1. `pytest tests/oil_micro/` — all unit + adapter tests green.
2. `python -m oil_micro.drivers.bt --start 2018-01-01 --end 2025-12-31 --csv data/raw/BCO_USD_*.csv` — output trade list matches `backend-oil-micro/backtest/engine.run_backtest()` exactly (Phase 2 ship gate).
3. `python -m oil_micro.drivers.replay --start 2026-06-13 --end 2026-06-20` against `golddigger_replay_oil` DB — trade list matches Phase 2 BT run (Phase 3 ship gate).
4. `python scripts/oil_micro_shadow.py --duration 48h` deployed to VPS in shadow mode — zero signal/order divergence vs production (Phase 4 ship gate).
5. Phase 5 cutover rehearsed on staging; user signs checklist; flip env var on prod during weekend close.
6. Phase 6 bake week — daily reconciliation reports show no anomalies.
7. Phase 7 delete old code; CI re-runs full test suite green.
