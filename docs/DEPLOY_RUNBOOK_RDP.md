# VPS Deploy Runbook — RDP / copy-paste (SSH not available)

Contabo VPS has **no SSH** — everything runs by you inside an **RDP** session in
**PowerShell (Administrator)**. Code + launchers are already on GitHub
(`fib-v2-clean`); the VPS pulls them. This runbook is ordered — do the phases
top to bottom. Paste output back to Claude when a step says *(verify)*.

**VPS facts:** Windows Server 2025 24H2 · AMD EPYC 8GB / 119GB free · IP `84.247.177.145` · DNS `midas.subashtrades.in` → that IP already set. Postgres source version on Mac = **15**.

**Standing rules:** demo account only · strategy/engine FROZEN · do NOT start live runners until the Mac is stopped (cutover, Phase 6) · no secret pasted into any shared channel.

---

## Phase 1 — Bootstrap (deps + code + build + DB create)

1. Open **PowerShell as Administrator** on the VPS.
2. Clone just enough to get the bootstrap script (or paste the script). Easiest:
   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass -Force
   git --version   # if 'not recognized', install Git first:
   winget install Git.Git -e --silent --accept-package-agreements --accept-source-agreements
   # reopen PowerShell so git is on PATH, then:
   git clone --branch fib-v2-clean https://github.com/SubashMourougayane/hand-of-midas.git C:\GoldDigger
   ```
3. Run the bootstrap (installs Python 3.11, Node 18, PostgreSQL 15, NSSM; pip installs; npm build; creates DB):
   ```powershell
   C:\GoldDigger\scripts\windows\bootstrap.ps1
   ```
   *(verify)* ends with green "Bootstrap complete". If a winget install needs a
   fresh PATH, close + reopen elevated PowerShell and re-run — it's idempotent.

> If `winget` is missing: install **App Installer** from the Microsoft Store first.

---

## Phase 2 — Timezone (recommended)

Set the VPS clock to **UTC** so logs read cleanly (trading math is unaffected —
code parses broker UTC+3 explicitly):
```powershell
Set-TimeZone -Id "UTC"
```

---

## Phase 3 — Move + restore the Postgres dump

On the **Mac**, the compressed dump is at `/tmp/golddigger_bt.dump` (~406 MB,
full history). Move it to the VPS via a cloud drive (Google Drive / Dropbox) or
RDP drive-redirection. Put it at e.g. `C:\GoldDigger\golddigger_bt.dump`, then:

```powershell
$env:PGPASSWORD = "midas"   # the postgres pw bootstrap used
pg_restore -U postgres -d golddigger_bt --no-owner --clean --if-exists C:\GoldDigger\golddigger_bt.dump
```
*(verify)* row counts match the Mac:
```powershell
psql -U postgres -d golddigger_bt -c "SELECT (SELECT count(*) FROM bt_runs) runs, (SELECT count(*) FROM bt_trades) trades, (SELECT count(*) FROM bt_signals) signals;"
```

---

## Phase 4 — Dashboard smoke (local)

```powershell
C:\GoldDigger\scripts\windows\run_dashboard.ps1
```
Open `http://127.0.0.1:8001/` in the VPS browser. *(verify)* landing + pages
load, historical Trades/Backtest show data from the restored DB. Ctrl-C to stop.

---

## Phase 5 — MT5 + DWX EA (manual GUI — only you can do this)

1. Install **MetaTrader 5** (JustMarkets build). Log into the **same JM-Demo2**
   demo account (required to adopt the 3 open positions). *(verify)* balance/equity
   matches the Mac.
2. Copy the DWX EA + its `Common\Files\DWX` protocol into the VPS MT5. Attach the
   EA to an **XAUUSD.ecn M15** chart.
3. Enable **AutoTrading** (toolbar) + Tools→Options→Expert Advisors: allow
   automated trading + allow DLL/file imports.
4. Confirm the bridge dir exists + updates:
   ```powershell
   $dwx = "$env:APPDATA\MetaQuotes\Terminal\Common\Files\DWX"
   Get-Item "$dwx\account_info.json" | Select LastWriteTime   # should be < 10s old
   ```
   If MT5 runs under a different Windows user, note the real path and set
   `DWX_DIR` accordingly in `_env.ps1` (or as a machine env var).
5. Restart the dashboard, open the Live page. *(verify)* `account_live` shows
   JM-Demo2 truth and the **3 open positions** appear.

Optional dry-run smoke (no orders sent), one leg for a few bars:
```powershell
cd C:\GoldDigger
. .\scripts\windows\_env.ps1
python -m bt_engine.runner.cli live --strategy fib_v2_intraday_a --symbol XAUUSD.ecn --timeframe M15 --dry-run --max-ticks 3
```

---

## Phase 6 — Public dashboard (caddy + TLS + auth)

1. Install caddy + open firewall:
   ```powershell
   winget install CaddyServer.Caddy -e --silent --accept-package-agreements --accept-source-agreements
   New-NetFirewallRule -DisplayName "HTTP"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
   New-NetFirewallRule -DisplayName "HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
   ```
   Also open 80 + 443 in the **Contabo control-panel firewall** if present.
2. Generate an auth hash + paste it into `scripts\windows\Caddyfile` (replace the placeholder):
   ```powershell
   caddy hash-password --plaintext 'PICK_A_STRONG_PASSWORD'
   ```
3. Run caddy (foreground to test, then as a service):
   ```powershell
   caddy run --config C:\GoldDigger\scripts\windows\Caddyfile
   ```
   *(verify)* browse `https://midas.subashtrades.in` from your laptop → auth
   prompt → dashboard, valid Let's Encrypt cert.

---

## Phase 7 — CUTOVER (the critical window)

**Order is mandatory. The 3 positions are safe at the broker on SL/TP during the gap.**

1. **On the Mac** — stop both live runners + engage kill switch:
   ```bash
   touch /Users/subash/SUBASH/GoldDigger/LIVE_DISABLED
   pkill -f "runner.cli live"
   pgrep -f "runner.cli live" || echo "MAC RUNNERS DEAD"
   ```
2. **On the Mac** — log MT5 **out** (or quit MT5) so it can't double-connect.
3. **On the Mac** — take a FRESH dump (captures the latest position/trade state):
   ```bash
   /opt/homebrew/opt/postgresql@15/bin/pg_dump -Fc -Z6 golddigger_bt -f /tmp/golddigger_bt_final.dump
   ```
   Move it to the VPS, re-restore (Phase 3 command, new filename).
4. **On the VPS** — register services + start them:
   ```powershell
   C:\GoldDigger\scripts\windows\install_services.ps1
   nssm start midas-dashboard
   nssm start midas-live-a
   nssm start midas-live-d
   ```
5. *(verify)* VPS Live page: 3 positions adopted with correct tickets
   `2118599832` (long 0.01), `2121027691` (long 0.05), `2123464608` (short 0.13);
   live P&L ticking. Logs in `C:\GoldDigger\logs\live_a.log` / `live_d.log` show
   `[BAR]` lines and no traceback.

---

## Phase 8 — Supervision + watch

- Services auto-restart (NSSM `AppExit Default Restart`) + start on boot.
- Schedule health snapshots every 15 min:
  ```powershell
  $act = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File C:\GoldDigger\scripts\windows\health_snapshot.ps1"
  $trg = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
  Register-ScheduledTask -TaskName "midas-health" -Action $act -Trigger $trg -RunLevel Highest -User "SYSTEM"
  ```
- Register caddy as a service too (NSSM) so the public dashboard survives reboot.
- **24-48h watch:** dashboard numbers sane, no orphaned tickets, adopted positions
  survive a service restart, first VPS-originated order fills cleanly (the real
  broker-parity test on the new machine).

---

## Rollback
If anything looks wrong post-cutover: `nssm stop midas-live-a; nssm stop midas-live-d`,
remove `LIVE_DISABLED` on the Mac, restart the Mac runners. The account + 3
positions are untouched at the broker throughout. Only ONE machine's runners may
be live at a time.

## Kill switch (VPS)
```powershell
New-Item -ItemType File C:\GoldDigger\LIVE_DISABLED   # runners abort on next poll
```
