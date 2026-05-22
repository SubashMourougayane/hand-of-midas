# GoldDigger — Critical Audit Report

**Date:** 2026-05-22
**Auditor:** Critics Engineer
**Verdict:** NOT READY FOR LIVE — 5 critical bugs, 6 high severity issues

---

## CRITICAL ISSUES (Must fix before going live)

### C1: Mean-Rev has NO condition-based exit in live
- **Backtest:** Exits when `c1 >= -0.4` OR `c2 >= -0.8` (conditions reverse), OR max 5 days, OR SL hit
- **Live:** Places order with SL only (tp=0). NO daily cron checks conditions. Trades exit ONLY via SL.
- **Impact:** Mean-Rev trades will hold losers indefinitely until SL hit. Backtest shows 69.9% WR from timely condition exits — live will be far worse.
- **Fix:** Add daily condition-exit check at 22:00 UTC for open Mean-Rev trades. Close via `close_trade()` when conditions reverse or after 5 days.
- **File:** `backend/scanner/scheduler.py` (missing), `backend/scanner/live_engine.py` (needs new function)
- **Status:** ✅ FIXED — `_check_mean_rev_exit()` added to daily_close_job

---

### C2: Cross-Market has NO 2-bar gap enforcement in live
- **Backtest:** `cross_market.py` line 53-56: `if bar - last_bar < min_bar_gap: continue`
- **Live:** `_run_cross_market()` fires every day if consensus >= 0.3. No check against last signal date.
- **Impact:** Overexposure — could fire daily during strong consensus periods instead of every 2+ days.
- **Fix:** Query DB for last Cross-Market signal date, skip if < 2 days ago.
- **File:** `backend/scanner/scheduler.py:_run_cross_market()`


---

### C3: Equity MA comparison is BROKEN
- **Backtest:** Compares current equity against mean of last 20 equity-after-trade values (e.g., $5200, $4800...)
- **Live:** Queries `SELECT pnl_usd FROM gd_trades` and compares equity ($5000+) against mean of individual PnLs ($50-200). Will NEVER trigger.
- **Impact:** DD protection "halve when equity < 20-trade MA" never activates in live.
- **Fix:** Query equity_after values from `gd_trades` or maintain equity snapshot, compare correctly.
- **File:** `backend/scanner/live_engine.py:_get_risk_multiplier()` lines 74-82


---

### C4: Alpha-Sweep uses bid prices in live, mid prices in backtest
- **Backtest:** `asia["mid_high"].max()`, `asia["mid_low"].min()`, sweep wick = `london["mid_high"]`
- **Live:** `max(c["bid_high"])`, `min(c["bid_low"])`, sweep wick = `bar["ask_high"]` or `bar["bid_low"]`
- **Impact:** Asia range, sweep detection thresholds, and TP calculations differ. Signals fire at different times.
- **Fix:** Compute mid prices in live: `(bid + ask) / 2` for all highs/lows/closes consistently.
- **File:** `backend/scanner/scheduler.py` lines 211-212, 232-242


---

### C5: No slippage on live entry price for SL/TP computation
- **Backtest:** `entry = ask_close + slippage(br)` → SL distance computed from slipped entry
- **Live:** `entry = c["ask_close"]` → SL distance computed from un-slipped price (slightly tighter SL → more units)
- **Impact:** Position size slightly larger than backtest intended. SL placed slightly closer to market.
- **Fix:** Add slippage to entry price before computing SL distance and units. (Note: actual OANDA fill is what it is — this only affects sizing and SL placement)
- **File:** `backend/scanner/scheduler.py` lines 304, 321


---

## HIGH SEVERITY ISSUES

### H1: Runtime crash — undefined `equity` variable
- **Line:** `live_engine.py:170` — `"equity": equity` but variable is named `equity_usd`
- **Impact:** Every successful trade fill crashes before persisting to DB. Trade placed on OANDA but invisible to the system.
- **Fix:** Change `equity` to `equity_usd`
- **File:** `backend/scanner/live_engine.py` line 170


---

### H2: SHORT break-even NEVER triggers
- **Line:** `live_engine.py:275` — `if tp <= 0 or sl >= entry: continue`
- **Problem:** For SHORT trades, initial SL is ABOVE entry (e.g., entry=4500, sl=4520). `sl >= entry` is always TRUE → always skips.
- **Impact:** Short Alpha-Sweep trades never get break-even protection in live.
- **Fix:** Use a DB flag `breakeven_applied` instead of comparing SL vs entry.
- **File:** `backend/scanner/live_engine.py` line 275


---

### H3: OANDA fills TP on wick touch, backtest requires close-through
- **Backtest:** Rule #3 — TP requires candle CLOSE through level
- **OANDA:** Server-side TP limit order fills on any price touch (intra-bar)
- **Impact:** Live exits earlier on TPs than backtest. Could be favorable (locks profit) or unfavorable (misses bigger move).
- **Fix:** Accept this as a known difference. OR: don't attach TP to order, monitor manually and only close when close-through occurs. Adds complexity.
- **File:** Structural OANDA behavior
 (decide: accept or manual TP monitoring)

---

### H4: Break-even detection polls every 60s, backtest checks bar high
- **Backtest:** Checks `bar_high >= 50% target` — guaranteed to see intra-bar spikes
- **Live:** Checks spot price every 60s — could miss a spike that briefly touches 50%
- **Impact:** Break-even triggers later in live or not at all if price only briefly spikes.
- **Fix:** Accept (conservative) or increase poll frequency to 10-15s during Alpha-Sweep holds.
- **File:** `backend/scanner/live_engine.py:check_alpha_sweep_breakeven()`
 (decide: accept or faster polling)

---

### H5: DD equity tracker mixes GBP P&L with USD starting equity
- **Line:** `live_engine.py:241` — `new_equity = dd_state["equity"] + realized_pl` (GBP value added to USD base)
- **Impact:** Internal equity counter becomes meaningless. Doesn't affect actual sizing (uses OANDA NAV).
- **Fix:** Store equity in GBP consistently, or convert realized_pl to USD before adding.
- **File:** `backend/scanner/live_engine.py` line 241


---

### H6: No max-hold enforcement for Cross-Market (20 days)
- **Backtest:** Expires trades after 20 bars (days) at close price
- **Live:** No mechanism to force-close after 20 days. OANDA doesn't have time-based trade expiry.
- **Impact:** Cross-Market trades could be held indefinitely if between SL and TP.
- **Fix:** Add daily check: if any Cross-Market trade is open > 20 days, close it.
- **File:** `backend/scanner/scheduler.py` (missing)


---

## MEDIUM SEVERITY ISSUES

### M1: Mixed bid/mid prices in Alpha-Sweep sweep detection
 (covered by C4 fix)

### M2: Cross-Market ATR uses bid prices (narrower), backtest uses mid
 (covered by consistency fix)

### M3: Daily bias uses bid_close vs mid_close
 (covered by C4 fix)

### M4: Inter-market returns use bid_close, backtest uses mid


### M5: Live uses OANDA NAV ($131k) for sizing, backtest uses $5k/year
- **Note:** This is BY DESIGN — live uses actual capital. Not a bug.
- **Status:** ✅ ACCEPTED

### M6: Undefined `acct` variable in `check_open_positions()` (dead code)
 (cleanup)

### M7: Alpha-Sweep M3 bar range calculated differently (ask_high - bid_low vs mid range)
 (minor)

---

## FIX PRIORITY ORDER

1. **H1** — `equity` → `equity_usd` (1 line, prevents runtime crash)
2. **H2** — SHORT break-even fix (logic bug, ~5 lines)
3. **C1** — Mean-Rev condition exit monitor (new function, ~30 lines)
4. **C2** — Cross-Market 2-bar gap (DB query + skip, ~5 lines)
5. **C3** — Equity MA fix (query change, ~5 lines)
6. **H6** — Cross-Market max hold 20 days (daily check, ~10 lines)
7. **C4** — Consistent mid prices in live (multiple line changes)
8. **C5** — Add slippage to live entry (2 lines)
9. **H5** — DD equity currency fix (small logic change)
10. **H3** — TP behavior decision (architectural — accept or build manual TP)
11. **H4** — Break-even poll frequency (config change)

---

## Verification After Fixes

- [ ] Start system, trigger a test signal manually, verify no crash
- [ ] Mean-Rev trade opens → verify daily condition check closes it
- [ ] Cross-Market signal → verify 2-bar gap prevents next-day repeat
- [ ] SHORT Alpha-Sweep → verify break-even triggers at 50% to TP
- [ ] Run for 24h in observation mode before trusting with real signals
