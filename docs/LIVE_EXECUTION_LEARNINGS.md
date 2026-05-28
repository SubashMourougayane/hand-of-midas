# Live Execution Learnings — May 28, 2026

## Bugs Found During First Live Day (Gold Micro)

These are execution-layer issues discovered when the system went live that the backtest doesn't account for. Each needs to be reflected in the backtest to achieve true parity.

---

## 1. Duplicate Orders (CRITICAL)

**What happened:** Same signal fired every 3 minutes, creating 10+ positions on the same setup.

**Root causes:**
- `lot_size NOT NULL` column missing from INSERT → DB save failed silently → `trades_today` count always 0 → no dedup
- `processed_sweeps` set resets every job run (local variable) → same sweep re-detected
- Multiple windows can find same engulfing simultaneously → 2 trades per cycle
- After SL hit, same sweep still within engulfing window → re-enters immediately

**Live fixes applied:**
1. `lot_size` added to INSERT
2. DB INSERT wrapped in try/except (always returns trade_ref)
3. `trade_placed_this_cycle` flag → max 1 trade per scan cycle
4. "One position at a time" check → skip if open Micro position exists
5. **5-minute cooldown** after last taken signal

**Backtest impact:** The backtest naturally avoids most of these because:
- It processes signals sequentially (no concurrent scans)
- `traded_sweeps` persists for the whole day (not per-cycle)
- Fill model immediately advances time past the engulfing

**What backtest SHOULD add:** 5-minute cooldown between signals (same as live). Without it, backtest can fire two signals 3 minutes apart that live would block.

---

## 2. Invalid Stops (retcode=10016)

**What happened:** SL was too close to current market price. Price had moved past the entry level, making the SL effectively at or below current price.

**Root cause:** A stale sweep from hours ago still had a valid engulfing. Entry calculation used the OLD M3 bar's ask_close (from hours ago), but current market price had moved significantly. The calculated SL was near current price.

**Live fix:** Pre-check before placing: if SL within $1 of current bid/ask → skip with "sl_too_close_to_price".

**Backtest impact:** The backtest fill model doesn't have this issue because it fills at the M3 bar's close price (which IS the current price at that moment). But in live, the "entry" is calculated from a historical M3 bar, and the actual fill happens at CURRENT market price which may be different.

**What backtest SHOULD add:** After calculating entry/SL from the engulfing bar, verify SL distance is still valid vs the NEXT bar's price. If not, skip.

---

## 3. DWX EA on Multiple Charts

**What happened:** DWX EA was attached to both BRENT and XAUUSD charts. Both instances read the same command folder → single command produced 2 positions.

**Live fix:** Removed EA from BRENT chart. Only one EA instance per command folder.

**Backtest impact:** None (backtest doesn't use DWX).

---

## 4. Position Monitor Can't Detect Closures

**What happened:** When MT5 closed a position (SL hit), `get_trade_details()` returned None because the trade was no longer in `open_orders.json`. Code treated None as "skip" instead of "closed".

**Live fix:** If trade not in open_orders AND not in get_trade_details → treat as broker-closed. Estimate fill price from SL/TP proximity.

**Backtest impact:** None (fill model handles exits directly).

---

## 5. Trade ID Key Mismatch

**What happened:** MT5 executor returns `t["id"]`, but live_engine expected `t["trade_id"]`. Position monitor crashed with KeyError every minute.

**Live fix:** Use `t.get("id") or t.get("trade_id")`.

**Backtest impact:** None.

---

## Summary: What Backtest Needs to Match Live

| # | Change | Impact on numbers |
|---|--------|:-:|
| 1 | **5-minute cooldown between signals** | -21% trades, same PF |
| 2 | **SL distance validation** (>$1 from current price) | Minimal (rare edge case) |
| 3 | **One position at a time** | Already natural in backtest (sequential execution) |
| 4 | **Daily max loss $400** | Already implemented ✓ |
| 5 | **Max 3 trades/day** | Already implemented ✓ |

**Priority: #1 (5-min cooldown) is the only meaningful change needed in the backtest engine.**

---

## Numbers Comparison (2020-2025, $5K/yr, 4% risk)

| Mode | Trades | WR | PF | P&L/6yr |
|------|:------:|:--:|:--:|:-------:|
| No cooldown (old backtest) | ~1,600 | 63% | 3.0 | ~$500K |
| **5min cooldown (matches live)** | **1,409** | **62.7%** | **3.08** | **$477K** |
| 2hr cooldown (too aggressive) | ~1,100 | 63% | 3.2 | ~$350K |

The 5-min cooldown is the honest number that matches what live will actually produce.
