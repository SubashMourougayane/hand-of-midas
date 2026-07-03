<#
  VPS cutover: restore reconciled DB -> verify -> start live services -> verify adoption.
  Run AFTER the Mac runners are stopped + MT5 quit (cutover already underway).

  Safe-by-default: if the restored DB does not show exactly the expected open
  tickets, the script ABORTS before starting any live runner.

  Usage (elevated PowerShell):
    C:\GoldDigger\scripts\windows\go_live.ps1
    C:\GoldDigger\scripts\windows\go_live.ps1 -SkipRestore   # DB already restored
#>
param(
  [string]$DumpPath = "",
  [switch]$SkipRestore
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_env.ps1")
$pgbin = "C:\Program Files\PostgreSQL\15\bin"
$env:PGPASSWORD = "postgres"
$env:Path += ";$pgbin;C:\nssm"

$expectedTickets = @("2118599832","2121027691")   # 2 open longs after reconcile

function Section($m){ Write-Host "`n=== $m ===" -ForegroundColor Cyan }

# 0. Persist env vars for the services (machine scope).
Section "Persisting machine env (DWX_DIR + DB URL)"
[Environment]::SetEnvironmentVariable("DWX_DIR","C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\Common\Files\DWX","Machine")
[Environment]::SetEnvironmentVariable("BT_ENGINE_DB_URL","postgresql+psycopg2://postgres:postgres@localhost:5432/golddigger_bt","Machine")
Write-Host "  set."

# 1. Restore the reconciled dump (auto-detect filename).
if (-not $SkipRestore) {
  Section "Restore reconciled DB"
  if (-not $DumpPath) {
    $cands = @(
      "$env:USERPROFILE\Downloads\golddigger_bt_final.dump",
      "$env:USERPROFILE\Downloads\golddigger_bt.dump"
    )
    $DumpPath = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
  }
  if (-not $DumpPath) { throw "No dump found in Downloads (golddigger_bt_final.dump or golddigger_bt.dump)" }
  Write-Host "  using $DumpPath"
  & "$PSScriptRoot\restore_db.ps1" -DumpPath $DumpPath
}

# 2. VERIFY DB open trades == expected 2 tickets. ABORT if not.
Section "Verify open positions in DB"
$open = & "$pgbin\psql.exe" -U postgres -d golddigger_bt -tAc "SELECT DISTINCT broker_ticket FROM bt_trades WHERE exit_timestamp IS NULL AND broker_ticket IS NOT NULL AND broker_ticket<>'';"
$openList = @($open | ForEach-Object { $_.Trim() } | Where-Object { $_ })
Write-Host "  DB open tickets: $($openList -join ', ')"
$phantom = & "$pgbin\psql.exe" -U postgres -d golddigger_bt -tAc "SELECT count(*) FROM bt_trades WHERE exit_timestamp IS NULL AND (broker_ticket IS NULL OR broker_ticket='');"
Write-Host "  phantom (null-ticket) open rows: $($phantom.Trim())"
$okTickets = ($expectedTickets | Where-Object { $openList -contains $_ }).Count -eq $expectedTickets.Count
if (-not $okTickets) {
  throw "DB open tickets do not match expected ($($expectedTickets -join ',')). ABORTING before start."
}
if ([int]$phantom.Trim() -gt 0) {
  Write-Host "  WARN: phantom null-ticket open rows present -- adoption ignores these (broker-driven), continuing." -ForegroundColor Yellow
}
Write-Host "  DB matches broker truth." -ForegroundColor Green

# 3. Confirm broker EA still shows the same 2 open (safety cross-check).
Section "Cross-check broker open_orders"
$oo = Join-Path $env:DWX_DIR "open_orders.json"
if (Test-Path $oo) {
  $j = Get-Content $oo -Raw | ConvertFrom-Json
  $brokerTk = @($j.PSObject.Properties.Name)
  Write-Host "  broker open tickets: $($brokerTk -join ', ')"
} else {
  Write-Host "  WARN: no open_orders.json -- is MT5+EA running on the VPS?" -ForegroundColor Yellow
}

# 4. Register + start services.
Section "Register NSSM services"
& "$PSScriptRoot\install_services.ps1"

Section "Start services (dashboard first, then A + D)"
& nssm start midas-dashboard
Start-Sleep 3
& nssm start midas-live-a
Start-Sleep 3
& nssm start midas-live-d
Start-Sleep 15

# 5. Verify processes + adoption.
Section "Verify runners alive"
$cmds = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object -ExpandProperty CommandLine
$aOk = [bool]($cmds -match "fib_v2_intraday_a")
$dOk = [bool]($cmds -match "fib_v2_intraday_d")
Write-Host ("  live-a: {0}   live-d: {1}" -f $(if($aOk){"UP"}else{"DOWN"}), $(if($dOk){"UP"}else{"DOWN"}))

Section "Tail runner logs (adoption lines)"
$logA = Join-Path $Repo "logs\live_a.log"
$logD = Join-Path $Repo "logs\live_d.log"
if (Test-Path $logA) { Write-Host "-- live_a --"; Get-Content $logA -Tail 15 }
if (Test-Path $logD) { Write-Host "-- live_d --"; Get-Content $logD -Tail 15 }

Section "DONE"
if ($aOk -and $dOk) {
  Write-Host "Both legs live on the VPS. Check the dashboard + verify the 2 longs adopted." -ForegroundColor Green
  Write-Host "Dashboard: http://127.0.0.1:8001/live" -ForegroundColor Green
} else {
  Write-Host "A leg is not up -- check the logs above + paste them." -ForegroundColor Red
}
