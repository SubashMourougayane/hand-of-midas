# `oil_micro/` — Unified Oil Micro Trading Engine

> **Status:** Design phase. Implementation tracked in task list (Phase 0 → Phase 7).
> **Replaces:** `backend-oil-micro/{backtest/engine,scanner/scheduler,scanner/live_engine}.py` (after Phase 7 cutover).

This package is the canonical Oil Micro trading engine. It runs identically in three modes — **BT (backtest)**, **Replay**, **Live** — by swapping I/O adapters at startup. There is exactly one place that defines what Oil Micro DOES; the only difference between modes is what it READS FROM and WRITES TO.

## Where to start

| If you want to... | Read |
|---|---|
| Understand why this package exists | [ARCHITECTURE.md](./ARCHITECTURE.md) — context, parity bugs, design decisions |
| Run a backtest locally | [DEVELOPMENT.md](./DEVELOPMENT.md) (Phase 1a) |
| Run a tape replay | [REPLAY.md](./REPLAY.md) (Phase 3) |
| Read the code style rules | [STYLE.md](./STYLE.md) |
| Add a new test | [TESTING.md](./TESTING.md) |
| Investigate a slow cycle | [PERFORMANCE.md](./PERFORMANCE.md) |
| Cut over from legacy to unified | [RUNBOOK.md](./RUNBOOK.md) (Phase 5) |
| Look up how a specific module works | per-module doc, e.g. `state_store.md` |

## Package layout

```
oil_micro/
├── core/                     # Five protocols + their implementations
│   ├── clock.py              # WallClock | TapeClock
│   ├── tick_source.py        # CsvTickSource | DwxTickSource | ReplayTickSource
│   ├── executor.py           # SimulatedExecutor | DwxExecutor
│   ├── state_store.py        # InMemoryStateStore | PostgresStateStore
│   └── notifier.py           # TelegramNotifier | NullNotifier | LogNotifier
├── managers/                 # Long-running responsibilities
│   ├── position.py           # BE arming + partial TP + MAX_HOLD
│   ├── pending.py            # F27 pending-order TTL reconcile
│   └── orphan.py             # Live-only safety net
├── adapters/                 # Wrappers over existing libs
│   ├── sim_executor.py       # → fill_model.execute_trade
│   └── dwx_executor.py       # → mt5_executor
├── drivers/                  # Three entry points
│   ├── bt.py                 # CLI: backtest over CSV
│   ├── replay.py             # CLI: tape replay
│   └── live.py               # FastAPI service (port 5056)
├── engine.py                 # OilMicroEngine.run_until()
├── gates.py                  # Wraps backend/scanner/production_gates.py
├── STYLE.md                  # Code quality contract (also docs/oil_micro/STYLE.md)
└── __init__.py
```

## Three modes — same engine

```
                    ┌─────────────────────┐
                    │   OilMicroEngine    │
                    │   .run_until(end)   │
                    └─────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
       ┌────────┐        ┌─────────┐       ┌──────────┐
       │   BT   │        │ Replay  │       │   Live   │
       │ driver │        │ driver  │       │  driver  │
       └────────┘        └─────────┘       └──────────┘
            │                 │                  │
       Csv tick          Replay tick         DWX tick
       Sim exec          Sim exec            DWX exec
       InMem store       PG store(replay)    PG store(live)
       Null notify       Log notify          Telegram notify
       Tape clock        Tape clock          Wall clock
```

The engine never knows which mode it's in. It calls `tick_source.get_h1_window(now, 24)` and gets a DataFrame. It calls `executor.place_limit(...)` and gets an `OrderRef`. The driver decides what's behind those calls.

## Building blocks (already shared, kept unchanged)

| Module | What it does |
|---|---|
| `backend-oil-micro/strategies/micro_alpha_sweep_oil.py:generate_signals` | Pure signal generation — Phase 5.5 unified |
| `backend/execution/fill_model.py:execute_trade` | Fill physics — gap-through SL, TP-wins-tie, slippage, BE, partial, MAX_HOLD |
| `backend/execution/limit_price.py:compute_limit_price` | F27 limit-price formula |
| `backend/scanner/production_gates.py` | Cooldown, daily-cap, DD pause, equity-MA |
| `backend/scanner/broker_to_dataframe.py` | Broker dict → BT-canonical DataFrame |
| DB schema (`gd_*` tables) | Unchanged |
| DWX EA + JSON wire protocol | Unchanged |

## Phase status

See `docs/oil_micro/PROGRESS.md` (created at Phase 1a) for live build status. As of Phase 0:

- [x] **Phase 0** — Design + standards docs (this folder)
- [ ] **Phase 1a** — Core protocols + BT skeleton
- [ ] **Phase 1b** — Live adapters (DwxExecutor, PostgresStateStore)
- [ ] **Phase 2** — BT-mode parity gate
- [ ] **Phase 3** — Replay-mode parity gate
- [ ] **Phase 4** — Live shadow DRY-RUN gate
- [ ] **Phase 5** — Cutover (atomic, rehearsed)
- [ ] **Phase 6** — Bake week
- [ ] **Phase 7** — Delete legacy code

Total ~5 calendar weeks per ARCHITECTURE.md.

## Where to add X

| You want to add... | Where it goes | What you also need to do |
|---|---|---|
| A new strategy filter (F29, F30, ...) | `backend-oil-micro/strategies/micro_alpha_sweep_oil.py` (already shared) | Add config key in `backend-oil-micro/config.py`. Both BT and Live pick it up automatically. |
| A new gate (e.g. weekend skip) | `backend/scanner/production_gates.py` + `oil_micro/gates.py` (wrapper) | Update `tests/test_production_gates.py`. |
| A new fill semantic | `backend/execution/fill_model.py` (still shared) | Update `tests/test_fill_model.py`. |
| A new broker (Interactive Brokers etc.) | New `oil_micro/adapters/<broker>_executor.py` + new `Driver` | Implement `Executor` Protocol. No engine changes. |
| A new persistence backend (SQLite, etc.) | New impl of `StateStore` Protocol | Make sure shared Protocol-level tests pass. |
| A new mode (e.g. paper trading on real ticks) | New driver in `oil_micro/drivers/` | Pick which Tick/Executor/State combos. No engine changes. |

The whole point of the architecture: **adding things doesn't require touching the engine.**

## Related

- [ARCHITECTURE.md](./ARCHITECTURE.md) — full design
- [STYLE.md](./STYLE.md) — code standards
- [TESTING.md](./TESTING.md) — test strategy
- [PERFORMANCE.md](./PERFORMANCE.md) — efficiency budgets
- `docs/parity/REPLAY_SERVER_PROPOSAL.md` — original tape replay proposal that kicked off this work
- `docs/parity/PARITY_AUDIT_2026-06-19.md` — 24 divergence axes that justified the rewrite
