# Session Handoff — 2026-06-16 (Filter #27 marathon)

> **Note:** This is the **second** session handoff for 2026-06-16. The first
> (`SESSION_2026_06_16.md`) covers the morning Spire/investor-pages work. This
> doc covers the evening-into-late-night Filter #27 marathon that began with
> three slipped live trades and ended with the full live limit-order mirror.

## Theme

End-to-end Filter #27 ship: 124-cell BT sweep → ship verdict per system (3 of 4 ship) → full live limit-order infrastructure (Python + DWX EA) → adversarial review → merged + pushed to `midas-deploy`. EA recompiled on VPS but Python services NOT YET restarted at session close.

## What Happened (Chronological)

### Phase 0 — Triggering incident

Three live LONG trades fired during morning Asia / London:
- `GD-MI-5794d040` Gold Micro LONG SL'd in 37min — calc entry $4318.47, fill $4318.68 (+$0.21 slip)
- `OIL-MI-207a8552` Oil Micro LONG SL'd in 15min — calc entry $82.18, fill $82.44 (**+27 pip slip turned R:R 2.3 → 0.85**), −$663.40 loss
- `GD-AL-d0b6bbee` Gold Macro SHORT — got LUCKY: calc $4343.68, fill $4335.72 (favorable −$7.96)

User asked to investigate slippage. Background research surfaced limit orders as #1 defense.

### Phase 1 — MAX_HOLD defer fix (parallel track, also shipped)

Earlier in the morning had MAX_HOLD-spam loop on `GD-AL-88faa516` during JustMarkets nightly maintenance window (broker rejected close → minute-by-minute Telegram error storm). Built defer-with-one-time-Telegram. Deployed before Filter #27 work began. Verified clean on subsequent close (banked +$398.80, exit_reason `MAX_HOLD (deferred)`).

### Phase 2 — Bar-vs-wallclock investigation

Surfaced during MAX_HOLD work: live counts wallclock seconds for `bars_held`, BT counts dataframe bars (which auto-skip closed-market windows). Diverges across maintenance breaks / weekends. Documented as `docs/INVESTIGATION_BAR_VS_WALLCLOCK_DRIFT.md`. Open for measurement, not yet fixed.

### Phase 3 — Filter #27 BT sweep

- Designed grid: 1 baseline + 30 limit-order variants (3 TTLs × 5 levels × 2 strict/loose) per system × 4 systems = **124 BTs**.
- Variant levels: A (signal.entry), B (engulf-close), C10/C20/C30 (pullback into structure by 10/20/30% of risk).
- Strict mode: requires touch + close-beyond-limit (sustained); loose: any wick touch fills.
- TTL: 3min / 6min / 15min (1 / 2 / 5 M3 bars).
- Built `scripts/run_filter_27_limit_orders.py` runner. Ran in background ~5hrs.
- **Killed and restarted twice** mid-sweep:
  1. Original runner had no intermediate JSON saves → user requested resilience. Added atomic JSON saves after each system + per-cell append-only JSONL.
  2. After restart, displayed `fill_rate = 120%` on baseline due to alpha_sweep-only `total_signals` denominator vs `n` numerator that included mean_rev + cross_market trades. Added `filled_signals` counter scoped strictly to alpha_sweep. Real numbers were unaffected (PF, P&L, missed all alpha_sweep-scoped already).

Final results:
- Oil Macro: best `ttl15_B_loose` +$180k (+22%), PF 4.70 → 5.43
- Oil Micro: best `ttl15_C10_loose` +$534k (+17%), PF 5.76 → 7.56
- Gold Micro: best `ttl15_C10_loose` +$28k (+8%), PF 4.52 → 5.35
- Gold Macro: best `ttl15_C10_loose` +$18k (+4%), PF 3.53 → 3.85

### Phase 4 — Yearly-slice gate (per [[feedback-replay-vs-real-backtest]])

Sliced 21yr backtest by year for each system's winning variant. Acceptance gate: ≥80% up-years, loss/gain ratio under ~25%, no recent regime tilt.

| System | Up | Loss/Gain | Recent | Verdict |
|---|---|---|---|---|
| Oil Macro | 18/21 | 2.2% | clean | ✅ |
| Oil Micro | 18/21 | 6.8% | clean | ✅ |
| Gold Micro | 15/21 | 18% | clean | ✅ |
| Gold Macro | **12/21** | **45%** | **5 of last 7 RED** | 🟡 STASH |

Yearly slice rejected Gold Macro despite +$18k aggregate. **This is exactly why we run yearly slices.**

### Phase 5 — Slippage attribution logging

Independent of Filter #27 but useful regardless. Bumped `_log` precision from millisecond to microsecond in all 4 services. Added bid/ask snapshots at `place_market_order_start` and `place_market_order_filled` so future slippage events can be decomposed:
- `(calc_entry) - (snap_send_bid/ask)` = strategy calc error
- `(snap_fill) - (snap_send)` = market move during roundtrip
- `(fill_price) - (snap_fill)` = spread cost / fill noise

### Phase 6 — BT defaults ship per system

Updated `backend-oil/config.py`, `backend-micro/config.py`, `backend-oil-micro/config.py` with the winning kwargs as new defaults. Verified each system: `run_backtest()` with NO kwargs reproduces the variant cell to-the-cent ($1,006,056.76 / $390,097.43 / $3,711,942.04 — all exact).

### Phase 7 — Live mirror Phase 1

Extracted `compute_limit_price` to `backend/execution/limit_price.py` — single source of truth. Both BT engines AND live engines import this. Live↔BT parity guaranteed by construction.

15 unit tests in `tests/test_limit_price.py` cover all 5 variants × both directions + error cases + 4 explicit BT-engine-inline parity probes. All pass.

All 4 BT engines refactored to call the helper. Re-ran baseline-equivalence on all 4 systems post-refactor: identical to-the-cent.

`mt5_executor.place_limit_order()` and `cancel_pending_order()` added. Same shape as `place_market_order` plus DWX command `OPEN_PENDING|sym|TYPE|vol|price|sl|tp|ttl_secs|comment` and `CANCEL_PENDING|ticket`. With slippage attribution snapshots.

`notify.limit_placed()` + `notify.limit_ttl_expired()` Telegram messages.

### Phase 8 — Live mirror Phase 2 (DWX EA)

Bumped EA version 2.00 → 2.10. Description and OnInit Print updated to identify post-recompile.

Added:
- `ExecuteOpenPending`: `TRADE_ACTION_PENDING` + `ORDER_TYPE_BUY_LIMIT`/`SELL_LIMIT` + `ORDER_TIME_SPECIFIED` expiration. Broker auto-cancels at TTL.
- `ExecuteCancelPending`: `TRADE_ACTION_REMOVE`. Idempotent harmless cases (already filled/cancelled/expired) just log retcode.
- `WritePendingOrders()`: iterates `OrdersTotal()` (vs `WriteOpenOrders`'s `PositionsTotal()`) filtered to InpMagic. Writes `pending_orders.json`. Logs only on count CHANGE (transition log) to avoid 25ms-tick spam.
- `OnTradeTransaction` branch for `TRADE_TRANSACTION_ORDER_DELETE` with `ORDER_STATE_CANCELED` or `ORDER_STATE_EXPIRED` → appends to `cancelled_orders.json` (separate from `closed_orders.json` which only handles position exits).

### Phase 9 — Live mirror Phase 3a (dry-run scaffolding)

Three live engines (Gold Macro NOT touched — config didn't ship Filter #27): added `cfg_entry_mode == "limit"` branch BEFORE `place_market_order` call. Computes intended limit, logs `limit_intent_computed`, journals `LIMIT_DRY_RUN_INTENT`, then falls through to existing market path.

Default `LIMIT_DRY_RUN=true` env var so accidental flag-flip without Phase 3b code present is loud (logs WARN, falls through safely).

### Phase 10 — Live mirror Phase 3b (real path + monitor)

When `LIMIT_DRY_RUN=false`:
- Real `place_limit_order` call → broker pending ticket
- INSERT `gd_trades` row with `mode='pending'`, `entry_time=NOW()` (placement time, not fill), `entry_price=intended_limit`, `oanda_trade_id=ticket`
- Journal `LIMIT_PLACED`, Telegram `notify.limit_placed`
- Return `trade_ref` (skip market path)

`pending_order_monitor()` reconciler in each live_engine:
- Reads `pending_orders.json`, `open_orders.json`, `cancelled_orders.json` from DWX dir
- For each `mode='pending'` DB row:
  - in pending file → no-op
  - in open file → flip `mode='live'`, update `entry_price` to actual broker fill, journal `LIMIT_FILLED`, `notify.trade_filled`
  - in cancelled file → set `exit_time=NOW()`, `exit_reason='LIMIT_TTL_EXPIRED'`, journal `LIMIT_TTL_EXPIRED`, `notify.limit_ttl_expired`
  - in NONE → orphan (file race / missed write); leave row, retry next 30s tick

`pending_order_monitor_job` registered in each scheduler.py as APScheduler interval, every 30s.

### Phase 11 — Defensive filter audit

Every query that iterates open trades got `COALESCE(mode, 'live') != 'pending'`. Found 5 reconciler queries per limit-shipped system (15 total) plus Gold Macro's daily-recon count. **Critical missed by adversarial review:** `price_stream._on_tick` runs on every broker tick (10-100x/sec) and would have iterated pending rows for SL/TP/BE detection on a not-yet-filled limit price. Caught in commit `6e5a224`.

One-at-a-time guards intentionally KEEP pending rows so a placed limit blocks new signals. Daily trade count includes pending so an expired-unfilled limit still counts toward `max_trades_per_day` (preserves "don't keep retrying same setup" intent).

### Phase 12 — Adversarial review + parity probe

User asked for full code coverage check. Verified:
- All 4 service cold-start imports work
- 23 unit tests pass
- One-at-a-time guards correctly count pending rows
- All 4 mode values (paper/NULL/live/pending) handled correctly by COALESCE pattern
- `lot_size` formula consistent (Gold /100, Oil /1000)
- Helper edge cases: NaN propagates, zero-risk passes through, errors raise on unknown args

Built `scripts/check_filter_27_live_bt_parity.py` — cron-friendly probe that asserts the helper produces correct outputs on 4 representative cases. Passes.

### Phase 13 — Merge + push

Reviewed 19 commits ahead of `midas-deploy` (0 behind, clean fast-forward). Switched to `midas-deploy`, fast-forward merge, pushed. Then noticed I should bump EA version + add count-change log to `WritePendingOrders` for observability. Made those changes, committed `60a995c`, pushed.

### Phase 14 — VPS deploy (partial)

User stopped Python services (`taskkill /F /IM python.exe`), deployed EA changes:
- Copied `DWX_Server.mq5` from repo to MT5 Experts folder
- Recompiled in MetaEditor (F7)
- Reattached EA to chart
- **Verified** in MT5 Experts tab: `[DWX] Server started v2.10 (Filter #27). ... Commands: OPEN, OPEN_PENDING, CANCEL_PENDING, MODIFY, CLOSE, CLOSE_PARTIAL, CLOSE_ALL`

But session ended before user did `git pull` on VPS + restart Python services. Health-API check confirmed: live `oil_pending_order_monitor` job NOT yet in scheduler list — Python still on old code.

## What's Live

| | |
|---|---|
| Branch | `midas-deploy` at `60a995c` (PUSHED to origin) |
| Filter branch | `filter/27-limit-order-sweep` (also pushed) |
| VPS DWX EA | v2.10 ✅ confirmed loaded 18:52 UTC |
| VPS Python services | OLD code (still on `375c85c` or earlier) — pending git pull + restart |
| `LIMIT_DRY_RUN` env var | Default `true` (no live behavior change until per-system flip) |

## Commits This Session

(reverse chrono — newest first)

| SHA | Description |
|---|---|
| `60a995c` | filter-27: EA observability — version bump + count-change log |
| `07c606b` | filter-27: cron-friendly parity probe script |
| `6e5a224` | filter-27 phase 3b: defensive filter for missed reconciler queries (price_stream × 3 + Gold Macro daily-recon) |
| `dffbfcd` | filter-27 doc: phase 3b status update |
| `0a98382` | filter-27 phase 3b: real-limit + pending-monitor (gold-micro + oil-micro) |
| `17d7a69` | filter-27 phase 3b: real-limit + pending-monitor (oil macro) |
| `b998a43` | filter-27 phase 3b: defensive `mode!='pending'` filter (oil macro reconciler queries) |
| `5f4667d` | filter-27 live phase 3a: dry-run scaffolding (3 engines) |
| `fcfa8e9` | filter-27 live phase 2: DWX EA pending-order primitives |
| `f974690` | filter-27 live phase 1: helper extract + executor primitives + notify |
| `bb7c95b` | filter-27 doc: live mirror design (§11.4) |
| `ed025fc` | Gold Micro: ship Filter #27 BT defaults (ttl15_C10_loose) |
| `4fad436` | Oil Micro: ship Filter #27 BT defaults (ttl15_C10_loose) |
| `4796ec9` | Oil Macro: ship Filter #27 BT defaults (ttl15_B_loose) |
| `33eafab` | Slippage attribution logging — μs precision + bid/ask snapshots |
| `0fba4e0` | filter-27 doc: yearly slices for all 4 systems + ship verdict |
| `e93df57` | filter-27: research documentation |
| `1049eda` | filter-27: fix fill_rate >100% (alpha_sweep scope) |
| `eeaabb3` | filter-27: intermediate JSON saves + run metadata |
| `e15586b` | filter-27: limit-order entry sim (BT-only, 124-cell sweep) |
| `8c6867b` | Postmortem: GD-MI-5794d040 |
| `375c85c` | Open investigation: bar-vs-wallclock drift in MAX_HOLD |
| `a7d2af3` | Defer MAX_HOLD on broker market-closed instead of erroring |

## Outstanding Issues

### CRITICAL
**None.** Code is all gated behind `LIMIT_DRY_RUN=true`. Worst case if VPS auto-restarts before user pulls: Python still runs old code, no behavior change.

### HIGH
1. **VPS Python services need pull + restart.** EA already at v2.10. Without Python restart, dry-run intent logging won't happen.

### MEDIUM
2. **Per-system flip plan post-restart.** Oil Macro first → 5+ trades → Gold Micro → 5+ trades → Oil Micro. Each is `LIMIT_DRY_RUN=false` env var on that one service + restart that one service.
3. **Bar-vs-wallclock investigation** (`docs/INVESTIGATION_BAR_VS_WALLCLOCK_DRIFT.md`). Untouched.

### LOW
4. **Backfill 4 zombie P&L** values from JustMarkets statement (NULL in DB from earlier orphan-reconciler incident).
5. **Calibration plan** (`docs/CALIBRATION_PLAN.md`) — wait for ≥30 clean live trades. Filter #27 dry-run is the upstream feeder.
6. **Filter #28 candidate**: skip 08:00-08:14 UTC entries (slippage-defense playbook tactic #3 / latency-window). Don't run until #27 fully shipped to live.

## Decisions Made

1. **Yearly-slice gate is non-negotiable.** Aggregate +$18k on Gold Macro looked fine; recent-regime check (5/7 red) saved us. Will continue using yearly slice on every future filter.
2. **3 of 4 systems ship.** Stashed Gold Macro. Lost $18k of theoretical aggregate (~2.4%) for safety. Worth it.
3. **Limit-order helper is a single source of truth.** `compute_limit_price` lives in one file, called by both BT and live. Live↔BT parity guaranteed by construction (modulo the engulf_close ask/bid tick-vs-bar-close drift on variant B, which is documented).
4. **`LIMIT_DRY_RUN=true` is the default.** Operator must explicitly opt in per service. Per-system staged rollout. Even after deploy, no real-money behavior change without manual flip.
5. **Don't run live-replay parity harness now.** Helper-level parity is unit-tested. Live behavior is gated by dry-run env var. The dry-run mode IS the parity test (24h of `LIMIT_DRY_RUN_INTENT` events vs actual market fills).
6. **One-day marathon, not split.** User explicit: "we have all the time", "no rushing", "no fake fills no phantom numbers", concern about context drop on session resume for Phase 3b's interconnected pieces.
7. **Strict-mode variants are POISON across all 4 systems.** Bottom-3 of every system's ranking. Don't ship strict mode in any future filter.

## What's Next

1. On VPS:
   ```powershell
   cd C:\hand-of-midas
   git pull  # fast-forward to 60a995c
   taskkill /F /IM python.exe
   Get-Process python -ErrorAction SilentlyContinue  # confirm clean
   .\start-win.bat
   ```
2. Verify Filter #27 loaded in Python via debug API:
   ```powershell
   curl https://midas.subashtrades.in/api/oil/debug/health | ConvertFrom-Json | Select -ExpandProperty scheduler_jobs
   ```
   Should show `oil_pending_order_monitor`.
3. Watch for first `LIMIT_DRY_RUN_INTENT` journal event on next signal.
4. After 24-48h of dry-run data, per-system flip starting with Oil Macro.

## File Inventory

### NEW

| Path | Purpose |
|---|---|
| `backend/execution/limit_price.py` | Single source of truth `compute_limit_price` helper |
| `tests/test_limit_price.py` | 15 unit tests for the helper |
| `tests/test_fill_model_limit.py` | 8 unit tests for limit-fill semantics |
| `scripts/run_filter_27_limit_orders.py` | 124-cell BT sweep runner |
| `scripts/check_filter_27_live_bt_parity.py` | Cron-friendly parity probe |
| `docs/FILTER_27_LIMIT_ORDER_RESEARCH.md` | 727-line research doc |
| `docs/INVESTIGATION_BAR_VS_WALLCLOCK_DRIFT.md` | Open investigation |
| `scripts/output/filter_27_results.json` | Sweep grid output |
| `scripts/output/filter_27_results.jsonl` | Per-cell append-only log |

### MODIFIED

- All 4 BT engines (`backend{,-micro,-oil,-oil-micro}/backtest/engine.py`) — kwargs, helper call, BacktestResult extension
- 3 live engines (`backend-{oil,micro,oil-micro}/scanner/live_engine.py`) — limit branch + pending_order_monitor
- 3 schedulers (`backend-{oil,micro,oil-micro}/scanner/scheduler.py`) — pending_order_monitor_job + import
- 3 price streams (`backend-{oil,micro,oil-micro}/scanner/price_stream.py`) — `mode!='pending'` filter
- 4 `_log.py` copies — μs precision
- 3 `config.py` (Oil Macro, Oil Micro, Gold Micro) — Filter #27 BT defaults shipped
- `backend/execution/mt5_executor.py` — place_limit_order, cancel_pending_order, bid/ask snapshots
- `backend/execution/__init__.py` — export new primitives, OANDA fallbacks
- `backend/execution/fill_model.py` + `backend-oil/execution/fill_model.py` — limit-order pre-walk + extended TradeResult
- `backend/notify.py` — limit_placed, limit_ttl_expired
- `backend/scanner/scheduler.py` — `mode!='pending'` filter on daily-recon count
- `mql5/DWX_Server.mq5` — v2.10 with OPEN_PENDING/CANCEL_PENDING/WritePendingOrders/OnTradeTransaction branch

## Numbers to Remember

| Metric | Value |
|---|---|
| BT cells run | 124 (31 variants × 4 systems) |
| Sweep wall-clock | 4h 19min (15,537 sec) |
| Cumulative ΔP&L if all 4 ship | +$760,778 / 21yr |
| Cumulative ΔP&L 3-of-4 (Gold Macro stash) | **+$742,778 / 21yr** = +$35,371/yr |
| Oil Macro best | `ttl15_B_loose`, +$180k (+22%), PF 4.70→5.43 |
| Oil Micro best | `ttl15_C10_loose`, +$534k (+17%), PF 5.76→7.56 |
| Gold Micro best | `ttl15_C10_loose`, +$28k (+8%), PF 4.52→5.35 |
| Gold Macro stash reason | 12/21 up years, 5/7 recent red, 45% loss/gain ratio |
| Oil Micro yearly slice | 18/21 up, $-39k drag vs $+573k benefit (6.8% ratio) |
| Unit tests passing | 23/23 (15 limit_price + 8 fill_model_limit) |
| EA version | 2.00 → **2.10** |
| Dry-run env var | `LIMIT_DRY_RUN=true` (default ON) |
| Filter #27 commit count this session | 23 |
| Branch tip | `60a995c` on `origin/midas-deploy` |

## What I'd Do If I Had 1 More Hour

1. **Push the VPS deploy myself if I had access** — pull + restart Python is mechanical. Verify health endpoints show `pending_order_monitor` jobs. Watch for first `LIMIT_DRY_RUN_INTENT` event.
2. **Build the dry-run analysis script** that joins `LIMIT_DRY_RUN_INTENT` events to actual market fills and computes "would have filled %" from real production data. Drop-in replacement for the deferred parity harness.
3. **Symlink setup** in `mql5/DWX_Server.mq5` between repo and MT5 Experts folder so future EA changes are git-pull + recompile without the manual copy step.

## Reference

- Research doc: `docs/FILTER_27_LIMIT_ORDER_RESEARCH.md`
- Investigation doc: `docs/INVESTIGATION_BAR_VS_WALLCLOCK_DRIFT.md`
- BT sweep runner: `scripts/run_filter_27_limit_orders.py`
- Parity probe: `scripts/check_filter_27_live_bt_parity.py`
- Sweep JSON: `scripts/output/filter_27_results.json`
- Memory entries: `~/.claude/.../memory/project_filter_27_limit_orders.md`, `project_dwx_ea_pending_orders.md`, `feedback_user_explicit_opt_in.md`, `session_2026_06_16_filter_27.md`, `next_session_tasks.md`

---

# Session Addendum (post-wrap deploy actions)

After the original handoff was written and committed (`7e96432`), the user
deployed Filter #27 to the VPS and progressed through the dry-run → real-limit
flip in this session. No new code commits — these are deploy-side actions.

## Deploy timeline (post-wrap)

1. **18:46 UTC** — User killed all python.exe on VPS (`taskkill /F /IM python.exe`).
2. **18:50 UTC** — User opened MetaEditor on VPS, recompiled `DWX_Server.mq5` (F7), reattached EA to chart.
3. **18:52 UTC** — MT5 Experts tab confirmed: `[DWX] Server started v2.10 (Filter #27). Symbols: XAUUSD.ecn,BRENT.ecn | Folder: DWX | Magic: 200000 | Commands: OPEN, OPEN_PENDING, CANCEL_PENDING, MODIFY, CLOSE, CLOSE_PARTIAL, CLOSE_ALL`. EA-side ready.
4. **~19:00 UTC** — User pulled `60a995c` on VPS, ran `start-win.bat`. All 4 services back up. Health-API check confirmed `*_pending_order_monitor` jobs registered on the 3 limit-shipped systems. Filter #27 fully loaded — but `LIMIT_DRY_RUN` defaulted to `true` (env var unset).
5. **19:18 UTC** — Gold Macro live signal fired: `GD-AL-2025e3d2` SHORT 55u @ $4333.26, SL $4343.21, TP $4308.94. **Market order path** (correct — Gold Macro stashed Filter #27). Slippage attribution log confirmed working: `snap_bid=4333.26 snap_ask=4333.36` at order_send, fill at $4333.26 = **zero slip** on this fire. μs-precision timestamps verified live.
6. **~20:30 UTC** — Trade GD-AL-2025e3d2 went floating-negative as price retraced from $4326 → $4337 (~$11 against). Position still within risk envelope ($6.16 / $9.95 SL distance = 38% consumed). No BE arming because price never touched the 35%-to-TP level ($4321.10).
7. **20:40 UTC** — User asked to flip Filter #27 to real-limit mode. Initial misstep: I started a code-change to flip the default from `"true"` to `"false"` in 3 live engines. User correctly objected — "is it not just one env change?" — code reverted, no commits, zero diff.
8. **~20:50 UTC** — Verified `.env` loading mechanism: each `config.py` calls `load_dotenv(<repo>/.env)` at import. So adding to `.env` is the canonical path (persistent, survives restart, no Windows-registry env-var management).
9. **~20:55 UTC** — Read existing `C:\hand-of-midas\.env` via debug API, appended `LIMIT_DRY_RUN=false` via `Add-Content`, verified file contents.
10. **~21:00 UTC** — Killed all 4 python services via debug API (gold endpoint dies along with them — expected). User ran `start-win.bat` on VPS to restart.
11. **~21:05 UTC** — All 4 services back up. In-process verification confirmed `LIMIT_DRY_RUN='false'` loaded in oil / micro / oil-micro Python processes. `pending_order_monitor` jobs all registered post-restart.

## Post-deploy state (live as of session close)

```
EA              v2.10                                  ✅ verified
.env            LIMIT_DRY_RUN=false (persistent)       ✅ on VPS disk
Python services 4/4 up (fresh PIDs ~21:05 UTC)         ✅
In-process env  LIMIT_DRY_RUN='false' on 3 limit svcs  ✅ verified
pending_order_monitor jobs registered                  ✅ all 3
Real-limit path active on next signal                  ✅ next Oil/Gold-Micro/Oil-Micro signal
Gold Macro path                                        ✅ market (stash respected)
```

## Open trades at session close

`GD-AL-2025e3d2` Gold Macro SHORT 55u @ $4333.26 — **floating loss ~$200**, runner active. Market order, not Filter #27. Filter #5 BE will arm if price drops to $4321.10. SL at $4343.21 = max −$547 if hit.

## Iteration learnings (not in original handoff)

### Lesson — env var, not config flag, for dry-run gate

User pushed back twice on dry-run gating decisions:
- First, on whether config.py should host the dry-run flag (it does NOT; flag is env-var only). Decision: keep env-var-only because per-process flippable without code change, defaults safely to dry-run.
- Second, on whether to change the default in code from `"true"` to `"false"`. Wrong move — should have just edited `.env`. User caught it; code was reverted before commit.

**Correct path for env-driven defaults:** when user wants to flip behavior, edit `.env`, restart services. **Never** change code to flip a default value when an env var already does the job.

### Lesson — debug API can self-suicide

When killing python.exe via debug API on the gold service, the same gold process stops responding (expected). User must restart from VPS terminal directly. Workflow: use debug API for `taskkill`, then `start-win.bat` from VPS console.

### Lesson — `.env` is gitignored, machine-local

`.env` lives at `<repo-root>/.env`, loaded by every config.py via `load_dotenv()`. **Not committed.** Each environment (Mac dev, VPS prod) has its own. Edits made on VPS don't propagate to repo and vice versa. Audit trail is via `git log` of code that READS env vars + the deploy logs of when each service restarted.

## Outstanding (post-wrap, additional to original)

| Priority | Item |
|---|---|
| HIGH | First Oil Macro / Gold Micro / Oil Micro signal post-deploy will be a REAL limit order. Watch for `📋 LIMIT PLACED` Telegram. If it doesn't fire (or `LIMIT_ORDER_FAILED` journal event fires), triage immediately — likely DWX EA `OPEN_PENDING` parsing or broker rejection. |
| HIGH | Watch `GD-AL-2025e3d2` runner — currently floating −$200, SL $6 above current. If SL fires that's −$547 day damage. |
| MEDIUM | Verify lifecycle-pair Telegram messages after first real limit fires: `📋 LIMIT PLACED` → either `✅ TRADE FILLED` or `⏱ LIMIT EXPIRED`. Critical sanity check on 30s monitor + EA cancelled_orders.json wiring. |
| MEDIUM | After first 3-5 real limit lifecycles, query `gd_journal` for `LIMIT_FILLED` events and compare `intended_limit` vs `actual_fill` field — proves live↔BT helper parity in production. |
| LOW | All other items from original handoff carried forward (zombie P&L backfill, calibration plan trigger, bar-vs-wallclock investigation, Filter #28 candidate). |

## Resume hint addendum

🦣 **Filter #27 is now REAL on 3 systems. Default-OFF dry-run via `.env`. Next limit-shipped signal = real broker pending order.** Expected first-fire targets per scan-window timing: Oil Macro / Gold Micro any time during 08-19 UTC (London/NY); Oil Micro rolling 24/7 except 21-22 UTC maintenance.
