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
| Fill model (execution rules) | ✅ DONE | `backend/execution/fill_model.py` — SL-before-TP, TP-at-close, slippage, gap fills, break-even |

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
| Backtest produces ~$155k | ✅ DONE | $151,511 (-2.3% from target, within random slippage variance) |
| Trade count matches | ✅ DONE | 1,012 vs source 1,029 (-17, from random slippage edge cases) |
| Per-strategy WR matches | ✅ DONE | Alpha 73.2%, MeanRev 69.4%, Cross 49.1% (all within 0.5pp) |
| No phantom fills | ✅ DONE | SL fills only at bid_low (LONG) or ask_high (SHORT), gap fills at open |
| Max DD corrected | ✅ DONE | Source reported -13.5% (bug: last year only). Real: -24.0% (2018) |
| R:R computed | ✅ DONE | Overall 1:1.99, Alpha 1:2.32, MeanRev 1:1.40, Cross 1:1.81 |

---

## Phase 2: FastAPI Server + API Routes

### API Routes
| Item | Status | Notes |
|------|--------|-------|
| FastAPI app (`main.py`) | ⬜ TODO | Port 5053, CORS, startup events |
| POST `/api/gold/backtest` | ⬜ TODO | Accept {strategies, start, end, capital, risk_pct}, return results |
| GET `/api/gold/state` | ⬜ TODO | Live state snapshot |
| WebSocket `/ws/gold` | ⬜ TODO | Real-time updates |
| GET `/api/gold/trades` | ⬜ TODO | Trade history with filters |
| GET `/api/gold/journal/events` | ⬜ TODO | Event log |
| GET/PUT `/api/gold/settings` | ⬜ TODO | Strategy params |
| Auth routes | ⬜ TODO | Single-user session |

---

## Phase 3: Database (PostgreSQL)

| Item | Status | Notes |
|------|--------|-------|
| Schema design (`database/schema.sql`) | ⬜ TODO | gd_trades, gd_signals, gd_equity, gd_journal, gd_dd_state |
| DB connection module (`db.py`) | ⬜ TODO | asyncpg / SQLAlchemy |
| Trades table | ⬜ TODO | Every trade persisted with all fields |
| Signals table | ⬜ TODO | All generated signals (taken + skipped with reason) |
| Equity snapshots | ⬜ TODO | Post-trade equity for DD tracking |
| DD state persistence | ⬜ TODO | Survive restarts |

---

## Phase 4: Next.js Dashboard

| Item | Status | Notes |
|------|--------|-------|
| Project init (Next.js 16 + Tailwind v4) | ⬜ TODO | |
| Retro terminal theme (globals.css) | ⬜ TODO | Copy from VibeTrader |
| Sidebar navigation | ⬜ TODO | Live, Backtest, Trades, Journal, Settings |
| `/backtest` page | ⬜ TODO | Config form + equity curve + trade table + stats |
| `/trades` page | ⬜ TODO | Sortable/filterable trade history |
| `/live` page | ⬜ TODO | Positions, signals, gold price, DD state |
| `/journal` page | ⬜ TODO | Per-trade event narrative |
| `/settings` page | ⬜ TODO | Strategy params, execution mode |

---

## Phase 5: Live Engine

| Item | Status | Notes |
|------|--------|-------|
| OANDA executor | ⬜ TODO | Market orders with SL+TP |
| Scheduler (APScheduler) | ⬜ TODO | 22:00 UTC daily + 08:00-10:30 UTC London |
| Position monitoring (1 min poll) | ⬜ TODO | Check SL/TP hit, update equity |
| Cross-Market daily cron | ⬜ TODO | Fetch data → consensus → signal → order |
| Mean-Rev daily cron | ⬜ TODO | Check conditions → signal → order |
| Alpha-Sweep London monitor | ⬜ TODO | M3 poll → sweep detect → engulfing → order |
| DD state persistence across restarts | ⬜ TODO | |

---

## Phase 6: Verification & Hardening

| Item | Status | Notes |
|------|--------|-------|
| Paper trade 1 week | ⬜ TODO | Compare signals to backtest frequency |
| Backtest via API matches CLI | ⬜ TODO | Same engine, same results |
| Error handling + reconnection | ⬜ TODO | OANDA timeouts, DB failures |
| `start.sh` (launch both services) | ⬜ TODO | |
| CLAUDE.md for the repo | ⬜ TODO | |

---

## Discrepancies Found vs Source

| Item | Source Claim | Actual | Impact |
|------|-------------|--------|--------|
| Max DD | -13.5% | -24.0% (2018) | Source only computed DD on last year (bug in line 286) |
| Trade count | 1,029 | 1,012 | -17 from random slippage variance (acceptable) |
| Total P&L | $155,022 | $151,511 | -2.3% (within slippage variance) |

---

## What's Next

**→ Phase 2: FastAPI server with `/api/gold/backtest` route**
