# Session Handoff — 2026-07-06/07 — Telegram alerts + hold-cap parity + dashboard $ fixes

Follows `SESSION_2026-07-05d_FRONTEND_MOBILE.md`. Weekend session: AFK monitoring
(30-min cron sweeps) interleaved with a run of real bug fixes surfaced from live
screenshots, one engine fix enforced live, a new Telegram notifier, and BT-vs-live
parity verification.

## Theme
Make the live book observable + trustworthy: Telegram trade alerts, fix every
dashboard $/R display defect against broker truth, and close the hold-cap
BT↔live parity gap (enforced live).

## What Happened (Chronological)
1. **AFK health cron** — session-only Claude cron (job 41511b61, :13/:43) sweeping
   services + MT5 truth + FX-week state every 30 min while user AFK. Confirmed weekend
   hold behavior: positions HELD (bar-count cap inert with no bars — expected).
2. **$ P&L overstatement (2b280e7)** — Trades showed +$914 vs broker +$525. Root: a
   BROKER_CLOSED weekend SL (ticket 2125844421) never reconciled (GUARD 2 blocked $
   backfill while closed_orders.json stale for days). Fixed reconciler to skip GUARD 2
   when a fresh open_orders confirms the ticket gone; FE shows "pending" not the 1-lot
   fantasy. Deployed + restarted legs; backfilled the stuck row ($85.68).
3. **Live-card + ledger polish** — booked-$ on live partial card (from SUPERSEDED
   sibling, backend enrich); click-to-copy tickets (CopyTag); Trades filter-rail/KPI/
   table polish; **verified all 9 trades listed** (9/9, no missing).
4. **Coin Lockup logo (520aefc)** — user picked "coinlock" from a generated gallery.
   New `MidasMark` (animated shimmer+aura) everywhere + favicons/PWA. SpireMark deleted.
5. **BE depiction (242ce99)** — found long 2118599832's SL never moved to BE (a
   PRE-07-03 slow-ack bug, already code-fixed). Manually MODIFY'd its live SL→BE
   (broker-confirmed), then made PositionCard read the live broker SL → "Risk·BE $0".
6. **RangeBar short-axis (08d839b)** — user caught: losing short moved tick toward TP.
   Axis was low-price-left always; fixed to SL=0%→TP=100% by direction.
7. **Net R partial (3c267a1)** — winner showed −0.06R (remainder-only) while $ was +$144.
   Total R now = partial_r + net_r, in ledger + KPI band.
8. **Hold-cap parity (9a61fd9)** — 2 A-longs held 74h/119h vs 12h cap. Root: bars_held
   reset to 0 on every adoption → dodged the cap under frequent restarts. Fixed: seed
   bars_held from true FX-open elapsed M15 bars (BT-parity, weekends skipped). +4 tests,
   103 pass. Deployed + restarted → both overdue longs correctly TIMEOUT-closed (net +$60).
9. **Telegram notifier (d365680)** — standalone `notifier/` service via Postgres
   LISTEN/NOTIFY (zero engine/leg touch). 7 user-approved templates. Additive trigger
   fix so reconcile $ broadcasts. Tested E2E (real event → 200). Installed midas-telegram
   NSSM svc; running.
10. **BT-vs-live parity (Fri + today)** — replayed DWX M15 through identical A+D code:
    every live fill matched a BT signal to the cent (SL/TP identical). Misses = restarts
    (warmup blindness), NOT edge failure. Today's 2 misses ≈ wash (dodged 1 loser, missed
    1 winner-in-progress).
11. **Durable refresh (7944535)** — both pages re-hydrate on WS reconnect + 20s poll +
    Trades debounced refetch on `trade` channel. Kills stale-frame scares.
12. **Trades $ dedup (e43f976)** — the "$588 vs $728" was NOT stale (my misdiagnosis) —
    a real dedup bug: SUPERSEDED row won + dropped the banked partial. Fixed dedup to
    pick terminal reconciled row + carry sibling booked-$; $ P&L adds partial. Ties to
    account ~$728.

## What's Live
- Branch `fib-v2-clean`, tip **`e43f976a0`**. VPS reset to it, dashboard rebuilt.
- **4 NSSM services RUNNING**: midas-live-a, midas-live-d, midas-dashboard, **midas-telegram** (new).
- Book **FLAT** (0 open). Balance = equity = **$10,728.87**. All-time +$728.87 (+7.29%).
- Legs restarted this session (reconciler deploy + hold-cap enforcement); telegram + dashboard restarts don't touch legs.

## Commits This Session
| SHA | Description |
|-----|-------------|
| 2b280e74e | broker $PnL overstatement — reconciler weekend-close backfill + FE pending guard |
| 1f7f85cce | live card booked $ + click-to-copy tickets |
| 48ff982f9 | live card booked $ from SUPERSEDED sibling (backend enrich) |
| 4c08380bc | Trades page polish — filter rail, KPI tiles, table rhythm |
| 520aefc87 | Coin Lockup brand mark everywhere + animate + favicons |
| 242ce9904 | PositionCard BE stop + $0 risk (broker-truth SL) |
| 08d839ba5 | RangeBar axis backwards for shorts |
| 3c267a1c8 | Net R excluded banked partial |
| 9a61fd960 | seed adopted bars_held from true FX-open age (hold-cap parity) |
| d3656809c | Telegram trade-alert notifier (LISTEN/NOTIFY) |
| 7944535a7 | durable dashboard refresh (WS reconnect + 20s poll) |
| e43f976a0 | Trades $ P&L dropped banked partial on re-adopted tickets |

## Outstanding Issues
- **MEDIUM** (#244): F4 parity — live fills at K+1 close vs BT K+1 open (few pts/trade). Known, benign.
- **MEDIUM** (#249): C2/C3/H1/H3/H4 BT-live parity divergences — not re-audited this session.
- **LOW**: dead LivePage components (~340 lines) still present (deferred, harmless).
- **LOW**: notifier token lives in NSSM env on a box with public RCE debt ([[public-vps-security-debt]]) — demo bot, low blast radius, but do the security pass before real go-public.
- **CARRIED**: S1 still PARKED pending 1-week live A+D workhorse watch; fresh 100X re-audit.

## Decisions Made
- Telegram = decoupled LISTEN/NOTIFY service, NOT engine hooks (no leg restart, can't stall trade loop).
- Enforce the hold-cap live NOW (restart while flat) — the overdue longs were the bug persisting; closing them = correct state.
- Close $ = wait-for-exact-broker-$ (reconciled), 150s watchdog fallback.
- "Restart costs trades" accepted as an operating principle — minimize leg restarts.

## What's Next
- Watch the first ORGANIC live trade flow through Telegram (entry→partial→close) to confirm the notifier end-to-end on a real fill (only tested with a synthetic event).
- Optional: quantify the session-window question (why A-long is london_ny not `all`) with a focused session sweep — user asked, deferred.
- Resume the deferred parity re-audit + 1-week workhorse watch.

## File Inventory
- **New**: `notifier/{telegram_notifier.py, templates.py, migration_notify_reconcile.sql, README.md}`, `dashboard/src/components/{MidasMark.tsx, ui/CopyTag.tsx}`, `dashboard/public/brand/*` + favicons.
- **Modified (engine)**: `bt_engine/bt_engine/runner/{live.py, broker_reconciler.py}`, `bt_engine/bt_engine/db/schema.sql`, `bt_engine/tests/unit/runner/test_{broker_reconciler,live_helpers}.py`.
- **Modified (dashboard)**: `src/pages/{LivePage,TradesPage}.tsx`, `src/components/{PositionCard,RangeBar,DataGrid}.tsx`, `src/lib/format.ts`, `src/components/ui/StatTile.tsx`, `src/components/{TopBar,SessionClocks}.tsx`, `src/pages/{LoginPage,LandingPage}.tsx`, `index.html`, `dashboard_backend/app/routers/live.py`.
- **Deleted**: `dashboard/src/components/SpireMark.tsx`.

## Numbers to Remember
- Account: balance = equity = **$10,728.87**; all-time **+$728.87** (bal − $10k deposit).
- Today (Jul-6) realized: **+$289.95** (88.40 + 85.68 − 28.26 + 144.13).
- Trades reconciled $ (10 tickets, deduped) ≈ **$739** (ties to account, residual ~$10 = pre-reconciler trades).
- The winner short 2131715201: +$144.13 (partial +1R banked, remainder BE-scratched at $0).
- BT-vs-live Fri+today: 9 BT signals, 4 live fills, ALL 4 exact-parity; 5 misses = restarts.
- Reconciler tests 23 pass; live-helpers 26 pass (4 new bars_held); full runner 103 pass.
