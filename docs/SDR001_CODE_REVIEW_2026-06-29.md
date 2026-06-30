# SDR-001 Live Engine Code Review

Date: 2026-06-29

Scope reviewed:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/tests`
- `/Users/subash/SUBASH/GoldDigger/research-baseline`

Test run:

```text
cd /Users/subash/SUBASH/GoldDigger/bt_engine
python3 -m pytest
151 passed, 1 warning in 182.95s
```

The test suite is green. The issues below are mainly live-trading correctness gaps, not basic unit-test failures.

## Executive Verdict

`bt_engine` is a useful parity/backtest scaffold, but it is not yet safe to call a live SDR-001 execution engine.

The biggest problem is that the current live path still behaves like a historical replay system:

- it can filter by historical baseline `zone_id`,
- it can precompute events from a full dataset,
- it submits orders too late for true next-open semantics,
- bounded live smoke mode never actually submits orders,
- dry-run fills are synthetic at price `1`.

These must be fixed before any live or paper-live decision is trusted.

---

## Issue 1 - Critical: Default `sleeve1_filter=True` makes future live trading impossible

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:64`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:81`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:108`

Current behavior:

`SDR001Strategy` defaults to `sleeve1_filter=True`, then loads historical `zone_id`s from:

```text
research-baseline/results/base/base_sleeve1_trades.csv
```

Then it only emits events whose generated `zone_id` exists in that historical baseline list.

Why this is bad:

Future live zones will not have historical baseline `zone_id`s. Also, `zone_id` is just `len(zones) + 1` inside the current generated frame, so it is not stable if the data window changes. A live rolling window can generate a `zone_id=39` that has nothing to do with historical baseline `zone_id=39`.

RCA:

The parity replay concept was carried into the live strategy. The baseline `zone_id` whitelist is valid only for reproducing historical frozen trades. It is not a live rulebook.

Fix:

- Split into two separate strategies:
  - `SDR001FrozenReplayStrategy`: can use historical ledger IDs.
  - `SDR001LiveStrategy`: must never use historical trade IDs.
- Replace `sleeve1_filter` with a machine-readable rulebook based on causal predicates.
- Example live gates:

```json
{
  "strategy_id": "XAU-SDR-001",
  "rules": [
    {
      "name": "rule_a",
      "all": ["cost_le_0p05", "ema8_aligned", "base_body_low", "ny_main_or_overlap"]
    }
  ]
}
```

Acceptance test:

- Run live strategy on a post-baseline synthetic future date with `sleeve1_filter` unavailable.
- It should still be able to emit a valid order if causal predicates pass.
- Add a guard that raises if `sleeve1_filter=True` is used in `mode="live"`.

---

## Issue 2 - Critical: Live event generation initializes once and then stops discovering new events

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:98`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:130`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:132`

Current behavior:

On the first `on_bar`, the strategy calls `_initialize_from_history(...)`, builds `pending_events`, sets `state.initialized=True`, and never recomputes again.

Why this is bad:

In live mode, `history` only contains bars available at that moment. Any zone/retest/confirmation that forms after the first tick will never be discovered.

RCA:

The code was adapted to satisfy backtest parity by precomputing from `preloaded_raw`. That model works for historical replay but not for live streaming.

Fix:

- For live mode, maintain incremental state:
  - resampled M5/M15 buffers,
  - active zones,
  - touched zones,
  - confirmation windows,
  - emitted trade keys.
- Re-evaluate new closed bars continuously.
- Alternatively, if keeping vectorized generation temporarily, rerun it on each new bar with a bounded rolling history and deterministic stable keys, then emit only new trade keys.

Acceptance test:

- Feed bars in two chunks.
- First chunk has no event.
- Second chunk completes a zone/retest/confirmation.
- Assert that the event is emitted after the second chunk.

---

## Issue 3 - Critical: Live order submission happens after the target bar has already closed

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:82`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:84`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:89`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:92`

Current behavior:

The engine receives only closed bars. It fills/submits pending orders when:

```python
o.intended_entry_bar == bar.timestamp
```

In backtest mode, this simulates a fill at that bar's open. In live mode, however, the code submits the broker order only after that same bar is already closed.

Why this is bad:

The live order is late by one full bar. A backtest fill at `09:05 open` becomes a live broker order after the `09:05` bar closes. That breaks BT/live parity and can materially change entries.

RCA:

The engine uses one unified closed-bar loop for both backtest and live, but backtest can fill at a historical open while live cannot travel back to that open.

Fix:

- For live, submit immediately after the confirmation bar closes, not when the next entry bar is later observed as closed.
- Introduce separate order timing semantics:
  - Backtest: `SIGNAL_CLOSE -> NEXT_BAR_OPEN fill`.
  - Live: `SIGNAL_CLOSE -> immediate market order / next tick fill`.
- Store the actual broker fill timestamp and fill price.

Acceptance test:

- Use a fake live broker and fake closed-bar provider.
- At confirmation close `T`, assert broker submit is called during processing of bar `T`, not at `T + timeframe`.

---

## Issue 4 - Critical: `max_ticks` live smoke loop never submits or fills orders

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/live.py:148`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/live.py:168`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/live.py:171`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/live.py:182`

Current behavior:

When `max_ticks` is provided, `run_live` calls `_bounded_loop(...)` instead of `run_engine(...)`. `_bounded_loop` collects `pending` orders but never submits them to the broker, never opens trades, and never walks exits.

Why this is bad:

Smoke tests can say the live loop works while order execution is completely bypassed.

RCA:

The bounded loop was added as a lightweight polling smoke test, but it reimplemented only the strategy step, not the engine lifecycle.

Fix:

- Remove `_bounded_loop`.
- Add `max_bars` or `max_ticks` support directly to `run_engine`.
- Ensure bounded mode still executes the same order-submit/fill/close path as unbounded live.

Acceptance test:

- Fake strategy emits one order.
- Run `run_live(..., max_ticks=...)` with fake broker.
- Assert `broker.submit_order` was called.

---

## Issue 5 - High: Dry-run fills use price `1`, making dry-run PnL and bracket behavior meaningless

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/live.py:49`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/live.py:51`

Current behavior:

`DryRunBroker.submit_order` creates a fill with:

```python
price = order.stop_price * 0 + 1
```

Why this is bad:

Every dry-run trade opens at price `1`, not near gold price. Stops, take profits, risk, MFE/MAE, and any journaled result become nonsense.

RCA:

The placeholder was left in the broker adapter. The comment says the engine reads next bar open through execution, but live mode does not use the execution model.

Fix:

- Pass the current bar or a quote snapshot into dry-run fill generation.
- Fill dry-run at:
  - current ask for buys,
  - current bid for sells,
  - or current/next bar open in simulated live tests.
- Never allow placeholder fill prices in dry-run.

Acceptance test:

- With a fake quote of `2000.25/2000.55`, assert dry-run buy fills at ask and sell fills at bid.

---

## Issue 6 - High: Real broker fill object is incomplete and can crash the engine

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/execution/dwx_broker.py:67`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/execution/dwx_broker.py:72`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/execution/dwx_broker.py:74`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/execution/dwx_broker.py:79`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:94`

Current behavior:

`DWXBrokerAdapter.fills()` returns a `Fill` with:

```python
symbol=""
side=0
```

If `price == 0.0` or no response is available, the generator yields nothing. The engine then calls:

```python
fill = next(deps.broker.fills())
```

and can raise `StopIteration`.

Why this is bad:

Live engine can crash after a successful command if the EA response is incomplete or async. Even when it does not crash, the fill object does not faithfully represent symbol/side.

RCA:

The broker adapter assumes the last command response is always a full fill confirmation. The engine assumes `fills()` always yields exactly one fill.

Fix:

- Make `submit_order` return a structured execution result containing ticket, symbol, side, volume, price, timestamp, and broker status.
- If the broker is asynchronous, separate `submit_order` from `wait_for_fill(ticket)`.
- Validate fill fields before opening `OpenTrade`.
- Do not use `next()` without handling absence.

Acceptance test:

- Fake bridge returns success without price.
- Engine should not crash; it should mark order as submitted/pending or fail gracefully with a journal event.

---

## Issue 7 - High: SDR-001 strategy hard-codes M1 timing

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:134`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:136`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/cli.py:95`

Current behavior:

`SDR001Strategy` uses:

```python
next_bar_ts = bar_ts + pd.Timedelta(minutes=1)
```

But the CLI live default timeframe is `H1`, and the strategy/event generator itself reasons across M1 raw data resampled to M5/M15.

Why this is bad:

If the live runner is started with `H1`, `M15`, or `M5`, the strategy looks one minute ahead and will miss most or all events. If it is started with `M1`, the code still needs enough rolling M1 history to generate M5/M15 context.

RCA:

The strategy wrapper assumes an M1 engine driver but the live runner accepts arbitrary timeframes and defaults to `H1`.

Fix:

- Make SDR-001 require `timeframe="M1"` at construction or live runner validation.
- Or pass timeframe seconds into the strategy and use `pd.Timedelta(seconds=seconds(timeframe))`.
- Prefer explicit architecture:
  - engine ingests M1,
  - strategy internally builds M5/M15/H1 features.

Acceptance test:

- Starting `bt-engine live --strategy sdr001 --timeframe H1` should fail fast with a clear message.
- Starting with `M1` should not fail.

---

## Issue 8 - High: Forward-rule feature gates are not computed by the live generator

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:110`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:113`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:116`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/generator.py:274`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/generator.py:324`

Current behavior:

The strategy supports `forward_rule`, but `generate_events_from_raw` returns only base event columns. It does not compute gates like:

- `cost_le_0p05`
- `ema8_aligned`
- `base_body_low`
- `ny_main_or_overlap`
- `orb_reversal`
- `fast_confirm_1`
- `body_ge_45`

Missing flags cause the mask to become `False`, dropping all events.

Why this is bad:

The exact SDR-001 live rulebook cannot currently be executed. The only way to reproduce the chosen base is still the historical `zone_id` whitelist, which is not live-safe.

RCA:

The research feature matrix logic was not ported into the live generator.

Fix:

- Port the feature builder used in research into production code.
- Create a `FeatureFrame` or `SignalFeatures` object with all rule predicates.
- Put rule predicates in one tested place.
- Make missing rule predicates a startup error, not a silent no-trade behavior.

Acceptance test:

- Given a known historical event row, live generator computes the same boolean predicates as the research feature matrix.

---

## Issue 9 - Medium: Live mode does not persist trades, journal events, signals, or account snapshots

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/live.py:109`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/live.py:135`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:98`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:108`

Current behavior:

`run_live` creates and closes a run row, but `on_trade_open` is not wired. `on_trade_close` only appends to an in-memory list. `SignalRepo`, `TradeRepo`, `JournalRepo`, and `AccountSnapshotRepo` are not connected to live events.

Why this is bad:

A live run can place orders without durable audit trail. If the process crashes, there is no complete trade lifecycle record.

RCA:

DB persistence exists for parity replay, but the real engine callback layer has not been implemented.

Fix:

- Add live callbacks:
  - on signal: insert `bt_signals`,
  - on order submit: insert journal event,
  - on fill: insert `bt_trades`,
  - on bar walk: insert `bt_bar_walk`,
  - on close: update trade and insert exit event,
  - on each poll: optional account snapshot.
- Commit in small transaction boundaries.

Acceptance test:

- Fake live run with one filled trade should leave rows in `bt_runs`, `bt_trades`, and `bt_journal_events`.

---

## Issue 10 - Medium: Signal/journal events emitted by strategies are ignored by the engine

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py:184`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:112`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:116`

Current behavior:

`SDR001Strategy` returns `new_events`, but `run_engine` never records or forwards them.

Why this is bad:

The strategy emits useful audit events like `ENTRY_SUBMIT`, but they disappear. This blocks the “full journal from signal to confirmation to entry to exit” requirement.

RCA:

The `StepResult` type supports events, but engine dependencies do not include an `on_event` callback or repo integration.

Fix:

- Add `on_strategy_event` callback to `EngineDeps`.
- In `run_engine`, iterate over `step.new_events` and forward them.
- Wire this callback to `JournalRepo`/`SignalRepo` in live and backtest runners.

Acceptance test:

- Stub strategy emits one `StrategyEvent`.
- Engine callback receives exactly that event.

---

## Issue 11 - Medium: Open positions are lost at process restart

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:68`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:69`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py:70`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/execution/dwx_broker.py:87`

Current behavior:

Every engine run starts with empty `pending` and `open_trades`. The broker adapter can read positions, but `run_engine` never reconciles them.

Why this is bad:

If the live process restarts while a position is open, the engine will not manage the stop/TP lifecycle or journal the existing position.

RCA:

There is no startup reconciliation between DB state, broker positions, and engine memory.

Fix:

- On live startup:
  - read broker positions,
  - read DB open trades,
  - reconcile by ticket/comment/magic,
  - rebuild `open_trades`,
  - cancel or alert on unknown positions.

Acceptance test:

- Fake broker starts with one open position.
- Engine restart reconstructs one `OpenTrade` and continues management.

---

## Issue 12 - Medium: `session_scope` is not a real context manager

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/db/engine.py:41`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/db/engine.py:45`

Current behavior:

`session_scope` yields a session but is not decorated with `@contextmanager`.

Why this is bad:

Callers cannot use:

```python
with session_scope() as s:
    ...
```

without getting incorrect behavior.

RCA:

The generator-style helper was written but not wrapped with `contextlib.contextmanager`.

Fix:

```python
from contextlib import contextmanager

@contextmanager
def session_scope() -> Iterator[Session]:
    ...
```

Acceptance test:

- `with session_scope() as s:` commits on success and rolls back on exception.

---

## Issue 13 - Medium: Baseline source imports are path-injected at runtime

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/generator.py:20`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/generator.py:21`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/data/normalize.py:13`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/data/normalize.py:15`

Current behavior:

Production code mutates `sys.path` to import from:

```text
research-baseline/code/src
```

Why this is bad:

The engine is not self-contained. Moving the package, deploying it, or changing the copied research baseline can change production behavior.

RCA:

Research code was reused directly instead of being promoted into a stable package/module boundary.

Fix:

- Vendor/promote the required functions into `bt_engine` proper:
  - ATR,
  - resample,
  - causality validation.
- Or package `intraday_edge_lab` as a formal dependency with pinned version/hash.
- Add startup hash check for the rulebook and source package.

Acceptance test:

- Install `bt_engine` in a clean virtual environment without `research-baseline` on disk.
- Import and run SDR generator successfully.

---

## Issue 14 - Low: Test coverage proves parity, not live causality

Evidence:

- `/Users/subash/SUBASH/GoldDigger/bt_engine/tests/parity/test_incremental_parity.py:71`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/tests/parity/test_incremental_parity.py:73`

Current behavior:

The incremental parity test passes `preloaded_raw=raw`, meaning the strategy sees the full slice upfront.

Why this is bad:

That is good for replay parity, but it does not prove live streaming behavior. A live strategy should discover events only after bars arrive.

RCA:

Tests were designed around historical reproduction first, not forward-only execution.

Fix:

- Add tests without `preloaded_raw`.
- Feed bars sequentially.
- Assert no event appears before its confirmation/entry time.
- Assert event appears when sufficient bars arrive.
- Assert future bars do not affect past emitted orders.

Acceptance test:

- Two datasets identical through time `T` but different after `T` must emit identical orders through `T`.

---

## Priority Fix Order

1. Block `sleeve1_filter=True` in live mode and create a real frozen rulebook JSON.
2. Replace one-shot live event initialization with true incremental event discovery.
3. Fix live order timing so orders submit immediately after signal close.
4. Remove `_bounded_loop` or make it use the same engine lifecycle.
5. Fix dry-run and real broker fill handling.
6. Wire live persistence and strategy events into DB/journal.
7. Add restart reconciliation.
8. Remove runtime `sys.path` coupling to `research-baseline`.

## Bottom Line

Original review verdict before the fix pass:

```text
BT/parity scaffold: usable
Forward paper-live signal engine: not certified
Live broker execution: blocked
```

---

## Fix Pass - 2026-06-29

Request:

Re-check every RCA, confirm whether the issue is real, fix confirmed issues, retest, then move to the next issue.

Verification:

```text
cd /Users/subash/SUBASH/GoldDigger/bt_engine
python3 -m pytest
164 passed, 1 warning in 216.96s
```

The remaining warning is the pre-existing pandas fragmentation warning in `bt_engine/strategies/sdr001/summary.py`; it is performance-only and not a correctness failure.

### Issue Resolution Status

| Issue | Re-confirmed? | Status | Fix Summary |
|---|---:|---|---|
| 1. `sleeve1_filter=True` default blocks future live trading | Yes | Fixed | `SDR001Strategy` now defaults `sleeve1_filter=False`; live validation rejects replay-only sleeve filtering. Frozen replay remains separate. |
| 2. Live event generation initializes once | Yes | Fixed | Non-preloaded/raw mode now recomputes from causal history on each bar and deduplicates with stable `trade_key`. |
| 3. Live order submitted after target bar close | Yes | Fixed | Live mode submits/fills newly emitted orders immediately during the signal bar processing cycle; BT still uses next-bar-open simulation. |
| 4. `max_ticks` bypasses execution | Yes | Fixed | Removed bounded side loop; `max_ticks` now maps to `run_engine(max_bars=...)`, preserving normal execution/fill/close path. |
| 5. Dry-run fill price = `1` | Yes | Fixed | `DryRunBroker` now fills at the current bar close and rejects invalid placeholder pricing. |
| 6. Real broker fill incomplete / `StopIteration` crash | Yes | Fixed | `DWXBrokerAdapter` stores the last order and returns complete fill fields; engine handles missing fills without crashing and emits `ORDER_SUBMIT_NO_FILL`. |
| 7. SDR-001 hard-coded M1 while live CLI allowed H1 | Yes | Fixed | SDR-001 live validation fails fast unless timeframe is `M1`. Other strategies can still use their own timeframes. |
| 8. Forward-rule feature gates missing | Yes | Fixed | Production generator now computes core live rule flags: cost, body, fast-confirm, base-body, session, EMA alignment, ORB continuation/reversal/inside, risk, impulse, zone width. Missing rule flags now raise instead of silently dropping all trades. |
| 9. Live mode missing durable audit trail | Yes | Fixed | Live runner now wires trade open/close, strategy signals, journal events, bar-walk journal, and account snapshots into the existing DB repos. |
| 10. Strategy events ignored by engine | Yes | Fixed | `EngineDeps.on_strategy_event` added; engine forwards `StepResult.new_events`. |
| 11. Open positions lost on restart | Yes | Fixed | Live runner reconstructs broker positions into `OpenTrade`; engine fires `on_trade_open` for initial positions so they are persisted before management continues. |
| 12. `session_scope` not a real context manager | Yes | Fixed | Added `@contextmanager` and regression test. |
| 13. Runtime `sys.path` injection to `research-baseline` | Yes | Fixed | Promoted normalization, ATR, and OHLCV resampling into `bt_engine`; generator and live normalization no longer mutate `sys.path`. |
| 14. Tests proved replay parity, not live causality | Yes | Fixed | Added tests for streaming event discovery, live signal-bar submission, no-fill handling, max-tick live execution path, dry-run pricing, forward flags, and restart reconciliation. |

### Files Changed

- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/core/engine.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/data/normalize.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/db/engine.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/execution/dwx_broker.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/runner/live.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/generator.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/bt_engine/strategies/sdr001/strategy.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/tests/integration/test_engine_loop.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/tests/unit/data/test_normalize.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/tests/unit/db/test_repo_streaming.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/tests/unit/execution/test_dwx_broker.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/tests/unit/runner/test_live_cli.py`
- `/Users/subash/SUBASH/GoldDigger/bt_engine/tests/unit/strategies/sdr001/test_strategy.py`

### Important Note

The frozen baseline replay remains intact and still passes the 1032-trade parity tests. The live/raw SDR-001 path is now structurally live-safe enough for paper-live validation, but it still needs observation before real money because broker latency, spread, slippage, and MT5/DWX operational behavior are outside unit-test guarantees.
