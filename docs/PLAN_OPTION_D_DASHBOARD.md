# Plan + Tracker: Option (d) — Bloomberg-grade Live Dashboard + Full Gate-Decision Instrumentation

**Status:** Phase 0 in progress  
**Created:** 2026-07-01  
**Branch:** `fib-v2-clean`  
**Approved plan:** `/Users/subash/.claude/plans/ok-now-that-we-piped-fog.md`

---

## Context

A+D intraday Fib V2 is **production-ready** on bt_engine (commits `6e674f584`, `1d278cc70`, `6e9890859`, `1a7d82814`, `1d55adff3` on `fib-v2-clean`). First paper-live attempt on JustMarkets-Demo2 ran cleanly but exposed one **blind spot**:

> "How will we even know if a trade was taken, or what every 15min scan is signaling?"

Today the only persistence is `[ENTRY_FILL]`, `[EXIT_*]`, and `[SIGNAL] type=ENTRY_SUBMIT`. Gate rejections (zone miss, regime fail, confirm-candle miss, dedup, min-risk) are **silently dropped**. There is no UI — the deleted frontend was last seen in commit `263632185`.

This plan builds:
1. **Full per-gate instrumentation** in the strategy + runner so every decision (pass/fail per gate per bar) lands in `bt_journal_events` and `bt_signals`.
2. **A Bloomberg-terminal-style live dashboard** — FastAPI + Vite/React SPA + WebSocket — that reads `bt_*` tables in real time so the operator can see what's happening as it happens AND replay closed trades bar-by-bar.

**Outcome:** paper-live resumes with full visibility. 24-48h watch yields a signed-off certification doc.

---

## Scope locked

| Question | Choice |
|---|---|
| Stack | FastAPI + Vite/React SPA |
| Real-time mech | WebSocket bidirectional |
| Scope | **Full** Bloomberg-style: live + journal + trades + signals (4 pages) |
| Push policy | Plan + tracker first, push all together when implementation starts |
| Bidirectional usage | Server pushes events; client buttons can later send kill-switch / pause commands (out of scope for v1; design leaves room) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  MT5 (DWX EA v2.16)                                                 │
│    └─ writes M1/M3/M15/H1/D1 JSON bars + tick → Common/Files/DWX/  │
└────────────────┬────────────────────────────────────────────────────┘
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  bt_engine/runner/live.py (run_live)                                │
│    ├─ Mt5LiveBarProvider — ingests bars                             │
│    ├─ FibV2IntradayA / FibV2IntradayD strategies                   │
│    │   └─ NEW: every gate emits StrategyEvent(type="GATE_*")        │
│    ├─ LiveSafetyBroker → JustMarkets-Demo2 via DWX                  │
│    └─ EquitySizer (Model B 1.5% asymmetric monthly)                 │
│            │                                                         │
│            ▼ (callbacks → repos)                                     │
└────────────┬────────────────────────────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PostgreSQL — golddigger_bt                                          │
│    bt_runs · bt_trades · bt_journal_events · bt_bar_walk             │
│    bt_signals · bt_account_snapshot                                  │
└────────────┬────────────────────────────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  NEW: dashboard_backend/  (FastAPI)                                  │
│    ├─ /api/runs                    — active + recent runs           │
│    ├─ /api/runs/{id}/trades        — trade list (paginated)         │
│    ├─ /api/trades/{id}/journal     — full event timeline            │
│    ├─ /api/trades/{id}/bar-walk    — bar-by-bar mfe/mae/distances   │
│    ├─ /api/signals/recent          — recent signals + gate rejects  │
│    ├─ /api/account/latest          — equity / balance / spread      │
│    ├─ /api/scan-status             — last bar processed per leg     │
│    └─ /ws/live                     — WebSocket push: journal +      │
│                                       trades + signals + account    │
│                                       (Postgres LISTEN/NOTIFY)      │
└────────────┬────────────────────────────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  NEW: dashboard/  (Vite + React + TS + Tailwind)                    │
│    Pages: /live · /journal · /trades · /signals                     │
│    Bloomberg-style: dark bg (#000/#0a0a0a), amber/green/red,        │
│      monospace tabular numerics, dense data-grid layouts.           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase tracker

### Phase 0 — Push current work + tracker doc

| ID | Task | Status | Notes |
|---|---|---|---|
| 0.1 | Write `docs/PLAN_OPTION_D_DASHBOARD.md` (this file) | ✅ DONE | |
| 0.2 | Commit tracker doc | ✅ DONE | `b6a875471` |
| 0.3 | Push `fib-v2-clean` to origin (incl. `1a7d82814`, `1d55adff3`, tracker doc) | ✅ DONE | pushed 2026-07-01 |

### Phase 1 — Backend instrumentation: full gate-decision events ✅ DONE

| ID | Task | Status | Notes |
|---|---|---|---|
| 1A | Add GATE_* event types to `JournalEvent` enum | ✅ DONE | 16 new types added |
| 1B | Emit gate events at every gate site (fib_v2 + intraday) | ✅ DONE | `_gate_buf` + `_emit_gate` helper; pure-write, no flow change |
| 1C | Wire engine + runner to persist gate events | ✅ DONE | live.py routes GATE_* to bt_signals w/ reason col |
| 1D | Postgres NOTIFY triggers | ✅ DONE | 5 triggers live, smoke-tested via psql + ws |
| 1E | Tests: unit + integration + parity re-run | ⏳ parity in progress | 17 gate-unit + 243 existing all green; parity 65min |

**Result:** All unit tests green (243 baseline + 17 new = 260 passing). `bt_signals` populates with `GATE_*` rows during runs. Parity re-run still running at 65min mark (expected window 25-90min for 21yr A+D). Commits: `6bca64008`.

### Phase 2 — Dashboard backend (FastAPI + WebSocket) ✅ DONE

| ID | Task | Status | Notes |
|---|---|---|---|
| 2A | Scaffold `dashboard_backend/` | ✅ DONE | pyproject + app/{main,deps,models}.py |
| 2B | REST endpoints: runs, trades, journal, signals, account, scan_status | ✅ DONE | 12 endpoints, smoke-tested against live DB |
| 2C | `/ws/live` WebSocket with asyncpg LISTEN | ✅ DONE | Broker fanout, run_id filter, 4 channels |
| 2D | Tests | ⏸ DEFERRED | smoke test passed end-to-end (NOTIFY→WS<3s); pytest suite to add |

**Result:** `curl localhost:8001/api/runs?limit=3` returns real paper-live runs from DB. `psql insert → asyncpg LISTEN → WebSocket push → client recv` confirmed end-to-end in <3s. Commits: `236a09062`.

### Phase 3 — Frontend Bloomberg-grade SPA ✅ DONE

| ID | Task | Status | Notes |
|---|---|---|---|
| 3A | Scaffold `dashboard/` (Vite+React+TS+Tailwind+recharts) | ✅ DONE | npm install + build green |
| 3B | Theme (black bg, amber/green/red, mono, tabular-nums) | ✅ DONE | tailwind theme.term.*, JetBrains Mono |
| 3C | Primitives: Pane, DataGrid, StatusBar, TopBar | ✅ DONE | |
| 3D | LivePage (4-pane grid) | ✅ DONE | open positions · signals · gate funnel · account |
| 3E | JournalPage (trade list + event timeline + bar-walk chart) | ✅ DONE | recharts with entry/SL/TP refs |
| 3F | TradesPage (sortable DataGrid) | ✅ DONE | sort by entry_ts, net_r, bars_held, risk |
| 3G | SignalsPage (gate-rejection funnel) | ✅ DONE | live + historical, filter by status prefix + leg |
| 3H | WebSocket hook (auto-reconnect, stale indicator) | ✅ DONE | 2s reconnect, >5s stale → amber dot |
| 3I | Build + mount in FastAPI StaticFiles | ✅ DONE | served at `localhost:8001/` |

**Result:** `npm run build` → `dist/index.html` + 174KB gzip JS. FastAPI serves SPA at root + REST/WS on same port. Curl `/` returns full HTML; `/assets/*.css` 200. Browser visual check pending Phase 4.

### Phase 4 — Wire to live + 24-48h watch

| ID | Task | Status | Notes |
|---|---|---|---|
| 4A | Wait for parity green | ⏳ in progress | 65+min in |
| 4B | `rm LIVE_DISABLED` | PENDING | |
| 4C | Relaunch A + D paper-live with dashboard up | PENDING | |
| 4D | First-trade DB sanity check | PENDING | |
| 4E | 24-48h soak | PENDING | |
| 4F | Write `docs/FIB_V2_INTRADAY_PAPER_LIVE_CERTIFICATION.md` | PENDING | |

**Acceptance:** 24h zero-error window; first trade journal has full GATE_PIVOT_DETECTED → ENTRY_FILL chain; certification doc committed.

---

## Bug-defense matrix (causality + look-ahead — 100th-time mandate)

| # | Risk | Mitigation |
|---|---|---|
| 1 | Gate event emit changes signal flow / shifts trade timing | Parity test (`test_parity_fib_v2_intraday_a.py`, `_d.py`) re-run after Phase 1B; drift must stay within current tolerance (A 0.16% net_R, D 0.25%) |
| 2 | Dashboard polling DB hammers Postgres | NOTIFY/LISTEN — zero-polling for changes; REST aggregates cache 1s |
| 3 | WebSocket payloads leak across runs | `?run_id=` server-side filter on LISTEN — server never pushes events outside subscribed run_id |
| 4 | Frontend shows stale account equity | StatusBar shows ws age in seconds; turns amber if >5s stale |
| 5 | NOTIFY payload size limit (8KB) | Trigger sends PK + ts + event_type only; client refetches detail via REST |
| 6 | Trigger overhead on every insert | Fires on INSERT only (~30-300/day live). Negligible. |
| 7 | Dashboard auth | v1 binds to localhost only. Real auth out of scope. |

---

## Endpoint shapes (locked, Phase 2)

| Path | Method | Returns |
|---|---|---|
| `/api/runs` | GET | `[{run_id, run_ref, mode, strategy_id, symbol, started_at, ended_at, status}]` (desc, limit 50) |
| `/api/runs/{run_id}` | GET | Run detail + summary stats from `bt_trades` agg |
| `/api/runs/{run_id}/trades?status=&page=&page_size=` | GET | Paginated trades |
| `/api/trades/{trade_id}` | GET | Trade row + live r-multiple if open |
| `/api/trades/{trade_id}/journal` | GET | `[{ts, event_type, detail}]` ASC |
| `/api/trades/{trade_id}/bar-walk` | GET | Bar-by-bar mfe_r/mae_r/unrealised_r/distance_to_{entry,stop,tp}_r |
| `/api/signals/recent?since=&leg=&run_id=&limit=200` | GET | Last N signals |
| `/api/signals/funnel?run_id=&since=` | GET | Counts per `status` |
| `/api/account/latest?run_id=` | GET | Latest snapshot |
| `/api/scan-status` | GET | `{last_bar_processed, bars_since_last_signal, runs_running: [...]}` |
| `/ws/live?run_id=` | WS | Server-pushed envelopes on NOTIFY |

WebSocket envelope:
```json
{
  "channel": "journal | signal | trade | account",
  "run_id": "uuid",
  "ts": "2026-07-01T12:34:56.000Z",
  "payload": { ... raw row ... }
}
```

---

## Visual spec (Bloomberg-grade)

- **Background:** `#000000`; pane borders `#FF9933` 1px
- **Color code:**
  - Green `#00CC00` — positive R, gate PASS, fill confirmed
  - Red `#FF3333` — negative R, gate FAIL, SL hit
  - Amber `#FF9933` — neutral / informational / borders / labels
  - Cyan `#00CCFF` — TP hit highlight
  - Muted gray `#666` — historical / inactive
- **Fonts:** `JetBrains Mono` / `IBM Plex Mono` / `Menlo` fallback; tabular-nums always on
- **No** rounded corners, shadows, card padding — borders + dense rows only
- **Density:** 11-12px font baseline, 4-6px row height
- **Time format:** `YYYY-MM-DD HH:MM:SS UTC` top-right
- **WS status dot:** top-right green/red/amber by latency

---

## Cut order if running out of time

1. Phase 1 instrumentation (the actual blind-spot fix — non-negotiable)
2. Phase 2 backend REST (enables future UI / external tools)
3. Phase 3 LivePage only (skip Journal/Trades/Signals)
4. Phase 4 watch
5. WebSocket → fall back to 1s poll if asyncpg LISTEN gets messy

---

## File inventory

### Modified
- `bt_engine/bt_engine/journal/events.py` (+30 LOC)
- `bt_engine/bt_engine/strategies/fib_v2/strategy.py` (+80 LOC)
- `bt_engine/bt_engine/strategies/fib_v2_intraday/strategy.py` (+30 LOC)
- `bt_engine/bt_engine/core/signal.py` (+5 LOC)
- `bt_engine/bt_engine/core/engine.py` (+3 LOC)
- `bt_engine/bt_engine/runner/live.py` (+20 LOC)
- `bt_engine/bt_engine/db/schema.sql` (+30 LOC)

### New
- `docs/PLAN_OPTION_D_DASHBOARD.md` (this file)
- `bt_engine/tests/unit/strategies/test_fib_v2_intraday_gate_events.py`
- `bt_engine/tests/integration/test_live_gate_events_persisted.py`
- `dashboard_backend/` (entire FastAPI app, ~600 LOC)
- `dashboard/` (entire Vite app, ~1500 LOC)
- `docs/FIB_V2_INTRADAY_PAPER_LIVE_CERTIFICATION.md` (Phase 4)

---

## Verification

```bash
# Phase 1 verification
cd /Users/subash/SUBASH/GoldDigger/bt_engine
python3 -m pytest tests/unit/ tests/parity/ -q
python3 -m pytest tests/unit/strategies/test_fib_v2_intraday_gate_events.py -v
python3 -m pytest tests/integration/test_live_gate_events_persisted.py -v

# Phase 2 verification
cd /Users/subash/SUBASH/GoldDigger/dashboard_backend
python3 -m pytest tests/ -v
uvicorn app.main:app --port 8001 &
curl http://localhost:8001/api/runs | jq
wscat -c "ws://localhost:8001/ws/live?run_id=<recent-run>"

# Phase 3 verification
cd /Users/subash/SUBASH/GoldDigger/dashboard
npm run build
# open http://localhost:8001/ — verify 4 pages, ws connected

# Phase 4 verification
rm LIVE_DISABLED
python3 -m bt_engine.runner.cli live --strategy fib_v2_intraday_a \
    --use-equity-sizer --start-balance 8985 --risk-pct 0.015 &
python3 -m bt_engine.runner.cli live --strategy fib_v2_intraday_d \
    --use-equity-sizer --start-balance 8985 --risk-pct 0.015 &
# Watch dashboard 24h
```

---

## Update log

- **2026-07-01** — Plan + tracker doc created. Phase 0 in progress.
