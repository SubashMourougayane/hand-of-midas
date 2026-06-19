# Session Handoff — 2026-06-19 (Part 2, Evening IST)

> First session-handoff (`SESSION_2026-06-19.md`) covered Phase 4-5-6 unification and morning Macro retirement. **This Part 2 covers everything from afternoon onward: the GD-MI-a94ebe4a postmortem, Phase 7 reconciler, Macro UI strip, General service, numpy live save, production audit, UI mismatch audit, parity audit, replay proposal, docs restructure, and the smoking gun (sweep-blacklist no-rollback).**

## Theme

A 14-hour deploy + audit + remediation marathon. Phase 6 unified code shipped. Smoke harness passed 100% byte-parity. Production live fired 0 trades vs BT's 4 in the post-deploy window. **Discovered that "smoke parity" ≠ "production parity"** — the harness can't see DB state pollution. Mapped 24 divergence axes and proposed a tape-replay server as the long-term fix.

---

## What Happened (Chronological)

### Block 1 — First post-deploy trade postmortem
- GD-MI-a94ebe4a closed: F27 limit fill +56s, Filter #5 BE armed, Filter #7 partial banked $194, runner MAX_HOLD'd at +$90. Total **+$284 net**.
- Discovered postmortem.py only reads final `pnl_usd` from `gd_trades` — Partial-TP $194 lives in journal but not in trade card. Latent ergonomic issue.
- First clean signal-→-fill-→-exit chain post-Phase-6 deploy.

### Block 2 — BT Parity Replay infrastructure
- Built `scripts/bt_replay.py` — per-trade replay block. For each closed live trade, runs system's BT on a ±15 day slice, finds matching same-direction signal within ±12 min, surfaces fired/not-fired + entry/exit/PnL.
- Wired into `scripts/postmortem.py` — auto-runs replay, renders block before journal events.
- Skill SKILL.md updated with 8th placeholder (`bt_replay_judgment`).
- Smoke tested 3 trades: 1 ⏳ DATA NOT YET AVAILABLE (today's, JM data not synced), 2 ❌ NO match (pre-Phase-6 drift, expected baseline).

### Block 3 — Phase 7 reconciler
- Built `scripts/reconcile_post_deploy.py`. Pulls last N closed trades, replays each, surfaces aggregate match-rate + capture %.
- First baseline run: 0/28 matched, 28 drift_no_match, 3 data_too_old, 10 limit_unfilled. **Exactly the gap that justified Phase 6.**

### Block 4 — Macro retirement everywhere
- start-win.bat: Gold:5053 + Oil:5054 spawns commented out (`[1/3]` instead of `[5/5]`).
- Frontend stripped Macros from: SystemSwitcher, TopBar, home page, settings, backtest, live (Sweep Proximity branch dead), TradeJourney, deck, playbook, robustness, report, trades comments, uikit Badge gallery.
- VPS PIDs killed via Micro debug API (avoid self-destruct rule).
- All endpoints verified: `/api/gold/state` → 502, `/api/oil/state` → 502; `/api/micro/state` + `/api/oil-micro/state` → 200.

### Block 5 — General service (port 5050)
- After Macro retire, `/api/auth/login` broke (was on Gold Macro 5053). Built `backend-general/main.py` to host auth + aggregate-debug + health.
- Caddyfile updated (via debug API): `/api/auth/* → :5050`, `/api/health → :5050`, `/api/debug/* → :5050`.
- Caddy reload via `& C:\caddy\caddy.exe reload`. Verified all endpoints work.

### Block 6 — CRITICAL numpy save
- 17:09 UTC: live SHORT order placed @ $4166.06 (ticket 2067274584). DB INSERT failed silently with `psycopg2.errors.InvalidSchemaName: schema "np" does not exist`.
- Root cause: numpy 2.x changed `repr(np.float64(x))` from `"4166.06"` to `"np.float64(4166.06)"`. psycopg2 has no built-in adapter for numpy types → fell back to `str()` → leaked into SQL.
- Trade SAVED by orphan-cancel reconciler within 13 seconds. **No money lost.**
- Shipped `dd044a3` — psycopg2 adapter for `np.float64/float32/int64/int32/bool_` in `backend/db.py` (registered at module import time). Plus `compute_limit_price` returns native `float()` defensively.
- 10 regression tests in `tests/test_psycopg2_numpy_adapter.py` — all pass.

### Block 7 — Production risk audit (17 findings, 4-stage framework)
- 3 parallel agents + manual code verification.
- **Verified real & shipped:**
  - C3: `exit_reason` + `event_type` VARCHAR(30) → VARCHAR(50) (was actively truncating `LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED` 36-char and `LIMIT_COMPUTE_FAILED_FELL_BACK_TO_MARKET` 40-char). Same class as Jun 10 orphan cascade. Migration applied live + `schema.sql` updated.
  - C2: `price_stream._log_journal` raw `json.dumps` → `safe_json_dumps`. Defense for the dormant OANDA price-stream path.
  - M3: EA `WriteSymbolBars` partial-bar warn (diagnostic).
- **REJECTED by VERIFY (audit was wrong):**
  - C1: APScheduler `max_instances=1` — already default.
  - C4: cross-process MT5 lock — H2 commit (Jun 17) already solved via per-cmd response files.
  - H3: `gd_journal` index — already on prod DB; schema synced.
- **Key learning:** 3/6 audit findings were false alarms. Framework's VERIFY stage saved unnecessary code changes.

### Block 8 — Active GD-MI-60f3aa09 trade analysis (verified clean post-numpy-fix)
- Confirmed Macros silent (15 ticks of `macro_scan_disabled_phase6` per cron).
- Today's 3 live trades fired BEFORE Phase 6 deploy (08:30/10:30/13:45 IST; deploy at 14:58 IST).

### Block 9 — UI/data mismatch audit (Playwright)
- Walked 16 pages, captured screenshots, cross-checked rendered values vs DB ground truth.
- 9 findings; 4 CRITICAL frontend bugs blocking proposed DB wipe:
  - M1: `/trades` showed identical data on both Micros (BT runs were combined-strategy)
  - M2: `/backtest` same — Oil tab showed Gold prices ($1645 not $40-90)
  - M3: `/journal` showed "0 of last 100" despite 224k DB rows (Oil Micro missing `/journal/events` route → 404)
  - M4: `/settings` hardcoded for OANDA + retired Mean-Rev/Cross-Market era
- Stage A shipped: M1+M2+M3 all fixed. SQL queries use `strategies = %s` (exact equality not `@>`), Oil Micro `/journal/events` route added, frontend journal accepts bare-list response, Gold Micro BT default cleaned to `["micro_alpha_sweep"]` only.
- Verified live: Oil Micro journal now shows 100 events; backtest shows real Oil prices.
- "20 years" stale messaging corrected to "7 years" (real JM CSV range).

### Block 10 — Live signal investigation
- Subash asked "why no trade?" — investigated.
- 15 sweeps consumed today, 3 became live trades, 12 marked-but-no-trade.
- Initial false claim: "live missed BT signals" attributed to "live more aggressive."
- User pushed back. Re-checked when Phase 6 deployed: 14:58 IST (`micro.20260619-1529.log` start time = 09:28 UTC).
- All 3 live trades fired BEFORE deploy → comparing to current-code BT was apples-to-oranges.
- Re-ran smoke harness on today's window: PASSED 100% byte-parity (5/5 BT trades match 5/5 live `dry_run` trades).

### Block 11 — SMOKING GUN found
- Smoke passes BUT live did 0 trades vs BT's 4 in production. How?
- Root cause: `backend-micro/scanner/scheduler.py:424` marks sweep consumed BEFORE `execute_signal()`. When engine cleanly returns `None` (`limit_price_through_market` etc.), `_daily_state["trades"]` is rolled back at line 457 but `_traded_sweeps["keys"]` and `gd_traded_sweeps` row are NOT. Sweep permanently blacklisted.
- BT only marks on `execute_trade()` SUCCESS. Pre-deploy live polluted DB with 12 marked-without-trade sweeps. Post-deploy live respects DB → blocks signals BT walks fresh.
- **The smoke harness mocks `is_sweep_consumed = lambda: False` so it can't see DB pollution.**

### Block 12 — Comprehensive parity audit
- 3 parallel agents (state-axis, harness-coverage-gap, execution-layer) → **24 divergence axes mapped**.
- Categorized: 4 P0 / 11 P1 / 9 P2.
- Smoke harness covers 6/24 — 18 are silent blind spots.
- 7 new test specs written.
- 5 standing process rules added.
- Doc: `docs/parity/PARITY_AUDIT_2026-06-19.md` (436 lines).

### Block 13 — Tape replay server proposal
- Subash's idea: feed 7yr historical OHLC into actual production live code via stub broker. Compare to BT trade list.
- Wrote up at `docs/parity/REPLAY_SERVER_PROPOSAL.md`: 3-layer design, "What's RIGHT" + 6 caveats, cost estimate, recommended order (ship A1+A2+stateful-BT-mode FIRST).

### Block 14 — Docs restructure
- 100 .md files at `docs/` top → 10 categorized subfolders (audits/bugs/filters/parity/research/postmortems/sessions/ops/architecture/proposals).
- Top level kept only: PROJECT_STATUS, PLAN, TODO, README.
- `docs/README.md` is new entry-point index.
- 31 memory files updated to new paths via bulk script.

---

## What's Live

**VPS state (commit `fc5b70e` after pull, but VPS still on `d95d135` — Stage A part 3 + restructure not yet pulled):**
- General service 5050: ✅ auth, debug aggregator, health
- Gold Micro 5055: ✅ scanning, 0 positions
- Oil Micro 5056: ✅ scanning, 0 positions
- Frontend 3001: ✅ rebuilt at last restart, serving Macros-stripped UI
- Macros 5053+5054: 🪦 dead (start-win.bat doesn't spawn them)
- Caddyfile: routes auth/debug/health → 5050
- DWX EA: not recompiled today (M3 partial-bar warn pending)

**Account:**
- NAV: $8,637.13 ($8,353 starting + $284 from a94ebe4a)
- Open positions: 0
- Open broker pending orders: 0

**Branch + commit:** `midas-deploy` at `fc5b70e` (latest). Local commits not pushed: this session-handoff plus restructure (`fc5b70e`) — already pushed earlier.

---

## Commits This Session (Part 2)

| SHA | Description |
|---|---|
| `97ef447` | Postmortem: GD-MI-a94ebe4a — Clean win F27+F5+F7 chain (+$284) |
| `8d6ed3e` | BT Parity Replay block + skill placeholder |
| `63833f9` | Phase 7: post-deploy reconciler + first baseline report |
| `8246d08` | Retire Macros from start-win.bat + frontend toggle |
| `8f46cb7` | General service (port 5050) for auth + aggregate debug |
| `dd044a3` | CRITICAL fix: numpy → psycopg2 adapter (live INSERT save) |
| `00beed3` | Strip Macros from methodology pages (deck, playbook, etc.) |
| `b0247d8` | Audit doc: 17 production-risk findings |
| `d76d472` | C3: VARCHAR(30) → VARCHAR(50) for exit_reason + event_type |
| `c4e5a7d` | C2: price_stream raw json.dumps → safe_json_dumps |
| `71a91f3` | M3 + H3: EA partial-bar warn + schema sync; mark C1+C4+H3 false alarms |
| `f0f61a7` | UI/data mismatch audit doc + screenshots |
| `3219bc0` | Stage A: M1+M2+M3 trades/backtest sys filter + journal endpoint |
| `880c8fe` | M3 part 2: journal frontend accepts bare-list |
| `55cfdc4` | M3 part 3: drop retired mean_rev + cross_market from BT defaults |
| `d95d135` | Fix '20 years' messaging — actual range is 7 years |
| `f10aca4` | Parity audit: 24 live↔BT divergence axes |
| `fc5b70e` | Docs restructure + tape replay proposal + parity audit indexed |

---

## Outstanding Issues

### CRITICAL (do first thing tomorrow)
1. **A1 fix** — sweep blacklist not rolled back on clean signal rejection. ~30 min via 4-stage framework. Add `_traded_sweeps.discard()` + `unmark_sweep_consumed()` in the `else: # signal not taken` branch.
2. **A2 fix** — F27 limit-TTL expiry doesn't roll back blacklist. Same pattern when `pending_order_monitor` cancels. ~30 min.
3. **Stateful parity test** — pre-pollute `gd_traded_sweeps` then run BT vs live. Asserts behaviour matches AFTER A1+A2 fix. Catches today's bug for the future. ~1hr.

### HIGH
4. **A5 fix** — cooldown reconstruction on live restart (extend `_restore_traded_sweeps_on_startup`).
5. **Replay-from-DB-state mode** in BT engine — load `gd_traded_sweeps`/`gd_signals`/`gd_dd_state` at snapshot, run BT from there. ~3hr. Catches A1, A5, A6.
6. **GD-MI-a94ebe4a postmortem update** — re-run `python scripts/postmortem.py GD-MI-a94ebe4a` once JM data covers `2026-06-19 ≥ 10:16 UTC`. The bt_replay_judgment block is currently `⏳ DATA NOT YET AVAILABLE`.

### MEDIUM
7. **A3 — DB persistence bypass** — BT replay-from-DB-state covers most of this; full fix is the tape replay server.
8. **A4 weekend gap** — task #302 still open.
9. **Tape Replay Server** (14-21hr) — proposal complete, build is next-week work.
10. **Re-run Phase 7 reconciler** after JM data refresh next weekend, with at least 5 post-Phase-6 trades.

### LOW
11. EA recompile pending (M3 partial-bar warn diagnostic only).
12. M4 (settings page Mean-Rev/Cross-Market panels) — frontend cosmetic; live UI strip already covered.
13. M5 (home hero $4.74M pre-retirement aggregate) — `frontend/lib/data/backtest.json` regen needed.
14. DB wipe (Stage B from earlier) — postponed; should run AFTER A1+A2 fixes ship to avoid re-polluting.

---

## Decisions Made

| Decision | Why |
|---|---|
| Macros retired everywhere (services + UI + start-win.bat) | Operational simplicity; only Micros are live. Keep Macros in research/playbook narrative pages — that's history. |
| General service on its own port 5050 | Auth shouldn't depend on a trading service being up. Single source of truth for cross-cutting concerns. |
| Numpy adapter at `backend/db.py` import time | Single source of truth — every service imports from here. Native float behaviour unchanged. |
| C3 VARCHAR(30) → VARCHAR(50) on both columns | Schema migration is metadata-only on Postgres (sub-second). Same class as Jun 10 orphan cascade. |
| C1+C4+H3 marked REJECTED by VERIFY | Framework caught audit's false-alarm rate (3/6). Documents the lesson — don't ship unnecessary code. |
| Smoke harness passed but production diverged → DON'T claim "100% parity" | Standing rule: name which axes verified. Smoke covers code-path; production needs state-pollution tests. |
| Don't wipe DB now | UI bugs are fixed (Stage A) but A1/A2 sweep-pollution bug not fixed. Wipe + ship-A1/A2 = correct order. |
| BT engine fall-back to config defaults | When `bt_replay.py` calls `run_backtest(strategies=[...])` without `entry_mode`, engine reads `MICRO_ALPHA_SWEEP['entry_mode']='limit'`. So BT IS using F27 limit-mode. Verified. |
| Always speak in IST first | Subash's standing rule — UTC translation is friction. Conversion cheatsheet saved. |

---

## What's Next

**Tomorrow morning, in this order:**

1. Push today's commits to remote (already there: `fc5b70e` is HEAD; `git push` not run today after restructure).
2. Pull on VPS (`git pull origin midas-deploy`), rebuild frontend (`npm run build`), restart all services via `start-win.bat`. Verify all 4 services up.
3. **Ship A1 fix** through 4-stage framework.
4. **Ship A2 fix** same way.
5. **Add `tests/harness/parity/test_stateful_parity.py`** — pre-pollute test, asserts pre-fix bug, asserts post-fix correct.
6. Run smoke harness + parity tests, all pass.
7. Push.

**This week:**
- Stateful BT mode (`replay_from_db_state`).
- A5 cooldown restart.
- Re-run Phase 7 reconciler with new live data accumulating.

**Next week:**
- Build Tape Replay Server per `docs/parity/REPLAY_SERVER_PROPOSAL.md`.

---

## File Inventory (this part 2 of session)

### NEW
- `scripts/bt_replay.py` — per-trade BT replay
- `scripts/reconcile_post_deploy.py` — Phase 7 aggregate reconciler
- `scripts/postmortem.py` — modified to wire BT replay block
- `backend-general/main.py` — auth + aggregate debug service
- `backend/db.py` — modified: numpy adapter registration
- `tests/test_psycopg2_numpy_adapter.py` — 10 regression tests
- `database/migrations/004_widen_exit_reason_and_event_type.sql`
- `database/schema.sql` — VARCHAR(30) → (50) on 2 columns; index added
- `docs/parity/PARITY_AUDIT_2026-06-19.md` — 24 axes
- `docs/parity/REPLAY_SERVER_PROPOSAL.md` — tape replay design
- `docs/audits/AUDIT_2026-06-19_PRODUCTION_RISK.md` — 17 findings
- `docs/audits/UI_DATA_MISMATCH_2026-06-19.md` — 9 findings
- `docs/ops/CADDY_GENERAL_SERVICE.md` — Caddyfile diff for VPS
- `docs/audit_2026-06-19_ui/*.png` — 16 Playwright screenshots
- `docs/audit_2026-06-19_ui_verify/*.png` — post-fix Playwright screenshots
- `docs/postmortems/reconcile_2026-06-19.md` — first reconcile baseline
- `docs/trades/GD-MI-a94ebe4a.md`, `GD-MI-83dd033b.md`, `GD-MI-2b152d33.md`
- `docs/README.md` — new entry-point index
- 100 .md files moved into 10 subfolders via `git mv` (history preserved)

### MODIFIED
- `backend-micro/scanner/price_stream.py`, `backend-oil-micro/scanner/price_stream.py` (C2)
- `backend-micro/routes/trades.py`, `backtest.py` (M1+M2)
- `backend-oil-micro/routes/trades.py`, `backtest.py`, `journal.py` (M1+M2+M3)
- `backend-micro/routes/backtest.py` — strategy default `["micro_alpha_sweep"]` only
- `backend/execution/limit_price.py` — return `float()` defensively
- `frontend/components/shell/SystemSwitcher.tsx`, `TopBar.tsx`, `InstrumentProvider.tsx`
- `frontend/lib/instrument.ts` — type narrowed to `"micro" | "oil-micro"`
- `frontend/app/page.tsx`, `live/page.tsx`, `settings/page.tsx`, `backtest/page.tsx`, `trades/page.tsx`, `journal/page.tsx`, `playbook/page.tsx`, `deck/page.tsx`, `robustness/page.tsx`, `report/page.tsx`, `uikit/page.tsx`
- `frontend/components/TradeJourney.tsx`
- `scripts/start-win.bat` — 5/5 → 3/3 services
- `mql5/DWX_Server.mq5` — partial-bar warn (M3)

### Memory entries (in `~/.claude/projects/-Users-subash-SUBASH-VibeTrader/memory/`)
- `feedback_ist_timeline.md` (NEW)
- `project_parity_audit_2026_06_19.md` (NEW)
- `project_replay_server_proposal.md` (NEW)
- `project_docs_restructure.md` (NEW)
- `bug_sweep_blacklist_no_rollback.md` (NEW — A1/A2 detailed)
- `feedback_smoke_harness_blind_spots.md` (NEW — standing rule)
- 31 existing memory files updated with new `docs/<subfolder>/X.md` paths
- `MEMORY.md` index updated (3 new + 2 new lines)

---

## Numbers to Remember

| Metric | Value |
|---|---|
| **Phase 6 deploy time today** | **14:58 IST (09:28 UTC)** |
| **Today's 3 live trades — all PRE-deploy** | -$156, -$308, +$284 = **-$180 net day** (incl partial $194 banked) |
| **NAV at session end** | $8,637.13 |
| **BT predicts post-deploy window** | 4 signals, +$376 net |
| **Live actual post-deploy** | 0 signals, $0 |
| **Smoke harness today** | 5/5 trades match (PASS) |
| **Parity axes mapped** | 24 (4 P0, 11 P1, 9 P2) |
| **Smoke harness coverage** | 6/24 axes = 25% |
| **Production audit findings** | 17; 6 critical/high; 3 shipped; 3 false alarms |
| **UI mismatch findings** | 9; M1+M2+M3 shipped; M4+M5 deferred |
| **Numpy save** | 1 trade (GD-MI-60f3aa09) cancelled by reconciler within 13s |
| **Commits this part 2** | 18 |
| **Cumulative commits today (parts 1+2)** | ~40 |
| **Memory files updated for docs restructure** | 31 |
| **Top-level docs reduced** | 100 → 4 |

---

## What I'd Do If I Had 1 More Hour

Ship A1 + write the stateful parity test. ~50 min. That closes today's smoking gun before tomorrow's first signal. Without A1, every subsequent `limit_price_through_market` rejection adds another sweep to the blacklist that BT walks fresh — the gap grows.

---

## Lessons (preserved as memory entries)

- **`feedback_smoke_harness_blind_spots.md`** — STANDING RULE: smoke pass ≠ production parity.
- **`bug_sweep_blacklist_no_rollback.md`** — A1/A2 detailed RCA + fix pattern.
- **`feedback_ist_timeline.md`** — Always IST first.
- **`project_parity_audit_2026_06_19.md`** — 24-axis map.
- **`project_replay_server_proposal.md`** — Tape replay design.
- **`project_docs_restructure.md`** — Folder reorg.

---

*Authored 2026-06-19 ~22:30 IST. Branch `midas-deploy` at `fc5b70e`. The session handoff for Part 1 (morning) is at `SESSION_2026-06-19.md` in this same folder.*
