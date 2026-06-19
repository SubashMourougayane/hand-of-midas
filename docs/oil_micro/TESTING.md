# `oil_micro/` — Test Strategy

> Scope: anything in `tests/oil_micro/`.
> Authority: this doc + `STYLE.md`.

## Why this matters

The legacy code's tests mocked the database, mocked `is_sweep_consumed`, mocked `get_open_trades`, mocked the broker. Those tests passed. Those mocks hid 5 parity bugs. We're not doing that again.

## Coverage gates

| Layer | Coverage required at merge |
|---|---|
| `oil_micro/core/*` | 90%+ |
| `oil_micro/managers/*` | 90%+ |
| `oil_micro/engine.py` | 90%+ |
| `oil_micro/gates.py` | 90%+ |
| `oil_micro/adapters/*` | 75%+ (real I/O is harder to unit-test; integration tests fill the gap) |
| `oil_micro/drivers/*` | 60%+ (CLI thin wrappers; integration tested by Phase 2/3 parity gates) |

`pytest --cov=oil_micro --cov-fail-under=85` in CI. Per-file thresholds enforced via `.coveragerc`.

## Test layout

```
tests/oil_micro/
├── conftest.py                       # shared fixtures (test DB, mock broker, csv slices)
├── test_engine_loop.py               # OilMicroEngine cycle with mocks
├── test_engine_e2e_bt.py             # full BT mode, real CSV
├── test_engine_e2e_replay.py         # full replay mode, real PG (golddigger_replay_oil)
├── test_engine_e2e_bt_replay_identity.py  # BT vs Replay must agree byte-for-byte
├── core/
│   ├── test_clock.py
│   ├── test_tick_source_csv.py
│   ├── test_tick_source_dwx.py
│   ├── test_tick_source_replay.py
│   ├── test_executor_sim.py
│   ├── test_executor_dwx.py
│   ├── test_state_store_inmem.py
│   ├── test_state_store_pg.py
│   └── test_state_store_protocol.py  # PARAMETRIZED — runs same suite against InMem + PG
├── managers/
│   ├── test_position_manager.py
│   ├── test_pending_manager.py
│   └── test_orphan_manager.py
├── adapters/
│   ├── test_sim_executor_adapter.py
│   └── test_dwx_executor_adapter.py
└── test_perf.py                      # cycle latency + bt/replay speed regression gates
```

## Test types

### 1. Unit tests (per module)

Every Protocol implementation has a unit test file. Tests are scoped to one method or one behavior. No Postgres, no broker, no FS I/O.

### 2. Protocol-level shared tests (parametrized)

`tests/oil_micro/core/test_state_store_protocol.py` runs the SAME set of behaviors against `InMemoryStateStore` AND `PostgresStateStore` via `pytest.fixture(params=[...])`. If they diverge, one is wrong. **This is the structural fix for the BT≠Live parity bug class** at the storage layer.

```python
@pytest.fixture(params=["inmem", "postgres"])
def state_store(request, ...):
    if request.param == "inmem":
        return InMemoryStateStore()
    return PostgresStateStore(test_db_url)

def test_snapshot_with_no_trades(state_store):
    snap = state_store.snapshot(now)
    assert snap.trades_today_filled == 0
    assert snap.consumed_sweep_keys == set()
    # ... 30+ behaviors, both impls run them
```

### 3. Property tests (Hypothesis)

`tests/oil_micro/test_executor_sim.py` uses `hypothesis` to generate bar sequences and asserts:

- SL touch + TP touch in same bar → TP wins (matches `fill_model.py:189`)
- Gap-through SL at open → instant fill at gap price + slippage
- Partial TP touch + BE arm → SL moves to entry on same bar
- MAX_HOLD reached → exit at last bar's mid

Property tests find edge cases that hand-written tests miss.

### 4. Integration tests (real Postgres, real CSV)

Critical-path tests run against a real Postgres DB (temp schema, truncated per test) and real CSV files. Use the `test_db` fixture pattern from existing `tests/conftest.py`.

**Why no mocked DB?** Today's bugs include a parity test that mocked `is_sweep_consumed = lambda: False`. That mock hid the bug for weeks. Mocked-DB tests are forbidden in critical-path tests.

### 5. End-to-end parity tests (Phase 2/3 ship gates)

- `test_engine_e2e_bt.py` — runs new BT mode against full 7yr CSV. Asserts trade list matches `backend-oil-micro/backtest/engine.run_backtest()` exactly.
- `test_engine_e2e_replay.py` — runs replay mode against same window. Asserts trade list matches Phase 2 BT output.
- `test_engine_e2e_bt_replay_identity.py` — convenience wrapper diffing them.

These are slow (35s + 100s respectively) — marked `@pytest.mark.slow`, run in CI on merge to `feature/tape-replay-server`.

### 6. Performance regression tests

`tests/oil_micro/test_perf.py` measures:
- Cycle latency (no signals): p50, p99
- BT 7yr wall-clock
- Replay ticks/sec single-process
- Replay ticks/sec parallel (Gold + Oil simultaneous)

Each test asserts against the budgets in `PERFORMANCE.md`. Slowdown vs baseline → CI fails.

## Fixtures

`tests/oil_micro/conftest.py` exposes:

```python
@pytest.fixture
def tape_clock() -> TapeClock:
    """TapeClock starting at 2024-01-01T00:00 UTC. Advance via clock.advance_to()."""

@pytest.fixture
def csv_tick_source(data_dir) -> CsvTickSource:
    """Loads BCO_USD_*.csv once per session; tests share."""

@pytest.fixture
def sim_executor(csv_tick_source) -> SimulatedExecutor:
    """Sim executor backed by the test CSV."""

@pytest.fixture
def inmem_store() -> InMemoryStateStore:
    """Empty, fresh per-test."""

@pytest.fixture
def pg_store(test_db) -> PostgresStateStore:
    """Real Postgres against test_db (truncated per test, schema fresh)."""

@pytest.fixture
def engine_bt(tape_clock, csv_tick_source, sim_executor, inmem_store) -> OilMicroEngine:
    """Engine wired for BT mode."""

@pytest.fixture
def engine_replay(tape_clock, csv_tick_source, sim_executor, pg_store) -> OilMicroEngine:
    """Engine wired for replay mode."""
```

## Running tests

```bash
# Quick unit + protocol tests (no slow integration)
pytest tests/oil_micro/ -m "not slow"

# Full suite including 7yr BT parity gate
pytest tests/oil_micro/

# Just one Protocol-level suite, both backends
pytest tests/oil_micro/core/test_state_store_protocol.py

# Performance regression
pytest tests/oil_micro/test_perf.py -v
```

## When tests find a regression

- **BT-parity test fails** → don't ship. Find the divergence first. Use the three-way diff harness (`scripts/replay_three_way_diff.py`) to localize.
- **Protocol-level test fails on one backend but not the other** → one impl is wrong. Use the Postgres impl as ground truth (it's closer to live).
- **Performance test fails** → profile (`cProfile` + `snakeviz`). Don't paper over with retries or wider tolerances.

## Adding tests

1. Decide which layer the test belongs in (unit / protocol / property / integration / e2e / perf).
2. Use the conftest fixtures — don't roll your own.
3. Test the contract the module promises (per its doc), not the implementation.
4. If the test mocks something the legacy code mocked, **stop and ask why**. The legacy mocks hid bugs.

## Related

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [STYLE.md](./STYLE.md)
- [PERFORMANCE.md](./PERFORMANCE.md)
- `tests/conftest.py` (legacy fixtures we still use for shared backend libs)
