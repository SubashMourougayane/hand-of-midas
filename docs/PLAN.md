# GoldDigger — Implementation Plan

## Context

Previous RSI+EMA50 strategy had phantom fill bug (89% of P&L was fake). New system uses 3 strategies with FIXED exits — impossible to phantom-fill. Backtested 20 years on real OANDA bid/ask data. $155k total profit on $5k fresh/year (148% avg annual return, PF 2.85, 59.6% WR, -13.5% max DD).

**Source of truth:** `/Users/subash/SUBASH/strategy-tester/scripts/generate_portfolio_dashboard.py`
**Handoff doc:** `/Users/subash/SUBASH/strategy-tester/GoldDiggerHandoff.md`

---

## Architecture

```
GoldDigger/
├── backend/
│   ├── main.py                       # FastAPI entry (port 5053)
│   ├── config.py                     # OANDA creds, DB URL, strategy params
│   ├── db.py                         # Database connection
│   ├── data/
│   │   ├── oanda_feed.py             # Fetch M3/H1/D candles (bid+ask)
│   │   ├── inter_market.py           # Fetch 6 correlated instruments daily
│   │   └── cache.py                  # CSV read/write for backtest
│   ├── strategies/
│   │   ├── base.py                   # Signal dataclass + interface
│   │   ├── alpha_sweep.py            # Asia sweep + M3 engulfing
│   │   ├── mean_rev.py               # Daily dip-buy
│   │   ├── cross_market.py           # Inter-market consensus
│   │   └── dd_protection.py          # Drawdown protection filters
│   ├── execution/
│   │   ├── fill_model.py             # CRITICAL: shared by backtest + live
│   │   ├── oanda_executor.py         # OANDA v20 order placement
│   │   ├── position_manager.py       # Track open positions via DB
│   │   └── risk_sizer.py             # Position sizing
│   ├── backtest/
│   │   ├── engine.py                 # Bar-by-bar processor
│   │   └── simulator.py              # Orchestrate + compute stats
│   ├── scanner/
│   │   ├── scheduler.py              # Cron: 22:00 UTC daily, 08:00-10:30 UTC
│   │   └── live_engine.py            # Signal → execute → persist
│   ├── journal/
│   │   └── logger.py                 # Event log per trade_ref
│   └── routes/
│       ├── auth.py
│       ├── state.py                  # /api/gold/state + WebSocket
│       ├── backtest.py
│       ├── trades.py
│       ├── journal.py
│       └── settings.py
├── database/schema.sql
├── data/raw/                         # Symlink to strategy-tester/data/raw/
├── scripts/
├── tests/
├── frontend/                         # Next.js 16 + Tailwind v4
│   ├── app/ (live, backtest, trades, journal, settings)
│   ├── components/
│   └── lib/
├── requirements.txt
├── start.sh
└── CLAUDE.md
```

---

## Build Order

### Phase 1: Core Engine + Backtest
1. Project scaffolding
2. `config.py`, `db.py`
3. `data/cache.py` — load CSVs from strategy-tester
4. `execution/fill_model.py` + tests (TDD — port from execute_on_tf)
5. `strategies/` — all 3 + DD protection + tests
6. `backtest/engine.py` + `simulator.py`
7. `main.py` + `routes/backtest.py`
8. Validate: backtest ≈ $155k

### Phase 2: Frontend
1. Next.js init + retro theme
2. Sidebar, StatCard, EquityChart, TradeTable
3. /backtest, /trades pages

### Phase 3: Live Engine
1. `oanda_executor.py`
2. `scanner/scheduler.py` + `live_engine.py`
3. WebSocket + /live page
4. Journal, settings

---

## Critical: fill_model.py Rules

1. Longs fill at ASK + slippage, Shorts at BID - slippage
2. SL checked BEFORE TP each bar
3. TP requires candle CLOSE through level (not wick)
4. Slippage: $0.03 + 0.3% × bar_range + random(0, 0.02)
5. Gap fills at gap price (worse than SL)
6. Break-even (Alpha-Sweep only): move SL to entry at 50% to TP
7. Min $5 SL on Alpha-Sweep trades
8. Skip first M3 bar after sweep

---

## Verification

- Backtest ≈ $155k (±1%)
- No phantom fills (SL never fills above bar high for LONG)
- Alpha-Sweep all have >= $5 SL
- Cross-Market skips when gold < 50-MA
- Paper trade 1 week matches expected frequency
