# Week-Long Observability Logging — Implementation Plan

## Context

The user (Subash) is going dark for a week. On return, they want to fully reconstruct what each of the 4 services did — every scan tick, every gate rejection, every signal/trade event, every error with traceback, every position-monitor cycle — from log files alone. No system access for 7 days.

**Current state (verified by codebase exploration):**
- 4 Uvicorn services running on Contabo Windows VPS, scheduled via APScheduler
- All stdout redirected to `logs/<svc>.log` via `scripts/start-win.bat` (PYTHONUTF8=1 already set)
- Logging is ad-hoc `print()` calls only — no `logging` module anywhere
- Coverage gaps:
  - ✓ Scan entry, sweep detection, signal-fire are logged
  - ✗ Asia/range computation NOT logged
  - ✗ EVERY gate rejection silent (bias / risk-too-small / TP-feasibility / max_trades / one-at-a-time / cooldown)
  - ✗ Per-cycle position monitor count NOT logged
  - ✗ Errors logged as `print(f"err: {e}")` — NO tracebacks captured
  - ✓ DB journal (`gd_journal`) captures structured events, but is event-only, not heartbeat
- Log files at deploy snapshot (2026-06-12): gold.log=2KB, oil/micro/oil-micro/frontend = 0KB after 24h live

**User decisions (clarified):**
- Default log level: **DEBUG** (max observability; ~10-50MB/svc/week is acceptable)
- Restart-based rotation: **YES** — rename existing `<svc>.log` → `<svc>.<timestamp>.log` before each fresh run

**Constraint:** Strictly additive. NO changes to backtest, signal-gen logic, live execution path, or strategy decisions. Logging must NEVER crash the scheduler.

---

## Architecture

**Single-line text logger via thin `print()` wrapper**, NOT Python's `logging` module. Three reasons:
1. start-win.bat's existing stdout-redirect is the proven path. Bringing in `logging.handlers` clashes (the shell redirect AND a `FileHandler` would write to the same file → race conditions or one wins silently).
2. Wrapping `print()` is mechanical, fail-safe (try/except inside), zero dependencies.
3. User wants "variants" filterable via `findstr` — a structured single-line format does this without sub-loggers.

**Line format (single column-aligned line):**
```
2026-06-12T05:33:12.481Z | INFO  | SCAN     | gold-micro | tick | windows=3 price_bid=4178.22 price_ask=4178.32
2026-06-12T05:33:12.482Z | DEBUG | GATE     | gold-micro | bias_block | window=08-12 bias=bullish side=bearish
2026-06-12T05:33:12.485Z | DEBUG | SCAN     | gold-micro | complete | signals=0 reject_bias=2 reject_risk=1 reject_tp=0
2026-06-12T05:34:00.013Z | DEBUG | POSITION | gold-micro | tick | open=0
2026-06-12T05:34:01.022Z | ERROR | SYSTEM   | gold-micro | scan_failed | err=KeyError: 'bid_close' tb=Traceback...
```

**Levels:** `DEBUG, INFO, WARN, ERROR, CRIT`. Threshold gated by env var `HOM_LOG_LEVEL` (default `DEBUG`). Set lower threshold = more verbose.

**Categories:** `SCAN, SIGNAL, GATE, POSITION, EXIT, BROKER, DB, SYSTEM`. Tag in line, not separate sub-loggers.

**Timestamp:** UTC ISO-8601 with millisecond precision.

**Filtering examples (operator reference):**
- `findstr " GATE " logs\micro.log` → all gate decisions
- `findstr " ERROR " logs\*.log` → all errors across services
- `findstr "SIGNAL.*tick" logs\gold.log` → signal events on Gold Macro

**Migration approach: ADDITIVE ONLY.** Existing `print()` calls remain untouched (they continue to flow through stdout to the log file). New `log.xxx()` calls are inserted at the gaps (Asia/range, every gate, end-of-scan summary, monitor heartbeat, traceback capture). Single output stream because both write to stdout. **Why:** rewriting ~120 prints is high-risk for low gain.

---

## Logger Module (`scanner/_log.py`)

One file per system (4 copies, identical content). Drop next to each scheduler. Reasons for not centralizing: each backend dir has its own sys.path setup; each runs from a different working dir; copy-paste of 60 lines is simpler than fighting Python imports across 4 service trees.

**API:**
```python
SERVICE_NAME: str  # "gold-macro" | "oil-macro" | "gold-micro" | "oil-micro" — set per file

def debug(category: str, msg: str, **fields) -> None
def info(category: str, msg: str, **fields)
def warn(category: str, msg: str, **fields)
def error(category: str, msg: str, **fields)
def exception(category: str, msg: str, **fields)  # auto-captures traceback.format_exc()
```

**Implementation sketch (~60 lines):**
- Read `HOM_LOG_LEVEL` from env once at import; map to int threshold
- Each function wraps the call in `try/except Exception: pass` (silent on internal failure — never raises)
- Build line as f-string from timestamp + level + category + service + msg + space-joined `key=value` pairs from `**fields`
- Use `print(line, flush=True)` so log line hits the file immediately (start-win.bat redirect handles file write)
- For `exception()`: prepend `traceback.format_exc()` into a `tb=...` field (newlines escaped to `\n` so each error stays one line for grep)

**Per-system service-name binding:**
- `backend/scanner/_log.py` → `SERVICE_NAME = "gold-macro"`
- `backend-oil/scanner/_log.py` → `SERVICE_NAME = "oil-macro"`
- `backend-micro/scanner/_log.py` → `SERVICE_NAME = "gold-micro"`
- `backend-oil-micro/scanner/_log.py` → `SERVICE_NAME = "oil-micro"`

---

## Concrete Insertion Points

**Scheduler scan-tick entry** (e.g. `backend-micro/scanner/scheduler.py:_run_micro_sweep_core` line 100ish):
```python
log.info("SCAN", "tick", windows=len(active_windows), price_bid=h1_candles[-1]["bid_close"], price_ask=h1_candles[-1]["ask_close"])
```

**Asia/range computed** (after consolidation calc, line ~262):
```python
log.debug("SCAN", "consol_range", window=f"{cstart}-{cend}", high=range_high, low=range_low, range=consol_range, min_required=cfg["min_range"])
```

**Per-gate rejection** (NEW — at every existing `continue`, add a log call before continuing):
```python
# After bias filter (line ~240ish) — before `continue`:
log.debug("GATE", "bias_block", bias=bias, side=sweep_dir)
continue

# After risk check (line ~370):
log.debug("GATE", "risk_too_small", risk=risk, min=0.3)
continue

# After tp_feasibility (line ~374):
log.debug("GATE", "tp_too_close", tp=tp, entry=entry, risk=risk, ratio=(tp-entry)/risk)
continue

# After cooldown (line ~234):
log.debug("GATE", "cooldown_active", last_signal=last_signal_time.isoformat(), age_seconds=(now-last_signal_time).total_seconds())

# After max_trades (line ~243):
log.debug("GATE", "max_trades_reached", trades_today=trades_today, max=cfg["max_trades_per_day"])

# After one-at-a-time / open_micro:
log.debug("GATE", "open_position_exists", strategy=strategy)
```

**End-of-scan summary** (NEW — before each return path of `_run_micro_sweep_core`):
```python
log.info("SCAN", "complete", signals_fired=trades_today, sweeps_seen=N, rejects=reject_counts_dict)
```
(reject counts collected via a small Counter local to the function — minor refactor)

**Signal fired** (existing print at signal time, ADD log line):
```python
log.info("SIGNAL", "fired", direction=direction, entry=entry, sl=sl, tp=tp, risk=risk, units=units, sweep_wick=sweep_wick, bias=bias)
```

**Position monitor heartbeat** (in `check_open_positions`, top of function):
```python
log.debug("POSITION", "tick", open=len(open_db_trades))
```

**Per-position state** (in the loop, per open trade):
```python
log.debug("POSITION", "state", ref=trade["trade_ref"], entry=entry_price, sl=sl_price, tp=tp_price, current_price=mid, mae=extremes.get("low" if side=="LONG" else "high"), be_armed=…)
```

**SL/TP detection** (replace existing print):
```python
log.info("EXIT", "detected", ref=trade_ref, reason=exit_reason, fill=fill_price, pnl=realized_pl)
```

**EXIT_AMBIGUOUS** (currently DB-only, surface to log):
```python
log.warn("EXIT", "ambiguous", oanda_id=oanda_id, sl_reached=sl_reached, tp_reached=tp_reached, streak=streak)
```

**Top-level exception capture** (replace `except Exception as e: print(f"err: {e}")` with):
```python
except Exception as e:
    log.exception("SYSTEM", "scan_failed", job="micro_sweep_job", err=str(e))
    _log_journal_safe(...)  # keep existing DB write
```

**Order placement** (in `live_engine.execute_signal`, after `place_market_order`):
```python
log.info("BROKER", "order_placed", direction=direction, units=oanda_units, sl=sl_price, tp=tp_price, fill=result.get("fill_price"))
# OR on failure:
log.error("BROKER", "order_failed", err=result.get("error"), retcode=...)
```

---

## Files Modified

**NEW (4 files, ~60 lines each, identical except SERVICE_NAME):**
- `backend/scanner/_log.py`
- `backend-oil/scanner/_log.py`
- `backend-micro/scanner/_log.py`
- `backend-oil-micro/scanner/_log.py`

**MODIFIED (8 files, ~15-25 log calls added per file, NO existing prints removed except inside `except` blocks):**
- `backend/scanner/scheduler.py`
- `backend-oil/scanner/scheduler.py`
- `backend-micro/scanner/scheduler.py`
- `backend-oil-micro/scanner/scheduler.py`
- `backend/scanner/live_engine.py`
- `backend-oil/scanner/live_engine.py`
- `backend-micro/scanner/live_engine.py`
- `backend-oil-micro/scanner/live_engine.py`

**MODIFIED (1 file, ~5 lines for restart-based rotation):**
- `scripts/start-win.bat`

In start-win.bat, before the `start /B cmd /c "... > logs\<svc>.log 2>&1"` lines, add:
```bat
REM Rotate prior logs (restart-based; preserves week-long history across restarts)
set TS=%date:~-4%%date:~3,2%%date:~0,2%-%time:~0,2%%time:~3,2%
if exist logs\gold.log ren logs\gold.log gold.%TS%.log
if exist logs\oil.log ren logs\oil.log oil.%TS%.log
if exist logs\micro.log ren logs\micro.log micro.%TS%.log
if exist logs\oil-micro.log ren logs\oil-micro.log oil-micro.%TS%.log
if exist logs\frontend.log ren logs\frontend.log frontend.%TS%.log
```

**NOT touched:**
- All `strategies/` files (signal-gen logic — strict no-touch)
- All `backtest/` engines
- `db.py`, `execution/`, MQL5 EA, frontend, parity harness inputs
- Existing `_log_journal` / `_log_signal` (DB writes — kept as-is, complementary)

---

## Verification

1. **Import test (per backend dir):**
   ```bash
   cd backend && python -c "from scanner._log import info; info('SCAN','test',k=1)"
   cd backend-oil && python -c "from scanner._log import info; info('SCAN','test',k=1)"
   cd backend-micro && python -c "from scanner._log import info; info('SCAN','test',k=1)"
   cd backend-oil-micro && python -c "from scanner._log import info; info('SCAN','test',k=1)"
   ```
   Each should print one well-formed line to stdout.

2. **Tests still green:**
   ```bash
   pytest tests/harness/ -x
   ```
   All 22 parity-harness tests + 42 oil-macro tests must pass. Logging is additive, no behavior change.

3. **Parity harness still bit-identical:**
   ```bash
   PARITY_DAYS=7 pytest tests/harness/test_22_parity.py::test_parity -v
   ```
   Numbers must match the v1.2 baseline (gold_micro 80.0%, oil_micro 86.1%, gold_macro 80.0%, oil_macro 75.0%) byte-identically. Anything else means the logging touched signal-gen by accident.

4. **Local smoke test on the VPS BEFORE leaving:**
   - Run start-win.bat fresh
   - Wait 5 min
   - `findstr " ERROR " logs\*.log` → empty
   - `findstr " GATE " logs\micro.log | head` → at least one rejection per scan cycle visible
   - `findstr " tick " logs\micro.log | wc -l` → ~5 entries (one per scan, every 3 min)
   - `findstr " complete " logs\micro.log | head` → end-of-scan summary lines
   - `type logs\gold.log` doesn't show encoding errors

5. **Force exception (in a sandbox copy):** temporarily add `raise ValueError("test")` inside one scheduler's main loop. Verify the resulting log line contains `tb=Traceback...` with the full stacktrace, all on one line (newlines escaped).

6. **Disk usage check:** after 4 hours of live operation, `dir logs\*.log` should show files in the 1-10MB range (extrapolating to 5-50MB/week per service — within the budget).

---

## Risk & Rollback

**Logging-induced crash protection:** Every public function in `_log.py` is wrapped in a top-level `try: ... except Exception: pass`. If a `**fields` value is unprintable, the call silently fails — strategy code continues uninterrupted.

**Rollback (single commit):** All changes land in one commit on a feature branch. To revert:
```bash
git revert <sha>
```
Removes 4 new files + ~150 modified lines across 9 files. Zero deletions of existing code (existing `print()` calls were preserved). System reverts to current logging behavior.

**Hot-flip log level without redeploy:** Set `HOM_LOG_LEVEL=INFO` in the start-win.bat env block to silence DEBUG noise without changing code.

**Worst case:** comment out the 8 `from scanner._log import ...` lines (one per scheduler/live_engine) and the schedulers run as before.

---

## What this DOES NOT do

- Does not centralize log files (each service still has its own log file — no merged stream)
- Does not add real-time alerting (no Telegram/email — user is consciously going dark)
- Does not rotate by date (rotation is restart-based — fine because services rarely restart)
- Does not parse logs into structured queries (operator uses `findstr`/`grep`)
- Does not refactor existing prints (they remain alongside new structured logs — both go to same file)
- Does not change DB journaling (existing `_log_journal` writes to `gd_journal` table continue unchanged)

---

## Branch & Workflow

**Implementation branch:** `feature/observability-logging` (off `midas-deploy`).

**Workflow:**
1. Branch off midas-deploy
2. Implement: 4 `_log.py` files + 8 file modifications + start-win.bat rotation
3. Verify locally (parity harness must stay bit-identical)
4. Push branch
5. User pulls branch on VPS, runs `start-win.bat`, observes logs for 5-30min
6. If healthy → merge to `midas-deploy`, user goes dark for a week
7. If broken → discard branch, no impact on midas-deploy
