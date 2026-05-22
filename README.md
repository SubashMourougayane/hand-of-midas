# ⛏️ GoldDigger + 🛢️ OilMiner

**Multi-asset algorithmic trading engine** — trades Gold (XAU/USD) and Brent Crude Oil (BCO/USD) using session sweep, mean-reversion, and inter-market consensus strategies.

Built from scratch after discovering the previous system had a critical backtest bug that inflated results by 89%. Every number in this system is honest, every fill is achievable in live.

---

## Performance (20 years, 2006-2026)

| | Gold | Oil | Combined |
|---|---|---|---|
| **Strategies** | Alpha-Sweep + Mean-Rev + Cross-Market | Alpha-Sweep | 4 strategies |
| **Trades** | 1,012 | 390 | 1,402 |
| **Win Rate** | 59.7% | 72.3% | — |
| **Profit Factor** | 3.40 | 8.31 | — |
| **Total P&L** | $177,235 | $314,803 | $492,038 |
| **Max Drawdown** | -19.0% | -14.9% | — |
| **Capital** | $5,000 fresh/year | $5,000 fresh/year | $10,000/year |
| **Losing Years** | 0 | 0 | 0 |

All results from real OANDA bid/ask data with realistic slippage, spread, and execution costs modeled.

---

## How It Works

### Alpha-Sweep (Gold + Oil)
London session sweeps Asia's high/low → 3-minute engulfing candle confirms reversal → enter with tight SL below the sweep wick. Holds ~4 hours max.

### Mean-Rev (Gold only)  
Detects gold dips using normalized MA conditions → buys the dip → exits when conditions reverse. Holds 1-5 days.

### Cross-Market (Gold only)
Reads 6 correlated markets (EUR, bonds, stocks, silver, oil) → when consensus says "gold up" → enters long. Holds up to 20 days.

### Drawdown Protection
- 3 consecutive losses → halve position size
- 5 consecutive losses → pause next 2 signals
- Equity below 20-trade average → halve again
- Gold below 50-day MA → skip Mean-Rev & Cross-Market longs

---

## Quick Start

```bash
# Prerequisites: PostgreSQL running, Python 3.12+, Node.js 18+

# Setup database
psql -U subash -f database/schema.sql

# Start everything
bash start.sh
```

Opens:
- **Gold Engine** → http://localhost:5053
- **Oil Engine** → http://localhost:5054  
- **Dashboard** → http://localhost:3001

---

## Dashboard

Dark retro terminal theme with real-time trading data.

| Page | What it shows |
|------|--------------|
| **Live** | Current price, account NAV (£/$/₹), open positions, DD state, signals |
| **Backtest** | Run historical tests, equity curve, P&L calendar, yearly breakdown |
| **Trades** | Full trade history with journey charts (entry → exit visualization) |
| **Journal** | Event log — every signal, entry, exit, skip, error |
| **Settings** | Strategy parameters, OANDA config, risk allocation |

Toggle between Gold and Oil via collapsible sidebar sections.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (3001)                    │
│  Next.js 16 + React 19 + Tailwind v4 + Recharts    │
│  Gold/Oil toggle • Backtest • Trades • Journal       │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
┌─────────▼─────────┐   ┌──────────▼──────────┐
│  Gold Backend      │   │  Oil Backend         │
│  FastAPI (5053)    │   │  FastAPI (5054)      │
│                    │   │                      │
│  • Alpha-Sweep     │   │  • Alpha-Sweep       │
│  • Mean-Rev        │   │                      │
│  • Cross-Market    │   │                      │
│  • Position Mon.   │   │  • Position Mon.     │
│  • Price Stream    │   │  • Price Stream      │
└────────┬───────────┘   └──────────┬───────────┘
         │                          │
         └──────────┬───────────────┘
                    │
         ┌──────────▼──────────┐
         │  OANDA v20 API      │
         │  Practice Account   │
         │  XAU_USD + BCO_USD  │
         └──────────┬──────────┘
                    │
         ┌──────────▼──────────┐
         │  PostgreSQL          │
         │  (golddigger DB)     │
         │  Trades • Signals    │
         │  Journal • DD State  │
         └─────────────────────┘
```

---

## Trading Schedule (UTC)

```
22:00       Cross-Market consensus + Mean-Rev dip check (Gold)
08:00-10:30 Alpha-Sweep: Asia sweep + M3 engulfing (Gold + Oil, every 3 min)
Every 1 min Position monitor: SL/TP detection + max hold enforcement
Real-time   Price stream: break-even detection tick-by-tick
```

---

## Safety Features

| Feature | What it prevents |
|---------|-----------------|
| Fixed SL/TP exits | Phantom fills (no trailing stops) |
| DB guards per strategy | Duplicate positions |
| Shared fill_model.py | Backtest ≠ live divergence |
| Max hold hard kill | Trades hanging open forever |
| GBP→USD conversion | Wrong position sizing |
| DD protection | Ruin from consecutive losses |
| Price stream (not polling) | Missed break-even triggers |
| 11-point audit | Every parity issue found and fixed |

---

## Development History

1. **VibeTrader** (May 2026) — RSI+EMA50 strategy, discovered phantom fill bug
2. **Strategy Tester** — 55 failed strategies tested, 3 winners found
3. **GoldDigger** — Clean-room rebuild with honest fills, 3 Gold strategies
4. **OilMiner** — Same Alpha-Sweep logic on Brent Crude, separate backend
5. **Audit** — 11 issues found between backtest and live, all fixed
6. **Live** — Running on OANDA demo, first signals May 22, 2026

---

## Files of Interest

| File | Why |
|------|-----|
| `backend/execution/fill_model.py` | The ONE critical module — all execution rules |
| `backend/scanner/scheduler.py` | Trading schedule orchestration |
| `backend/scanner/price_stream.py` | Real-time tick-by-tick OANDA stream |
| `backend/scanner/live_engine.py` | Signal → DD check → size → execute → persist |
| `AUDIT_REPORT.md` | Full backtest vs live parity audit |
| `GDHandOffProgress.md` | Complete build progress tracker |
| `OilMinerProgress.md` | Oil engine progress |

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12 + FastAPI + APScheduler |
| Frontend | Next.js 16 + React 19 + Tailwind v4 + Recharts |
| Database | PostgreSQL 17 |
| Broker | OANDA v20 REST + Streaming API |
| Data | 20 years bid/ask candles (M3, H1, Daily) |

---

## License

Private. Not for distribution.
