# Tape Replay Server — Proposal

> **Author:** Subash, brainstormed 2026-06-19 evening IST.
> **Status:** Proposal, not yet built.
> **Trigger:** [PARITY_AUDIT_2026-06-19.md](./PARITY_AUDIT_2026-06-19.md) identified 24 divergence axes; smoke harness covers 6/24; user demands 100% parity from signal-gen → order-fill.
> **Related:** [project-live-bt-unified](../../../.claude/projects/-Users-subash-SUBASH-VibeTrader/memory/project_live_bt_unified.md) (Phase 6 unified signal-gen).

---

## The idea (Subash's words)

> "We have 7 year data of JM. Live code is taking market data feed in live every 1M and 3M, not every tick. So what if I wrote a server that will stream the past data OHLC of 1M and 3M periodically, simulate live, and let the live code replay on the data to make sure 100% parity — along with DB. Just that we will clean up those data later."

In one sentence: **feed historical bars into the actual production code path running against a real (isolated) DB, and assert that the resulting trade list equals BT's.**

---

## Why this is different from the smoke harness

The current smoke harness (`scripts/phase6_smoke_test.py`) and parity tests under `tests/harness/parity/` mock too much:

- `is_sweep_consumed = lambda: False` — never tests against real DB pollution.
- `get_open_trades = lambda: []` — bypasses position-monitor code paths.
- `mock_execute` for the cooldown query — bypasses `gd_signals` reads.
- All cron jobs disabled — code never sees its own real interleaving.

**Smoke harness validates code-path equivalence on the same input. The replay server validates production-behaviour equivalence on the same input.** Two different things.

---

## What's RIGHT about this approach

### ✅ Exercises actual production code paths

Scheduler, scanner, `live_engine`, `mt5_executor`, DB writes — all unchanged. The replay swaps **only the broker layer**. Every pollution path, every cron interleaving, every state-restore-on-startup path actually runs. Smoke harness mocks them; this doesn't.

### ✅ Catches state-pollution bugs

Today's bug (A1, sweep blacklist no-rollback) was invisible to the smoke harness because the harness uses fresh state. The replay server, running through 7 years of data, will hit `limit_price_through_market` rejection thousands of times — every one a real `gd_traded_sweeps` INSERT. By day 30 of replay the DB is realistically polluted, and any divergence between live's `is_sweep_consumed` reads and BT's clean `_traded_sweeps` set surfaces immediately.

### ✅ The only honest answer to "100% parity"

If BT trade list ≡ replay trade list on the same data, parity is real. Not "code looks similar", not "tests pass", not "smoke harness green" — actually identical trade outputs from the actual production loop. Anything less is a claim, not a proof.

### ✅ Cheap to run

7 years × 1.6M M3 bars at ~1000× speed = roughly **1 hour wall-clock per system**. We can run it nightly as a regression gate. Two systems × 1 hour = manageable.

---

## What's tricky / where it can lie to you

### ⚠️ #1 — Network latency

BT is 0 ms. Replay server feeds bars instantly. Live's real broker fill takes 5–10 s in production (DWX file IPC + broker round-trip). **Replay can't model this latency** without injecting artificial delays.

**Implication:** replay parity proves logic equivalence. It does **not** prove that real-broker entry slippage matches BT's modeled slippage. Latency drift (axes E1, E2 in PARITY_AUDIT) needs separate measurement from live capture.

### ⚠️ #2 — Broker rejection paths

Real broker rejects ~2–5% of orders (insufficient margin, invalid price, server-side filter, network error). Replay server is a fake broker — it never rejects. **Replay will be cleaner than reality.**

**Implication:** axis E3 (rejection retry) is not testable via replay. Need a mode where the replay broker injects synthetic rejections at empirical rate.

### ⚠️ #3 — Tick granularity

Live SL/TP fills at the first tick that crosses. The M3 OHLC walk only sees aggregate high/low. The BE-arm path specifically polls live ticks every 60 s and modifies SL on broker — replay can't do that without real ticks.

**Implication:** axes T3 (BE-arm cadence) and E6 (intra-bar SL/TP fill) need M1 or actual tick data. M3 replay catches signal-gen / sweep-mark / rejection logic; not micro-fill behaviour.

### ⚠️ #4 — DB pollution shape

Today's `gd_traded_sweeps` pollution had a specific sequence: pre-deploy live populated 15 rows, post-deploy live read them. The replay's pollution will look *similar* but not *identical* — different timing, different rejection mix (no real-broker rejects).

**Implication:** A1 will still show up under replay, but the exact DB row sequence won't reproduce production exactly. Replay catches the **class** of bug, not the precise production state.

### ⚠️ #5 — Time-acceleration breaks scheduled jobs

APScheduler runs `daily_recon` at 00:05 UTC. At 1000× replay speed, midnight occurs every ~86 s wall-clock. Cron jobs that fire on wall-clock will fire wrong.

Two options:
- **(a) Inline triggers:** replay engine calls `daily_recon`, `position_monitor`, `pending_order_monitor` synthetically between tape bars based on tape time.
- **(b) Time adapter:** patch `datetime.now()` and `time.time()` to return tape time. Cron triggers fire correctly via APScheduler internals.

(a) is simpler and more controllable. (b) is more accurate but harder to debug.

### ⚠️ #6 — DWX file IPC won't work at speed

DWX EA polls files at ~1 s. Replay at 1000× would overflow the file system in seconds.

**Solution:** stub `backend/execution/mt5_executor.py` entirely. Replace the file-write/poll layer with an in-process FakeBroker that has the same Python API contract (`place_market_order`, `place_limit_order`, `cancel_pending_order`, `modify_stop_loss`, `close_partial`) but resolves orders against the tape directly.

---

## The clean design (3 layers)

```
┌──────────────────────────────────────────────────────┐
│  Tape Server                                          │
│  reads data/raw/XAU_USD_M3.csv chronologically       │
│  pushes (bid_o,h,l,c, ask_o,h,l,c, ts) at clock_rate │
└────────────────┬─────────────────────────────────────┘
                 │
        ┌────────▼─────────┐
        │  Tape Bridge     │   replaces DWX/MT5 layer
        │  serves bars +   │   - get_candles()
        │  fake broker     │   - get_current_price()
        │                  │   - place_market_order()
        │                  │     → instant fill at next bar's open
        │                  │   - place_limit_order()
        │                  │     → walk M3 like BT, real fill
        │                  │   - modify_stop_loss()
        │                  │   - close_partial()
        └────────┬─────────┘
                 │
        ┌────────▼─────────┐
        │  Live Code       │   UNCHANGED:
        │  (scheduler,     │   - scanner/scheduler.py
        │   scanner,       │   - scanner/live_engine.py
        │   live_engine,   │   - backend/db.py
        │   db)            │     (writes to REAL test DB)
        └────────┬─────────┘
                 │
        ┌────────▼─────────┐
        │  Test DB         │   Postgres test DB
        │  golddigger_     │   Real schema, real INSERT/UPDATE.
        │  replay          │   Truncated before each run.
        │                  │   Compared to BT trade list at end.
        └──────────────────┘
```

### Tape Server responsibilities

- Read `data/raw/XAU_USD_M3.csv` (and `BCO_USD_M3.csv`) row-by-row.
- Maintain "tape time" — the timestamp of the current bar.
- Stream bars to Tape Bridge at configurable rate (`1000×` default; `live` rate for end-to-end timing tests).
- Optionally inject synthetic broker rejections at empirical rate (config flag `inject_reject_rate=0.03` for 3%).

### Tape Bridge responsibilities

- Implement the same Python API as `backend/execution/mt5_executor.py`.
- For `get_candles()`: serve a rolling window of bars from the tape position.
- For `get_current_price()`: return mid of current bar's OHLC.
- For `place_market_order()`: register order, fill at next bar's open with configured slippage.
- For `place_limit_order()`: register pending order with TTL bars; walk M3 OHLC like BT's `fill_model._fill_within_ttl()`. If wick crosses limit → fill. If TTL expires → return TTL_EXPIRED.
- For `modify_stop_loss()`: update in-memory order book.
- For `close_partial()`: split position, fill at current bar mid.
- Emit `closed_orders.json`-equivalent events into `journal` table at correct tape time.

### Live Code

**No changes.** Imports `mt5_executor` which is now Tape Bridge. Imports `db` which writes to the test DB. All scheduler / scanner / strategy code unchanged.

### Test DB

- Separate Postgres database: `golddigger_replay` (NOT `golddigger`).
- Same schema as production (apply `database/schema.sql`).
- Truncate all tables before each replay run.
- After replay, query `gd_trades` and compare to BT's trade list for the same date range.

---

## Cost / effort estimate

| Component | Hours |
|---|---:|
| Tape Server (read CSV, emit bars at rate) | 2–3 |
| Tape Bridge (stub `mt5_executor` API) | 4–6 |
| Test DB setup + truncate machinery | 1 |
| Schedule-time vs tape-time adapter | 2–3 |
| Cron-trigger inline replacement | 2 |
| First runnable end-to-end on 1 day of data | 1–2 |
| Validate BT ≡ replay on 1 day | 2–4 |
| Run on full 7 yr + debug to convergence | overnight + 8 hr |
| **Total** | **14–21 hr build + ~8 hr debug** |

---

## What it would catch (mapped to PARITY_AUDIT axes)

✅ **A1** — sweep blacklist not rolled back on rejection
✅ **A2** — F27 limit-TTL doesn't roll back blacklist
✅ **A5** — cooldown lost on restart (replay can simulate restart at hour T)
✅ **A6** — `dd_state` staleness (replay writes real `dd_state`)
✅ **A7** — position-open guard (replay maintains real DB rows)
✅ **A8** — sweep window overlap behavior
✅ **T1** — cron-tick alignment (replay simulates 3-min cron over tape time)
✅ **T2** — signal staleness
✅ **T4** — cron concurrency (replay runs real scheduler threads)

⚠️ Partial / needs separate tooling:
- **A3** — DB persistence bypass: replay USES real DB so this becomes "is BT's trade list achievable when live code uses DB?"
- **A4** — weekend gap: depends on whether tape includes weekend bars. JM CSV does not, which is realistic — replay walks the gap correctly.
- **E5** — F27 fill rate: replay can simulate broker rejection rate. Not the same as live's real rate but configurable.

❌ Cannot catch:
- **E1, E2, E3, E4** — network latency, slippage, broker rejection, multi-EA contention. These are real-broker physics. Need live capture + statistics, not replay.
- **T3** — BE-arm tick cadence. Needs M1 tick-replay variant.
- **E6** — SL/TP intra-bar tick fill. Same.
- **E8** — BE phantom trigger from stale `market_data.json`. Replay can't reproduce DWX file staleness.

**Net catch rate: ~12–15 of 24 axes.** Combined with live capture for execution layer, this is the path to honest "100% parity".

---

## Open design questions

1. **Single-system replay or multi-system?**
   Run Gold + Oil Micro concurrently against same tape (same `gd_traded_sweeps` table) → catches T4 (cron concurrency, multi-system contention). But more complex to debug. Start single-system, expand to multi.

2. **Speed control granularity.**
   1× = realistic; 1000× = fast iteration; 10000× = full 7yr in ~6 minutes. Need ability to slow down for debugging specific bars.

3. **Replay determinism.**
   BT uses `np.random.seed(42)` for slippage. Replay should mirror this. Or skip slippage entirely in replay broker — clean comparison.

4. **Snapshot points.**
   For long replays, ability to checkpoint state every N hours of tape time. Resume from checkpoint on debug.

5. **DB cleanup safety.**
   Replay must NEVER write to production `golddigger` database. Hard guard: replay engine refuses to start if `DB_NAME != "golddigger_replay"`.

6. **Integration with smoke harness.**
   Should replay be a separate CLI tool, or merge into `scripts/phase6_smoke_test.py` as a `--mode=replay` flag? Separate tool is cleaner.

---

## Recommended order of operations

### Step 1 (this week, ~1 hr): ship A1 + A2 fixes
Without these, the very first replay run produces wildly diverged trade lists from sweep-pollution alone. Debugging "is this A1 or another bug" wastes time. Fix A1+A2 first, then replay's first run is meaningful.

### Step 2 (also this week, ~3 hr): minimal stateful BT mode
Add `replay_from_db_state(snapshot_date)` flag to BT engine. Loads `gd_traded_sweeps`, `gd_signals`, `gd_dd_state` from DB at the snapshot moment, runs BT from that point. Cheaper than full replay; catches A1, A5, A6 with much less code.

### Step 3 (next week, ~14–21 hr): full Tape Replay Server
Build the 3-layer design above. Validate on 1 day → 1 week → 1 month → full 7 yr.

### Step 4 (month 2): replay as deploy gate
Run replay on every Phase-style refactor. "Replay this month's data through new code; trade list must match BT trade list." This is the answer to "no more bugs that surface a day later."

---

## Honest assessment

**Yes, build it. But build it third.**

A1 + A2 fixes are 30 minutes of work each and catch the bug we already know about. The minimal stateful-BT-mode is 3 hours and catches ~6 of the 24 axes. The full replay server is 14–21 hours and catches ~12–15 axes — but the marginal value over stateful-BT is mostly multi-system + cron concurrency + execution-layer state.

If you have the bandwidth, build all three sequentially. If not, A1+A2+stateful-BT gets you 90% of today's problem solved at 20% of the effort. The full replay server is the long-term answer to "no more bugs missed", but it's not the urgent move.

---

*Document created 2026-06-19 evening IST. Linked from PARITY_AUDIT_2026-06-19.md.*
