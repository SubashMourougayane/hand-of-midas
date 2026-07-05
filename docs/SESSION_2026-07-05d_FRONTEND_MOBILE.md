# Session Handoff — 2026-07-05/06 (d) — Frontend Mobile Pass + Numbers Reconcile

Fourth handoff of the 2026-07-05 arc (rolled past midnight into 07-06). Prior:
`SESSION_2026-07-05c_AUDITFIXES_RESEARCH.md`. This doc = full frontend mobile/UX
audit + fixes, plus two dashboard number bugs found & fixed while verifying.

## Theme
Make every dashboard page mobile-friendly + aligned (audit-driven), and reconcile
every on-screen number against MT5 truth — fixing two real display bugs surfaced
in the process.

## What Happened (Chronological)
1. **PnL / research spillover** (earlier in arc, already committed): fixed-1-lot A+D
   BT (+2831R/PF1.63/8-8), S1-alone Model B $29k, ICT-2022 1728-combo sweep (phantom),
   classic-indicator batch (VWAP/trend/SMA all dead post look-ahead-fix). All reject; S1 stands.
2. **Frontend mobile audit** — 3 parallel Explore agents mapped every page/component.
   Finding: LandingPage 33 breakpoints, app pages 4-5, components ~0. Desktop-only interior.
3. **Mobile pass built** (5 phases): globals `.scroll-slim`; App safe-area bottom pad;
   MobileNav 6 routes + 44px; TopBar `lg:hidden` account strip; DataGrid card-reflow
   below md (kills 820px scroll trap); PositionCard 2/3/5; unified Backtest shell;
   Architecture header + 12-col text grids stack; per-page grid/width/touch fixes.
   Deferred: ~340 lines dead LivePage components (interleaved w/ used helpers).
4. **Local review** — spun up Vite :5173 + local backend :8001 for phone review;
   verified login API (good→token, bad→401, proxy 200).
5. **OPEN RISK bug (earlier commit 4eb814a)** verified fixed live: tile now |stop-entry|×lots.
6. **Trades KPI bug** — Net R (-1.73) vs $ P&L (+243) opposite signs. Root: KPI "closed"
   set required net_r!=null, so H1 broker-closed rows (net_r=null, real broker_net_usd
   incl -$501) dropped from BOTH KPIs while showing in ledger. Fix: $ counts all closed
   rows (ties to ledger +$535), R-metrics stay on scored subset. Label "N scored · M closed".
7. **"Missing short" scare** — user screenshots showed 2 positions/$10,388. Diagnosed:
   LOCAL dev stack, stale. VPS always had 3 + $10,846. Hard refresh fixed. Killed local servers.
8. **Sydney session clock** added to footer (D-short trades all sessions) + real FX-week
   open guard (Sun≥21:00 UTC → Fri<22:00 UTC, Sat shut).

## What's Live
- Branch `fib-v2-clean`, tip **`a0e7fdd78`**. Dashboard deployed + HEALTH 200.
- Both legs RUNNING, 3 positions undisturbed (2118599832 L, 2125844421 S, 2126588609 L).
- All frontend changes deployed to VPS (midas.subashtrades.in). Legs never restarted (frontend-only).

## Commits This Session (this doc's batch)
| SHA | Description |
|-----|-------------|
| a1ff1b052 | Frontend: full mobile-friendly + UI alignment pass |
| b1cb0d6d7 | Trades KPIs: count broker-closed rows in $ P&L |
| 5ef13a0c7 | SessionClocks: add Sydney clock |
| a0e7fdd78 | SessionClocks: real FX-week guard (Sun 21:00 → Fri 22:00 UTC) |

## Outstanding Issues
- **MEDIUM**: LivePage only re-hydrates via 60s poll, NOT on WS reconnect → stale tab
  after dashboard restart (durable fix = re-hydrate on reconnect + 20s poll). Recurring scare source.
- **MEDIUM**: ~340 lines dead LivePage components (PnlHero/HealthBar/etc.) — deferred deletion.
- **MEDIUM**: task #250 backend half — reconciler doesn't stamp net_r on H1-closed rows
  (so they're $-counted but not R-scored). Frontend now handles gracefully.
- **LOW**: Sydney clock only shows lg+ (SessionClocks row is hidden lg:flex by design).
- Carried from prior: F4/C2/C3/H3/H4 BT-live parity; fresh 100X re-audit; 1-week workhorse watch; S1 still PARKED.

## Decisions
- Card-reflow (not horizontal-scroll) for mobile tables — user chose.
- Full clean+unify scope — but dead-code deletion deferred as edit-risky (noUnusedLocals off = harmless).
- $ P&L counts ALL closed incl. broker-closed (ties to ledger); Net R stays R-only.
- Sydney clock uses real FX-week (Sun 21:00 UTC open) not calendar weekend.
- Deploy after user phone-review per plan; frontend-only, legs untouched every deploy.

## What's Next
Durable auto-refresh (re-hydrate LivePage on WS reconnect + 20s poll) so stale-tab
scares stop. Then the deferred backend items + fresh 100X re-audit + workhorse watch.

## File Inventory (modified)
- Shell/global: `App.tsx`, `theme/globals.css`, `components/{MobileNav,TopBar,SessionClocks}.tsx`.
- Primitives: `components/ui/{button,tabs}.tsx`, `components/{DataGrid,PositionCard,FilterBar,FilterChips}.tsx`.
- Pages: `pages/{LivePage,TradesPage,BacktestPage,SignalsPage,JournalPage,ArchitecturePage,LoginPage}.tsx`.

## Numbers to Remember
- Live truth (verified vs MT5): equity $10,846.06 / balance 10,526.77 / float +319.29;
  OPEN RISK $196 (=139+57+0); 3 positions.
- Trades: $ P&L +$535 (post-fix, ties to ledger), Net R +2.35 (5 scored · 6 closed), PF 1.60.
- Deposit baseline broker-verified: +$506.31 → exactly $10,000 (2026-07-01 16:37).
- FX week: Sun 21:00 UTC (Sydney) → Fri 22:00 UTC (NY close).
