<#
  Post-cutover live health check. Read-only. Confirms the VPS runners adopted
  the open positions and everything is streaming. Run anytime after go_live.

  Usage: C:\GoldDigger\scripts\windows\verify_live.ps1
#>
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "_env.ps1")
$pgbin = "C:\Program Files\PostgreSQL\15\bin"
$env:PGPASSWORD = "postgres"
$env:Path += ";$pgbin;C:\nssm"
$LogDir = Join-Path $Repo "logs"

function Section($m){ Write-Host "`n=== $m ===" -ForegroundColor Cyan }

# 1. Service states.
Section "NSSM service status"
foreach ($s in @("midas-dashboard","midas-live-a","midas-live-d")) {
  $st = & nssm status $s 2>&1
  $col = if ("$st" -match "RUNNING") { "Green" } else { "Red" }
  Write-Host ("  {0,-18} {1}" -f $s, $st) -ForegroundColor $col
}

# 2. Processes.
Section "Python processes"
$cmds = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object -ExpandProperty CommandLine
$aOk = [bool]($cmds -match "fib_v2_intraday_a")
$dOk = [bool]($cmds -match "fib_v2_intraday_d")
$uOk = [bool]($cmds -match "uvicorn")
Write-Host ("  live-a: {0}   live-d: {1}   dashboard: {2}" -f `
  $(if($aOk){"UP"}else{"DOWN"}), $(if($dOk){"UP"}else{"DOWN"}), $(if($uOk){"UP"}else{"DOWN"}))

# 3. Log tails (both NSSM redirect + launcher paths).
Section "live-a log (last 25)"
foreach ($p in @("$LogDir\midas-live-a.out.log","$LogDir\midas-live-a.err.log","$LogDir\live_a.log")) {
  if (Test-Path $p) { Write-Host "-- $p --" -ForegroundColor DarkGray; Get-Content $p -Tail 25 }
}
Section "live-d log (last 25)"
foreach ($p in @("$LogDir\midas-live-d.out.log","$LogDir\midas-live-d.err.log","$LogDir\live_d.log")) {
  if (Test-Path $p) { Write-Host "-- $p --" -ForegroundColor DarkGray; Get-Content $p -Tail 25 }
}
Section "dashboard log (last 10)"
foreach ($p in @("$LogDir\midas-dashboard.out.log","$LogDir\midas-dashboard.err.log")) {
  if (Test-Path $p) { Write-Host "-- $p --" -ForegroundColor DarkGray; Get-Content $p -Tail 10 }
}

# 4. DB open positions (should still be the 2 longs, now owned by fresh live runs).
Section "DB open positions"
& "$pgbin\psql.exe" -U postgres -d golddigger_bt -c "SELECT broker_ticket, leg, side, entry_price, run_id FROM bt_trades WHERE exit_timestamp IS NULL ORDER BY broker_ticket;"

Section "Active (unended) live runs"
& "$pgbin\psql.exe" -U postgres -d golddigger_bt -c "SELECT ref, strategy_id, created_at, end_ts FROM bt_runs WHERE mode='live' AND end_ts IS NULL ORDER BY created_at DESC LIMIT 6;"

# 5. Dashboard HTTP.
Section "Dashboard HTTP"
foreach ($u in @("http://127.0.0.1:8001/","http://127.0.0.1:8001/api/runs?limit=1")) {
  try {
    $r = Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 8
    Write-Host ("  {0} -> HTTP {1}" -f $u, $r.StatusCode) -ForegroundColor Green
  } catch { Write-Host ("  {0} -> ERR {1}" -f $u, $_) -ForegroundColor Red }
}

# 6. EA freshness.
Section "DWX EA heartbeat"
$acct = Join-Path $env:DWX_DIR "account_info.json"
if (Test-Path $acct) {
  $age = [int]((Get-Date) - (Get-Item $acct).LastWriteTime).TotalSeconds
  $col = if ($age -lt 15) { "Green" } else { "Red" }
  $j = Get-Content $acct -Raw | ConvertFrom-Json
  Write-Host ("  account_info.json {0}s old | server={1} balance={2} equity={3}" -f $age, $j.server, $j.balance, $j.equity) -ForegroundColor $col
} else { Write-Host "  no account_info.json" -ForegroundColor Red }

Section "SUMMARY"
if ($aOk -and $dOk -and $uOk) {
  Write-Host "All three services UP. Review logs above for 'adopted'/[BAR] lines + no tracebacks." -ForegroundColor Green
} else {
  Write-Host "One or more DOWN -- inspect the .err.log tail above." -ForegroundColor Red
}
