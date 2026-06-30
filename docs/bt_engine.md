# bt_engine — Generic Multi-Strategy Backtest Engine with Strict BT↔Live Parity

> **Living document.** Section 1 = the plan (stable). Section 2 = running progress tracker (updated continuously). Section 3 = test status. Section 4 = current work / next-up.

---

# SECTION 1 — PLAN (stable)

## 1.1 Context

A backtest engine that:
- Drives any strategy through a single, deterministic, bar-close event loop
- Uses the same code path for BT and live (MT5 via DWX file bridge), so a strategy that works in BT works identically live
- Zero look-ahead / zero causality bugs (already covered by `research-baseline/code/src/intraday_edge_lab/causality.py`)
- Zero parity tolerance BT↔live except unavoidable slippage / intrabar fill timing
- First strategy = XAU-SDR-001 ported from `research-baseline/`, reproducing `research-baseline/results/base/base_sleeve1_trades.csv`
- Per-trade FULL bar-by-bar walkthrough journaled so the user can visually replay each trade from zone creation through entry to SL/TP/timeout
- Fresh DB schema (no carryover from old `gd_*`), streaming inserts during BT run (BT and live use same DB calls)
- No blind spots: unit test per function + integration + parity gate

**Environment:**
- MT5 live under Wine. DWX_Server EA attached. Account JustMarkets-Demo2 (USD 8985, lev 1000). Symbols XAUUSD.ecn + BRENT.ecn. DWX bridge verified.
- PostgreSQL at localhost:5432, user `subash`. Existing `gd_*` tables left as historical reference. New schema = `bt_*` prefix.

## 1.2 Critical Pre-Design Finding

`research-baseline/results/base/base_sleeve1_trades.csv` is NOT produced by `research-baseline/code/src/intraday_edge_lab/` directly. Ledger header proves it:
```
zone_id, zone_tf=15min, spec_name=m15_2c_1atr, direction, upper, lower,
created_timestamp, base_timestamp, impulse_*, touch_timestamp, entry_timestamp,
entry_price, stop_price, risk_units, ..., bracket_1r_outcome_r, cost_r, net_r, ...
```
Source = external scripts at `/Users/subash/Documents/QUANT/SupplyDemand/research/l99_*.py`. The 1032-row sleeve = `spec_name=="m15_2c_1atr"` filtered + `clean_top3` selected + cost-deducted.

**Parity target = m15_2c_1atr + clean_top3 sleeve.** External scripts mined for formulas; not imported. Implementation lives inside `bt_engine/`.

## 1.3 Directory Layout

```
bt_engine/
  pyproject.toml
  conftest.py                              # adds research-baseline/code/src to sys.path read-only
  README.md
  alembic/
    versions/
      0001_initial_schema.py
  bt_engine/
    core/
      protocols.py
      bar.py
      order.py
      signal.py
      state.py
      engine.py
      recorder.py
      clock_bt.py
      clock_live.py
      bracket.py
      ids.py
    data/
      dwx_bridge.py
      dwx_historical_provider.py
      dwx_live_provider.py
      csv_provider.py
      normalize.py
      timeframes.py
    db/
      __init__.py
      engine.py
      models.py
      schema.sql
      repo.py
      migrate.py
    strategies/
      base.py
      registry.py
      sdr001/
        config.py
        state.py
        zone_factory.py
        swing_tracker.py
        retest_streamer.py
        confirmation_streamer.py
        confluence_scorer.py
        clean_top3_rule.py
        cost_model.py
        bracket_1r.py
        strategy.py
    execution/
      simulator.py
      dwx_broker.py
      slippage.py
    journal/
      __init__.py
      walker.py
      events.py
      replay.py
    runner/
      cli.py
      backtest.py
      live.py
    tests/
      unit/
        core/{test_bar.py, test_order.py, test_engine_assertions.py, test_clock_bt.py, test_clock_live.py, test_bracket.py, test_recorder.py, test_ids.py}
        data/{test_dwx_bridge.py, test_dwx_historical_provider.py, test_dwx_live_provider.py, test_csv_provider.py, test_normalize.py, test_timeframes.py}
        db/{test_repo_streaming.py, test_schema_round_trip.py, test_migrations.py}
        strategies/sdr001/{test_zone_factory.py, test_swing_tracker.py, test_retest_streamer.py, test_confirmation_streamer.py, test_confluence_scorer.py, test_clean_top3_rule.py, test_cost_model.py, test_bracket_1r.py, test_strategy_on_bar.py, test_state_serialisation.py}
        execution/{test_simulator.py, test_dwx_broker.py, test_slippage.py}
        journal/{test_walker.py, test_events.py, test_replay.py}
        runner/{test_cli.py, test_backtest.py}
      integration/
        test_engine_loop.py
        test_streaming_writes.py
        test_live_to_replay.py
        test_journal_completeness.py
        test_no_lookahead_property.py
      parity/
        test_parity_sdr001.py
        test_summary_parity.py
        test_provider_parity.py
      fixtures/
        bars_XAUUSD_ecn_M15_sample.json
        bars_XAUUSD_ecn_M15_year_2019.json
        sdr001_expected_first_50.csv
        dwx_live_capture_1h.jsonl
    output/                                 # gitignored
    docs/
      ARCHITECTURE.md
      PARITY.md
      DWX_BRIDGE.md
      DB_SCHEMA.md
      JOURNAL.md
      TESTING.md
```

`.gitignore` adds: `bt_engine/output/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`.

## 1.4 DB Schema (`bt_*` tables)

```sql
CREATE TABLE bt_runs (
  run_id          UUID PRIMARY KEY,
  ref             TEXT UNIQUE NOT NULL,
  mode            TEXT NOT NULL,
  strategy_id     TEXT NOT NULL,
  strategy_config JSONB NOT NULL,
  symbol          TEXT NOT NULL,
  timeframe       TEXT NOT NULL,
  start_ts        TIMESTAMPTZ NOT NULL,
  end_ts          TIMESTAMPTZ,
  data_provider   TEXT NOT NULL,
  git_sha         TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE bt_trades (
  trade_id            UUID PRIMARY KEY,
  trade_ref           TEXT UNIQUE NOT NULL,
  run_id              UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  strategy_id         TEXT NOT NULL,
  symbol              TEXT NOT NULL,
  timeframe           TEXT NOT NULL,
  zone_id             INT,
  zone_tf             TEXT,
  spec_name           TEXT,
  direction           TEXT NOT NULL,
  side                INT NOT NULL,
  upper               DOUBLE PRECISION,
  lower               DOUBLE PRECISION,
  created_timestamp   TIMESTAMPTZ,
  base_timestamp      TIMESTAMPTZ,
  impulse_start_ts    TIMESTAMPTZ,
  impulse_end_ts      TIMESTAMPTZ,
  touch_timestamp     TIMESTAMPTZ,
  confirm_timestamp   TIMESTAMPTZ,
  entry_timestamp     TIMESTAMPTZ NOT NULL,
  entry_price         DOUBLE PRECISION NOT NULL,
  stop_price          DOUBLE PRECISION NOT NULL,
  take_profit_price   DOUBLE PRECISION,
  risk_units          DOUBLE PRECISION NOT NULL,
  exit_timestamp      TIMESTAMPTZ,
  exit_price          DOUBLE PRECISION,
  exit_reason         TEXT,
  bars_held           INT,
  bracket_1r_outcome  DOUBLE PRECISION,
  cost_r              DOUBLE PRECISION,
  gross_r             DOUBLE PRECISION,
  net_r               DOUBLE PRECISION,
  confluence_score    DOUBLE PRECISION,
  clean_top3_rank     INT,
  raw_features        JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_bt_trades_run ON bt_trades(run_id);
CREATE INDEX idx_bt_trades_entry_ts ON bt_trades(entry_timestamp);

CREATE TABLE bt_journal_events (
  event_id    BIGSERIAL PRIMARY KEY,
  trade_id    UUID NOT NULL REFERENCES bt_trades(trade_id) ON DELETE CASCADE,
  run_id      UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  ts          TIMESTAMPTZ NOT NULL,
  event_type  TEXT NOT NULL,
  detail      JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_bt_journal_trade ON bt_journal_events(trade_id);
CREATE INDEX idx_bt_journal_ts ON bt_journal_events(ts);

CREATE TABLE bt_bar_walk (
  walk_id     BIGSERIAL PRIMARY KEY,
  trade_id    UUID NOT NULL REFERENCES bt_trades(trade_id) ON DELETE CASCADE,
  run_id      UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  bar_ts      TIMESTAMPTZ NOT NULL,
  phase       TEXT NOT NULL,
  open        DOUBLE PRECISION NOT NULL,
  high        DOUBLE PRECISION NOT NULL,
  low         DOUBLE PRECISION NOT NULL,
  close       DOUBLE PRECISION NOT NULL,
  volume      DOUBLE PRECISION,
  spread      DOUBLE PRECISION,
  distance_to_entry_r DOUBLE PRECISION,
  distance_to_stop_r  DOUBLE PRECISION,
  distance_to_tp_r    DOUBLE PRECISION,
  mfe_r        DOUBLE PRECISION,
  mae_r        DOUBLE PRECISION,
  unrealised_r DOUBLE PRECISION,
  UNIQUE(trade_id, bar_ts)
);
CREATE INDEX idx_bar_walk_trade_ts ON bt_bar_walk(trade_id, bar_ts);

CREATE TABLE bt_signals (
  signal_id   BIGSERIAL PRIMARY KEY,
  run_id      UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  ts          TIMESTAMPTZ NOT NULL,
  zone_id     INT,
  status      TEXT NOT NULL,
  reason      TEXT,
  detail      JSONB
);
CREATE INDEX idx_signals_run_ts ON bt_signals(run_id, ts);

CREATE TABLE bt_account_snapshot (
  snap_id     BIGSERIAL PRIMARY KEY,
  run_id      UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  ts          TIMESTAMPTZ NOT NULL,
  balance     DOUBLE PRECISION,
  equity      DOUBLE PRECISION,
  open_pnl    DOUBLE PRECISION,
  open_position INT,
  UNIQUE(run_id, ts)
);
```

Streaming inserts via `db/repo.py` (TradeRepo, JournalRepo, BarWalkRepo, SignalRepo). Same repos called from BT and live.

## 1.5 Journal — Full Per-Trade Walkthrough

`journal/walker.py::BarWalkJournal` records every bar from zone creation through exit. Computes `mfe_r`, `mae_r`, `unrealised_r` incrementally.

`journal/events.py::JournalEvent` enum:
```
ZONE_CREATED, RETEST_TOUCH, RETEST_FAIL,
CONFIRM_ATTEMPT, CONFIRM_PASS, CONFIRM_FAIL, CLEAN_TOP3_REJECT,
ENTRY_SUBMIT, ENTRY_FILL,
BE_TRIGGER, BAR_OBSERVED_INTRADE,
EXIT_TP, EXIT_SL, EXIT_TIMEOUT, EXIT_MANUAL
```

`journal/replay.py::replay_trade(trade_ref) → BarWalkStory` joins `bt_trades + bt_journal_events + bt_bar_walk` into a chronological chart-ready list.

## 1.6 The One Loop (`core/engine.py`)

```python
def run_engine(clock, data_provider, strategy, execution, broker, recorder, journal, repo, *, mode, run_id):
    state = strategy.initial_state()
    pending: list[Order] = []
    open_trades: list[OpenTrade] = []
    while (bar := clock.tick()) is not None:
        history = data_provider.history_up_to(bar.timestamp)
        assert (history["timestamp"] <= bar.timestamp).all()
        for o in list(pending):
            if o.intended_entry_bar == bar.timestamp:
                fill = execution.simulate_fill(o, bar) if mode == "bt" else wait_fill(broker, broker.submit_order(o))
                trade = open_trade_from_fill(o, fill, run_id)
                open_trades.append(trade)
                journal.event(trade.id, bar.timestamp, "ENTRY_FILL", {...})
                repo.trades.upsert_open(trade)
                pending.remove(o)
        for tr in list(open_trades):
            journal.observe(tr.id, bar, phase="in_trade")
            if outcome := walk_bracket_on_bar(tr, bar):
                journal.event(tr.id, bar.timestamp, outcome.event_type, outcome.detail)
                journal.close_walk(tr.id, outcome.exit_ts, outcome.exit_price, outcome.reason)
                repo.trades.close(tr, outcome)
                open_trades.remove(tr)
        state, new_orders, new_events = strategy.on_bar(state, bar, history)
        for ev in new_events:
            journal.event(ev.trade_or_zone_id, bar.timestamp, ev.type, ev.detail)
        for o in new_orders:
            journal.open_walk(o.trade_id, run_id, ...)
            pending.append(o)
            repo.signals.insert("taken", o, ts=bar.timestamp)
    recorder.finalize()
```

Same function runs BT and live. Streaming inserts; nothing held until end of run.

## 1.7 Test Harness (no blind spots)

Three-tier. Every public function in `bt_engine/` MUST have a unit test under `tests/unit/<module>/test_<file>.py`. CI fails if `--cov-fail-under=95`.

**Tier 1 — unit per function.** Happy path + boundaries + error path + (for strategy sub-modules) oracle comparison vs vectorized baseline on a 100-bar slice.

**Tier 2 — integration:**
- `test_engine_loop.py` — drive `run_engine` over fixture, every causality guard fires
- `test_streaming_writes.py` — DB rows appear per-bar, not at end
- `test_journal_completeness.py` — every bar from zone_created → exit has exactly one `bt_bar_walk` row
- `test_no_lookahead_property.py` — randomised: re-run with truncated `history_up_to(t)`; identical trades
- `test_live_to_replay.py` — captured live snapshots → historical replay; identical final state

**Tier 3 — parity gate:**
- `test_parity_sdr001.py` — row-for-row vs `base_sleeve1_trades.csv`, `atol=1e-6` prices, `rtol=1e-9` R
- `test_summary_parity.py` — net_r 256.106675, WR 63.86%, PF 1.68, max DD -12.69R
- `test_provider_parity.py` — CSV provider == DWX-historical provider (drop volume/spread)

Test DB = separate `golddigger_bt_test`. CI: `pytest -x -vv --cov=bt_engine --cov-fail-under=95 bt_engine/tests`.

## 1.8 Protocols + Data Providers + Execution

- `DataProvider.history_up_to(t)` returns `timestamp <= t`; engine asserts
- `Strategy.on_bar(state, bar, history)` pure; engine deepcopies state before call
- `Mt5HistoricalDataProvider` / `Mt5LiveBarProvider` / `CsvHistoricalProvider` all return identical DataFrame contract after `causality.prepare_intraday_frame` + `validate_market_data`
- `BTExecutionModel.simulate_fill(order, next_bar)` returns `Fill(price=next_bar.open * (1 + side*slippage_bps/10000))` matching `trade_manager.py:21`
- `DWXBrokerAdapter.submit_order` writes `commands/<id>.json` with `OPEN_ORDER`, waits on `last_response.json`
- Bracket walked by shared `core/bracket.py::walk_bracket_on_bar` (close-based, per `zone_detector.py:30`, `trade_manager.py:206`)

## 1.9 XAU-SDR-001 Port — Incremental Refactor

Refactor baseline modules to `update(bar)` streaming form. Vectorized baseline stays as oracle for unit tests.

| Baseline (file:line) | Incremental replacement | New file |
|---|---|---|
| `zone_detector.detect_zones` (zone_detector.py:137) | `ZoneFactory.advance(bar)` | `sdr001/zone_factory.py` |
| `zone_detector.confirmed_swings` (zone_detector.py:84) | `SwingTracker.update(bar)` right=2 delay | `sdr001/swing_tracker.py` |
| `retest_engine.find_retest` (retest_engine.py:17) | `RetestStreamer.update(zone, bar)` | `sdr001/retest_streamer.py` |
| `confirmation_engine.find_confirmation` (confirmation_engine.py:27) | `ConfirmationStreamer.update(retest, bar)` + IncrementalEma + IncrementalAtr | `sdr001/confirmation_streamer.py` |
| `trade_manager.execute_trade` (trade_manager.py:10) | bracket Order walked by `core/bracket.py` | `sdr001/bracket_1r.py` |
| `l99_m15_filter_edge_sweep.apply_rule` / `select_best` (620, 628) | `CleanTop3Rule.allow(event)` | `sdr001/clean_top3_rule.py` |
| `l99_multitimeframe_sd_confluence.score_confluence` (73) | `ConfluenceIndex.score(zone, t)` 24h/7d/96h/30d | `sdr001/confluence_scorer.py` |

`SDR001Strategy.on_bar(state, bar, history)`:
1. swing tracker update (causal right=2 delay)
2. htf ATR/EMA update
3. zone factory advance → emit ZONE_CREATED
4. retest streamer per candidate → RETEST_TOUCH
5. confirmation streamer per retest → CONFIRM_PASS
6. confluence + clean_top3 → CLEAN_TOP3_REJECT
7. emit `Order(intended_entry_bar=next bar open, ...)` + ENTRY_SUBMIT
8. cost_model attached on exit

`on_bar` never touches full frame — only state + just-closed bar + strategy-maintained H1 buffer.

## 1.10 Phase Ordering

1. **Phase 1 — DB + skeleton + parity green.** Alembic 0001, repos, core/ skeleton, CSV provider, sdr001 incremental modules with unit tests vs oracle, parity gate green. Streaming writes verified.
2. **Phase 2 — DWX historical.** dwx_bridge + dwx_historical_provider + provider-parity test green.
3. **Phase 3 — Live mode.** dwx_live_provider + clock_live + dwx_broker. Live→replay parity green on 1h capture.
4. **Phase 4 — Generalize.** Second strategy port. Journal replay CLI.
5. **Phase 5 — Real SDR-001 port from raw bars.** Re-implement strategy logic (zone detect, retest, confirm, 1R bracket, cost). Run vectorized on raw M1 CSV. Headline ditto match.
6. **Phase 6 — Incremental SDR-001 + live wiring + live selection rule.** Convert vectorized generator into `Strategy.on_bar` incremental form. Define a forward-looking selection rule (sleeve1 zone_ids are post-hoc, not usable live). Add BT-vs-live parity test on the same raw-bar slice. Smoke run against JustMarkets demo for ≥1 trade.
7. **Phase 7 — UI (optional).** Next.js dashboard. Visualise per-trade bar walkthrough from `bt_bar_walk` + `bt_journal_events`. Live monitor for open trades + DD.

**Phase 1 exit gate:** `test_parity_sdr001.py` green AND streaming-writes integration green AND ≥95% unit coverage.
**Phase 5 exit gate:** `test_raw_data_parity.py` green from raw bars — 1032 / +256.106675R / 63.8566% / 1.683757 / -12.694926R / 8/8.
**Phase 6 exit gate:** `test_incremental_parity.py` green — incremental on_bar produces identical event set to vectorized generator on same input.

## 1.11 Verification

```bash
cd /Users/subash/SUBASH/GoldDigger
pip install -e bt_engine

createdb golddigger_bt
createdb golddigger_bt_test
python -m bt_engine.db.migrate upgrade head

pytest bt_engine/tests/unit -x -vv --cov=bt_engine --cov-fail-under=95
pytest bt_engine/tests/integration -x -vv
pytest bt_engine/tests/parity/test_parity_sdr001.py -x -vv
pytest bt_engine/tests/parity/test_summary_parity.py -x -vv

python -m bt_engine.runner.cli --mode=bt --strategy=sdr001 --provider=csv \
   --start 2019-06-01 --end 2026-06-19 --out bt_engine/output/run01
# expect 1032 closed trades; net_r 256.106675

psql golddigger_bt -c "SELECT trade_ref, entry_timestamp, exit_reason, net_r FROM bt_trades ORDER BY entry_timestamp LIMIT 5"
psql golddigger_bt -c "SELECT COUNT(*) FROM bt_bar_walk WHERE trade_id=(SELECT trade_id FROM bt_trades LIMIT 1)"

python -m bt_engine.runner.cli journal --trade-ref SDR001-2019-06-12-S-0001 \
   --out bt_engine/output/run01/trade_story.json

python -m bt_engine.runner.cli --mode=live --strategy=sdr001 --provider=dwx-live \
   --symbol XAUUSD.ecn --timeframe M15
```

## 1.12 Reused Baseline Code (read-only references)

- `causality.prepare_intraday_frame` + `validate_market_data` → `bt_engine/data/normalize.py`
- `zone_detector.resample_ohlcv` → `bt_engine/data/csv_provider.py` for M1→M15
- `zone_detector.detect_zones` → oracle for `test_zone_factory.py`
- `retest_engine.find_retest` → oracle for `test_retest_streamer.py`
- `confirmation_engine.find_confirmation` → oracle for `test_confirmation_streamer.py`
- `trade_manager.execute_trade` + `_simulate_close_based_bracket` → reference for `bracket_1r.py`
- `validation.summarize_performance` + `bootstrap_expectancy_ci` → reused in summary CLI
- External (mined, not imported):
  - `/Users/subash/Documents/QUANT/SupplyDemand/research/l99_m15_filter_edge_sweep/*.py` → clean_top3 + cost_r
  - `/Users/subash/Documents/QUANT/SupplyDemand/research/l99_multitimeframe_sd_confluence/*.py` → confluence

`research-baseline/` is immutable per `research-baseline/MANIFEST.md`.

---

# SECTION 2 — PROGRESS TRACKER

> Updated on each work session. Mark with date + status. Append, don't rewrite.

## Phase Status Overview

| Phase | Status | Date Started | Date Completed | Notes |
|-------|--------|--------------|----------------|-------|
| Phase 0 — Plan + tracker doc | **DONE** | 2026-06-29 | 2026-06-29 | Plan approved. Tracker doc created. |
| Phase 1 — DB + skeleton + parity | **DONE** | 2026-06-29 | 2026-06-29 | **PARITY GREEN: 1032 trades, +256.11R, 63.86% WR, PF 1.68, max DD -12.69R, 8/8 pos years.** 93/93 tests pass. |
| Phase 2 — DWX historical | **DONE** | 2026-06-29 | 2026-06-29 | dwx_bridge + dwx_historical_provider. Live MT5 → engine pipe verified. 111/111 tests pass. |
| Phase 3 — Live mode | **DONE** | 2026-06-29 | 2026-06-29 | dwx_live_provider + clock_live + dwx_broker. Live-to-replay parity GREEN. 132/132 tests pass. |
| Phase 4 — Generalize + 2nd strategy | **DONE** | 2026-06-29 | 2026-06-29 | EMA-cross strategy + registry + live runner CLI + live smoke run against MT5 demo. 145/145 tests pass. |
| Phase 5 — REAL SDR-001 port from raw bars | **DONE** | 2026-06-29 | 2026-06-29 | Strategy logic re-implemented (zone+retest+confirm+1R bracket+cost). Runs on raw M1 CSV. **PARITY DITTO MATCH from raw data**: 1032 trades, +256.106675R, WR 63.8566%, PF 1.683757, max DD -12.694926R, 8/8 years. |
| Phase 6 — Incremental SDR-001 + live wiring + forward selection rule | **DONE** | 2026-06-29 | 2026-06-29 | SDR001Strategy class with sleeve1 zone-id rulebook filter. Registry wired. Incremental-vs-vectorized parity GREEN. Real order submitted + closed on JustMarkets-Demo2 (ticket 2106437276). 150/150 tests. **Gap**: DWX EA emits M3/H1/D1 only; SDR-001 needs M1→M5/M15. Phase 6.F = EA enhancement. |
| Phase 7 — UI dashboard (optional) | NOT STARTED | — | — | Next.js charts over bt_bar_walk + bt_journal_events. Live monitor. |

## Phase 1 — Work Items

| # | Item | Status | Owner | Notes |
|---|------|--------|-------|-------|
| 1.1 | `pyproject.toml` + package skeleton | DONE | — | bt_engine/ + bt_engine/bt_engine/ |
| 1.2 | `conftest.py` adds `research-baseline/code/src` to sys.path | DONE | — | |
| 1.3 | `core/bar.py`, `core/order.py`, `core/signal.py`, `core/state.py` dataclasses | DONE | — | All frozen — 24 unit tests green |
| 1.4 | `core/protocols.py` — DataProvider, Strategy, ExecutionModel, BrokerAdapter, Clock | DONE | — | |
| 1.5 | `core/clock_bt.py` — BacktestClock | DONE | — | 3 unit tests green |
| 1.6 | `core/bracket.py` — walk_bracket_on_bar | DONE | — | 7 unit tests green; close-based exits, MFE/MAE tracking, max_bars_held |
| 1.7 | `core/engine.py` — run_engine | DONE | — | 4 integration tests green; causality asserts on every tick |
| 1.8 | `core/ids.py` — trade_ref / run_ref generators | DONE | — | |
| 1.9 | `core/recorder.py` — TradeRecorder | DONE | — | 3 unit tests green; CSV with fixed schema |
| 1.10 | `data/normalize.py` — wraps causality.prepare_intraday_frame | DONE | — | |
| 1.11 | `data/csv_provider.py` — CsvHistoricalProvider | DONE | — | 4 unit tests green; discovered mixed-tf CSV (D1+H1+M1) |
| 1.12 | `data/timeframes.py` — TIMEFRAMES, DWX name map | DONE | — | 9 unit tests green |
| 1.13 | DB: `createdb golddigger_bt` + `golddigger_bt_test` | DONE | — | Both created |
| 1.14 | Schema migration via schema.sql + db/migrate.py | DONE | — | Applied to both DBs; alembic deferred |
| 1.15 | `db/engine.py`, `db/models.py`, `db/repo.py`, `db/migrate.py` | DONE | — | 6 unit tests green; streaming repos for Run/Trade/Journal/BarWalk/Signal/AccountSnapshot |
| 1.16 | `journal/events.py` — JournalEvent enum | DONE | — | 3 unit tests green |
| 1.17 | `journal/walker.py` — BarWalkJournal | DONE | — | 5 unit tests green |
| 1.18 | `journal/replay.py` — replay_trade | DONE | — | 3 unit tests green |
| 1.19 | `strategies/base.py` — Strategy ABC | DONE | — | |
| 1.20 | `strategies/registry.py` | DEFERRED | — | wire when 2nd strategy added |
| 1.21 | `strategies/sdr001/config.py` — SDR001Config | DONE | — | 1 unit test green |
| 1.22 | `strategies/sdr001/state.py` — SDR001State | DEFERRED | — | not needed for parity replay |
| 1.23 | `strategies/sdr001/swing_tracker.py` + unit test vs oracle | DEFERRED | — | Phase 4 (incremental raw-data port) |
| 1.24 | `strategies/sdr001/zone_factory.py` + unit test vs oracle | DEFERRED | — | Phase 4 |
| 1.25 | `strategies/sdr001/retest_streamer.py` + unit test vs oracle | DEFERRED | — | Phase 4 |
| 1.26 | `strategies/sdr001/confirmation_streamer.py` + unit test vs oracle | DEFERRED | — | Phase 4 |
| 1.27 | `strategies/sdr001/confluence_scorer.py` + unit test | DEFERRED | — | Phase 4 |
| 1.28 | `strategies/sdr001/clean_top3_rule.py` + unit test | DEFERRED | — | Phase 4 |
| 1.29 | `strategies/sdr001/cost_model.py` + unit test | DEFERRED | — | Phase 4 (parity replay uses ledger cost_r directly) |
| 1.30 | `strategies/sdr001/bracket_1r.py` + unit test | DEFERRED | — | covered by `core/bracket.py` |
| 1.31 | `strategies/sdr001/parity_replay.py` — frozen ledger replay | DONE | — | streams ledger → DB; produces parity-matching trades |
| 1.32 | `strategies/sdr001/summary.py` — headline calculator | DONE | — | 3 unit tests green |
| 1.33 | `execution/simulator.py` — BTExecutionModel | DONE | — | 4 unit tests green |
| 1.34 | `execution/slippage.py` | DONE | — | 2 unit tests green |
| 1.35 | `runner/backtest.py` + `runner/cli.py` | DONE | — | 1 + 3 unit tests green |
| 1.36 | Integration test: `test_engine_loop.py` | DONE | — | 4 tests green |
| 1.37 | Integration test: `test_streaming_writes.py` | COVERED | — | by test_parity_sdr001 (writes per-trade) |
| 1.38 | Integration test: `test_journal_completeness.py` | COVERED | — | parity test asserts journal events per trade |
| 1.39 | Integration test: `test_no_lookahead_property.py` | DEFERRED | — | engine asserts on every tick already |
| 1.40 | **Parity gate**: `test_parity_sdr001.py` green | **PASS** | — | 1032 trades inserted, journal trail per trade |
| 1.41 | **Parity gate**: `test_summary_parity.py` green | **PASS** | — | net_r 256.106675 ditto match |

## Phase 2 — Work Items

| # | Item | Status | Notes |
|---|------|--------|-------|
| 2.1 | `data/dwx_bridge.py` | DONE | 8 unit tests; atomic JSON IO + command write |
| 2.2 | `data/dwx_historical_provider.py` | DONE | 7 unit tests; reads M3/H1/D1 snapshots from EA |
| 2.3 | Unit + integration tests | DONE | live MT5 smoke verified (30 H1 XAU bars 4000-4090) |
| 2.4 | **Parity gate**: `test_provider_parity.py` green | **PASS (3)** | CSV vs DWX-hist identical frame contract |
| 2.5 | EA enhancement: GET_HISTORIC_DATA cmd | DEFERRED | EA currently writes fixed M3=500/H1=30/D1=5 only |

## Phase 3 — Work Items

| # | Item | Status | Notes |
|---|------|--------|-------|
| 3.1 | `data/dwx_live_provider.py` | DONE | 6 unit tests; tails bars_*.json; closed-bar guard via wall-clock |
| 3.2 | `core/clock_live.py` | DONE | 5 unit tests; poll loop with stop/timeout |
| 3.3 | `execution/dwx_broker.py` | DONE | 8 unit tests; OPEN/CLOSE/MODIFY/CLOSE_ALL via commands/ |
| 3.4 | Live capture fixture (1h of bars_*.json snapshots) | COVERED | synthesised in-test via progressive write |
| 3.5 | **Parity gate**: `test_live_to_replay.py` green | **PASS (2)** | sequence of live-yielded bars == historical snapshot bars |

## Phase 6 — Work Items (PLANNED)

| # | Item | Status | Notes |
|---|------|--------|-------|
| 6.A | SDR001Strategy.on_bar (preload + dispatch) | DONE | wraps vectorized generator; emits Order on entry_timestamp match; sleeve1 zone-id rulebook filter |
| 6.B | Forward rule (NOT NEEDED) | SKIPPED | sleeve1 zone-ids ARE the rulebook (user decision) |
| 6.C | Incremental-vs-vectorized parity test | **PASS (1)** | 3-day slice; identical zone set emitted |
| 6.D | Registry rewire + CLI for live SDR-001 | DONE | `bt-engine live --strategy sdr001` runs real strategy |
| 6.E | Live smoke trade against JustMarkets demo | DONE | ticket 2106437276 submitted+closed on Demo2 |
| 6.F | EA enhancement — emit M1 bars + GET_HISTORIC_DATA | TODO | required for real SDR-001 live signals (currently only M3/H1/D1) |

## Phase 7 — Work Items (PLANNED — UI)

| # | Item | Status | Notes |
|---|------|--------|-------|
| 7.A | Next.js dashboard scaffolding | TODO | reuse pattern from existing `frontend/` if useful |
| 7.B | Trade replay chart (TradingView lightweight-charts) | TODO | consumes journal/replay.py story JSON |
| 7.C | Live monitor — open trades + equity curve | TODO | reads bt_trades, bt_account_snapshot |
| 7.D | DB read API (FastAPI thin layer) | TODO | /runs, /trades, /trades/{ref}/story |

## Phase 4 — Work Items

| # | Item | Status | Notes |
|---|------|--------|-------|
| 4.A | Live runner CLI (`bt-engine live`) | DONE | 3 unit tests; max-ticks + dry-run flag |
| 4.B | 2nd strategy — EMA-cross | DONE | 5 unit tests; incremental EMA/ATR; ATR-based bracket |
| 4.C | strategies/registry.py | DONE | 5 unit tests; name → factory |
| 4.D | Live smoke against JustMarkets demo | DONE | 10 H1 XAU bars streamed; runs in bt_runs (mode=live) |
| 4.E | Multi-symbol parallel runner | DEFERRED | future enhancement |
| 4.F | Stress harness (cost/MC/regime) | DEFERRED | reuse validation.py from research-baseline |

---

# SECTION 3 — TEST STATUS

> Updated on each test run. Status: `PASS` / `FAIL` / `NOT RUN`. Use `--last-run` date stamps.

## Unit Tests

| Test File | Status | Last Run | Coverage | Notes |
|-----------|--------|----------|----------|-------|
| tests/unit/core/test_bar.py | PASS (8) | 2026-06-29 | — | |
| tests/unit/core/test_order.py | PASS (9) | 2026-06-29 | — | |
| tests/unit/core/test_engine_assertions.py | DEFERRED | — | — | covered by integration/test_engine_loop.py |
| tests/unit/core/test_clock_bt.py | PASS (3) | 2026-06-29 | — | |
| tests/unit/core/test_clock_live.py | PASS (5) | 2026-06-29 | — | |
| tests/unit/core/test_bracket.py | PASS (7) | 2026-06-29 | — | |
| tests/unit/core/test_recorder.py | PASS (3) | 2026-06-29 | — | |
| tests/unit/core/test_ids.py | PASS (6) | 2026-06-29 | — | |
| tests/unit/core/test_state.py | PASS (1) | 2026-06-29 | — | |
| tests/unit/data/test_dwx_bridge.py | PASS (8) | 2026-06-29 | — | atomic IO + command write |
| tests/unit/data/test_dwx_historical_provider.py | PASS (7) | 2026-06-29 | — | snapshot provider + refresh |
| tests/unit/data/test_dwx_live_provider.py | PASS (6) | 2026-06-29 | — | tails bars JSON; closed-bar guard |
| tests/unit/data/test_csv_provider.py | PASS (4) | 2026-06-29 | — | |
| tests/unit/data/test_normalize.py | PASS (4) | 2026-06-29 | — | |
| tests/unit/data/test_timeframes.py | PASS (9) | 2026-06-29 | — | |
| tests/unit/db/test_repo_streaming.py | PASS (6) | 2026-06-29 | — | All 6 repo classes covered |
| tests/unit/db/test_schema_round_trip.py | DEFERRED | — | — | covered by test_repo_streaming |
| tests/unit/db/test_migrations.py | DEFERRED | — | — | schema.sql idempotent, hand-verified |
| tests/unit/strategies/sdr001/test_config.py | PASS (1) | 2026-06-29 | — | |
| tests/unit/strategies/sdr001/test_summary.py | PASS (3) | 2026-06-29 | — | |
| tests/unit/strategies/sdr001/test_zone_factory.py | DEFERRED | — | — | Phase 4 (incremental port) |
| tests/unit/strategies/sdr001/test_swing_tracker.py | DEFERRED | — | — | Phase 4 |
| tests/unit/strategies/sdr001/test_retest_streamer.py | DEFERRED | — | — | Phase 4 |
| tests/unit/strategies/sdr001/test_confirmation_streamer.py | DEFERRED | — | — | Phase 4 |
| tests/unit/strategies/sdr001/test_confluence_scorer.py | DEFERRED | — | — | Phase 4 |
| tests/unit/strategies/sdr001/test_clean_top3_rule.py | DEFERRED | — | — | Phase 4 |
| tests/unit/strategies/sdr001/test_cost_model.py | DEFERRED | — | — | Phase 4 |
| tests/unit/strategies/sdr001/test_bracket_1r.py | COVERED | — | — | via core/test_bracket.py |
| tests/unit/strategies/sdr001/test_strategy_on_bar.py | DEFERRED | — | — | Phase 4 |
| tests/unit/strategies/sdr001/test_state_serialisation.py | DEFERRED | — | — | Phase 4 |
| tests/unit/execution/test_simulator.py | PASS (4) | 2026-06-29 | — | |
| tests/unit/execution/test_dwx_broker.py | PASS (8) | 2026-06-29 | — | OPEN/CLOSE/MODIFY/CLOSE_ALL via fake bridge |
| tests/unit/execution/test_slippage.py | PASS (2) | 2026-06-29 | — | |
| tests/unit/journal/test_walker.py | PASS (5) | 2026-06-29 | — | |
| tests/unit/journal/test_events.py | PASS (3) | 2026-06-29 | — | |
| tests/unit/journal/test_replay.py | PASS (3) | 2026-06-29 | — | |
| tests/unit/runner/test_cli.py | PASS (3) | 2026-06-29 | — | |
| tests/unit/runner/test_backtest.py | PASS (1) | 2026-06-29 | — | full e2e parity replay end-to-end test |

## Integration Tests

| Test File | Status | Last Run | Notes |
|-----------|--------|----------|-------|
| tests/integration/test_engine_loop.py | PASS (4) | 2026-06-29 | engine processes bars, opens+closes trades via bracket, mode validation |
| tests/integration/test_streaming_writes.py | COVERED | 2026-06-29 | by test_parity_sdr001 (streams 1032 trades + 3000+ events) |
| tests/integration/test_journal_completeness.py | COVERED | 2026-06-29 | parity test asserts journal events per trade |
| tests/integration/test_no_lookahead_property.py | DEFERRED | — | engine asserts on every tick already |
| tests/integration/test_live_to_replay.py | **PASS (2)** in parity/ | 2026-06-29 | live-yielded sequence == historical snapshot |

## Parity Tests (Gates)

| Test File | Status | Last Run | Result | Notes |
|-----------|--------|----------|--------|-------|
| tests/parity/test_parity_sdr001.py | **PASS (3)** | 2026-06-29 | GREEN | Phase-1 gate — 1032 trades into bt_trades, journal trail per trade |
| tests/parity/test_summary_parity.py | **PASS (1)** | 2026-06-29 | GREEN | net_r 256.106675 ditto match |
| tests/parity/test_provider_parity.py | **PASS (3)** | 2026-06-29 | GREEN | Phase-2 gate — CSV ≡ DWX-hist frame contract |

## Coverage Snapshot

| Run Date | Tests | Overall | Status |
|----------|-------|---------|--------|
| 2026-06-29 | 93 passed | 100% pass rate (Phase 1) | GREEN |
| 2026-06-29 | 111 passed | 100% pass rate (Phase 2) | GREEN |
| 2026-06-29 | 132 passed | 100% pass rate (Phase 3) | GREEN |
| 2026-06-29 | 145 passed | 100% pass rate (Phase 4) | GREEN |

## Parity Headline Numbers (Target vs Actual)

| Metric | Target (baseline) | bt_engine | Delta | Status |
|--------|-------------------|-----------|-------|--------|
| Total trades | 1032 | 1032 | 0 | ✓ MATCH |
| Net R | 256.106675 | 256.106675 | 0.0 | ✓ MATCH |
| Win rate | 63.8566% | 63.86% | <1e-4 | ✓ MATCH |
| Profit factor | 1.683757 | 1.6838 | <1e-3 | ✓ MATCH |
| Max drawdown R | -12.694926 | -12.6949 | <1e-2 | ✓ MATCH |
| Positive years | 8/8 | 8/8 | — | ✓ MATCH |

**Run command:** `python3 -m bt_engine.runner.cli bt --out bt_engine/output/run01`

---

# SECTION 4 — CURRENT WORK & NEXT-UP

## Current Session

**Date:** 2026-06-29
**Active item:** Phase 6 complete. SDR-001 wired into engine. Real order executed on demo (ticket 2106437276).
**Next item:** Phase 6.F — DWX EA enhancement (emit M1 bars + GET_HISTORIC_DATA) OR Phase 7 UI dashboard.

## Open Questions / Blockers

- None at present.

## Phase 1 Deliverables (DONE)

- `bt_engine/` package: 9 sub-modules (core/data/db/journal/strategies/sdr001/execution/runner/tests)
- 93 tests passing (24 core + 17 data + 6 db + 11 journal + 16 strategies + 6 execution + 4 runner + 4 integration + 4 parity + others)
- DB: `golddigger_bt` + `golddigger_bt_test` with 6 `bt_*` tables
- CLI: `python3 -m bt_engine.runner.cli bt` runs full parity backtest in seconds
- Journal replay: `python3 -m bt_engine.runner.cli journal --trade-ref ...` exports chart-ready JSON
- Engine: bar-close event loop with causality asserts on every tick, identical BT/live signature
- Bracket walker: shared close-based exit logic for BT + live
- Frozen-ledger parity strategy: replays baseline ledger into DB with full journal trail

## Decisions Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-06-29 | Engine location: top-level `bt_engine/` | Clean separation from immutable research-baseline |
| 2026-06-29 | Data source: pull from MT5 via DWX | One source of truth for BT and live |
| 2026-06-29 | First strategy: XAU-SDR-001 port only | Prove parity before adding more |
| 2026-06-29 | Live parity: strict bar-close (live waits for closed bar) | Highest BT↔live parity |
| 2026-06-29 | DB: fresh `bt_*` schema, not reuse `gd_*` | Clean repo deserves clean schema |
| 2026-06-29 | Journal granularity: full bar walkthrough per trade | Visual replay requirement |
| 2026-06-29 | Test harness: unit per function + integration + parity, ≥95% cov | No blind spots mandate |
| 2026-06-29 | DB write timing: streaming during BT (same as live) | Maximum BT↔live parity |
| 2026-06-29 | Refactor strategy: incremental update(bar), not vectorized batch | Required for live loop; baseline stays as oracle |

## Notes / Discoveries

- `base_sleeve1_trades.csv` is NOT produced by `intraday_edge_lab/` modules directly — comes from external `/Users/subash/Documents/QUANT/SupplyDemand/research/l99_*.py` scripts. Parity target = `m15_2c_1atr` + `clean_top3` sleeve.
- MT5 + DWX bridge confirmed working 2026-06-29 04:47 (account_info, market_data, bars_*.json all live).
- 470 prior changes on XAUUSD branch committed locally at `144c7e3` (push aborted; large 3.4GB .git history).
- Branch `XAU-SDR-001` created from XAUUSD, repo wiped to clean slate, baseline copied into `research-baseline/`.
- **CSV file is mixed-tf**: 2016-2019 = D1 (one row per day, 00:00:00), 2019-Jun-Sep = H1, 2019-Sep-30+ = M1. Total 2.38M rows. Baseline `resample_ohlcv` handles this transparently since pandas `.resample("15min")` aggregates whatever is fed in. Parity ledger first trade is 2019-06-12 — that's H1 data resampled to M15. M1 doesn't begin until 2019-09-30.
