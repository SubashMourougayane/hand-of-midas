# `oil_micro/` — Performance & Efficiency

> Cycle latency is the key metric. Every line written under this plan respects the budgets below.
> Authority: this doc + `STYLE.md` + `TESTING.md`.

## Why this matters

The replay run on Jun 19 took 40 minutes for 2 days of tape because:
1. `position_monitor_job` fired every minute regardless of open positions
2. Each position-monitor call did 4-6 DB queries
3. Two replay processes contended for Postgres + memory

We're not building that twice. Performance budgets are part of the design, not afterthought tuning.

## Mode budgets

| Mode | Target | Rationale |
|---|---|---|
| **Live cycle (no signals)** | < 100 ms p99 | Cron tick must finish well before next 1-min boundary. Headroom for occasional broker-IPC stalls. |
| **Live cycle (with signal)** | < 1 s p99 | Place order + DB writes + Telegram. 1s is the broker-roundtrip ceiling we accept. |
| **Replay (ticks/sec)** | > 200 t/s on dev Mac, single-process | Today's runner does ~100 t/s — we're targeting 2x. 1 year ≈ 525,600 ticks → 1 year in ~45 min. |
| **Replay (parallel)** | > 150 t/s/process when Gold + Oil run simultaneously | Today's parallel run dropped to ~50 t/s/process due to PG contention. New: connection pooling fixes it. |
| **BT (7yr)** | < 60 s wall-clock | Today's BT runs 7yr in ~35 sec. Hold the line; the unified engine MUST NOT make BT slower. |

## Component budgets

| Component | Live p99 | BT p99 | Notes |
|---|---|---|---|
| `StateStore.snapshot()` | < 20 ms | < 1 ms | Live = single CTE round-trip. BT = in-memory dict assemble. Today's 6-query mosaic is ~50 ms. |
| `generate_signals()` | unchanged | unchanged | Already shared, already fast. |
| `Executor.advance()` | n/a (no-op) | < 50 ms | Walks 1 minute of M3 = at most 1 bar. |
| Position/Pending/Orphan managers (no open trades) | < 10 ms total | < 1 ms total | Early-return on empty state. |
| `apply_gates()` | < 5 ms | < 1 ms | Pure function over the snapshot. |
| `_log_journal` | < 5 ms | < 0.1 ms | Live: 1 INSERT. BT: dict append. Critical: no `json.dumps` on hot path. |

## Performance discipline

- **Profile before optimizing.** `cProfile` + `snakeviz` on every Phase 2/3 milestone. Top-3 hotspots get fixed; the rest left alone. **Premature optimization is forbidden** — the budgets above are the only target.
- **No O(N²) over trade history.** State queries are bounded (last 20 trades, today's signals). If something walks all-time, it's wrong.
- **Pandas slicing is expensive — cache aggressively.**
  - `CsvTickSource` loads CSVs ONCE at instance init, slices on every call. No re-reads.
  - Repeated H1 slices for the same `now` → memoize on `(now.minute // 3, now.date())`.
  - Index lookups via `searchsorted`, not `.loc[ts]` (which is slower).
- **DB writes batch where possible.** `gd_journal` events buffered per cycle, flushed once. Today's code does N writes per cycle on busy paths.
- **No expensive ops in hot paths.**
  - No `json.dumps` in cron-tick. Pre-serialize event templates; substitute via dict.
  - No `datetime.fromisoformat` in inner loops. Parse once at boundary.
  - No regex in cron-tick (today's `_parse_ts` does this — port it to a stdlib datetime parse with timezone fixup).
- **Replay-mode parallelism is fair.** Multiple `oil_micro.drivers.replay` processes can run on different replay DBs without CPU starvation.
  - **Connection pool per process**, no shared lock.
  - Postgres connection limit raised if needed (default is enough for 4 parallel processes).
  - No global GIL contention (replay engine is mostly I/O bound + pandas).

## Hot-path inventory (what's allowed and what isn't)

The "hot path" = the cron-tick body, called once per minute in live and ~1440 times per day in replay.

**Allowed in hot path:**
- One `state_store.snapshot()` call (one round-trip)
- One `tick_source.get_*_window()` call per timeframe (cached internally)
- `generate_signals()` (pure, fast)
- `apply_gates()` (pure)
- One executor call per signal (rare)

**NOT allowed in hot path:**
- Multiple SELECT queries (collapse into snapshot CTE)
- Telegram HTTP (offload to a worker queue, fire-and-forget)
- Pandas `.read_csv()` (load at startup only)
- `json.dumps` of large dicts (pre-serialize templates)
- Regex parsing (use stdlib datetime)
- `time.sleep` (use clock-driven cadence)

## Perf regression gate

`tests/oil_micro/test_perf.py` lands in Phase 1a with these assertions:

```python
def test_cycle_latency_no_signals(engine_bt):
    """100 cycles, p99 < 100 ms (BT). Same harness, < 100 ms (live)."""

def test_bt_7yr_wall_clock(engine_bt):
    """Full 7yr completes < 60 s. Today's baseline ~35 s."""

def test_replay_ticks_per_second(engine_replay):
    """Single-process replay > 200 t/s on dev hardware."""

def test_replay_parallel_no_starvation(engine_replay_oil, engine_replay_gold):
    """Both processes simultaneously > 150 t/s each."""
```

CI runs these on merge to `feature/tape-replay-server`. Slowdown vs the baseline measured in Phase 1a → CI fails. Phase 4 ship gate adds: live cycle p99 measured over 48 hr; must be < 1 sec.

## Profiling recipes

### Per-cycle profile

```bash
cd /Users/subash/SUBASH/GoldDigger
python -c "
import cProfile, pstats
from oil_micro.drivers.bt import run_bt_for_window
from datetime import datetime, timezone
cProfile.run('run_bt_for_window(start=datetime(2024,1,1,tzinfo=timezone.utc), end=datetime(2024,1,2,tzinfo=timezone.utc))', '/tmp/oil_bt.prof')
"
snakeviz /tmp/oil_bt.prof
```

### DB query profile (live mode)

Postgres `auto_explain` extension; `pg_stat_statements` for top queries.

### Memory profile (replay parallel)

`memray run --output /tmp/replay.bin scripts/run_replay_jun19.py --year2024`. Then `memray flamegraph /tmp/replay.bin`.

## What to do when budgets are missed

1. Profile FIRST. Don't guess. Don't refactor blind.
2. Fix the biggest hotspot. Re-measure.
3. If still over budget, escalate: discuss whether budget is wrong or the design is wrong.
4. **Never widen the budget without discussion.** Budgets are guard rails, not goals.

## Related

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [STYLE.md](./STYLE.md)
- [TESTING.md](./TESTING.md)
- `replay/runner.py` — current replay; informs the perf budgets above
