# Register A, D, and the dashboard as NSSM services (auto-restart + start on boot).
# Requires NSSM on PATH (https://nssm.cc). Run as Administrator.
# Re-runnable: removes an existing service of the same name before re-adding.
. (Join-Path $PSScriptRoot "_env.ps1")

$Pwsh = (Get-Command powershell.exe).Source  # Windows PowerShell host

# Resolve the REAL python.exe. Get-Command may return the Microsoft Store alias
# stub (C:\...\WindowsApps\python.exe) which is a no-op under a service (no user
# session) -- the service would "start" then instantly exit with empty logs.
# Prefer the actual pythoncore install; fall back to Get-Command only if needed.
$PyCandidates = @(
  "C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe",
  "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
) + @((Get-Command python -All -ErrorAction SilentlyContinue).Source)
$PyExe = $PyCandidates | Where-Object { $_ -and (Test-Path $_) -and ($_ -notlike "*WindowsApps*") } | Select-Object -First 1
if (-not $PyExe) { throw "No real python.exe found (only the WindowsApps stub). Fix Python install." }
$PyDir = Split-Path $PyExe -Parent
$PgBin = "C:\Program Files\PostgreSQL\15\bin"
$SvcPath = "$PyDir;$PgBin;C:\nssm;$env:SystemRoot\System32;$env:SystemRoot"
$DbUrl = if ($env:BT_ENGINE_DB_URL) { $env:BT_ENGINE_DB_URL } else { "postgresql+psycopg2://postgres:postgres@localhost:5432/golddigger_bt" }

$LogDir = Join-Path $Repo "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Register a service that runs python.exe DIRECTLY (no powershell/.ps1 wrapper --
# that layer can silently no-op under a service). $pyArgs is the argument string.
function Register-PySvc($name, $pyArgs) {
  $ErrorActionPreference = "SilentlyContinue"
  & nssm status $name 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { & nssm stop $name 2>&1 | Out-Null; & nssm remove $name confirm 2>&1 | Out-Null }
  $ErrorActionPreference = "Stop"
  & nssm install $name $PyExe $pyArgs
  & nssm set $name AppDirectory $Repo
  & nssm set $name Start SERVICE_AUTO_START
  & nssm set $name AppExit Default Restart
  & nssm set $name AppRestartDelay 5000
  # Env is NOT inherited by services -- pass everything the runner needs.
  & nssm set $name AppEnvironmentExtra "PYTHONPATH=$($env:PYTHONPATH)" "DWX_DIR=$($env:DWX_DIR)" "BT_ENGINE_DB_URL=$DbUrl" "PATH=$SvcPath"
  # Capture stdout+stderr to logfiles so failures are visible.
  & nssm set $name AppStdout (Join-Path $LogDir "$name.out.log")
  & nssm set $name AppStderr (Join-Path $LogDir "$name.err.log")
  Write-Output "registered service: $name  (python=$PyExe)"
}

# Live legs: exact production args (mirror the Mac procs). Balance 10000.
$aArgs = "-m bt_engine.runner.cli live --strategy fib_v2_intraday_a --timeframe M15 --use-equity-sizer --start-balance 10000.0 --risk-pct 0.015 --max-live-lot 2.0 --max-entry-slip-ratio 1.15 --max-open-positions 4"
$dArgs = "-m bt_engine.runner.cli live --strategy fib_v2_intraday_d --timeframe M15 --use-equity-sizer --start-balance 10000.0 --risk-pct 0.015 --max-live-lot 2.0 --max-entry-slip-ratio 1.15 --max-open-positions 4"
$dashArgs = "-m uvicorn app.main:app --host 127.0.0.1 --port 8001"

Register-PySvc "midas-live-a"    $aArgs
Register-PySvc "midas-live-d"    $dArgs
Register-PySvc "midas-dashboard" $dashArgs

Write-Output ""
Write-Output "Start with:  nssm start midas-dashboard ; nssm start midas-live-a ; nssm start midas-live-d"
Write-Output "IMPORTANT: do NOT start the live services until the Mac runners are stopped (cutover)."
