# JustMarkets MT5 Migration Plan

## Current State

| | OANDA (current) | JustMarkets MT5 (target) |
|---|---|---|
| **Connection** | REST API (HTTP) | DWX Connect (file-based EA) |
| **Server** | api-fxpractice.oanda.com | JustMarkets-Demo2 |
| **Login** | 101-004-39331014-001 | 11004471001 |
| **Symbols** | XAU_USD, BCO_USD | XAUUSD.ecn, BRENT.ecn |
| **Timeframes** | M3, H1, D (via API) | M3 native, all timeframes |
| **Reliability** | 522 errors ~40% off-hours | Stable (local terminal) |
| **Latency** | 200-500ms per call (+ retries) | 25-100ms (file I/O) |
| **Platform** | Linux EC2 (direct HTTP) | Mac local (Wine) or EC2 (Wine) |
| **Account** | UK demo (GBP) | Demo (USD) |

## Architecture

```
┌─────────────────────────────────────────────────┐
│  MT5 Terminal (Wine on Mac/EC2)                  │
│  ├── XAUUSD.ecn chart (M3)                      │
│  ├── BRENT.ecn chart (M3)                       │
│  └── DWX_Server.mq5 EA (attached to chart)      │
│       ├── Writes: market_data.json              │
│       ├── Writes: open_orders.json              │
│       ├── Writes: account_info.json             │
│       ├── Reads:  commands/*.txt (orders)       │
│       └── Timer: 25ms polling                   │
└─────────────────────────────────────────────────┘
            │ File I/O (MQL5/Files/DWX/)
            ▼
┌─────────────────────────────────────────────────┐
│  Python Backend (Hand of Midas)                  │
│  ├── mt5_executor.py (replaces oanda_executor)  │
│  │    ├── get_current_price() → reads JSON      │
│  │    ├── get_account_summary() → reads JSON    │
│  │    ├── get_candles() → reads from MT5 bars   │
│  │    ├── place_market_order() → writes cmd     │
│  │    ├── modify_stop_loss() → writes cmd       │
│  │    ├── close_trade() → writes cmd            │
│  │    └── get_open_trades() → reads JSON        │
│  ├── scanner/scheduler.py (UNCHANGED logic)     │
│  ├── scanner/live_engine.py (UNCHANGED logic)   │
│  ├── execution/fill_model.py (UNCHANGED)        │
│  └── strategies/ (UNCHANGED)                    │
└─────────────────────────────────────────────────┘
```

## Symbol Mapping

| OANDA | JustMarkets MT5 | Notes |
|---|---|---|
| XAU_USD | XAUUSD.ecn | Gold |
| BCO_USD | BRENT.ecn | Brent Crude Oil |
| XAG_USD | XAGUSD.ecn | Silver (Cross-Market) |
| EUR_USD | EURUSD.ecn | Cross-Market |
| SPX500_USD | US500.ecn | Cross-Market |
| USB10Y_USD | N/A | May not exist — need alternative |
| USB02Y_USD | N/A | May not exist — need alternative |

## What Changes

### Must Replace: `backend/execution/oanda_executor.py` → `backend/execution/mt5_executor.py`

Current OANDA functions to replace:

| Function | OANDA (current) | MT5/DWX (new) |
|---|---|---|
| `get_current_price(instrument)` | HTTP GET /pricing | Read `DWX/market_data.json` |
| `get_account_summary()` | HTTP GET /account | Read `DWX/account_info.json` |
| `get_candles(instrument, granularity, count)` | HTTP GET /candles | MT5 `CopyRates` via DWX or file export |
| `place_market_order(instrument, units, sl, tp)` | HTTP POST /orders | Write command to `DWX/commands/` |
| `modify_stop_loss(trade_id, new_sl)` | HTTP PUT /trades/{id} | Write modify command |
| `close_trade(trade_id)` | HTTP PUT /trades/{id}/close | Write close command |
| `get_open_trades(instrument)` | HTTP GET /openTrades | Read `DWX/open_orders.json` |
| `get_trade_details(trade_id)` | HTTP GET /trades/{id} | Read from DWX history |

### Must Update: Symbol Names

All references to `XAU_USD` → `XAUUSD.ecn`, `BCO_USD` → `BRENT.ecn` etc.
Use a mapping dict so the rest of the code doesn't change.

### Does NOT Change

- `backend/execution/fill_model.py` — backtest fill logic (uses CSV data)
- `backend/strategies/` — signal generation (uses preloaded DataFrames)
- `backend/backtest/engine.py` — backtest orchestration
- `backend/scanner/scheduler.py` — signal flow logic (calls executor interface)
- `backend/scanner/live_engine.py` — trade execution logic (calls executor interface)
- Frontend dashboard — API routes stay the same
- DD protection — unchanged
- Config thresholds — unchanged

## DWX Server EA Setup

### Files Needed in `MQL5/Experts/`
- `DWX_Server.mq5` — the main EA that bridges MT5 ↔ Python

### DWX Communication Protocol

**MT5 → Python (EA writes, Python reads):**
```
MQL5/Files/DWX/
├── market_data.json      # {"XAUUSD.ecn": {"bid": 4533.15, "ask": 4533.39, "time": "..."}}
├── open_orders.json      # {ticket: {symbol, type, lots, sl, tp, open_price, ...}}
├── account_info.json     # {balance, equity, margin, free_margin, ...}
├── bar_data.json         # Historical bars when requested
└── messages.json         # Status/error messages
```

**Python → MT5 (Python writes, EA reads):**
```
MQL5/Files/DWX/
├── commands/
│   ├── open_order_1716789000.txt    # "OPEN|XAUUSD.ecn|BUY|0.10|4530|4520|4560"
│   ├── modify_order_1716789001.txt  # "MODIFY|12345678|4525"
│   └── close_order_1716789002.txt   # "CLOSE|12345678"
└── subscriptions.txt                # Symbols to stream prices for
```

## M3 Timeframe

**Key question resolved:** JustMarkets MT5 DOES support M3 natively.
- Chart timeframes available: M1, M2, M3, M4, M5, M6, M10, M12, M15, M20, M30, H1, H2, H3, H4, H6, H8, H12, D1, W1, MN1
- Can request M3 bars via `CopyRates(symbol, PERIOD_M3, ...)`
- DWX can export M3 bars on request

This eliminates the PF degradation (1.59) from the previous MT5 EA attempt which used M5 approximation.

## Implementation Steps

### Phase 1: DWX Server EA (Day 1)
1. Write `DWX_Server.mq5` EA — handles:
   - Price streaming (writes market_data.json every 100ms)
   - Account info (writes every 1s)
   - Order execution (reads commands every 25ms)
   - Bar data export (M3, H1, D on request)
   - Open positions (writes every 500ms)
2. Compile and attach to XAUUSD.ecn M3 chart
3. Verify files appear in `MQL5/Files/DWX/`

### Phase 2: Python Executor (Day 1)
1. Write `backend/execution/mt5_executor.py` with same interface as `oanda_executor.py`
2. Symbol mapping: `INSTRUMENT_MAP = {"XAU_USD": "XAUUSD.ecn", "BCO_USD": "BRENT.ecn"}`
3. File watcher: reads DWX JSONs, writes command files
4. Test: price reads, order placement, SL modify, close

### Phase 3: Integration (Day 2)
1. Config switch: `EXECUTOR = "mt5"` vs `"oanda"` in config.py
2. Update scheduler imports to use mt5_executor
3. Update live_engine imports
4. Run on local Mac (where MT5 is running)
5. Verify: signal → order → SL modify → close cycle

### Phase 4: Candle Data (Day 2)
1. Export M3 + H1 + D history from MT5 for backtesting
2. Verify backtest numbers match (same strategy, same fill model, different broker data)
3. Cross-Market signals: check if USB10Y/USB02Y available on JustMarkets
   - If not: find alternative yield proxy or drop Cross-Market strategy

### Phase 5: EC2 Deployment (Day 3)
1. Install Wine + Xvfb on EC2
2. Install MT5 under Wine
3. Login to JustMarkets-Demo2
4. Attach DWX EA
5. Start Python backend with mt5_executor
6. Verify live trading works from EC2

## Risk Assessment

| Risk | Impact | Mitigation |
|---|---|---|
| MT5 crashes under Wine | Blind (no prices/orders) | Watchdog script restarts MT5 |
| DWX file latency (25-100ms) | Slight delay vs OANDA | Still faster than OANDA 522 retries |
| Wine instability on EC2 | Random crashes | Systemd auto-restart + Wine stable |
| Missing Cross-Market symbols | Lose 1 strategy ($40K/21yr) | Find alternatives or keep OANDA for data |
| JustMarkets demo → live | Different spreads/fills | Test demo first, switch later |
| Fill mode differences | Order rejection | Test FOK/IOC/RETURN per symbol |

## Fill Mode Research Needed

JustMarkets requires specific fill mode per symbol type:
- ECN accounts typically use `ORDER_FILLING_IOC` (Immediate or Cancel)
- Some symbols may require `ORDER_FILLING_FOK` (Fill or Kill)
- Must test with actual demo orders before going live

## Success Criteria

1. Dashboard loads in <100ms (no OANDA dependency for display)
2. Trade lifecycle works: signal → entry → BE modify → exit
3. M3 bars available in real-time (no M5 approximation)
4. Backtest numbers within 5% of OANDA backtest (different spreads)
5. No phantom fills (same fill_model.py used)
6. Stable for 24h without MT5 crash

## Timeline

- **Day 1:** DWX EA + Python executor + local test
- **Day 2:** Integration with scheduler + candle data export + backtest verification
- **Day 3:** EC2 deployment + stability test
- **Day 4:** 24h demo observation + comparison with OANDA signals

## Key Decisions

1. **Keep OANDA as fallback?** — Yes, for first week. Run both in parallel.
2. **Which account for live?** — JustMarkets demo first, then live after 50 trades validate.
3. **Cross-Market without bonds?** — May need to find yield curve proxy on MT5 or disable that strategy.
4. **Local vs EC2?** — Build locally first (MT5 already running), deploy to EC2 later.
