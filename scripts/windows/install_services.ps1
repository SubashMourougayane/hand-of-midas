# Register A, D, and the dashboard as NSSM services (auto-restart + start on boot).
# Requires NSSM on PATH (https://nssm.cc). Run as Administrator.
# Re-runnable: removes an existing service of the same name before re-adding.
. (Join-Path $PSScriptRoot "_env.ps1")

$Pwsh = (Get-Command powershell.exe).Source  # Windows PowerShell host

# Resolve absolute python.exe + its Scripts dir. Services run as LocalSystem,
# which does NOT inherit the user-scoped Python 3.14 PATH, so the launchers'
# bare `python` would fail. Inject the full python dir onto the service PATH.
$PyExe = (Get-Command python).Source
$PyDir = Split-Path $PyExe -Parent
$PgBin = "C:\Program Files\PostgreSQL\15\bin"
$SvcPath = "$PyDir;$PgBin;C:\nssm;$env:SystemRoot\System32;$env:SystemRoot"
$DbUrl = if ($env:BT_ENGINE_DB_URL) { $env:BT_ENGINE_DB_URL } else { "postgresql+psycopg2://postgres:postgres@localhost:5432/golddigger_bt" }

function Register-Svc($name, $script) {
  $existing = & nssm status $name 2>$null
  if ($LASTEXITCODE -eq 0) { & nssm stop $name; & nssm remove $name confirm }
  & nssm install $name $Pwsh "-ExecutionPolicy Bypass -File `"$script`""
  & nssm set $name AppDirectory $Repo
  & nssm set $name Start SERVICE_AUTO_START
  & nssm set $name AppExit Default Restart
  & nssm set $name AppRestartDelay 5000
  # Env is NOT inherited by services -- pass everything the launchers need.
  & nssm set $name AppEnvironmentExtra "PYTHONPATH=$($env:PYTHONPATH)" "DWX_DIR=$($env:DWX_DIR)" "BT_ENGINE_DB_URL=$DbUrl" "PATH=$SvcPath"
  Write-Output "registered service: $name  (python=$PyExe)"
}

Register-Svc "midas-live-a"    (Join-Path $PSScriptRoot "live_a.ps1")
Register-Svc "midas-live-d"    (Join-Path $PSScriptRoot "live_d.ps1")
Register-Svc "midas-dashboard" (Join-Path $PSScriptRoot "run_dashboard.ps1")

Write-Output ""
Write-Output "Start with:  nssm start midas-dashboard ; nssm start midas-live-a ; nssm start midas-live-d"
Write-Output "IMPORTANT: do NOT start the live services until the Mac runners are stopped (cutover)."
