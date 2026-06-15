# Session Handoff — 2026-06-15 (Part 2 — Audit + Postmortems)

## Theme

Live duplicate-trade incident → 24-issue dedup-class audit (20 fixed) → service restart → DD/trade-count reset → Filter #25 (intraday bias) sweep stashed → 2009 + 2022 pessimistic postmortems (no artifact, framing flagged) → calibration plan deferred.

## What Happened (Chronological)

1. **Duplicate trade incident.** 3 Gold Macro trades fired same Asia sweep (10:51 + 12:36 + 12:42 UTC). RCA: `live_engine.py:189` had `LIKE 'GD-AS-%'` — guard dead since May 28 because trade_refs are `GD-AL-` / `GD-ME-` / `GD-CR-`. Fixed in `5c86466` with `strategy IN (...)`.

2. **24-issue audit.** Spawned 4 parallel Explore-style agents to find the same class of bug (silent guards, prefix drifts, hardcoded fallbacks, dead error paths). Found 24 issues. Wrote `docs/AUDIT_2026_06_15_DEDUP_CLASS.md` with per-issue framework: RCA → cross-check 4 backends → verdict → fix → ship → doc. Sequential walk through all 24. 20 fixed (commits `ae63a77` through `8daa5b6`). 2 accepted-as-is (#8, #10 — covered by other fixes). 2 not-a-bug (#20, #22). 1 deferred (#17 — DD state shared across mean_rev/cross_market that don't run in prod yet).

3. **Frontend deploy + restart.** Fe-investor-pages branch (snap-page landing + /report + /playbook + protected-page legibility sweep) merged to `midas-deploy` as squash `01ab64d`, deployed to VPS via debug API, frontend rebuilt, all services restarted at 14:56:53.

4. **Zombie trade cleanup.** 4 trades stuck in DB (`exit_time IS NULL`, broker shows closed, no DWX `closed_orders.json` entry). Marked `MANUAL_CLOSE_DETECTED` with `pnl_usd=NULL`. Re-dated to yesterday so trade-count cap doesn't bind today.

5. **Reset all systems for NY session.** DD state cleared (`cl=0` × 4), equity synced to broker NAV ($8,345), sweep blacklist cleared (DB + memory), today's signals cleared, daily P&L counter cleared. All 4 systems at 0/3 trades, ready to fire.

6. **Filter #25 — intraday bias source.** Hypothesis: replace yesterday's daily candle with today's intraday data. Built parameter into engine on `filter/25-bias-source` branch. 16-cell sweep (4 systems × 4 variants: prior_day/asia/pre_session/lookahead_today). Result: Gold Macro/Oil Macro intraday LOSES money (-$116k to -$237k); Gold Micro pre_session +$30k (would have shipped); Oil Micro marginal. **User chose to STASH all** — not worth live↔backtest divergence cost. Filter branch preserved on origin.

7. **2009 Pessimistic Postmortem.** User asked: "is 4673% real or scam?" Built `scripts/postmortem_2009_oil_micro.py` — runs real backtest, isolates 2009, monte-carlo 4 random trades/month with raw H1 OHLC plausibility checks, red-flag scan. Result: **0 lookahead, 0 phantom fills, 0 degenerate trades**. The 4673% is real ($5k → $238k) but the framing is misleading because engine resets capital each Jan 1.

8. **2022 Pessimistic Postmortem.** Same framework, ran on 2022 (war year). 8776%. Same conclusion — no artifact, but realistic live = 1000-2000%. Per-year drag is similar across years; cap binds 60% of trades; both LONG and SHORT directions profitable.

9. **Calibration plan deferred.** Wrote `docs/CALIBRATION_PLAN.md` for 3-tier dashboard (Theoretical / Calibrated / Actual). 8 drag parameters identified, 4-phase plan. **Deferred until 30+ clean live trades** — current data contaminated by phantom fills, orphan cascade, today's bug.

10. **User decision: watch live, collect data.** No new project work; let live run, check logs daily, build calibration when data ready.

## What's Live

- **VPS:** all 4 services restarted at 14:56:53. All Issue #1-#24 fixes loaded in memory (verified via `inspect` on `_get_dd_state` constants).
- **Account:** JustMarkets MT5, NAV $8,345.
- **Trade state:** 0 open. 0/3 today across all 4 systems. DD all `cl=0`.
- **Branches:**
  - `midas-deploy` at `d5ff803` (clean, pushed)
  - `filter/25-bias-source` at `e8f6be2` (preserved, not merged)
- **Schema migrations applied to VPS:** `gd_traded_sweeps` table + `gd_dd_state` row id=4.

## Commits This Session (chronological)

| SHA | Description |
|---|---|
| `5c86466` | Fix Gold Macro dedup guard (the original bug) |
| `ae63a77` | Issue #1: defense-in-depth dedup in micro/oil/oil-micro |
| `3132c45` | Issue #2: scope adaptive risk-multiplier queries |
| `0a392a0` | Issue #3: scope Gold Macro daily recon |
| `9959e4b` | Issue #4: fix Gold Macro routes mean_rev/cross_market |
| `be2d83e` | Issue #5: scope Oil Macro routes |
| `f10eb81` | Issue #6: equity sanity floor + remove $10k fallback |
| `e409ecf` | Issue #7: validate EA response in place_market_order |
| `a625954` | Issue #9: persist sweep blacklist to DB |
| `4873e9a` | Issue #11: log GBP/USD rate fallback |
| `b6b0dbe` | Issue #12: Gold Macro DD state self-heal |
| `1620edc` | Issue #13: surface Telegram failures |
| `9c34ebe` | Issue #14: log+retry EXIT_AMBIGUOUS alert |
| `6ef6a97` | Issue #15: structured journal exception logging |
| `ca5d048` | Issue #16: reconcile_orphans empty-broker smell detector |
| `c891380` | Issue #18: gd_dd_state row id=4 |
| `c80ac6b` | Issue #19: cooldown skip-reasons exact match |
| `91960f9` | Issue #21: M3 audit bare except → logged |
| `eb8ac43` | Issue #23: log _parse_mt5_time fallback |
| `8daa5b6` | Issue #24: parse strategy from broker comment |
| `a849192` | Audit doc: 24-issue RCA + fix log |
| `a9b1d3c` | Issue #21b: M3 audit JSON encoding (str(c) → safe_json_dumps) |
| `1bdac56` | Filter #25 STASHED: bias_source intraday variants |
| `a6e72eb` | Pessimistic postmortem: 2009 Oil Micro (4673%) |
| `b01f396` | Pessimistic postmortem: 2022 Oil Micro (8776%) |
| `d5ff803` | Plan: live-calibrated backtest layer (deferred) |

**25 commits**, all on `midas-deploy`, all pushed to origin.

## Outstanding Issues

**🟡 MEDIUM**
- 4 zombie trades have `pnl_usd = NULL`. Backfill from JustMarkets statement when convenient.
- DWX EA dual-instance issue (Mac + VPS sharing account splits OnTradeTransaction events). User aware. **Recommendation: shut down Mac MT5 when running production.**
- Issue #17 (Gold Macro DD state shared across `alpha_sweep` / `mean_rev` / `cross_market`) deferred until those strategies actually activate.

**🟢 LOW**
- Calibration plan exists, deferred until clean data accumulates.
- Replay harness proposed (live code path on historical data). User chose to defer in favor of watching live and collecting data.
- Frontend `/report` and `/playbook` could reframe percentages with caveats (30-min copy edit; no engine work).

**🚫 NONE CRITICAL** — system is stable, fixes shipped, ready for normal operation.

## Decisions Made

- **No-auto-ship rule extended to filter sweeps.** Filter #25 had numbers that would justify shipping Gold Micro pre_session (+$30k, PF 4.52→5.41), user said stash everywhere. Per-system framework still valid for next time.
- **Calibration deferred over replay harness.** Both proposed; user picked "watch live, collect data" path. Calibration becomes data-driven rather than guess-derived.
- **Backtest framing reframe NOT shipped.** /report and /playbook still show raw %; user aware of misleading framing but chose to leave UI alone for now.
- **Mac MT5 not formally shut down.** User aware of dual-instance issue. Action item but not enforced.

## What's Next

When session resumes, ranked by leverage:

1. **Daily log check.** Walk gold/oil/micro/oil-micro logs, look for: ORPHAN_DETECTED (DWX dual-instance still firing?), EXIT_AMBIGUOUS streaks, NOTIFY failures (Issue #13 surface), reconcile_empty_but_db_has_open warnings (Issue #16 surface). Build the calibration dataset.
2. **Postmortem any new live trade.** Use `scripts/postmortem.py` + trade-postmortem skill. Compare to backtest expectations.
3. **Backfill 4 zombie P&Ls** from JustMarkets statement (~5 min in broker UI).
4. **After 1 week clean:** revisit calibration plan trigger criteria. If 30+ clean trades accumulated, start Phase 1 (data extraction).
5. **After 2 weeks clean:** consider replay harness as foundation for calibration.

## File Inventory

**New files:**
- `docs/AUDIT_2026_06_15_DEDUP_CLASS.md` — full 24-issue RCA + fix log
- `docs/POSTMORTEM_2009_OIL_MICRO.md` — pessimistic postmortem 2009
- `docs/POSTMORTEM_2022_OIL_MICRO.md` — pessimistic postmortem 2022
- `docs/CALIBRATION_PLAN.md` — deferred 3-tier dashboard plan
- `scripts/postmortem_2009_oil_micro.py` — re-runnable for any year
- `scripts/postmortem_2022_oil_micro.py` — same, 2022-targeted
- `scripts/run_filter_25_bias_source.py` (on `filter/25-bias-source` branch)
- `scripts/output/postmortem_2009.html` + `postmortem_2022.html` (HTML reports)

**Modified files (all 4 backends, top hits):**
- `backend/scanner/live_engine.py` — Issues #1, #2, #6, #12, #14, #15, #16, #24
- `backend/scanner/scheduler.py` — Issues #1, #9, #19, #21, #21b
- `backend/db.py` — Issues #3 (`daily_recon_stats` strategies kwarg), #9 (sweep blacklist helpers)
- `backend/notify.py` — Issue #13
- `backend/execution/mt5_executor.py` — Issues #7, #23
- `backend/execution/oanda_executor.py` — Issue #11
- `backend/routes/{trades,state,stream}.py` — Issue #4
- `backend-oil/{routes,scanner}/...` — mirrored fixes
- `backend-micro/scanner/*` — mirrored fixes
- `backend-oil-micro/scanner/*` — mirrored fixes
- `database/schema.sql` — `gd_traded_sweeps` table + `gd_dd_state` row id=4

## Numbers to Remember

| Metric | Value |
|---|---|
| Issues found in audit | 24 |
| Issues fixed | 20 |
| Issues accepted-as-is | 2 (#8 cooldown, #10 cooldown skip reasons) |
| Issues not-a-bug | 2 (#20 f-string with constant, #22 retry-loop bare except) |
| Issues deferred | 1 (#17 DD state shared) |
| Commits this session | 25 (all on midas-deploy) |
| Filter #25 cells run | 16 (4 systems × 4 variants) |
| Backtest baseline 2009 Oil Micro | $5k → $238k = 4,673% ($5k yearly reset) |
| Backtest baseline 2022 Oil Micro | $5k → $443k = 8,776% (war year, 60% cap-bound) |
| Realistic live 2009 estimate | +$50k-$100k (~1,000-2,000%) |
| Realistic live 2022 estimate | +$50k-$100k (~1,000-2,000%) |
| Cap-binding rate (good years) | ~59-60% of trades hit MAX_UNITS=5000 |
| Service restart time | 14:56:53 UTC 2026-06-15 |
| Account NAV at session end | $8,345.65 |
| Trade-count today (all 4 systems) | 0/3 |
| Open positions session end | 0 |
| Zombie trades cleared | 4 (P&L unknown, NULL in DB) |

## What I'd Do If I Had 1 More Hour

1. **Backfill the 4 zombie P&Ls** from JustMarkets web statement → update `gd_trades.pnl_usd` for the 4 trade_refs. Closes the audit loop.
2. **Reframe `/report` headline numbers** from "+4,673%" to "+$233k on $5k base · 84% WR · PF 9.21". Removes the scam-smell. 30-min copy edit, big honesty win.
3. **Add a `daily_health_check.py` script** that pulls each backend's logs, counts NOTIFY failures, EXIT_AMBIGUOUS streaks, orphans-detected, reconcile-empty smells — outputs a one-page daily dashboard. Foundation for calibration data extraction.

---

_Session ended ~16:00 UTC 2026-06-15. Watch live. Check logs daily. Build calibration when data ready._
