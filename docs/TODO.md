# TODO — Hand Of Midas

## PENDING

### Engulfing Tolerance Relaxation ($0.10 buffer)

**Status:** PENDING — revisit after 30+ live trades  
**Date raised:** 2026-05-26  
**Priority:** Medium (potential +$3,600/yr, +33% PF improvement)

#### What happened today (May 26, 2026)

Gold bullish sweep triggered at ~12:45 UTC. Asia range $4,522-$4,560. Price dipped below $4,520 (sweep level) and H1 bar closed back above $4,522 — textbook sweep confirmed.

System searched for M3 bullish engulfing in the 2-hour window (12:45-14:45 UTC).

**Bar 7 (13:06 UTC) — missed by $0.01:**
```
Previous bar (RED):  O=4521.54  C=4520.47  → body bottom (pb) = 4520.47
Current bar (GREEN): O=4520.48  C=4524.01  → body bottom (cb) = 4520.48

Engulfing check: cb <= pb?
  4520.48 <= 4520.47? → NO (missed by $0.01)
```

If the trade had been taken:
- Entry: ~$4,524.06
- SL: $4,517.70
- TP: $4,601.50
- Result: Price rose to $4,532+ within 30 minutes. Would be +$8.47/oz (+1.33R).
- On 48 units: +$407 floating profit.

#### Research results (21-year simulation)

Tested relaxing the strict `cb <= pb` to `cb <= pb + tolerance`:

| Tolerance | Trades | WR | PF | Total $ | $/yr |
|---|---|---|---|---|---|
| $0.00 (current) | 1,203 | 62.7% | 3.15 | +$145,078 | +$6,908 |
| $0.05 | 1,352 | 66.1% | 4.03 | +$209,958 | +$9,998 |
| **$0.10** | **1,393** | **67.0%** | **4.18** | **+$220,730** | **+$10,511** |
| $0.20 | 1,411 | 68.4% | 4.35 | +$233,123 | +$11,101 |
| $0.50 | 1,431 | 68.8% | 4.44 | +$242,547 | +$11,550 |
| $1.00 | 1,446 | 69.2% | 4.55 | +$250,247 | +$11,917 |

Key findings:
- 2,261 near-miss patterns over 21 years (median miss: $0.045)
- +190 extra trades at $0.10 tolerance, ALL with higher WR and PF
- The risk/reward filters (SL distance, TP ratio, asia range cap) reject bad setups — engulfing strictness is redundant as primary gatekeeper

#### Why NOT implement now

1. We tested 6 values and picked the best — classic optimization bias
2. No out-of-sample validation (all 21 years used for both discovery and testing)
3. Improvement is suspiciously monotonic (every level better than previous)
4. One missed trade ($0.01 on one day) is an anecdote, not evidence

#### When to implement

- After 30+ live trades on current strict system
- If 3+ near-misses occur that would have been profitable → live evidence
- Implement as `cb <= pb + 0.10` in all 4 engulfing check locations:
  - `backend/strategies/alpha_sweep.py`
  - `backend-oil/strategies/alpha_sweep.py`
  - `backend/scanner/scheduler.py`
  - `backend-oil/scanner/scheduler.py`
- Re-run backtest to confirm numbers match simulation
- Add test case to `tests/test_variant_c_bias.py`

#### Risk if implemented

- Could be overfitting to 21-year historical patterns
- Adds ~9 trades/year — if those 9 are losers in live, PF drops
- Irreversible in perception (hard to tighten back after loosening)

---

### Oil Backtest Engine — Missing Pause Counter (DONE)

**Status:** COMPLETED (2026-05-26)  
**Fix:** Added `pause_counter` to `backend-oil/backtest/engine.py`  
**Result:** Oil backtest now matches live DD behavior (1326 trades, was 1350)

---

### JustMarkets MT5 Integration

**Status:** IN PROGRESS  
**Branch:** `feature/justmarkets-mt5`  
**What's done:**
- DWX_Server.mq5 compiled and running
- mt5_executor.py — full lifecycle tested (open/modify/close)
- Unified execution layer (EXECUTOR=mt5 switch)
- Full audit: 13/13 checks pass

**What's next:**
- Wire Oil backend-oil to use unified executor
- Run local for 2 days, compare signals with EC2/OANDA
- Deploy to EC2 with Wine if stable

---

### Cross-Market Strategy — Missing Bond Symbols

**Status:** PENDING  
**Issue:** JustMarkets MT5 doesn't have USB10Y_USD or USB02Y_USD  
**Impact:** Cross-Market strategy uses 6 instruments, 2 are missing  
**Options:**
1. Find yield curve proxy available on JustMarkets
2. Run Cross-Market with 4/6 instruments (reduced weight)
3. Keep OANDA for Cross-Market data feed only, execute on MT5

---

### Dashboard — Sweep Proximity for Oil

**Status:** COMPLETED (2026-05-26)  
**Fix:** Removed `if (instrument === "oil") return null` + fixed hardcoded "gold" prefix

---

### Dashboard — Sweep Status UX

**Status:** COMPLETED (2026-05-26)  
**Fix:** Added `sweep_status` field: WAITING → ACTIVE → EXPIRED → TRADED  
**Frontend:** Needs UI update to show EXPIRED state (currently still blinks)

---

### Dashboard — Page Load Stability

**Status:** COMPLETED (2026-05-26)  
**Fixes applied:**
- Background thread OANDA fetcher (never blocks API routes)
- force-dynamic on all pages (no static prerender)
- no-cache headers via nginx + next.config
- Handle scan-status error response gracefully
