# OilMiner — Progress Tracker

**Last updated:** 2026-05-22

---

## Phase 1: Core Engine (Backtest)

| Item | Status | Notes |
|------|--------|-------|
| Alpha-Sweep strategy (Oil thresholds) | ✅ DONE | `backend-oil/strategies/alpha_sweep.py` — ext=$0.20, min_sl=$0.10, max=5000 barrels |
| Fill model (shared) | ✅ DONE | Symlinked from `backend/execution/fill_model.py` |
| Backtest engine | ✅ DONE | `backend-oil/backtest/engine.py` — Alpha-Sweep only, BCO_USD data |
| Data linked | ✅ DONE | BCO_USD M3/H1/D symlinked from strategy-tester |
| Config module | ✅ DONE | `backend-oil/config.py` — all Oil-specific parameters |
| Backtest validated | ✅ DONE | 390 trades, 72.3% WR, PF 8.31, $315k, 0 phantom fills |
| Max hold enforcement (Gold+Oil) | ✅ DONE | Position monitor hard-kills Alpha-Sweep after 80 bars |

---

## Phase 2: FastAPI Server (port 5054)

| Item | Status | Notes |
|------|--------|-------|
| `main.py` (port 5054) | ⬜ TODO | FastAPI entry, CORS, lifespan |
| POST `/api/oil/backtest` | ⬜ TODO | Run Oil Alpha-Sweep backtest |
| GET `/api/oil/backtest/latest` | ⬜ TODO | Load from DB |
| GET `/api/oil/state` | ⬜ TODO | Live state (price, positions, DD) |
| GET `/api/oil/trades` | ⬜ TODO | Trade history |
| GET `/api/oil/trades/backtest` | ⬜ TODO | Backtest trades from DB |
| GET `/api/oil/journal/events` | ⬜ TODO | Event log |
| GET `/api/oil/journey` | ⬜ TODO | Trade journey chart data |

---

## Phase 3: Live Engine

| Item | Status | Notes |
|------|--------|-------|
| OANDA executor (BCO_USD) | ⬜ TODO | Same as Gold executor, different instrument param |
| Scanner/scheduler (London 08:00-10:30 only) | ⬜ TODO | No daily cron needed (no Mean-Rev/Cross-Market) |
| Price stream (BCO_USD) | ⬜ TODO | For break-even detection |
| Max hold enforcement | ✅ DONE | Shared position monitor handles all Alpha-Sweep trades |
| DD protection (shared) | ⬜ TODO | Same gd_dd_state table, counts across all instruments |

---

## Phase 4: Frontend (shared, add Oil nav)

| Item | Status | Notes |
|------|--------|-------|
| Instrument context/toggle (Gold \| Oil) | ⬜ TODO | Sidebar or top-level toggle |
| API_BASE switches between port 5053/5054 | ⬜ TODO | Based on active instrument |
| All pages work for Oil (backtest, trades, journal, live) | ⬜ TODO | Same components, different data source |

---

## Phase 5: Integration

| Item | Status | Notes |
|------|--------|-------|
| DB: instrument column in gd_trades/signals/journal | ⬜ TODO | Or separate via port-based routing |
| `start.sh` updated (3 services) | ⬜ TODO | Gold backend + Oil backend + frontend |
| Both fire independently during London | ⬜ TODO | Max 1 Gold + 1 Oil per day |
| DD counter shared across instruments | ⬜ TODO | Gold loss → Oil gets halved too |

---

## Validation

| Item | Status | Notes |
|------|--------|-------|
| Backtest ~390 trades, ~72% WR, PF ~8 | ✅ DONE | Verified, no phantom fills |
| Gold backtest unchanged after Oil addition | ⬜ TODO | Regression check |
| Paper trade 1 week (Oil) | ⬜ TODO | Observe alongside Gold |

---

## What's Next

**→ Phase 2: FastAPI server on port 5054 with backtest + state routes**
**→ Phase 4: Frontend instrument toggle**
**→ Phase 5: start.sh with both backends**
