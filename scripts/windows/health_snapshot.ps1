# Autonomous health snapshot (Windows). Writes logs\monitor\snap_<epoch>.json:
#   - EA alive age (account_info.json mtime)
#   - balance / equity from DWX
#   - A / D live proc alive?
#   - open trades count from DWX
# Schedule every 15 min via Task Scheduler.
. (Join-Path $PSScriptRoot "_env.ps1")

$Ts = [int][double]::Parse((Get-Date -UFormat %s))
$OutDir = Join-Path $Repo "logs\monitor"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Out = Join-Path $OutDir "snap_$Ts.json"

$Dwx = $env:DWX_DIR
$acct = Join-Path $Dwx "account_info.json"
$eaAge = -1; $balance = "null"; $equity = "null"
if (Test-Path $acct) {
  $eaAge = $Ts - [int][double]::Parse((Get-Date (Get-Item $acct).LastWriteTimeUtc -UFormat %s))
  try {
    $j = Get-Content $acct -Raw | ConvertFrom-Json
    if ($null -ne $j.balance) { $balance = $j.balance }
    if ($null -ne $j.equity)  { $equity  = $j.equity }
  } catch {}
}

# Live procs: match the CLI command line via WMI (Get-Process has no args).
$cmds = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object -ExpandProperty CommandLine
$aAlive = [int]([bool]($cmds -match "fib_v2_intraday_a"))
$dAlive = [int]([bool]($cmds -match "fib_v2_intraday_d"))

$openOrders = Join-Path $Dwx "open_orders.json"
$openCount = "null"
if (Test-Path $openOrders) {
  try {
    $oo = Get-Content $openOrders -Raw | ConvertFrom-Json
    $openCount = ($oo.PSObject.Properties | Measure-Object).Count
  } catch {}
}

$snap = [ordered]@{
  ts = $Ts; ea_age_s = $eaAge; balance = $balance; equity = $equity
  a_alive = $aAlive; d_alive = $dAlive; open_trades = $openCount
}
$snap | ConvertTo-Json -Compress | Set-Content -Path $Out -Encoding utf8
Write-Output "wrote $Out (ea_age=${eaAge}s a=$aAlive d=$dAlive open=$openCount)"
