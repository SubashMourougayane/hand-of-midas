# Debug API

Read-only HTTP introspection for all 4 services. Built so Claude (and you) can debug without SSH'ing into the VPS.

**Base URLs:** `https://midas.subashtrades.in/api/{svc}/debug/*` where `svc` ∈ `gold | oil | micro | oil-micro`.

**Cross-service aggregates** (Gold port only): `https://midas.subashtrades.in/api/debug/all-*`.

**No auth. No scrubbing.** The endpoints expose secrets, file paths, full env, raw config dicts, full DB rows, full DWX file contents, and unredacted tracebacks. By design — same risk as SSH access. Don't make this public.

**Read-only by discipline.** No POST/PATCH/DELETE endpoints. Mutation cannot sneak in.

## Logs

```bash
# Tail last 500 lines of micro.log
curl -s 'https://midas.subashtrades.in/api/micro/debug/logs?lines=500'

# All errors in the last hour, across categories
curl -s 'https://midas.subashtrades.in/api/gold/debug/logs?level=ERROR&since=1h&lines=200'

# All gate rejections on Oil Micro since yesterday
curl -s 'https://midas.subashtrades.in/api/oil-micro/debug/logs?category=GATE&since=1d'

# Regex grep on signal events
curl -s 'https://midas.subashtrades.in/api/gold/debug/logs?grep=SIGNAL.*fired&lines=50'

# Plain text (no JSON envelope) — pipe to grep/awk
curl -s 'https://midas.subashtrades.in/api/gold/debug/logs/raw?lines=2000' | grep ERROR

# List rotated log files
curl -s 'https://midas.subashtrades.in/api/gold/debug/logs/files'

# Read a specific rotated file
curl -s 'https://midas.subashtrades.in/api/gold/debug/logs?filename=gold.20260612-1900.log&lines=1000'
```

## Journal & DB

```bash
# Recent journal events for this service (default-scoped to its strategies)
curl -s 'https://midas.subashtrades.in/api/gold/debug/journal?limit=200'

# Specific trade timeline
curl -s 'https://midas.subashtrades.in/api/gold/debug/journal?trade_ref=GD-AL-bb3f6047'

# All BE_ARMED events on this service
curl -s 'https://midas.subashtrades.in/api/oil/debug/journal?event_type=BE_ARMED'

# Single trade — full DB row + all journal events
curl -s 'https://midas.subashtrades.in/api/gold/debug/trade/GD-AL-6da58d64'

# Open trades on this service
curl -s 'https://midas.subashtrades.in/api/gold/debug/trades?status=open'

# Closed trades since 7 days ago
curl -s 'https://midas.subashtrades.in/api/oil/debug/trades?status=closed&since=7d&limit=200'

# Recent signals (taken=False shows what got filtered out)
curl -s 'https://midas.subashtrades.in/api/micro/debug/signals?taken=false&since=2d'

# Orphan check — broker/DB position mismatches
curl -s 'https://midas.subashtrades.in/api/gold/debug/orphans'

# Raw SQL — read-only by discipline (you can write a DELETE; the API won't stop you)
curl -s --get --data-urlencode "q=SELECT strategy, COUNT(*) FROM gd_trades GROUP BY strategy" \
  'https://midas.subashtrades.in/api/gold/debug/sql'
```

## Config & strategy state

```bash
# Full config module dump for this service
curl -s 'https://midas.subashtrades.in/api/gold/debug/config'

# Internal scheduler module state — _traded_sweeps, _seen_sweeps, etc.
# Plus introspected APScheduler jobs with next_run times.
curl -s 'https://midas.subashtrades.in/api/oil/debug/scanner-state'

# Today's asia/range computation if exposed by the scheduler
curl -s 'https://midas.subashtrades.in/api/gold/debug/asia'
```

## DWX / broker

```bash
# Dump every DWX bridge file with parsed JSON contents + staleness
curl -s 'https://midas.subashtrades.in/api/gold/debug/dwx'

# Live broker account snapshot
curl -s 'https://midas.subashtrades.in/api/gold/debug/account'

# Live price (broker side, not cached)
curl -s 'https://midas.subashtrades.in/api/oil/debug/price'

# Last N M3 bars the scanner is seeing
curl -s 'https://midas.subashtrades.in/api/micro/debug/bars?timeframe=M3&count=50'
```

## Health / system

```bash
# pid, uptime, memory, disk, scheduler status, scheduler jobs
curl -s 'https://midas.subashtrades.in/api/gold/debug/health'

# Last 20 captured exceptions (requires logger to call record_exception)
curl -s 'https://midas.subashtrades.in/api/gold/debug/exceptions?limit=20'

# Full os.environ — INCLUDES SECRETS by design
curl -s 'https://midas.subashtrades.in/api/gold/debug/env'

# Live thread list + per-thread stack traces (last 15 frames)
curl -s 'https://midas.subashtrades.in/api/gold/debug/threads'
```

## Code / repo

```bash
# Read any file under repo_root
curl -s --get --data-urlencode 'path=backend/scanner/scheduler.py' \
  'https://midas.subashtrades.in/api/gold/debug/code'

# Grep across .py/.ts/.tsx/.sql files
curl -s --get --data-urlencode 'pattern=daily_bias' \
  'https://midas.subashtrades.in/api/gold/debug/code/grep'

# Grep within a subdir
curl -s --get \
  --data-urlencode 'pattern=phantom_fill' \
  --data-urlencode 'path=backend/scanner' \
  'https://midas.subashtrades.in/api/gold/debug/code/grep'

# Git state
curl -s 'https://midas.subashtrades.in/api/gold/debug/git'
```

## Code execution

Run arbitrary Python in-process, run a script from the repo, or run a shell command. Same risk class as SSH access — there's no sandbox.

```bash
# Inline Python — assign to _result to return a value
curl -s -X POST 'https://midas.subashtrades.in/api/gold/debug/exec/python' \
  -H 'Content-Type: application/json' \
  -d '{"code":"from backend.execution.mt5_executor import get_candles\n_result = get_candles(\"XAU_USD\",\"M3\",10)"}'

# GET form for quick one-liners
curl -s --get \
  --data-urlencode 'code=import os; _result = os.listdir(".")' \
  'https://midas.subashtrades.in/api/gold/debug/exec/python'

# Run a script from the repo
curl -s --get \
  --data-urlencode 'path=scripts/print_today_h1_bars.py' \
  --data-urlencode 'timeout=30' \
  'https://midas.subashtrades.in/api/gold/debug/exec/script'

# Or POST with arguments
curl -s -X POST 'https://midas.subashtrades.in/api/gold/debug/exec/script' \
  -H 'Content-Type: application/json' \
  -d '{"path":"scripts/foo.py","args":["arg1","arg2"],"timeout":120}'

# Shell command (Windows on VPS)
curl -s --get --data-urlencode 'cmd=git pull' \
  'https://midas.subashtrades.in/api/gold/debug/exec/shell'
```

## Notify (Telegram)

```bash
# Recent Telegram-related journal events (sent / failed)
curl -s 'https://midas.subashtrades.in/api/gold/debug/notify/recent?limit=50'
```

## Cross-service (Gold port only)

```bash
# Health snapshot of all 4 services in one call
curl -s 'https://midas.subashtrades.in/api/debug/all-health'

# Orphan check across all services
curl -s 'https://midas.subashtrades.in/api/debug/all-orphans'

# Combined recent state (recent signals + trades + dd_state for all)
curl -s 'https://midas.subashtrades.in/api/debug/all-state'

# All exceptions captured across services
curl -s 'https://midas.subashtrades.in/api/debug/all-exceptions?limit=20'
```

## Filter syntax

`since=` accepts:
- Relative: `30m`, `2h`, `1d`, `45s`
- Absolute ISO-8601: `2026-06-12T08:00:00`

`level=` is one of: `DEBUG`, `INFO`, `WARN`, `ERROR`, `CRIT`.

`category=` is one of: `SCAN`, `SIGNAL`, `GATE`, `POSITION`, `EXIT`, `BROKER`, `DB`, `SYSTEM`.

`grep=` is a Python regex applied to the full line (timestamp + level + category + service + msg + fields).

## Architecture

- `backend_common/debug_router.py` — single shared module
- Each service's `main.py` builds a `DebugConfig` with its strategies, instrument, scheduler module, db helper, log filename, and DWX dir getter
- 24 endpoints per service, mounted under `/api/{svc}/debug/*`
- Cross-service aggregator mounted only on Gold @ 5053 under `/api/debug/*`

## Adding new endpoints

When you find a debugging gap, add the endpoint inside `build_debug_router()` in `backend_common/debug_router.py`. All 4 services pick it up automatically on next restart. No per-service duplication.
