# Deployment Plan — Windows Contabo VPS

**Goal:** move the full live trading stack (MT5 + DWX EA + Postgres + bt_engine A/D live runners + dashboard) from the Mac (Wine-MT5) onto a fresh **native Windows** Contabo VPS, preserving the full DB history and adopting the 3 open live positions.

**Decisions (locked with user 2026-07-03):**
- **Runtime:** Native Windows (not WSL, not Docker). MT5 is native; Python/Postgres native; bash scripts rewritten as `.ps1`/`.bat`.
- **DB data:** Migrate history — `pg_dump golddigger_bt` on Mac → restore on VPS. Track record continuous.
- **Cutover:** Hard cutover — stop Mac runners first, verify dead, then start VPS runners which adopt the 3 open positions. Broker SL/TP covers the brief gap.
- **MT5 account:** SAME JM-Demo2 demo (required to adopt the 3 open positions). Demo-only per standing safety rule.

**Standing constraints:** strategy/engine FROZEN (only the already-lifted live-runner fixes are in play); demo account only; secrets never committed; leaked password already flagged for rotation.

---

## Current stack (from survey)

| Component | Today (Mac/Wine) | Notes |
|---|---|---|
| Live A (long) | `python -m bt_engine.runner.cli live --strategy fib_v2_intraday_a --symbol XAUUSD.ecn --timeframe M15 --use-equity-sizer --start-balance 5000 --risk-pct 0.015 --max-live-lot 2.0 --max-open-positions 4 --max-spread 0.50 --max-entry-slip-ratio 1.15 --poll-interval 1.0` | Model B sizer |
| Live D (short) | same, `--strategy fib_v2_intraday_d` | shares ONE account |
| Dashboard | `scripts/run_dashboard.sh` → uvicorn `app.main:app` :8001, serves `dashboard/dist` | PYTHONPATH = bt_engine + dashboard_backend |
| Postgres | DB `golddigger_bt` @ localhost:5432 | shared by runners + dashboard |
| DWX bridge | file bridge in Wine MT5 `Common/Files/DWX/` | JSON IPC + pipe commands |
| Kill switch | touch `<repo>/LIVE_DISABLED` | runner aborts |
| Secrets | `.env` (untracked) | DATABASE_URL, OANDA_TOKEN, TELEGRAM_* |

**Ports:** dashboard 8001 (HTTP+WS), Postgres 5432 (local only).

---

## Windows-portability gaps (MUST fix)

1. **Hardcoded Mac DWX path** — `bt_engine/bt_engine/data/dwx_bridge.py` `DEFAULT_DWX_DIR` points at Wine path. Windows native MT5 writes to
   `C:\Users\<user>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\DWX`.
   **Fix:** wire a `DWX_DIR` env-var override (code change — small, live-runner-adjacent; treat as an infra fix, not a strategy change) OR pass an explicit path. Prefer env override so no hardcoded machine path ships.
2. **Hardcoded repo path** — `scripts/run_dashboard.sh`, `run_parity_logged.sh` embed `/Users/subash/SUBASH/GoldDigger`. Rewrite as `.ps1` using repo-relative pathing.
3. **Bash-only health script** — `scripts/health_snapshot.sh` uses `pgrep`, `stat -f`, `psql`. Rewrite as PowerShell (`Get-Process`, `os.path.getmtime` via a tiny Python helper, `psql` on PATH).
4. **Process supervision** — no launchd on Windows. Use **NSSM** (or Task Scheduler) to run A, D, dashboard as auto-restart services.
5. **Shebangs ignored** — always invoke `python -m ...` explicitly.

Cross-platform-OK (no change): `Path()` usage in Python, `SPA_DIST` resolution in `app/main.py`, TCP Postgres DSN.

---

## Phased plan

### Phase 0 — VPS base provisioning
- [ ] RDP into fresh Windows Contabo VPS. Confirm specs (≥2 vCPU / 4GB RAM / 40GB disk target).
- [ ] Install: **Python 3.11+** (add to PATH), **Node 18+ LTS**, **PostgreSQL 16** (server + client tools + psql on PATH), **Git**, **NSSM**.
- [ ] Install **MetaTrader 5** (JustMarkets build). Do NOT log in yet.
- [ ] Windows Firewall: keep 8001 + 5432 **local-only** (bind 127.0.0.1). Dashboard exposure decided in Phase 6.

### Phase 1 — Code + deps
- [ ] `git clone` repo (branch `fib-v2-clean`) to e.g. `C:\GoldDigger`.
- [ ] `pip install -e bt_engine` and `pip install -e dashboard_backend` (or install their pyproject deps).
- [ ] `cd dashboard && npm ci && npm run build` → produces `dashboard/dist`.
- [ ] Recreate `.env` on VPS BY HAND (never from git): set `DATABASE_URL=postgresql://<vpsuser>:<pw>@localhost:5432/golddigger_bt`; OANDA/TELEGRAM only if actually used by live path (verify — live runner uses DWX, not OANDA). Rotate any previously-leaked credential here.

### Phase 2 — Windows portability fixes (code)
- [ ] Add `DWX_DIR` env-var override to `dwx_bridge.py` (fallback to current default if unset). Set `DWX_DIR=C:\Users\<user>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\DWX` on VPS.
- [ ] Author `scripts/run_dashboard.ps1` (repo-relative PYTHONPATH + uvicorn :8001).
- [ ] Author `scripts/live_a.ps1`, `scripts/live_d.ps1` wrapping the two CLI commands.
- [ ] Author `scripts/health_snapshot.ps1` (process check + DWX file freshness + Postgres ping).
- [ ] Commit these as an infra PR on `fib-v2-clean` (no strategy/engine touch). Run test suite before commit.

### Phase 3 — Postgres migrate
- [ ] On Mac: `pg_dump -Fc golddigger_bt > golddigger_bt.dump` (do this at cutover, AFTER Mac runners stopped — Phase 5 — so it's the freshest state; a dry pre-dump now is fine for schema validation).
- [ ] Create DB on VPS: `createdb golddigger_bt`; load schema from `bt_engine/bt_engine/db/schema.sql` if starting fresh, OR just `pg_restore` the dump.
- [ ] `pg_restore -d golddigger_bt golddigger_bt.dump`. Verify row counts (bt_runs / bt_trades / bt_signals) match Mac.

### Phase 4 — MT5 + DWX on VPS
- [ ] Log MT5 into **JM-Demo2** (same account). Verify balance/equity matches Mac view.
- [ ] Install DWX EA on an XAUUSD.ecn M15 chart; enable AutoTrading + allow DLL/file access. Confirm `Common\Files\DWX\account_info.json` updates (<10s mtime).
- [ ] Run dashboard on VPS + verify `account_live` shows JM-Demo2 truth and the 3 open positions appear via `positions_live`.
- [ ] Optional (user chose hard cutover, not parallel dry-run): a single `--dry-run --max-ticks N` smoke of each leg to confirm the bridge + DB write path before going live. Recommended — cheap insurance, no orders sent.

### Phase 5 — Hard cutover (the critical window)
**Order matters. Positions are safe at broker on SL/TP during the gap.**
1. [ ] On Mac: touch `LIVE_DISABLED` and/or kill both runner procs. **Verify both dead** (`pgrep` returns nothing).
2. [ ] Confirm no Mac process is still writing DWX commands (watch `commands/` dir quiet).
3. [ ] Fresh `pg_dump` on Mac → copy dump to VPS → `pg_restore` (overwrite Phase 3 load) so VPS DB = exact final Mac state incl. the 3 open trade rows.
4. [ ] Start VPS live A + live D (via NSSM or the `.ps1` wrappers). Runner `_open_trades_from_positions` adopts the 3 open positions per-leg (real ticket, entry, hold-cap forward-only).
5. [ ] Verify on VPS dashboard: 3 positions adopted (2 long 0.01/0.05, 1 short 0.13), correct tickets (2118599832 / 2121027691 / 2123464608), P&L live.
6. [ ] Confirm Mac MT5 no longer needs to run (VPS owns the account now). Log Mac MT5 out to avoid any accidental double-connect.

### Phase 6 — Supervision + monitoring + hardening
- [ ] Register A, D, dashboard as **NSSM services** with auto-restart on crash + on boot.
- [ ] Schedule `health_snapshot.ps1` every 15 min (Task Scheduler) → writes JSON snapshots; alert if a leg proc dies or DWX file goes stale.
- [ ] Decide dashboard exposure: keep 127.0.0.1-only + RDP to view, OR reverse-proxy (caddy/nginx) + auth if remote view wanted. Default: local-only (safest).
- [ ] Verify kill switch path works on VPS (`LIVE_DISABLED` at repo root).
- [ ] 24-48h watch: parity of dashboard numbers, no orphaned tickets, hold-cap behavior, restart-survival of adopted positions.

### Phase 7 — Decommission Mac
- [ ] After stable 24-48h on VPS, retire Mac runners permanently (keep repo + `.env` as cold backup).
- [ ] Document final VPS runbook (start/stop/restart, where logs live, how to trigger kill switch).

---

## Risks / gotchas
- **Double-manage** — the ONE thing that must not happen. Mac MUST be fully stopped + MT5 logged out before VPS starts. Enforced by Phase 5 ordering.
- **DWX EA config** — AutoTrading + file/DLL permissions differ per fresh MT5 install; the EA silently no-ops if not enabled. Verify `account_info.json` freshness before trusting.
- **Server time** — broker is UTC+3; VPS OS timezone should not matter (code parses broker `open_time` explicitly) but set VPS clock to UTC to avoid log confusion.
- **Adopted trade DB gap** — adopted positions reconstruct fib/qty from broker, not original setup (known LOW issue). Unchanged by move.
- **pg version skew** — dump/restore across major Postgres versions can warn; match versions or use `pg_restore --no-owner`.
- **First VPS trade is the real parity test** — BT=live is proven for strategy code; broker execution parity on a NEW machine/MT5 build is only proven once the first VPS-originated order fills cleanly. Watch it.

## Open items to confirm before Phase 0
- VPS specs + Windows version (Server 2022 vs 10/11).
- Whether OANDA/Telegram are actually on the live path (survey says live uses DWX; OANDA token may be research-only → can omit from VPS `.env`).
- Remote dashboard access wanted, or RDP-only?
