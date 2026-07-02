<#
  Verify the MT5 DWX bridge on the VPS BEFORE cutover. Read-only.
  - Locates the DWX dir (searches the MetaQuotes terminal tree).
  - Checks EA liveness (account_info.json mtime).
  - Prints account (balance/equity/login/server) + open positions.
  - Flags whether the 3 expected open tickets are present.
  - Prints the exact DWX_DIR to set in _env.ps1 if it differs from the default.

  Usage: C:\GoldDigger\scripts\windows\verify_mt5.ps1
#>
$ErrorActionPreference = "Continue"

# Open positions to adopt at cutover. The 0.13 short 2123464608 CLOSED on
# 2026-07-03 (now in closed_orders) so only the 2 longs remain. Update this if
# positions open/close before cutover.
$expected = @("2118599832","2121027691")   # 2 longs (0.01 + 0.05)
$termRoot = "$env:APPDATA\MetaQuotes\Terminal"

Write-Host "`n===== MT5 / DWX VERIFY =====" -ForegroundColor Cyan

# 1. Locate account_info.json (the EA heartbeat file).
$acctFile = Get-ChildItem $termRoot -Recurse -Filter "account_info.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $acctFile) {
  Write-Host "[FAIL] no account_info.json found under $termRoot" -ForegroundColor Red
  Write-Host "       Is the DWX EA attached + AutoTrading enabled?" -ForegroundColor Red
  return
}
$dwxDir = Split-Path $acctFile.FullName -Parent
Write-Host "DWX dir: $dwxDir" -ForegroundColor Gray

# 2. EA liveness (mtime age).
$ageSec = [int]((Get-Date) - $acctFile.LastWriteTime).TotalSeconds
$aliveOk = $ageSec -lt 15
$col = if ($aliveOk) { "Green" } else { "Red" }
Write-Host ("[{0}] EA alive :: account_info.json {1}s old" -f $(if($aliveOk){"PASS"}else{"FAIL"}), $ageSec) -ForegroundColor $col

# 3. Account snapshot.
try {
  $acct = Get-Content $acctFile.FullName -Raw | ConvertFrom-Json
  Write-Host "`n-- ACCOUNT --" -ForegroundColor Cyan
  Write-Host ("  login   : {0}" -f $acct.number)
  Write-Host ("  name    : {0}" -f $acct.name)
  Write-Host ("  server  : {0}" -f $acct.server)
  Write-Host ("  currency: {0}" -f $acct.currency)
  Write-Host ("  balance : {0}" -f $acct.balance)
  Write-Host ("  equity  : {0}" -f $acct.equity)
} catch { Write-Host "[WARN] could not parse account_info.json: $_" -ForegroundColor Yellow }

# 4. Open positions.
$ooFile = Join-Path $dwxDir "open_orders.json"
Write-Host "`n-- OPEN POSITIONS --" -ForegroundColor Cyan
$foundTickets = @()
if (Test-Path $ooFile) {
  try {
    $oo = Get-Content $ooFile -Raw | ConvertFrom-Json
    # DWX open_orders.json: keys are ticket numbers -> order dict.
    $orders = $oo.orders
    if (-not $orders) { $orders = $oo }   # some EA versions omit the wrapper
    foreach ($p in $orders.PSObject.Properties) {
      $t = $p.Name; $o = $p.Value
      $foundTickets += $t
      # DWX lot field varies by EA version: lots / volume / lot_size.
      $lots = $o.lots; if (-not $lots) { $lots = $o.volume }; if (-not $lots) { $lots = $o.lot_size }
      Write-Host ("  ticket {0}  {1}  lots={2}  open={3}  sl={4}  tp={5}" -f `
        $t, $o.type, $lots, $o.open_price, $o.SL, $o.TP)
    }
    if ($foundTickets.Count -eq 0) { Write-Host "  (none)" -ForegroundColor Yellow }
  } catch { Write-Host "[WARN] could not parse open_orders.json: $_" -ForegroundColor Yellow }
} else {
  Write-Host "[WARN] no open_orders.json at $ooFile" -ForegroundColor Yellow
}

# 5. Expected-ticket check.
Write-Host "`n-- EXPECTED TICKETS (3 open at cutover) --" -ForegroundColor Cyan
$allFound = $true
foreach ($e in $expected) {
  $hit = $foundTickets -contains $e
  if (-not $hit) { $allFound = $false }
  $c = if ($hit) { "Green" } else { "Red" }
  Write-Host ("  {0}  {1}" -f $e, $(if($hit){"PRESENT"}else{"MISSING"})) -ForegroundColor $c
}

# 6. DWX_DIR guidance.
$defaultDir = "$env:APPDATA\MetaQuotes\Terminal\Common\Files\DWX"
Write-Host "`n-- DWX_DIR --" -ForegroundColor Cyan
if ($dwxDir -ieq $defaultDir) {
  Write-Host "  matches _env.ps1 default. No change needed." -ForegroundColor Green
} else {
  Write-Host "  DIFFERS from default. Set this before starting runners:" -ForegroundColor Yellow
  Write-Host "    `$env:DWX_DIR = `"$dwxDir`"" -ForegroundColor Yellow
  Write-Host "  (or edit scripts\windows\_env.ps1 to hardcode it)" -ForegroundColor Yellow
}

Write-Host "`n===== END =====" -ForegroundColor Cyan
if ($aliveOk -and $allFound) {
  Write-Host "EA live + all 3 positions visible. Ready for cutover." -ForegroundColor Green
} else {
  Write-Host "Not ready: fix EA-alive / missing tickets above before cutover." -ForegroundColor Red
}
