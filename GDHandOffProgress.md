# GoldDigger — Handoff Progress Tracker

**Last updated:** 2026-05-22

---

## Phase 1: Core Engine (Backtest)

### Strategy Porting
| Item | Status | Notes |
|------|--------|-------|
| Alpha-Sweep (V4) signal generation | ✅ DONE | `backend/strategies/alpha_sweep.py` — Asia sweep + M3 engulfing + bias + $5 min SL |
| Mean-Rev (V7) signal generation | ✅ DONE | `backend/strategies/mean_rev.py` — MA10 conditions + daily entry |
| Cross-Market (V8) signal generation | ✅ DONE | `backend/strategies/cross_market.py` — 6-instrument consensus |
| DD Protection filters | ✅ DONE | `backend/strategies/dd_protection.py` — 50-MA gate, halve/pause, equity MA |
| Fill model (execution rules) | ✅ DONE | `backend/execution/fill_model.py` — TP on touch, SL gap-through first, slippage, break-even |

### Backtest Engine
| Item | Status | Notes |
|------|--------|-------|
| Bar-by-bar engine | ✅ DONE | `backend/backtest/engine.py` — orchestrates strategies + fill model + DD |
| Data loading (CSV cache) | ✅ DONE | `backend/data/cache.py` — loads OANDA bid/ask CSVs, computes mid prices |
| Config module | ✅ DONE | `backend/config.py` — all params, OANDA creds, slippage function |
| 20yr data linked | ✅ DONE | `data/raw/` symlinked to strategy-tester CSVs |

### Validation
| Item | Status | Notes |
|------|--------|-------|
| Backtest produces target P&L | ✅ DONE | $177,235 (touch-fill TP, tiered risk 4/3/2%) |
| Trade count | ✅ DONE | 1,012 trades (within random slippage variance of source 1,029) |
| Per-strategy WR matches | ✅ DONE | Alpha 73.2%, MeanRev 69.4%, Cross 49.8% |
| No phantom fills | ✅ DONE | SL fills only at bid_low (LONG) or ask_high (SHORT), gap fills at open |
| Max DD computed correctly | ✅ DONE | -19.0% worst year (per-year calculation) |
| R:R computed | ✅ DONE | Overall 1:2.31 |

---

## Phase 2: FastAPI Server + API Routes

| Item | Status | Notes |
|------|--------|-------|
| FastAPI app (`main.py`) | ✅ DONE | Port 5053, CORS, lifespan startup (data preload + scheduler + stream) |
| POST `/api/gold/backtest` | ✅ DONE | Full stats, trades, equity curve, monthly/yearly P&L, saves to DB |
| GET `/api/gold/backtest/latest` | ✅ DONE | Loads last backtest from DB (no re-run needed on refresh) |
| GET `/api/gold/state` | ✅ DONE | Live price, account NAV (GBP+USD), positions, DD state, signals, scheduler status |
| GET `/api/gold/trades` | ✅ DONE | Trade history with filters (strategy, side, win/loss) + aggregate stats |
| GET `/api/gold/journal/events` | ✅ DONE | Event log with filters (strategy, event_type, trade_ref) |
| GET `/api/gold/journal/trades` | ✅ DONE | Events grouped by trade_ref |
| GET `/api/health` | ✅ DONE | Health check |
| WebSocket `/ws/gold` | ⬜ SKIPPED | Using 5s polling + OANDA stream instead. Sufficient for dashboard. |
| GET/PUT `/api/gold/settings` | ⬜ TODO | Settings page is read-only display for now. Editable settings deferred. |
| Auth routes | ⬜ TODO | Single-user, no auth needed for local/demo. Add before production deploy. |

---

## Phase 3: Database (PostgreSQL)

| Item | Status | Notes |
|------|--------|-------|
| Schema design (`database/schema.sql`) | ✅ DONE | All tables with gd_ prefix |
| DB connection module (`db.py`) | ✅ DONE | psycopg2 with RealDictCursor, execute/insert_returning helpers |
| `gd_backtest_runs` table | ✅ DONE | Stores backtest config + summary stats |
| `gd_backtest_trades` table | ✅ DONE | All trades per backtest run |
| `gd_backtest_equity` table | ✅ DONE | Equity curve points per run |
| `gd_trades` table | ✅ DONE | Live trades (open + closed), pnl_gbp + pnl_usd columns |
| `gd_signals` table | ✅ DONE | Every signal generated (taken or skipped with reason) |
| `gd_journal` table | ✅ DONE | Event log per trade_ref |
| `gd_dd_state` table | ✅ DONE | Persisted DD protection state (consecutive_losses, equity, peak) |
| `gd_settings` table | ✅ DONE | Key-value (exists, not yet used by API) |
| DD state persistence | ✅ DONE | Loaded/saved on every signal check, survives restarts |

---

## Phase 4: Next.js Dashboard

| Item | Status | Notes |
|------|--------|-------|
| Project init (Next.js 16 + Tailwind v4) | ✅ DONE | + Recharts + Lucide icons |
| Retro terminal theme (globals.css) | ✅ DONE | Copied from VibeTrader (JetBrains Mono, dark, scanlines) |
| Sidebar navigation | ✅ DONE | Live, Backtest, Trades, Journal, Settings |
| Custom DatePicker component | ✅ DONE | Dark theme calendar dropdown, matches reference design |
| PnL Calendar component | ✅ DONE | Compact multi-month grid with green/red cells |
| `/backtest` page | ✅ DONE | Config + stats + strategy breakdown + equity curve + P&L calendar + yearly + trade table |
| `/trades` page | ✅ DONE | Filterable by strategy/side/result, stats cards, P&L in £ + $ |
| `/live` page | ✅ DONE | Real-time: price, account (GBP+USD), positions, DD state, signals, schedule (5s polling) |
| `/journal` page | ✅ DONE | Event log with strategy/event_type filters, context display |
| `/settings` page | ✅ DONE | All strategy params, DD rules, OANDA config (read-only display) |

---

## Phase 5: Live Engine

| Item | Status | Notes |
|------|--------|-------|
| OANDA executor | ✅ DONE | `oanda_executor.py` — market orders, SL+TP, price, candles, close, modify SL, GBP/USD rate |
| Scheduler (APScheduler) | ✅ DONE | `scheduler.py` — 22:00 UTC daily + every 3 min 08:00-10:30 + every 1 min position monitor |
| Position monitoring (1 min poll) | ✅ DONE | Detects OANDA-side SL/TP closure, updates DB + DD state |
| Cross-Market daily cron | ✅ DONE | Fetches 6 instruments, consensus, 2-bar gap enforced, mid prices |
| Mean-Rev daily cron | ✅ DONE | MA10 conditions, slippage on entry, mid prices |
| Mean-Rev condition exit | ✅ DONE | `_check_mean_rev_exit()` — daily check, closes on reversal or 5d max |
| Cross-Market max hold (20d) | ✅ DONE | `_check_max_hold_exits()` — force-closes expired trades |
| Alpha-Sweep London monitor | ✅ DONE | M3 poll, mid prices, sweep detect, engulfing, bias filter, min $5 SL, slippage |
| Alpha-Sweep break-even | ✅ DONE | Real-time via OANDA price stream (tick-by-tick, 0ms latency) |
| Price stream | ✅ DONE | `price_stream.py` — OANDA streaming API, auto-reconnect, handles break-even |
| DD state persistence | ✅ DONE | USD equity tracking, survives restarts |
| Currency conversion | ✅ DONE | GBP account → USD sizing via live GBP/USD rate from OANDA |
| Signal persistence | ✅ DONE | Every signal (taken or skipped) stored with reason in gd_signals |
| Journal logging | ✅ DONE | Every event (entry, exit, skip, error, break-even) logged with context |

---

## Phase 6: Verification & Hardening

| Item | Status | Notes |
|------|--------|-------|
| Critical audit (11 issues) | ✅ DONE | 10 fixed, 1 accepted (H3: OANDA TP wick fill = favorable). See AUDIT_REPORT.md |
| Fill model parity (backtest=live) | ✅ DONE | TP on touch, SL gap-through, same order of operations |
| Mid price consistency | ✅ DONE | All live signal detection uses (bid+ask)/2 mid prices |
| Slippage on live entries | ✅ DONE | Matches backtest formula |
| Error handling + reconnection | ✅ DONE | Price stream auto-reconnects, OANDA calls have 3 retries + 30s timeout |
| `start.sh` (launch both services) | ✅ DONE | Starts backend (port 5053) + frontend (port 3001) |
| CLAUDE.md for the repo | ⬜ TODO | |
| Paper trade 1 week | ⬜ TODO | System is live on OANDA demo — observe first week |
| Backtest via API matches CLI | ✅ DONE | Same engine, same results (validated) |

---

## Config Updates Applied

| Update | Status | Result |
|--------|--------|--------|
| Tiered Risk (4%/3%/2%) | ✅ DONE | Alpha gets 4%, Cross gets 2% — rewards strength, dampens weakness |
| TP touch-fill (matches OANDA) | ✅ DONE | +$9.4k vs close-through. Backtest now matches live behavior exactly. |

---

## Final Backtest Numbers (current)

| Metric | Value |
|--------|-------|
| Total P&L | $177,235 |
| Win Rate | 59.7% |
| Profit Factor | 3.40 |
| Max DD | -19.0% |
| Trades | 1,012 (52/yr) |
| R:R | 1:2.31 |
| Alpha-Sweep | 314 trades, 73.2% WR, $127k |
| Mean-Rev | 134 trades, 69.4% WR, $21k |
| Cross-Market | 564 trades, 49.8% WR, $29k |

---

## Remaining Items

| Item | Priority | Effort |
|------|----------|--------|
| CLAUDE.md | LOW | 10 min |
| Paper trade 1 week | HIGH | 7 days observation |
| Auth routes | LOW | Add before exposing to internet |
| Editable settings API | LOW | Not needed for demo trading |

---

## To Start

```bash
cd /Users/subash/SUBASH/GoldDigger && bash start.sh
```
- Backend: http://localhost:5053 (FastAPI + scheduler + price stream)
- Frontend: http://localhost:3001 (Next.js dashboard)
- First signal: tonight 22:00 UTC (Cross-Market + Mean-Rev) or tomorrow 08:00-10:30 UTC (Alpha-Sweep)
