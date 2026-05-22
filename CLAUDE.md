# Hand Of Midas — CLAUDE.md

Multi-asset algorithmic trading platform. Trades Gold (XAU/USD) and Brent Crude Oil (BCO/USD) on OANDA demo account using session sweep, mean-reversion, and inter-market consensus strategies. Repo folder: `GoldDigger/`.

---

## Architecture

```
GoldDigger/
├── backend/              # Gold engine (port 5053) — 3 strategies
├── backend-oil/          # Oil engine (port 5054) — Alpha-Sweep only
├── frontend/             # Next.js dashboard (port 3001) — shared
├── database/schema.sql   # PostgreSQL schema (gd_ prefix)
├── data/raw/             # Symlinked CSV data (20yr, bid+ask)
├── logs/                 # Service logs (gold.log, oil.log, frontend.log)
├── scripts/              # Validation scripts
└── start.sh              # Launches all 3 services
```

---

## Strategies

### Alpha-Sweep (Gold + Oil) — Intraday, ~4hr hold
- Asia session high/low from H1 (00:00-08:00 UTC)
- London sweeps Asia H/L → M3 engulfing confirms → entry
- Daily bias filter, skip first bar after sweep, min $5 SL (Gold) / $0.10 (Oil)
- TP: 2× Asia range | Break-even at 50% to TP | Max hold: 80 bars

### Mean-Rev (Gold only) — 1-5 day hold
- Dual MA10 condition check on daily data
- Entry at next day open | SL: 1× avg 10-day range
- Exit: conditions reverse OR max 5 days

### Cross-Market (Gold only) — Up to 20 day hold
- 6 correlated markets: EUR/USD, US10Y, SPX500, Silver, Oil, US2Y
- Weighted consensus score ≥ 0.3 → LONG
- SL: 2× ATR(14) | TP: 4× ATR(14) | Max hold: 20 days

---

## Trading Schedule (UTC)

| Time | What | Instrument |
|------|------|-----------|
| 22:00 daily | Cross-Market + Mean-Rev | Gold |
| 08:00-10:30 (every 3 min) | Alpha-Sweep | Gold + Oil |
| Every 1 min | Position monitor (SL/TP/MaxHold) | Both |
| Real-time stream | Break-even detection | Both |

---

## Key Parameters

| Param | Gold | Oil |
|-------|------|-----|
| Risk % (Alpha-Sweep) | 4% | 4% |
| Risk % (Mean-Rev) | 3% | — |
| Risk % (Cross-Market) | 2% | — |
| Max position | 100 oz | 5,000 barrels |
| Yearly capital (backtest) | $5,000 fresh | $5,000 fresh |
| Live sizing | OANDA NAV (USD-converted) | OANDA NAV (USD-converted) |

---

## Critical Rules (NON-NEGOTIABLE)

1. **No trailing stops** — all exits are fixed SL/TP/time/condition
2. **TP fills on touch** (bar high/low) — matches OANDA instant fill
3. **SL gap-through first** — if open past SL, fills at open price
4. **Shared fill_model.py** — backtest and live use identical logic
5. **Max 1 position per strategy per instrument** — DB guards prevent duplicates
6. **DD protection shared across instruments** — 3 losses → halve, 5 → pause
7. **Max hold enforcement** — position monitor hard-kills Alpha-Sweep at 80 bars
8. **GBP→USD conversion** — account is GBP, sizing uses USD-equivalent via live rate

---

## Database (PostgreSQL: golddigger)

| Table | Purpose |
|-------|---------|
| gd_backtest_runs | Backtest configs + summary stats |
| gd_backtest_trades | All trades per backtest run (full ISO timestamps) |
| gd_backtest_equity | Equity curve points |
| gd_trades | Live trades (open + closed) |
| gd_signals | Every signal (taken + skipped with reason) |
| gd_journal | Event log per trade_ref |
| gd_dd_state | Persisted DD protection state |
| gd_settings | Key-value config |

---

## Running

```bash
bash start.sh
```

Starts Gold (5053) + Oil (5054) + Frontend (3001). Logs in `logs/`.

```bash
tail -f logs/gold.log  # Watch Gold activity
tail -f logs/oil.log   # Watch Oil activity
```

---

## OANDA

- Account: 101-004-39331014-001 (UK demo, GBP)
- API: https://api-fxpractice.oanda.com/v3
- Stream: https://stream-fxpractice.oanda.com/v3
- Token: in config.py (hardcoded)

---

## What NOT To Do

- **Don't use trailing stops** — the previous system had a phantom fill bug that inflated results by 89% from trailing SL fills at impossible prices
- **Don't store just DATE for trade timestamps** — use full ISO timestamp (journey chart needs exact bar time)
- **Don't run backtest with different capital and compare returns** — results scale linearly with capital
- **Don't hardcode API_BASE in frontend** — use useInstrument() context for correct port routing
- **Don't mark ALL backtest runs as not-latest** — filter by strategy to keep Gold and Oil independent
- **Don't check `sl >= entry` for SHORT break-even** — SHORT SL starts above entry by definition
- **Don't mix GBP P&L with USD equity** — always convert via live GBP/USD rate

---

## Backtest Results (current)

| Instrument | Trades | WR | PF | P&L (20yr, $5k/yr) |
|-----------|--------|-----|-----|-----|
| Gold (3 strategies) | 1,012 | 59.7% | 3.40 | $177,235 |
| Oil (Alpha-Sweep) | 390 | 72.3% | 8.31 | $314,803 |

---

## Source of Truth

- Strategy logic: `/Users/subash/SUBASH/strategy-tester/scripts/generate_portfolio_dashboard.py`
- Handoff: `/Users/subash/SUBASH/strategy-tester/GoldDiggerHandoff.md`
- Oil handoff: `/Users/subash/SUBASH/strategy-tester/OilMinerHandoff.md`
- Audit: `AUDIT_REPORT.md` (11 issues found, 10 fixed, 1 accepted)
- Failures learned from: `/Users/subash/SUBASH/VibeTrader/eval/FAILURES.md` (55 items)
