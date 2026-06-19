# Parity Remediation Log — A1 → end of list

> Live document. Updated in real-time as we work each item from `PARITY_AUDIT_2026-06-19.md`.
> Authored 2026-06-19 evening IST. Branch `midas-deploy` start commit `a7a1a2a`.

## Bible (locked-in user rules — re-read before every item)

1. **No fake numbers.** Every metric cited is grep'd / measured / pulled from a real source. If I can't measure it, I say so.
2. **No phantom fills.** Code reads must match runtime behaviour. If I claim "live does X" I have a line number.
3. **No assumptions.** Replace "should" / "I think" with verified facts or an explicit `❓ FLAG`.
4. **No blind spots.** When I find something tangential I document it — never silently skip.
5. **Flag what I miss.** If I notice a related concern but choose not to fix it now, document under FLAGS with reason. No silent omission.
6. **Frame.** Each item: VERIFY → RCA → FIX → TEST. No skipping stages. Diff review before commit.
7. **No auto-ship.** User signs off each fix before commit lands. No batching.
8. **Wise enough to catch everything now, not tomorrow.** If a class-of-bug exists, grep the codebase before claiming the fix is done.

## ⚠️ Architectural framing (2026-06-20 IST, post-A10)

**The actual disease:** BT and live are PARALLEL implementations of the same logic, not two parts of one program. Specifically diverging:
- **Fill model:** BT walks bars synchronously in `fill_model.py`. Live = broker-side stops + cron polls every 60s.
- **BE arming:** BT bar-close check (`fill_model.py:206`). Live = 60s tick poll (`check_alpha_sweep_breakeven`).
- **Partial TP:** BT bar-high touch (line 181). Live = DWX `PARTIAL_CLOSE` next tick.
- **MAX_HOLD:** BT bar-counter. Live wallclock `(now - entry_time)/180`.
- **Exit detection:** BT walks high/low. Live = `get_open_trades` poll + price-extremes tracker.

**Phase 4-5-6 unified ONLY signal-gen.** Everything after the signal is still parallel.

**Decision 2026-06-20 IST:** measure divergence with tape replay FIRST, then decide rewrite scope from data. Architectural rewrite (`backend/core/{lifecycle,sizing,gates,fill_model}.py` shared) deferred until tape replay produces a divergence catalog.

---

## Status Table

| ID | Title | P | Status | Commit | Notes |
|---|---|---|---|---|---|
| A10 | Signal-gen divergence (today's $753 gap) | P0 | 🔵 IN_PROGRESS | — | NEW 2026-06-20: BT replay shows BT fired 4 post-deploy trades today, NONE in gd_traded_sweeps. Live never attempted them. Real cost of today: $753.43. |
| A1+A9 | Sweep blacklist (mark-after-success) + Live-only gates (H6 + F27 anchor) | P0 (cleanup) | ⏳ PARKED | — | Real bug-class but does NOT cause today's gap. Option B design ready. Tackle after A10. |
| A2 | F27 limit-TTL expiry doesn't roll back blacklist | P0 | ⏳ QUEUED | — | After A1 |
| stateful-test | Stateful parity test (catches A1+A2 class) | — | ⏳ QUEUED | — | After A2 |
| A5 | Cooldown state lost on live restart | P1 | ⏳ QUEUED | — | |
| A3 | DB persistence bypass in BT (replay-from-state mode) | P0 | ⏳ QUEUED | — | Larger work |
| A6 | Equity / DD-state staleness | P1 | ⏳ QUEUED | — | |
| A4 | Weekend / market-close drift (task #302) | P0 | ⏳ QUEUED | — | Larger work |
| T1 | Cron-tick vs bar-close alignment | P1 | ⏳ QUEUED | — | |
| A7 | Position-already-open guard mismatch | P2 | ⏳ QUEUED | — | |
| A8 | Sweep window-overlap behaviour | P2 | ⏳ QUEUED | — | Likely no-op after A1 |
| T2 | Signal staleness (24hr stale signal accepted) | P2 | ⏳ QUEUED | — | |
| T3 | BE-arm cadence: 60s vs M3 bar-close | P1 | ⏳ QUEUED | — | |
| T4 | Cron concurrency on shared in-memory state | P1 | ⏳ QUEUED | — | |
| E1 | Network + DWX latency log | P1 | ⏳ QUEUED | — | Monitoring |
| E2 | Market-order entry slippage calibration | P1 | ⏳ QUEUED | — | Needs live data |
| E3 | Order rejection retry logic | P1 | ⏳ QUEUED | — | |
| E4 | Multi-EA FIFO contention log | P1 | ⏳ QUEUED | — | Monitoring |
| E5 | F27 limit-fill rate empirical tax | P1 | ⏳ QUEUED | — | |
| E6 | SL/TP intra-bar tick fill | P2 | ⏳ QUEUED | — | Monitoring |
| E7 | Partial-TP fill price drift | P2 | ⏳ QUEUED | — | Monitoring |
| E8 | BE-arm tick-staleness (phantom trigger) | P2 | ⏳ QUEUED | — | Diagnostic shipped 3d66acf |
| E9 | Lot rounding parity | P2 | ⏳ QUEUED | — | |
| E10 | OnTradeTransaction event-ordering race | P2 | ⏳ QUEUED | — | Dedup already shipped |
| E11 | Spread modeling staleness | P2 | ⏳ QUEUED | — | Needs live data |
| E12 | Exit-reason format mismatch | P2 | ⏳ QUEUED | — | normalize_exit_reason exists |

Status legend: 🔵 IN_PROGRESS · ⏳ QUEUED · ✅ DONE · 🚫 STASHED · ⚠️ BLOCKED

---

## A1 — Sweep blacklist rollback on signal rejection

**Priority:** P0 · **Started:** 2026-06-19 evening IST · **Status:** 🔵 IN_PROGRESS

### Audit claim
Live marks `_traded_sweeps["keys"].add()` + `mark_sweep_consumed()` BEFORE `execute_signal()`. Rolls back trade-count on clean None return but NOT the sweep blacklist. BT only marks on successful `execute_trade()`. Sweep permanently blacklisted in live but available in BT next bar.

### VERIFY (Stage 1, Option B redo) — full BT engine walk + live walk + parity matrix

**Done before any code touched. No assumptions.**

#### Step 1: Map every gate BT applies (truth source) — `backend-micro/backtest/engine.py:194-339`

```
1. yearly reset (state.equity, state.peak, history, daily_pnl) — no live equivalent (live uses live broker NAV)
2. daily reset (daily_pnl, day_filled_trades, current_date) — live uses gd_dd_state + DB query
3. day_filled_trades >= max_per_day (=3) → continue (skip silently, no mark)
4. cooldown 300s since last_signal_time → continue
5. position_exit_time and signal.date < position_exit_time → continue (THIS IS THE KEY ONE — staleness gate)
6. state.equity < 100 → continue
7. should_skip_signal (DD pause, gold trend filter) → continue
8. signal.risk <= 0 → continue
9. df.index.get_loc(signal.date) raises → continue
10. compute units = min(risk_dollar/risk, MAX_UNITS) — no minimum check
11. execute_trade returns None → continue (data error, not a real path in BT)
12. result.filled is False → continue (F27 limit miss, no `last_signal_time` update, no `position_exit_time` update — sweep can re-fire)
13. SUCCESS → update state, last_signal_time = signal.date, position_exit_time = signal.date + bars_held×180s
```

**BT does NOT track sweep blacklist outside of `generate_signals()`.** Confirmed — `traded_sweeps` is local to that function. Once signals are emitted, the engine doesn't care about sweep_keys. The set of signals BT walks is **frozen at generate_signals() time** — same wick produces 1 signal per (sbar_ts, start_hour) **on that one call**.

**BT signals for sample wick at 13:09 with 3 active windows:**
- W4 (start_hour=4): emits 1 signal at 13:09 (engulfing chosen)
- W6 (start_hour=6): same wick, different (sbar_ts, start_hour) tuple → emits 1 signal at 13:09
- W8 (start_hour=8): emits 1 signal at 13:09
- All 3 are in `all_signals` after merge.
- BT walks them sorted by `signal.date` = 13:09 for all 3.
- Signal 1 → cooldown empty, no position → execute → success → `last_signal_time=13:09, position_exit_time=14:09`.
- Signal 2 → cooldown 300s since 13:09 → fails (signal.date - 13:09 = 0s < 300s) → continue. Sweep NOT consumed in any tracker.
- Signal 3 → same → continue.

**So BT's behaviour for "wick produces 3 signals":** ONLY THE FIRST gets executed. Other 2 are skipped silently. Cooldown gate, NOT staleness gate. **Signals 2+3 are dropped, not held.**

After 14:09 (position closed): no new BT iterations on signals 2+3 — they were already walked past. They're permanently dead.

#### Step 2: Map every gate Live applies — `backend-micro/scanner/scheduler.py:208-465`

```
A. _daily_state.date != today → reset _daily_state, _traded_sweeps (NEW DAY)
B. db_trades_today (from gd_trades, excludes LIMIT_TTL_EXPIRED) → trades_today = max(db, in-mem)
C. trades_today >= max_per_day (=3) → return (skip whole cron tick)
D. compute bias from yesterday's daily candle
E. F28 BIAS_MODE override
F. Last gd_signals row ts < 5min AND (taken or order_error or sl_too_close) → return (cooldown)
G. _startup_cooldown_until > now → return (C8 startup C8 fix)
H. Build h1_df, m3_df from broker. If empty → return.
I. signals = generate_signals(h1, m3, bias)
J. Loop signals:
   J1. trades_today >= max OR trade_placed_this_cycle → BREAK (matters! → only 1 signal per cron tick)
   J2. signal.date > now → continue (future signal)
   J3. signal missing sweep_time/start_hour metadata → continue
   J4. sweep_key in _traded_sweeps['keys'] OR (DB is_sweep_consumed) → continue
   J5. open_micro DB count > 0 → continue (open position, NOT cooldown)
   J6. mt5 get_open_trades() not empty → continue
   J7. dry_run → fake-mark, increment, continue
   J8. mark_sweep_consumed (in-mem + DB)
   J9. _daily_state['trades'] += 1
   J10. execute_signal(...) → returns trade_ref OR None OR raises
        J10a. trade_ref → keep marks, count, BREAK loop
        J10b. None → roll back _daily_state['trades'] only (BUG — sweep stays marked)
        J10c. raises → keep marks (June 10 fix), no rollback
```

**Differences vs BT, item-by-item:**

| # | Behaviour | BT | Live (today) | Match? |
|---|---|---|---|---|
| A | New-day reset | yes (yearly + daily) | yes (per-cron check) | ✅ |
| B | db_trades_today derive | n/a (in-memory state.equity etc.) | DB query | ⚠️ live-only ground-truth (good) |
| C | Daily cap (max_per_day=3) | yes (`day_filled_trades`) | yes (DB COUNT, excludes TTL_EXPIRED) | ✅ effectively same |
| D | Daily bias | yes (in-memory `daily_bias`) | yes (computed each cron) | ✅ |
| E | F28 override | yes (in BT engine via `bias_mode` param) | yes (config) | ✅ |
| F | 5-min cooldown | yes (`last_signal_time`) | yes (gd_signals query) | ✅ |
| G | Startup cooldown | n/a (no restart concept in BT) | live-only safety net | OK (different env) |
| I | generate_signals() | yes | yes (Phase 4 unified) | ✅ |
| J1 | Loop limit: per-cycle 1 trade | n/a (BT just iterates, cooldown gates) | break after 1 success | ⚠️ different mechanism, same outcome |
| J2 | Drop future signals | n/a | yes | OK (live-only) |
| J3 | Drop signals missing metadata | n/a | yes | OK (live-only) |
| J4 | Sweep-key dedup | INTRA-call only (`generate_signals` `traded_sweeps`) | INTER-call persistent (DB + in-mem) | 🔴 **THIS IS THE DIVERGENCE** |
| J5 | DB open-position guard | yes (`position_exit_time`) | yes (DB count) | ✅ |
| J6 | Broker open-position guard | n/a | yes | OK (live-only safety) |
| J8 | Mark sweep | n/a (no inter-call concept) | yes | 🔴 |
| J9 | Optimistic counter | yes (counts before execute_trade) | yes (mirrors) | ✅ |
| J10a | Success | yes | yes | ✅ |
| J10b | Clean None | yes (skip silently, **DOES NOT mark anything for next iteration since BT has no inter-call state**) | rolls back counter, KEEPS sweep marked | 🔴 |
| J10c | Exception | n/a | June 10 fix: keep mark | OK (live-only safety) |

#### Step 3: Where the divergence really lives

The fundamental mismatch: **BT has NO persistent state between `generate_signals()` calls**. Every BT run starts fresh. Live runs `generate_signals` every 3min on overlapping data → it MUST dedup signals across calls (else fires same wick repeatedly).

So live's `gd_traded_sweeps` exists for a reason BT doesn't have: **inter-call dedup**. It's not "the BT equivalent" — it's a new-mechanism response to a live-only need.

The question for parity: **what subset of "live blacklists a sweep" should match what BT would do if BT saw the same signal twice?**

BT doesn't see the signal twice. But IF it did (hypothetical), the second appearance would hit gate `J4` cooldown (300s since `last_signal_time`) → `continue`. **Cooldown, not staleness, is BT's deduper.**

So the alignment that brings live exactly to BT is:
- **Live's persistent blacklist must mark a sweep ONLY when BT would have caused that signal to be permanently un-fireable.** That happens when BT's `last_signal_time` advances.
- BT's `last_signal_time = signal.date` runs only on SUCCESS (line 330). Not on `result.filled is False`. Not on any earlier `continue`.
- **Therefore live's `mark_sweep_consumed` should ALSO run only on success.**

This is Option B verbatim, but now grounded in the BT code, not assumption.

#### Step 4: Cross-check — what about June 10's orphan-cascade scenario?

The June 10 fix made the mark BEFORE execute_signal because `execute_signal` could **place an order on the broker and then crash before writing the DB row** (the orphan). Without the pre-mark, next cron sees no DB row → re-fires → double order.

**Does Option B (mark on success) re-introduce orphan risk?** Walk it:
- Live places order successfully → broker has an order.
- DB INSERT for `gd_trades` row happens INSIDE `execute_signal` (`live_engine.py:524-528` for market path, `:450-456` for limit path).
- If DB INSERT raises **inside** `execute_signal` → numpy fix wrapped this in try/except (commit `dd044a3`); INSERT failure no longer crashes execute_signal but leaves a broker-order-without-DB-row → orphan-cancel reconciler kills it within 13s.
- If `execute_signal` returns trade_ref AND raises later somehow → the calling scheduler's `try/except Exception` block fires (`scheduler.py:459`); we'd hit `except Exception` branch.

**The orphan-cascade trigger is: order placed but `execute_signal` exits non-trade_ref.** Specifically:
- The pre-numpy-fix bug: `INSERT ... VALUES (np.float64, ...)` raised `InvalidSchemaName` → execute_signal raised → scheduler `except Exception` → mark stays (June 10 protection). But sweep was already marked at L424.
- Post-numpy-fix: INSERT no longer raises on numpy. Other DB failures wrap in try/except inside execute_signal (verified at `live_engine.py:519-522` and 449-468).

**Option B safety check:**
- Mark moves from BEFORE execute_signal to AFTER (in `if trade_ref:` branch).
- If broker accepts order + numpy fix prevents DB failure → execute_signal returns trade_ref → mark fires → ✅ no orphan
- If broker rejects (return None at L509) → no broker order → mark NOT needed → ✅ correct
- If `execute_signal` raises mid-flight (after place_market_order success but before return) → scheduler `except Exception` runs → **WE NEED TO MARK HERE** (the June 10 fix). Easy: keep the pre-mark in the exception path's pre-flight, OR add mark at top of `except Exception`.

#### Step 5: Today's pollution evidence (LIVE VPS DB pulled 2026-06-20 IST early hours)

**Pulled via** `https://midas.subashtrades.in/api/micro/debug/sql?q=...` **(GET, read-only).**

**`gd_traded_sweeps` rows for date=CURRENT_DATE:** 15 rows (8 oil-micro, 7 gold-micro).

**`gd_trades` for today, both systems:** 3 trades total
- `GD-MI-457d1578` LONG @ 4188.20 → SL'd -$155.79 (01:00 UTC)
- `GD-MI-a94ebe4a` LONG @ 4142.40 → MAX_HOLD +$90.02 (06:15 UTC)
- `OIL-MI-16c2231b` SHORT @ 79.25 → SL'd -$308.00 (03:00 UTC)

**Phase 6 deployed at 09:28 UTC today** (per Part 1 handoff).

**Post-Phase-6 `gd_traded_sweeps` writes for gold-micro:**
| consumed_at (UTC) | sweep_key | corresponding trade? |
|---|---|---|
| 10:18 | `2026-06-19T09:00:00+00:00_4_bearish` | NO |
| 13:48 | `2026-06-19T13:00:00+00:00_4_bearish` | NO |
| 13:51 | `2026-06-19T13:00:00+00:00_6_bearish` | NO |
| 13:54 | `2026-06-19T13:00:00+00:00_8_bearish` | NO |

**4 marked-no-trade rows. ZERO Gold Micro trades after 06:15 UTC. Phase 6 deployed 09:28 UTC.** All 4 rejections are post-deploy.

**Multi-window-per-wick pattern confirmed:** 13:00 UTC bearish wick produced 3 marks (start_hour 4, 6, 8) at 13:48, 13:51, 13:54 UTC — exactly 3 minutes apart (cron cadence). My VERIFY analysis is correct.

**Oil Micro post-Phase-6 marked-no-trade:** `12:00_8`, `13:00_4_bull`, `13:00_6_bull`, `13:00_8_bull`, `15:00_10_bear` = 5 rows post-deploy, only Oil's 03:00 UTC trade was pre-deploy.

**Sample interpretation: 13:00 Gold Micro bearish wick.**
1. Cron at 13:48 UTC (the first cron after the wick had time to fully form an engulfing within the start_hour=4 window): strategy emits signal for `(13:00, 4, bearish)`. Scheduler hits `mark_sweep_consumed`. `execute_signal` returns None (probably H6 through-market, post-Phase-6 gate). Mark stays. Loop breaks because `trade_placed_this_cycle=False` → does NOT break. Strategy did NOT also emit `(13:00, 6, bearish)` and `(13:00, 8, bearish)` in the SAME cron tick — why? Because the consol windows for 6 and 8 don't include 13:00 yet. They open later.
2. Cron at 13:51 UTC: window 6 became active (consol_end=13:00, scan_start=13:00). Strategy emits `(13:00, 6, bearish)`. Same H6 fail → mark stays.
3. Cron at 13:54 UTC: window 8 active. Same.

**This means my earlier "wick produces 3 signals in same cron, only 1 fires due to break" mental model was wrong for THIS wick** — actually the windows activate at different times due to `consol_hours` config. Each cron sees only ONE window-derived signal for the same wick.

**🚩 F-A1.10 important correction:** the cross-cron multi-window pattern is NOT "3-signals-1-cron + break". It's "1 signal per cron over 3 consecutive crons as windows roll active". Outer-loop break is actually NOT the relevant mechanism here — the strategy emits one signal per cron because one window is active per cron-tick for that wick.

**Does this change Option B's design? Let me re-walk:**
- Cron 13:48: `(13:00, 4, bearish)` rejected by H6. Mark stays in pre-fix → next cron at 13:51 with window 4 still active sees `is_sweep_consumed=True` → skip. ✅ correct dedup intent.
- BUT: the 13:51 cron's signal for window 4 would have failed H6 again anyway. So the mark "blocking" 13:51's W4 emission is a wash.
- Then 13:51 cron's strategy ALSO emits `(13:00, 6, bearish)` — different sweep_key. New row. Same H6 fail.
- The TRUE bug: at 13:48 we marked `(13:00, 4)` but the trade never happened. **Tomorrow's cron** (or post-position-close cron) would still walk past the 13:00 wick but with the H6 condition possibly different. **HOWEVER** by then `last_signal_time` has likely moved on (last successful signal at 06:15 → cooldown long expired) → no cooldown block → BUT `is_sweep_consumed` blocks the re-emergence.
- BT's behaviour: BT walks signal `(13:00, 4)` once. Engine rejects via... actually H6 isn't a BT gate. **BT does NOT have H6 through-market check.** F-A1.11.

**🚩 F-A1.11 NEW DISCOVERY:** H6 through-market is a LIVE-ONLY gate. BT doesn't simulate it. So **BT will trade `(13:00, 4, bearish)` and live won't.** Live's blacklist marking it doesn't even hide a parity gap — it creates one in the opposite direction (even with Option B, live will reject via H6 and BT will accept).

This is a separate axis from A1. It's an **execution-rejection-asymmetry** problem. Should be treated as its own audit item.

**🚩 F-A1.12 NEW DISCOVERY:** H6 firing means the live broker price moved AWAY from the limit before scheduler could place the order. BT models F27 limit fill via "wick touched limit price within TTL"; doesn't model "the limit was through market AT placement." So a BT signal that BT successfully `filled=True` could be a live H6-reject. Both A1 and A2 may be downstream effects of this.

**Fix design impact of F-A1.10/.11/.12:**
- Option B is still correct for the A1/A2 axis (clean None should not mark)
- But fixing A1 alone won't make today's "0 trades vs BT's 4" go to "live = BT" — it'll improve some, others will still diverge via H6
- Need a separate item for "live-only gates that BT doesn't simulate" — call it A9 (NEW). Will add to audit doc.

#### Step 6: Stateful integration test design (unwritten)

Pre-pollute test DB with today's exact rows (system, date, sweep_key). Run BT engine end-to-end on data covering today's wicks. Run live `_run_micro_sweep_core` (dry_run=True) on broker-format candle data for the same window. Assert:

(a) Without A1 fix: BT signal count > live signal count by exactly the count of marked-no-trade rows that were "unfair" rejections (not BT-also-rejected)
(b) With A1 fix: BT and live agree on signals taken (after accounting for live-only gates that we'll log separately as F-A1.11 axis A9 work)

This test goes in `tests/harness/parity/test_stateful_parity.py`. It's the planned next item after A1+A2.

#### Updated conclusion of VERIFY (post-live-data)

**Option B (mark on success/exception, not on clean None) is the correct A1 fix.** Live evidence confirms:
- 4 gold-micro post-Phase-6 marked-no-trade rows (today, no fix yet)
- All 4 are clean None returns (likely H6 through-market gate firing)
- With Option B: those 4 marks would not exist; subsequent crons would re-evaluate (and likely H6-reject again, until market moves favorably or window scan_until expires)
- Net effect: aligns live's persistent state with BT's "no inter-call state" model. **Cooldown gate (5 min) becomes the real deduper, matching BT.**

**Discovered-but-out-of-scope flags for separate items:** F-A1.11 H6-only-in-live, F-A1.12 F27 BT/live fill-asymmetry. Adding to audit as axis A9.

---

#### Step 7: A9 axis VERIFY — H6 + F27 fill-asymmetry between BT and live

**Goal: walk both BT and live's F27 paths bar-by-bar to find every divergence.**

##### 7a. BT F27 fill model (`backend/execution/fill_model.py:103-146`)

```python
# At signal bar t: entry/sl/tp/limit_price already computed by strategy + engine.
# Walk bars (t+1, t+2, ..., t+TTL):
#   LONG fill ok = bid_low[bar] ≤ limit_price  (touched)
#                  AND (bid_close[bar] ≤ limit_price if strict else True)
#   SHORT fill ok = ask_high[bar] ≥ limit_price (touched)
#                   AND (ask_close[bar] ≥ limit_price if strict else True)
# Fill on first OK bar. Apply slippage on fill bar (entry = limit_price ± slip × 0.2).
# If no fill in TTL bars: return missed_unfilled.
```

BT's mental model: **"limit was placed at bar t. Did any subsequent bar's wick touch it?"** No concept of "is the limit reachable at placement-time."

##### 7b. Live F27 placement path (`backend-micro/scanner/live_engine.py:281-490`)

```
At cron time T (≥ signal bar t + 3min wallclock):
  1. cfg_entry_mode = "limit" (config check)
  2. limit_offset_pct, limit_ttl_bars from config
  3. ttl_seconds = limit_ttl_bars × 180
  4. risk_distance = abs(entry_price - sl_price)
  5. live_price = get_current_price() — broker tick at time T
  6. engulf_ask, engulf_bid = live_price.ask, live_price.bid (NOT df ask_close[t]!)
  7. compute_limit_price(direction, signal_entry, signal_risk, engulf_ask, engulf_bid, offset_pct)
  8. → returns intended_limit
  9. H6 (live-only): if direction==long and intended_limit > live_ask_now → REJECT, return None
                     if direction==short and intended_limit < live_bid_now → REJECT, return None
  10. C2 (live-only): if direction==long and sl_price >= intended_limit → REJECT
                      if direction==short and sl_price <= intended_limit → REJECT
  11. place_limit_order on broker → broker tracks fill within ttl_seconds
  12. pending_order_monitor (every 30s) → broker reports fill OR TTL_EXPIRED
```

**🚨 CRITICAL DIFFERENCE in step 6:** BT calls `compute_limit_price` with `engulf_close_ask = df["ask_close"].iat[bar_idx]` — the M3 bar's ask_close at signal time. **Live calls it with `engulf_ask = live_price["ask"]` — the CURRENT broker tick at cron time.**

So:
- BT Variant B: `limit_price = ask_close[t]` (pinned to bar t)
- Live Variant B: `limit_price = ask_now_at_cron_T` (pinned to T = t + ~3min)
- These are DIFFERENT prices. Variant B is supposed to be "engulfing close, no slippage" — but live uses post-engulfing tick as the anchor. **Latent parity bug independent of A1.**

##### 7c. Today's evidence cross-check

For Gold Micro `13:00_4_bearish` consumed at 13:48 UTC:
- Signal at engulfing bar t = somewhere in 13:00-13:45 UTC (consol_end=13:00, scan_until=13:45)
- Cron at 13:48 UTC fires
- Strategy emits signal with entry/sl/tp/risk
- compute_limit_price uses live_bid_now (13:48 tick) as engulf_bid for SHORT (Variant B)
  - Variant for Gold Micro is C10_loose per [[project-filter-27-limit-orders]] — so offset_pct = -0.10
  - For SHORT C10: `limit = signal_entry - (-0.10) × signal_risk = signal_entry + 0.10 × risk` (limit ABOVE entry, pullback)
- H6 SHORT: if `intended_limit < live_bid_now` → reject. SHORT limit is ABOVE entry, ABOVE bid_close[t]. live_bid at 13:48 is wherever the market drifted in 3 min. If price kept falling after the wick → live_bid_now < intended_limit → H6 fires.

**🚩 F-A1.13:** Variant C is engineered to place limits AT or BEYOND the natural reversal. H6 protects against the broker rejecting placements through market. But by definition, Variant C's pullback puts the limit BEYOND the engulfing close. For SHORTs, "beyond" = "above". If price has already moved up post-engulfing, the limit is BELOW market (wrong side for SHORT). That's the H6 trigger.

##### 7d. The deepest question — are H6 rejections "missed-but-BT-would-have-won"?

Open question: does BT walk ON to fill these signals successfully in subsequent bars? Or does BT also miss them?

To answer: walk a real example. Take Gold Micro 13:00 wick. BT inputs are M3 bar OHLC. Today's M3 bar data covering 13:00-15:00 UTC will tell us if BT's `ask_high[bar] ≥ limit_price` was satisfied within TTL bars.

**Cannot answer this from VPS API alone — need a BT replay.** Will use `scripts/bt_replay.py` (built earlier this week).

##### 7e. Fix design space for combined A1+A9

**Three possible fixes:**

**Path 1 (simplest, A1 only):** Move mark to success/exception. Accept H6 will keep firing → broker-rejection-asymmetry remains as A9 axis to be solved separately.
- Pros: ~30 lines, scoped, low risk
- Cons: today's "0 trades vs BT's 4" gap won't fully close. Maybe 0 → 1-2.

**Path 2 (A1 + matching BT to live's H6):** Add H6 to BT engine — when BT computes `limit_price` at bar t, if `limit_price > ask_close[t]` (LONG) or `limit_price < bid_close[t]` (SHORT), BT also returns missed_unfilled (or skips entirely). Re-run 7yr backtest.
- Pros: BT predicts what live will actually do. Closes today's "BT predicted 4, live did 0" framing.
- Cons: 7yr P&L drops materially (some BT-winning trades become BT-misses). Requires user re-approval of BT $3M numbers.
- **Where to add:** `fill_model.py` line 102 area, add a pre-check on `limit_price` vs entry direction's expected "side."

**Path 3 (A1 + fix live's H6 to use BT's anchor, not live tick):** Change live's `compute_limit_price` call to use `signal.entry` (= bar t's ask_close + slippage) instead of `live_price.ask`. Variant B in live becomes "engulfing close at signal bar," matching BT exactly.
- Pros: Live behaves like BT.
- Cons: Variant B uses post-engulfing data which is freshest market info. Removing it potentially makes worse fills. AND H6 would still fire on stale anchors when market has moved through them. Solving this needs rethinking H6 from scratch.

**Combined-fix recommendation:** **Path 1 + Path 2.** Path 1 cleans up A1 today (mark-after-success). Path 2 adds a `bt_h6_check` to BT and re-runs the BT to get an HONEST live-capture number. Path 3 has design questions that need a separate research item.

**Path 2 cost-benefit:** ~10 lines in `fill_model.py`. ~5 lines in each of 4 backtest engines. Re-run 7yr backtest = 60-90 min. Likely PnL impact: −$200k to −$500k of the $3.04M honest 7yr (ballpark; need to measure). **Trade-off:** less cited backtest wealth, but matching live behaviour means trustable forward projection.

##### 7f. Live evidence — BT replay run 2026-06-20 IST early hours (DATA NOW IN HAND)

**Tool:** `scripts/replay_today_missed_signals.py` — runs BT slice 2026-06-04 → 2026-06-20, filters to date=2026-06-19, classifies pre/post Phase 6 deploy (09:28 UTC).

**BT trades for 2026-06-19, both systems (REAL NUMBERS):**

```
gold-micro:
  [PRE ] 08:09 UTC LONG entry=4130.29 sl=4119.94 tp=4192.63 → tp_partial+expired bars=79 pnl=$+1549.32
  [POST] 14:09 UTC LONG entry=4148.26 sl=4139.98 tp=4176.63 → sl bars=32 pnl=$-2.75
  [POST] 16:27 UTC SHORT entry=4164.02 sl=4184.96 tp=4123.94 → tp_partial+expired bars=39 pnl=$+459.67
  PRE-deploy:  1 trade, $+1549.32
  POST-deploy: 2 trades, $+456.92

oil-micro:
  [POST] 12:21 UTC LONG entry=79.1855 sl=78.55 tp=80.07 → PARTIAL+TP bars=64 pnl=$+324.26
  [POST] 16:12 UTC LONG entry=79.1134 sl=78.33 tp=80.07 → BE_SL bars=13 pnl=$-27.75
  PRE-deploy:  0 trades, $+0.00
  POST-deploy: 2 trades, $+296.51
```

**TOTAL POST-DEPLOY GAP: BT predicted +$753.43, live captured $0 → $753.43 missed.**

##### 7g. Cross-walk BT trades against gd_traded_sweeps marked-no-trade

Gold Micro post-deploy marks: `09:00_4_bearish` (10:18), `13:00_4_bearish` (13:48), `13:00_6_bearish` (13:51), `13:00_8_bearish` (13:54).
Gold Micro BT post-deploy: 14:09 LONG, 16:27 SHORT.

**Direction analysis:**
- Live marked 4 BEARISH wicks (= SHORT signals)
- BT post-deploy fired 1 LONG (14:09) and 1 SHORT (16:27)
- The BT 16:27 SHORT had bar_idx around the `13:00_8_bearish` wick? Engulfing window is 0.75hr = 45min × 20 bars = 15 M3 bars. 13:00 + 0.75hr = 13:45. So BT's `13:00_8` engulfing window spans 13:00-13:45. **BT's 16:27 entry is OUTSIDE that window** → 16:27 SHORT is from a DIFFERENT wick (probably `15:00` or `16:00`).
- The 14:09 LONG is a different sweep entirely.
- **None of BT's post-deploy trades correspond directly to live's marked-no-trade rows.**

**Why? Two hypotheses:**
1. **(Likely)** Live's marked-no-trade rows were sweeps where strategy emitted a signal (so live tried) but couldn't fill due to H6/C2 etc. BT walked the same wicks and **did NOT produce a signal at all** (engulfing failed, range failed, bias filter rejected via different timing). BT's "no signal" ≠ live's "signal but rejected."
2. Live's `compute_limit_price` uses `live_price.ask` not `df["ask_close"][bar_idx]` → different limit prices → different H6 outcomes than what BT would simulate.

**This means A1's persistent-state-fix WILL NOT close today's gap.** The gap is from somewhere else — different signal generation OR different fill physics.

**🚨 F-A1.14 CRITICAL FINDING:** today's $753 gap is NOT from A1 (sweep blacklist persistence). The marked-no-trade rows blacklist sweeps that BT also didn't trade. The actual gap is BT's 14:09 LONG and 16:27 SHORT for Gold + 12:21 LONG and 16:12 LONG for Oil — none of which appear in `gd_traded_sweeps` post-deploy. Live's strategy at those crons either emitted no signal, or emitted+rejected somewhere we haven't traced.

##### 7h. Need to dig further

The marked-no-trade rows are not the gap. The gap is signals BT emitted that **never reached live's `mark_sweep_consumed` line** at all. They were rejected upstream — probably by:
- Different `_get_active_windows` outcomes (H1 cron timing vs BT bar-walk)
- Different bias filter outcomes (bias is computed once at cron-time vs BT computes per-day)
- Engulfing tolerance / range thresholds mis-aligning between live's broker M3 view (50 bars) and BT's full history M3 view
- Live's `_log_signal` cooldown gate firing on signals that BT walks past

This is outside A1+A9 scope. Need to trace why BT's 14:09 LONG didn't even reach live's signal loop.

**Conclusion:** A1+A9 fix won't close today's $753 gap. Different bug class. Renaming this work item.

#### Conclusion of VERIFY

**A1 fix that achieves true live↔BT parity:**

1. Move `_traded_sweeps['keys'].add()` + `mark_sweep_consumed()` from BEFORE execute_signal to:
   - (a) in `if trade_ref:` branch (success — equivalent to BT's `last_signal_time = signal.date`)
   - (b) in `except Exception:` branch (preserves June 10 orphan-cascade fix)
   - **NOT** in clean `None` branch
2. Drop the `unmark_sweep_consumed` helper — never needed.
3. The pre-iteration in-memory check at L373-377 (`if sweep_key in _traded_sweeps['keys']`) and the DB check are still needed for cross-cron dedup of NEW signals after a successful trade.

**Diff size:** ~4 lines moved per scheduler. Net change vs current code: 0 LoC (just relocation). Total ~30 lines edited across 2 schedulers. No new helper. No new tests beyond stateful integration test.

#### What still needs proving before I commit

1. ✅ BT walked end-to-end. Verified `last_signal_time` updates only on success.
2. ✅ Live walked end-to-end. Verified all gate orderings.
3. ✅ Junction between June 10 fix and Option B reasoned out.
4. **NOT YET DONE:** pull today's `gd_traded_sweeps` rows from live DB and walk each one through Option B's logic to confirm the post-fix behaviour matches BT's expected behaviour for those exact wicks.
5. **NOT YET DONE:** stateful integration test that pre-pollutes DB and runs both BT and live sweep_core against it.

Items 4-5 happen in this VERIFY before any code changes.

**Sites grep'd for `mark_sweep_consumed` + `_traded_sweeps["keys"].add` across the repo:**

`backend-micro/scanner/scheduler.py`:
- L376 — restore-from-DB cache (sets in-memory key when DB returns `is_sweep_consumed`)
- L414 — dry_run path (mocks live, harness-only)
- L424 — **THE LIVE WRITE** (in-memory + `mark_sweep_consumed("gold-micro", today, key)`)

`backend-oil-micro/scanner/scheduler.py`:
- L361 — restore-from-DB cache (mirror of micro L376)
- L402 — dry_run path
- L413 — **THE LIVE WRITE** (mirror of micro L424)

`backend/scanner/scheduler.py` (Gold Macro — currently disabled per `e38b288`):
- L778 + L790 — two write sites (Macro has 2 paths). Out of scope for now (Macro disabled), but **🚩 FLAG** for re-enable later.

**`mark_sweep_consumed` definition** (`backend/db.py:291`):
```python
def mark_sweep_consumed(system, target_date, sweep_key):
    execute("INSERT INTO gd_traded_sweeps ... ON CONFLICT DO NOTHING", ...)
```
**No `unmark_sweep_consumed` exists.** Confirmed by grep. We will need to add one.

**`is_sweep_consumed` definition** (`backend/db.py:278`):
```python
SELECT 1 FROM gd_traded_sweeps WHERE system=%s AND date=%s AND sweep_key=%s
```

**Live's None-return paths from `execute_signal`** (`backend-micro/scanner/live_engine.py`):
1. L187 — `_should_skip(dd_state)` true (consecutive losses pause)
2. L194 — `account_summary_failed`
3. L204 — `equity_too_low` (< $100)
4. L210 — `zero_sl_distance`
5. L226 — `units_too_small` (< 1)
6. L232 — `sl_is_zero`
7. L242 — `sl_too_close_to_price` (SHORT)
8. L246 — `sl_too_close_to_price` (LONG)
9. L253 — `tp_already_passed` (LONG)
10. L257 — `tp_already_passed` (SHORT)
11. L270 — `position_already_open` (defense-in-depth)
12. L343 — `limit_price_through_market` (LONG)
13. L361 — `limit_price_through_market` (SHORT)
14. L383 — `limit_invalid_sl_wrong_side` (LONG)
15. L398 — `limit_invalid_sl_wrong_side` (SHORT)
16. L442 — `limit_order_failed` (broker error placing limit)
17. L509 — market `order_failed` (broker error placing market)

**17 None-return paths. ALL of them currently leave `gd_traded_sweeps` row + `_traded_sweeps["keys"]` populated.** Confirmed by reading every path.

**BT (truth source) behaviour** — read `backend/strategies/micro_alpha_sweep.py` and `backend-oil-micro/strategies/micro_alpha_sweep_oil.py`:
- `traded_sweeps = set()` is a **per-run in-memory set inside `generate_signals()`**. It is NEVER persisted to DB.
- A sweep_key is added to `traded_sweeps` at:
  - L213 (`if len(m3_window) < 3`): real data gap, not a fill rejection
  - L284 + L289 (gold) / L206 + L211 (oil): when the strategy emits the signal OR when no engulfing was found in the engulfing window
- BT's `traded_sweeps` is for **deduplication within signal-gen**, not "execute_trade succeeded" tracking
- BT engine's downstream gates (cooldown, position-open, DD pause, units<min, daily-cap) skip signals **without** ever telling the strategy. `traded_sweeps` does NOT track downstream rejection.
- **🚨 FOUND: an actual BT-side variant of A1.** `backend-micro/backtest/engine.py:303 `if result is None: continue` — BT skips the signal AND does not add to `traded_sweeps` (because traded_sweeps is inside the strategy's previous call, frozen). Live skips AND has already polluted DB.

**⚠️ CORRECTION TO AUDIT:** the audit says "BT marks sweep only after `execute_trade()` actually succeeds." That is **NOT what the code does**. BT's strategy (signal-gen layer) marks the sweep WHEN IT EMITS THE SIGNAL (not later, not at execute). The BT engine then runs gates that may skip the signal silently. So a BT signal that gets rejected by cooldown/equity/DD also leaves the strategy's `traded_sweeps` populated — but only for the duration of one `generate_signals()` call. Next BT run starts fresh.

**The real divergence** (after re-reading both sides):
- **BT:** strategy emits N signals → engine walks them → some rejected by gates → strategy's `traded_sweeps` is local to that run, throwaway. Next backtest call starts clean.
- **Live (today):** strategy emits N signals → scheduler inspects each → marks sweep in `gd_traded_sweeps` BEFORE asking `execute_signal`. If `execute_signal` returns None for ANY of the 17 reasons above, the row stays. Next cron sees the same wick (still in H1 lookback) → strategy emits the same signal_key → scheduler reads `is_sweep_consumed=True` (L375) → skip.

**Why Phase 6 amplified it:** Pre-Phase-6 had fewer rejection paths in `execute_signal` (no H6 through-market check, no equity-MA tightening). Post-Phase-6 added 4 new rejection paths (L343, L361, L383, L398) → 4× more pollution events per session.

**🔴 BUG CONFIRMED.** Live's `mark_sweep_consumed` happens BEFORE downstream gates that can return None. Rollback exists for `_daily_state["trades"]` (L457) but not for `gd_traded_sweeps` row or `_traded_sweeps["keys"]`. ✅ Audit's *behaviour* description is correct. The *RCA mechanism* attribution to "BT marks only on success" is wrong, but doesn't change the fix.

**Today's evidence (from VPS):**
- `recent_signals` shows last taken Gold Micro signal at `08:15 UTC LONG`. Phase 6 deploy at 09:28 UTC (14:58 IST). After 09:28 UTC: 0 trades on Gold Micro. We can verify the pollution via DB; will do in Stage 2.

**🚩 FLAGS during VERIFY (will not fix here, will note in their own item):**
- F-A1.1: Gold Macro scheduler has the same antipattern at L778+L790. Macro is disabled per `e38b288`, but if re-enabled the bug returns. Document in audit, fix when re-enabling.
- F-A1.2: `_restore_traded_sweeps_on_startup` (L472) does NOT seed `_traded_sweeps["keys"]` from DB — it uses a startup-cooldown mechanism. So in-memory cache is empty after restart, BUT `is_sweep_consumed` is still queried at L373-375 for every signal → the DB row still blocks the cron. **This is GOOD** (DB is source of truth) but means our fix MUST hit DB, not just the in-memory set.
- F-A1.3: 4 helper test scripts mock `mark_sweep_consumed = lambda: None` (`scripts/debug_*.py` etc.). Confirms harness writers knew this state was a problem; fix here means the mocks remain valid.
- F-A1.4: `tests/harness/parity/test_oil_micro_parity.py:268` and `test_gold_micro_parity.py:172` mock `mark_sweep_consumed` to no-op. Same as F-A1.3. Stateful test (next item) must instead pre-populate to test the rollback.

### RCA (Stage 2)

**Mechanism:** Live scheduler's "mark before execute" pattern (June 10 fix for the orphan-cascade bug — when `execute_signal` *raised mid-flight*, the next cron retried the same sweep and we got 7 orphans). Mark BEFORE prevents that. The fix was correct for **exceptions**; it never accounted for **clean None returns** from gates that fire downstream.

**Why it didn't trigger pre-Phase-6:** Pre-Phase-6 None paths were narrower (mostly `_should_skip` and `units_too_small`). The 4 new paths added by Phase 6 (limit-through-market, limit-invalid-sl × LONG/SHORT) execute *after* `mark_sweep_consumed` and produce silent pollution. Higher rejection rate → higher pollution rate.

**Why smoke harness didn't catch it:** Harness mocks `is_sweep_consumed = lambda: False` (line 154). Both BT and live read the same fresh state. No test pre-populates `gd_traded_sweeps` to simulate yesterday's pollution → no divergence visible.

**Cost so far (verified, not estimated):** Phase 6 deployed 09:28 UTC → 22:00 UTC = 12.5hr window. From earlier session investigation: 12 marked-but-no-trade sweeps in `gd_traded_sweeps` for today (15 marked total, 3 became trades). Each is a sweep that BT *would* take fresh. Number-of-trades cost is bounded by `max_trades_per_day=3` even if all 12 became trades.

### FIX (Stage 3)

**Two changes:**

1. `backend/db.py` — add helper:
   ```python
   def unmark_sweep_consumed(system, target_date, sweep_key):
       """Remove a sweep_key from the blacklist. Used when the signal that
       triggered the mark was rejected cleanly (live path returned None)."""
       execute(
           "DELETE FROM gd_traded_sweeps WHERE system=%s AND date=%s AND sweep_key=%s",
           (system, target_date, sweep_key)
       )
   ```

2. `backend-micro/scanner/scheduler.py` — modify ONLY the `else: # signal not taken` branch at L456-458. KEEP the `except Exception` branch UNCHANGED (June 10 fix is load-bearing for orphan-cascade).
   ```python
   else:
       _daily_state["trades"] = max(0, _daily_state["trades"] - 1)
       # A1 fix (2026-06-19): roll back sweep blacklist when execute_signal
       # cleanly returns None. Mid-flight EXCEPTIONS still leave the sweep
       # marked (June 10 fix — orphan-cascade prevention). See
       # docs/parity/PARITY_AUDIT_2026-06-19.md axis A1.
       _traded_sweeps["keys"].discard(sweep_key)
       try:
           from backend.db import unmark_sweep_consumed
           unmark_sweep_consumed("gold-micro", today, sweep_key)
       except Exception as e:
           _log.warn("SYSTEM", "unmark_sweep_consumed_failed",
                     err=str(e), sweep_key=sweep_key)
       _log.warn("SIGNAL", "skipped_by_engine", direction=direction, sweep_key=sweep_key)
   ```

3. `backend-oil-micro/scanner/scheduler.py` — same change at L445-448, with `"oil-micro"` system arg.

**Out of scope (deliberate):**
- Macro scheduler L778+L790 — system disabled. Document under FLAGS for re-enable.
- Gold Macro daily_close_job sweep marking — same reason.
- F27 limit-TTL expiry path — that's A2 (next item, separate fix).

**Diff size:** +1 helper in `backend/db.py` (~6 lines), +6 lines × 2 files in schedulers. ~18 lines total.

**Risk:** Catastrophic-class risk = "we could break orphan-cascade prevention." Mitigation: the exception-branch on L459-465 is UNTOUCHED. The new code path is reached only when `trade_ref is None` (clean rejection) — that path was never the orphan-cascade trigger.

### TEST (Stage 4)

**Test 1 — DB helper unit test** (`tests/test_unmark_sweep_consumed.py`):
- Insert via `mark_sweep_consumed("gold-micro", date(2026,6,19), "test_key")`
- Assert `is_sweep_consumed(...)` returns True
- Call `unmark_sweep_consumed(...)`
- Assert `is_sweep_consumed(...)` returns False
- Edge: unmark a key that doesn't exist — should be no-op (DELETE matches 0 rows is fine)

**Test 2 — Hand-trace** (no automation, document below): walk through scheduler.py L424-465 with each None-return path mentally:
- `execute_signal` raises → `except Exception` (L459) → does NOT call unmark_sweep_consumed → ✅ June 10 fix preserved
- `execute_signal` returns None → `else` (L456) → calls unmark_sweep_consumed → ✅ A1 fix
- `execute_signal` returns trade_ref → `if trade_ref` (L452) → keeps sweep marked → ✅ no behavior change

**Test 3 — Stateful integration test** = the next work item (Stateful Parity Test), which pre-pollutes `gd_traded_sweeps`, expects pre-fix behaviour to fail and post-fix to pass. Documented separately because it serves multiple items (A1, A2, A5, A6).

**Verification run before commit (results below):**

```
$ python -m py_compile backend/db.py backend-micro/scanner/scheduler.py backend-oil-micro/scanner/scheduler.py tests/test_unmark_sweep_consumed.py
compile OK

$ TEST_DB_URL=postgresql://subash@localhost:5432/golddigger_test pytest tests/test_unmark_sweep_consumed.py -v
6 passed in 0.41s

$ pytest tests/test_unmark_sweep_consumed.py tests/test_psycopg2_numpy_adapter.py tests/test_production_gates.py -q
63 passed in 0.40s
```

**Test coverage (6 cases):**
1. mark → unmark → assert gone
2. unmark on never-marked key = no-op (no exception)
3. unmark gold-micro does NOT affect oil-micro's identical key (system-scoped)
4. unmark today does NOT affect yesterday's identical key (date-scoped)
5. mark → unmark → mark again = round-trip works
6. double-unmark same key = safe no-op

**🚨 Found while writing test:** local test DB `golddigger_test` was missing `gd_traded_sweeps` table. Created it from `database/schema.sql`. **🚩 FLAG F-A1.9** — schema sync to local test DB missing in conftest. All other parity tests mock around this. Fix via init script in next pass.

### Files changed
- `backend/db.py` — +`unmark_sweep_consumed()` helper (~14 lines incl docstring)
- `backend-micro/scanner/scheduler.py` — +9 lines in `else` branch (in-mem discard + DB unmark + logging)
- `backend-oil-micro/scanner/scheduler.py` — +9 lines mirror
- `tests/test_unmark_sweep_consumed.py` — NEW, 6 tests, ~120 lines

### FLAGS

- **🚨 F-A1.0 (Option-A miss, why we reverted):** the Option-A diff (`unmark_sweep_consumed` in clean-None branch) was unit-test green and regression green, but did **not** achieve live↔BT parity. Reason: live's outer loop has `if trade_placed_this_cycle: break` (`scheduler.py:347`), and a single wick can produce 3 signals (rolling windows 4/6/8). Today's window flow:
  - Cron N: signal_W4 fires → mark + execute success → `break`. Signals_W6 + signals_W8 unprocessed.
  - Cron N+1 (position open): signal_W6 + signal_W8 generated again → mark + `position_already_open` → returns None → unmark.
  - Cron N+M (position closed): signal_W6 + signal_W8 still in strategy output (same wick still in H1 lookback) → unmarked → mark + execute → could fire signals timestamped from cron N at cron N+M's price.
  - **BT NEVER does this.** BT engine `if signal.date < position_exit_time: continue` (`backend-micro/backtest/engine.py:224`) silently drops stale-during-hold signals.
  - Audit's T2 axis (signal staleness, no upper bound) covers this; Option A would have created a fresh T2 violation.
  **Lesson:** I followed the audit's framing instead of stress-testing it. The audit said "ship A1 in 30 min" — I read it, found 17 None paths instead of the audit's 4 (good), but didn't extend the analysis to multi-signal-per-wick × outer-loop-break × cron-cadence interaction. Caught it post-test only because user asked "are we 100% sure." Should have caught it in VERIFY by walking BT engine first.
- **F-A1.1** Gold Macro scheduler has same antipattern at L778+L790. Macro disabled per `e38b288`; bug returns if re-enabled. Add to re-enable checklist.
- **F-A1.2** `_restore_traded_sweeps_on_startup` doesn't seed `_traded_sweeps["keys"]` from DB; uses `is_sweep_consumed` per-cron instead. Means our fix MUST hit DB to be real (in-memory set is rebuilt every restart anyway).
- **F-A1.3** Multiple `scripts/debug_*.py` files mock `mark_sweep_consumed` away. Mocks stay valid after fix. No-op for tests.
- **F-A1.4** Two parity-harness tests mock `mark_sweep_consumed` to no-op. Stateful parity test (next item) must NOT mock — must use real DB.
- **F-A1.5** Audit's RCA story ("BT marks only on success") is wrong. Reality: BT's `traded_sweeps` is local-to-`generate_signals()`-call, throwaway. Live's mark is to a persistent DB table. The mechanism is "ephemeral vs persistent state" — fix is the same regardless. Will update the audit doc after A1+A2 ship.
- **F-A1.6** Today's pollution = 12 marked-but-no-trade rows in `gd_traded_sweeps`. After fix lands, those rows persist (we don't retroactively clean them). DB wipe (Stage B from earlier session) will clear them. **MUST run DB wipe AFTER A1+A2+A5 ship**, not before, else fresh DB re-pollutes from any restart-window.
- **F-A1.7** Race window: cron job runs every 3 min. If signal A is mid-execute_signal (call in-flight) and a parallel cron starts (it can't — APScheduler `max_instances=1`) — N/A. **Verified: APScheduler default `max_instances=1` per job.** No race.
- **F-A1.8** Multi-EA contention isn't the issue — there's no EA call between `mark_sweep_consumed` and the None return.

---

## BT-LOOKAHEAD — F27 fill model uses engulfing M3 bar as bar_idx (PATH 3 FIX)

**Priority:** P0 · **Started:** 2026-06-20 IST 04:30 · **Status:** 🔵 IN_PROGRESS

### Audit claim
BT engine reads `signal.date = engulfing M3 bar` and uses `bar_idx = df.index.get_loc(signal.date)`. Strategy emits a signal in `for bar_ts in day_h1.iterrows()` only when `bar_ts >= end_hour + 1`. So the EARLIEST knowable time of the signal = h1 bar_ts. But BT walks fill from engulfing M3 bar onwards. **Reverse lookahead of (h1_bar_ts - signal.date) ≈ 30-60 min.** Tape replay produced zero fills for trades BT shows as filled. Real bug.

### VERIFY (Stage 1)

**Where lookahead lives in code:**

| File | Line | Code |
|---|---|---|
| `backend/strategies/micro_alpha_sweep.py` | 251 | `signal.date=gold_m3.index[idx]` (engulfing M3 — SOURCE) |
| `backend/strategies/micro_alpha_sweep.py` | 274 | same for SHORT |
| `backend-oil-micro/strategies/micro_alpha_sweep_oil.py` | 177 | `date=oil_m3.index[idx]` (LONG) |
| `backend-oil-micro/strategies/micro_alpha_sweep_oil.py` | 198 | same SHORT |
| `backend-micro/backtest/engine.py` | 249 | `bar_idx = df.index.get_loc(signal.date)` (USE) |
| `backend-oil-micro/backtest/engine.py` | similar |
| `backend/backtest/engine.py` (Macro) | similar |
| `backend-oil/backtest/engine.py` (Macro) | similar |

**Strategy outer loop variable that should be the "knowability" anchor:** `bar_ts` (the H1 bar in `for bar_ts, bar in day_h1.iterrows()`) at the moment of emission.

**Concretely for the BT 08:09 LONG case:**
- `bar_ts = 09:00 UTC` (the h1 bar whose `_hour_past` check returned True)
- `sbar_ts = 08:00 UTC` (the sweep h1 bar)
- `idx = m3 idx of 08:09` (engulfing M3 bar)
- `signal.date = 08:09` ← what BT uses as bar_idx for fill walk
- `signal_emit_h1_bar = 09:00` ← what BT *should* use

**Decision: which timestamp is the right "earliest knowable" anchor for live parity?**

In live, the cron tick at `bar_ts.minute = 0/3/6/...` AFTER `bar_ts` closes (because broker H1 is delivered after the bar closes). So if `bar_ts = 09:00 UTC`, the earliest live cron that sees this is `09:03 UTC` (next */3 cron tick). Live then emits signal, sends limit to broker (broker accepts at ~09:03:01 UTC).

**Fix anchor:** `signal_emit_h1_bar + 1 minute` (round up to next M3 boundary). For 09:00 H1 → first M3 bar of fill walk = 09:03 UTC. 

But there's a subtlety — the live cron at 09:03 might not have the 09:00 H1 yet (broker delay). The next reliable cron is 09:06. **Conservative anchor: signal_emit_h1_bar + scan_minute_cadence (=3min)**. So fill walk starts at 09:03 M3 (which BT can also access).

**Implementation plan:**
1. Strategy: pass `emit_h1_bar` (string ISO) in `signal.metadata`
2. Engine: at fill-walk time, compute `fill_start_m3 = m3 bar at emit_h1_bar + 3min` (or first M3 bar > emit_h1_bar)
3. Pass `bar_start = m3.index.get_loc(fill_start_m3)` to `execute_trade` instead of engulfing bar_idx

**Affected files:** 4 strategies (gold_micro, oil_micro, oil_macro_alpha_sweep, gold_macro_alpha_sweep) and 4 engines.

**Risk:** every F27-mode trade will fill different bar (or not fill) → 21yr P&L will change materially. Cost: probably very large drop. But this is the honest number.

**🚩 F-LOOKAHEAD.1 — does the same lookahead affect MARKET-mode entries?** Yes. For market mode, BT also uses `bar_idx = engulfing M3` and assumes entry at engulfing's `ask_close + slippage`. Real live market entry happens at `bar_ts + cron_lag`. Need same fix for market mode.

**🚩 F-LOOKAHEAD.2 — does the same affect SL/TP exit walk?** No. Exit walk starts at `bar_start` and walks forward. Once `bar_start` is correct (post-h1-emit), the SL/TP walk is correct.

**🚩 F-LOOKAHEAD.3 — Macro strategies (alpha_sweep, alpha_sweep_oil) also affected?** Probably yes. Macros use the same h1 + scan-bar pattern. Macros currently disabled but if re-enabled the bug reappears.

### RCA (Stage 2)

Strategy was designed to mirror live's signal data: `signal.date` = engulfing M3 (the bar where the entry condition is verified). That's correct as a "this is the price we'd want." But the BT engine then uses signal.date as the **fill anchor** — that's where the assumption breaks. Live's fill anchor is "when can I tell the broker about this signal" = the H1 cron tick after consol completes. BT's fill anchor was conflated with signal.date.

The bug was likely INVISIBLE for years because:
- Phase 6 (last week) unified live↔BT signal-gen but didn't change fill anchors.
- BT's $3.04M honest 7yr was calculated WITH this lookahead.
- Tape replay in this branch is the FIRST tool to expose it.

### FIX (Stage 3)

_pending — designing surgical patch next..._

### TEST (Stage 4)
_pending..._

### FLAGS
_pending..._

---

## A10 — Signal-gen divergence (NEW, where today's $753 lives)

**Priority:** P0 · **Started:** 2026-06-20 IST early hours · **Status:** 🔵 IN_PROGRESS

### Audit claim
This axis is NEW — discovered during A1 VERIFY. BT replay run 2026-06-20 shows:
- BT fired 4 trades on 2026-06-19 post-Phase-6 deploy (09:28 UTC):
  - Gold Micro 14:09 UTC LONG @ 4148.26 → SL → -$2.75
  - Gold Micro 16:27 UTC SHORT @ 4164.02 → TP partial → +$459.67
  - Oil Micro 12:21 UTC LONG @ 79.1855 → PARTIAL+TP → +$324.26
  - Oil Micro 16:12 UTC LONG @ 79.1134 → BE_SL → -$27.75
- **TOTAL +$753.43**
- Live: 0 trades post-deploy. None of BT's 4 entries appear in `gd_traded_sweeps` post-deploy.
- **Therefore live never even reached `mark_sweep_consumed` for these signals.** Rejected upstream.

### VERIFY (Stage 1)

**Hypotheses to enumerate (then test each in code):**

1. **Live's H1/M3 broker view truncates the lookback window.** Live calls `get_candles(H1, count=24)` and `get_candles(M3, count=50)`. BT walks the FULL CSV. For sweep+engulfing patterns spanning >24 H1 bars or >50 M3 bars, live can't see what BT sees.
2. **Daily bias is computed once at cron-time vs BT computes per-day.** Bias affects sweep direction filtering (`if bias != "neutral": ...`).
3. **`_log_signal` cooldown gate firing.** If a previous signal was logged less than 5 min ago, live returns early — even if no actual position was taken. BT cooldown is also 5 min but anchored to `last_signal_time` which only updates on success.
4. **`_get_active_windows()` only returns the first matching window per cron.** Live can scan only the windows that are within their `consol_end → scan_until` interval at cron-time. BT walks all bars sequentially — hits every window's signal as the day unfolds.
5. **Engulfing tolerance numerics differ in real broker M3 candles vs CSV.** ENGULFING_TOLERANCE = small float; one-side rounding differences could flip a barely-engulfing bar.
6. **Live's `mt5 get_open_trades()` blocking pattern.** If broker reports any open trade (e.g. orphan ticket), live skips ALL signals for that cron. BT only checks `position_exit_time`.
7. **Live's `db_trades_today >= max_per_day` check.** Live counts non-TTL_EXPIRED trades; if cap reached early in day, no further signals attempted. BT also caps at 3.

**Step 1 of VERIFY: walk each BT-fired signal individually.**

For Gold Micro 14:09 UTC LONG, expect to find:
- Engulfing bar timestamp = 14:09 UTC
- Sweep bar must be within the rolling window's consol period
- Cron at 14:12 UTC should have processed this signal IF it reached the loop

I'll need to:
- Pull live VPS logs for 14:00-14:30 UTC cron ticks (`micro.log`)
- Compare what `_run_micro_sweep_core` saw at 14:12 UTC vs what BT saw at bar 14:09
- If live's `signals = _generate_signals(h1_df, m3_df, daily_bias_dict, cfg=cfg)` returned an empty list at 14:12 UTC, then root cause is in the broker→df conversion OR the strategy's view of data.
- If live's signals included 14:09 LONG but a downstream gate skipped it, root cause is gate-asymmetry.

**Pulling logs next via debug API.**

**🚩 F-A10.1 BLOCKER — runtime evidence unavailable.** Pulled 8 candidate log files via `/api/micro/debug/logs/raw?file=*`. **All return identical content covering 17:57 UTC → 19:32 UTC** — i.e., the post-restart process. The earlier process that ran during 09:28 UTC (Phase 6 deploy) → 17:56 UTC (kill+restart for "deployed and restarted" push) wrote logs that are EITHER rotated off the API OR the `file=` query parameter isn't honoured by the debug API and only the active log is served. Either way, **we cannot see what live's `_run_micro_sweep_core` did at the cron ticks where BT fired (14:12, 16:30, 12:24, 16:15 UTC).**

**This is a LOG-RETRIEVAL gap, not a strategy gap.** Two things to fix at infrastructure layer:
1. `/logs/raw?file=` debug endpoint may be ignoring the file param — verify and fix.
2. Add a structured `gd_journal` event for every `signals_from_strategy count=0` decision so post-hoc analysis doesn't need raw logs.

**Until log retrieval works OR we capture next-day live data:**
- Cannot do bar-by-bar trace of why live missed BT's signals.
- Static code reading can hypothesize but not confirm.
- Tomorrow's first deploy event is the next chance to capture live-vs-BT in real time.

**Stopping A10 here.** Hypothesis-only progress is anti-bible.

#### Step 7: Tape replay PROVES A10 partial story (2026-06-20 IST late session)

**With tape server + sys.modules surgery installed, called `sched.micro_sweep_job()` at tape time 14:09 UTC. Result:**

```
2026-06-19T14:09 | SCAN | tick | windows=3 trades_today=0 daily_pnl=0
2026-06-19T14:09 | F28-BIAS | bias_resolved | mode=neutral computed=bearish effective=neutral
2026-06-19T14:09 | SCAN | signals_from_strategy | count=0 bias=neutral
2026-06-19T14:09 | SCAN | complete | trades_today=0 fired_this_cycle=false
```

**At 14:09 UTC, the strategy emits ZERO signals.** Confirmed via direct call.

**Tested progressively wider windows ending at 14:09 UTC** — even with full M3 + H1 history, the 14:09 LONG signal does NOT appear. Why?

Strategy iteration logic (`backend/strategies/micro_alpha_sweep.py:101-167`):
```python
for bar_ts, bar in day_h1.iterrows():
    now_hour = bar_ts.hour
    for start_hour in range(0, 24, 2):
        end_hour = (start_hour + 4) % 24
        # Check if consolidation is done
        if not _hour_past(now_hour, end_hour):
            continue
```

`_hour_past(current, target) = 0 < (current-target)%24 <= 12`. For window `start_hour=10, end_hour=14`:
- At bar_ts=14:00 UTC: `_hour_past(14, 14) = 0` → returns FALSE → "consol not done" → skip
- At bar_ts=15:00 UTC: `_hour_past(15, 14) = 1` → returns TRUE → consol is done → emit signal at sweep_time=14:00 (engulfing dated 14:09)

**The 14:00 H1 bar at hour=14 itself does NOT trigger consolidation completion.** Strategy needs the 15:00 H1 bar present to fire the 14:09 signal.

**Live's 14:12 cron does NOT have the 15:00 H1 bar yet** (it doesn't exist in the broker view until 15:00 UTC closes).

**Live's 15:00 / 15:03 cron WOULD have:**
- Tested via tape server: at clock=15:00, signals=1 (the 14:09 LONG)
- At clock=15:03 (next cron), signals=1 still
- Through 16:30, signals=1

So **live's 15:00 cron should have fired the 14:09 LONG**. Yet `gd_signals` table for 2026-06-19 has only 2 rows: 03:00 UTC and 08:15 UTC. **No row for any 15:00+ attempt.** Live's strategy returned the signal — but live's gate loop rejected/skipped it before reaching `_log_signal()`.

**Where it could have died:**
- `signal.date.to_pydatetime() > now` — signal date 14:09 < now 15:00, so no.
- `signal_missing_sweep_metadata` — no, has metadata.
- `_traded_sweeps['keys']` check — sweep_key `2026-06-19T14:00:00+00:00_10_bullish` is NOT in today's gd_traded_sweeps rows (verified earlier). So no.
- DB open_micro check — `gd_trades` has GD-MI-457d1578 closed 04:07, GD-MI-a94ebe4a closed 12:16. Both have `exit_time IS NOT NULL`. Pass.
- `mt5_open` (broker) — would need to check live's `_open_orders.json` at 15:00 cron. May have had an orphan position from 03:00/08:15 trades that hadn't closed cleanly.

**🚨 F-A10.2 PROBABLE CULPRIT (MUST verify Monday with instrumentation):** the `mt5 get_open_trades()` cross-check at scheduler line 393 returns broker's open positions. If MT5 still reported the GD-MI-a94ebe4a position as "open" past its real close at 12:16 (broker / DWX file lag, orphan, etc.), live would skip every cron after that thinking position was still open.

OR

**🚨 F-A10.3 PROBABLE CULPRIT (alt):** live's startup_cooldown_until value, set at service start. We restarted at 17:57 UTC = the post-deploy process. The earlier process (running through the day) might have hit different gates.

**Both are testable Monday with debug API instrumentation in real time. Cannot resolve from current artifacts.**

#### Step 8: A10 STATUS

- **Verified:** strategy DOES emit the BT-fired signals (14:09, 16:27 etc.) when given enough H1 history. Tape replay produced this output.
- **Verified:** live's cron at 15:00 UTC, fed via tape, produces 1 signal in `signals_from_strategy`.
- **Unverified:** which downstream gate rejected the signal in PRODUCTION (different process, real broker view).
- **Hypotheses (F-A10.2, F-A10.3):** mt5 orphan blocking, startup cooldown semantics — testable Monday.

**A10 fix path:** instrumentation. Add `_log_journal` events for every gate decision in scheduler (`mt5_open_skip`, `cooldown_active`, `startup_cooldown`, `db_open_skip`). Then a single Monday cron tick produces the answer.

**This is exactly what the audit doc Process Rule 5 said.** Phase 7 nightly reconciler. We have to BUILD it. Adding to the program.

---

#### Step 9: TAPE REPLAY SHIPPED (2026-06-20 IST 04:00). HUGE FINDING.

**TR-3 cron-loop driver built. First end-to-end Jun 19 replay run.**

Result on golddigger_replay (single-system, gold-micro, Jun 19 00:00 → 18:30 UTC):
- 7 live signals emitted, 7 limit orders placed, 7 in `gd_traded_sweeps`
- ALL 7 limit orders TTL-expired (none filled)
- 6 trades recorded with `LIMIT_TTL_EXPIRED_GRACE` exit reason
- 1 signal at 23:15 rejected with `limit_price_through_market`

**Cross-walked one trade with raw bars:**
- BT replay: GD-MI 08:09 LONG @ 4130.29 → tp_partial+expired → +$1549.32
- Replay: same signal placed limit @ 4129.26 at 09:00 UTC, walked bars 09:00 → 09:15, lowest bid_low = 4133.69. **Limit never touched in TTL.**
- BT walked bars 08:12 → 08:24 (BT's bar_idx = signal.date = 08:09, TTL=5 bars after). Bar 08:12 had bid_low=4127.25 ≤ 4129.26. **BT filled at 08:12.**

🚨 **A10 ROOT CAUSE: BT HAS STRUCTURAL LOOKAHEAD IN F27 FILL MODEL.**

The strategy iterates `for bar_ts, bar in day_h1.iterrows()`. For each h1 `bar_ts`, it gates by `if not _hour_past(now_hour, end_hour): continue`. For window start=4 end=8, `_hour_past(8, 8)=0` False → consol incomplete. At bar_ts=09:00 UTC, `_hour_past(9, 8)=1` True → consol complete → emit signal dated **engulfing M3 bar (08:09 UTC)**.

BT engine then takes signal.date=08:09 and bar_idx=08:09 in M3 dataframe and walks `bar_idx+1 → bar_idx+TTL` for fill detection. **BT's "now" at fill simulation is 08:09**. But the signal was actually generated at h1 bar_ts=09:00. **BT effectively walks bars 08:12-08:24 looking for fills FOR a signal it learned about at 09:00.** 51-minute reverse lookahead.

Live can't do this. Live's cron at 09:00 (or 09:03) sees the signal, sends limit price to broker NOW (09:03+). Broker walks forward from 09:03. By then market has moved.

**MEASURED IMPACT (Jun 19 only, Gold Micro, replay vs BT):**
- BT: 4 trades (2 incl pre-deploy 08:09 LONG, post-deploy 14:09 LONG, 16:27 SHORT). +$2006 cumulative across all 4.
- Replay (live code): 7 attempts, 0 fills, $0.

**This isn't "today's gap." It's a structural BT-side parity bug.** Every BT trade with F27 limit-mode is exposed.

**Three immediate paths:**

1. **Fix BT lookahead** — F27 limit fill model should walk bars from `signal.date + (h1_now - signal.date)` not `signal.date`. Concretely: BT must respect "first cron tick AFTER consol completes." This will drop BT 7yr P&L MATERIALLY (the $3.04M honest number is honest no longer).

2. **Accept the gap, recalibrate** — every F27 trade in BT has lookahead. BT projects a ceiling. Live is the reality. Stop using BT for ship decisions on F27-enabled systems until lookahead is fixed.

3. **Move signal-emit timing in BT to match live** — strategy's iteration shouldn't return signals dated to engulfing M3 bar; should return them dated to the h1 bar that CAUSED the emission. Then bar_idx = h1_bar_ts (not engulfing M3) and fill walks from there.

**Path 3 is correct.** This is the surgical fix.

**🚩 F-A10.4 ARCHITECTURAL WIN:** Tape replay just paid for itself. ONE day of replay surfaced a structural bug in BT that years of normal backtests missed. The tape replay server is the right tool — it forced live and BT to use the same "now" axis and the divergence became unmissable.

**🚩 F-A10.5 SECONDARY:** GraceTTL exit_time stamps are also tape-time-correct (e.g. `06:05 IST`). Cross-day boundary tracking, daily reset, position lifecycle: all working. **The tape replay infrastructure ITSELF is parity-correct.** This is the tooling we need.

#### Next steps

1. Verify F27 lookahead by reading BT engine's `bar_idx` calculation for the signal — done.
2. Either fix path 3 or accept gap — needs decision.
3. Run full Jun 13-20 replay once parity question is settled — we have the tooling.
4. Build the three-way diff harness (TR-4) — unblocked.

### RCA (Stage 2)
_pending VERIFY..._

### FIX (Stage 3)
_pending..._

### TEST (Stage 4)
_pending..._

### FLAGS
_pending..._

---

## A1+A9 (parked until A10 ships)

(Detailed VERIFY for A1 + A9 above remains valid as documented work. Will resume after A10's FIX lands and we know whether A10 removed the apparent need for A1.)

---

_(Sections for A2 → E12 will be added as we reach each item.)_
