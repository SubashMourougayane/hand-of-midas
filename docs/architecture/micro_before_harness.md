# Gold Micro — All Pending Bugs (Before Harness)

**Last updated:** 2026-05-29  
**Total bugs found across all sessions:** 30+  
**Fixed:** 22  
**Still open:** 12  

---

## LIVE-BREAKING (must fix before next trade)

| # | Bug | File | Impact | How it kills you |
|---|-----|------|--------|-----------------|
| **B1** | `_price_cache` undefined — position monitor crashes every 1 min | `backend-micro/scanner/live_engine.py:215,285` | No break-even, no exit detection, no price extremes tracking | Trade 2 today would have been a scratch (+$0.05) instead of full SL loss (-$562). Hotfix committed but NOT deployed on VPS. |

---

## EXECUTION GAPS (backtest works, live doesn't match)

| # | Bug | File | Impact | Scenario |
|---|-----|------|--------|----------|
| **B2** | Incomplete H1 bars pass sweep detection | `backend-micro/scanner/scheduler.py:157` | False sweep trigger | MT5 doesn't return `complete` field. At 14:35, the 14:00 bar is only 35 min old. Price spikes above range (temporary) → triggers sweep → entry → bar closes back inside range = bad signal. ~1 false trade per 2-3 weeks. |
| **B3** | Window 22-02 uses different data in backtest vs live | `backend/strategies/micro_alpha_sweep.py` vs live | 11% trades unvalidated | Backtest processes day-by-day, so window 22-02 only gets 2 bars (00,01) from current day. Live gets 4 bars (22,23,00,01) across midnight. Different range = different sweep levels. |
| **B4** | DWX `_wait_response` — no thread lock | `backend/execution/mt5_executor.py:64-81` | Phantom fills (trade_id=0) | scheduler writes command + position_monitor writes command within 100ms. Thread A reads Thread B's response. Records fake trade. ~33% overlap window per minute. |
| **B5** | Dedup key format mismatch | backtest vs live | Live takes fewer trades | Backtest keys on `(timestamp, window_start)` — same bar can fire for different windows. Live keys on `(timestamp, direction)` — blocks same bar across ALL windows. |
| **B6** | Daily bias could lag 1 day | `backend-micro/scanner/scheduler.py:158` | Wrong filter direction | If MT5/OANDA returns only completed daily candles (no in-progress), `daily_candles[-2]` is day-before-yesterday. Wrong bias → allows/blocks wrong signals. |
| **B7** | Same-bar TP+SL — backtest always awards TP | `backend/execution/fill_model.py:73-78` | Backtest WR slightly inflated | In M3 bars where both TP and SL are touched, backtest checks TP first (wins). Live broker fills whichever hit first chronologically. |
| **B8** | No orphan detection — MT5 positions without DB record | `backend-micro/scanner/live_engine.py` | Unmonitored positions | If entry succeeds on MT5 but DB INSERT fails, position exists with no tracking. No break-even, no max-hold, no exit detection. Runs until broker SL/TP. No alerting. |

---

## BACKTEST PARITY (numbers don't perfectly match live)

| # | Bug | File | Impact | Severity |
|---|-----|------|--------|----------|
| **B9** | BE distance differs: backtest entry+$0.04, live entry+$0.30 | `fill_model.py:86` vs `live_engine.py:382` | Live locks more profit after BE | LOW — favors live |
| **B10** | Max-hold: backtest counts M3 bars, live counts wall clock | `live_engine.py` | Live exits 1hr earlier on trades spanning market close (21-22 UTC) | LOW |
| **B11** | Equity MA formula differs | `dd_protection.py:65` vs `live_engine.py:83` | Different sizing decisions during drawdowns | LOW |
| **B12** | Random slippage in entry price calculation | `config.py:56` | `np.random.uniform(0, 0.02)` makes signal acceptance non-deterministic | LOW — $0.02 negligible |

---

## TOTAL BUG HISTORY (all sessions)

### Session May 28-29 (first live day): 14 bugs found+fixed
1. Duplicate positions (10 dupes on May 28) — FIXED
2. Trade ref collision — FIXED
3. DD state not isolated (id=3) — FIXED
4. Break-even checking wrong instrument — FIXED
5. Max-hold bar calculation off — FIXED
6. Sweep re-fire after SL (C5) — FIXED
7. Exit estimation lies about P&L (C4) — FIXED
8. Daily max loss was dead code (C1) — FIXED
9. MAX_HOLD close crashes on missing "time" field (C2) — FIXED
10. Orphan position on _log_signal failure (C3) — FIXED
11. Double-halving in backtest (H4) — FIXED
12. Startup cooldown for restart re-fire (C8) — FIXED
13. One-at-a-time in backtest (C9) — FIXED
14. Price extremes for exit estimation (C7) — FIXED

### Session May 29 (today): 1 new bug caused by fixes
15. `_price_cache` stale reference from C7 rename — committed, NOT deployed

### GOD MODE Audit #1 (May 28 PM): 10 bugs found
- C1, C2, C3 = FIXED immediately
- H4, H5, H6 = H4 FIXED, H5+H6 still open
- M7-M10 = documented, low priority

### GOD MODE Audit #2 (May 29 PM): 9 new bugs found
- C7, C8, C9 = FIXED
- H7-H11 = still open
- M11 = documented

---

## ROOT CAUSE ANALYSIS: Why bugs keep appearing

1. **5 async components vs 1 atomic function** — Backtest is one loop. Live is scheduler + position_monitor + break-even + price_stream + executor. Each can fail independently.

2. **No integration test** — Changes are verified with `ast.parse()` (syntax only). No test runs the live code path end-to-end with real-ish data.

3. **Variable renames without grep** — C7 crash was a rename that missed 2 references. A `grep` would catch this in 1 second.

4. **Config splits** — `backend/config.py` vs `backend-micro/config.py` vs `backend-oil/config.py`. Same key names, different values. Easy to change one and forget others.

5. **No regression test after fix** — Each fix is verified to solve the target bug but not tested against ALL scenarios (startup, restart, concurrent access, edge cases).

---

## WHAT THE HARNESS SHOULD DO

Before any deploy, run:

1. **Syntax + import test** — `python -c "import backend-micro.scanner.scheduler"` (catches undefined names at import time)
2. **Replay test** — Feed last 24hrs of M3+H1 data through the LIVE scheduler code path (not backtest). Verify: signals match, entries match, exits match, no crashes.
3. **Position monitor test** — Simulate: trade opens, price moves, trade disappears from MT5. Verify: exit detected, P&L correct, DD state updated.
4. **Break-even test** — Simulate: price reaches 50% to TP. Verify: SL moves to entry+$0.30.
5. **Restart test** — Kill scheduler, restart, verify: no re-fire of old sweeps, startup cooldown active.
6. **Thread safety test** — Two concurrent calls to `_wait_response`. Verify: no cross-contamination.

If ALL pass → deploy. If ANY fail → block deploy, fix first.

---

## PRIORITY ORDER FOR FIXES

1. **B1** — Deploy the hotfix (git pull + restart). 30 seconds.
2. **B4** — Threading lock on DWX. Prevents phantom fills. 20 min.
3. **B8** — Orphan detection (reverse reconciliation). Prevents silent money-at-risk. 30 min.
4. **B2** — Filter H1 bars by `bar_timestamp + 3600 <= now`. Prevents false sweeps. 10 min.
5. **B6** — Verify daily candle date before using bias. 10 min.
6. **B3** — Include previous day bars for overnight windows in backtest. 30 min.
7. **B5, B7, B9-B12** — Low priority parity issues. Won't cause money loss.

**After all fixes: build the harness. Then no deploy without passing.**
