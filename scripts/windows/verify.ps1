<#
  End-to-end verification of the VPS install BEFORE going live.
  Runs every automated check and prints a PASS/FAIL summary. Read-only:
  starts NO live trading, sends NO orders. Safe to run anytime.

  Usage (elevated PowerShell):
    C:\GoldDigger\scripts\windows\verify.ps1
#>
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "_env.ps1")
$pgbin = "C:\Program Files\PostgreSQL\15\bin"
$env:PGPASSWORD = "postgres"
$env:Path += ";$pgbin"

$results = [ordered]@{}
function Check($name, $ok, $detail) {
  $results[$name] = [bool]$ok
  $tag = if ($ok) { "PASS" } else { "FAIL" }
  $col = if ($ok) { "Green" } else { "Red" }
  Write-Host ("[{0}] {1} :: {2}" -f $tag, $name, $detail) -ForegroundColor $col
}

Write-Host "`n===== VPS VERIFY =====" -ForegroundColor Cyan
Set-Location $Repo

# 1. Tooling present.
try { $py = (python --version) 2>&1; Check "python" $true $py } catch { Check "python" $false "$_" }
try { $nd = (node --version) 2>&1;   Check "node"   $true $nd } catch { Check "node" $false "$_" }
try { $pg = (& "$pgbin\psql.exe" --version) 2>&1; Check "psql" $true $pg } catch { Check "psql" $false "$_" }

# 2. Package imports on this Python.
$imp = python -c "import bt_engine, pandas, numpy, sqlalchemy, asyncpg, fastapi, uvicorn; print('ok')" 2>&1
Check "imports" ($imp -match "ok") "$imp"

# 3. SPA build present.
$spa = Test-Path "$Repo\dashboard\dist\index.html"
Check "spa_dist" $spa "$Repo\dashboard\dist\index.html"

# 4. DB reachable + row counts (history migrated).
$counts = & "$pgbin\psql.exe" -U postgres -d golddigger_bt -tAF',' -c "SELECT (SELECT count(*) FROM bt_runs),(SELECT count(*) FROM bt_trades),(SELECT count(*) FROM bt_signals),(SELECT count(*) FROM bt_journal_events);" 2>&1
$parts = "$counts".Trim().Split(',')
$journalOk = ($parts.Count -eq 4 -and [int]$parts[3] -gt 0)
Check "db_counts" $journalOk "runs=$($parts[0]) trades=$($parts[1]) signals=$($parts[2]) journal=$($parts[3])"

# 5. BT==live parity on THIS python (the deploy-critical gate). A few min.
Write-Host "`n-- running parity gates (a few min) --" -ForegroundColor DarkGray
$env:PYTHONPATH = "$Repo\bt_engine;$Repo\dashboard_backend"
python -m pytest `
  bt_engine/tests/parity/test_parity_fib_v2_intraday_a.py `
  bt_engine/tests/parity/test_parity_fib_v2_intraday_d.py `
  bt_engine/tests/parity/test_live_to_replay.py `
  bt_engine/tests/parity/test_provider_parity.py `
  -q 2>&1 | Tee-Object -Variable pytestOut | Out-Host
$lastLine = ($pytestOut | Select-String "passed|failed|error" | Select-Object -Last 1)
$parityOk = ($pytestOut -match "passed" -and $pytestOut -notmatch "failed")
Check "bt_live_parity" $parityOk (if ($lastLine) { $lastLine.ToString().Trim() } else { "no pytest summary" })

# 6. Dashboard boots + serves (start in a job, poll, kill).
Write-Host "`n-- booting dashboard for a health check --" -ForegroundColor DarkGray
$job = Start-Job -ScriptBlock {
  param($repo)
  $env:PYTHONPATH = "$repo\bt_engine;$repo\dashboard_backend"
  $env:BT_ENGINE_DB_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/golddigger_bt"
  Set-Location $repo
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
} -ArgumentList $Repo
Start-Sleep 10
$httpOk = $false; $httpDetail = "no response"
try {
  $r = Invoke-WebRequest "http://127.0.0.1:8001/" -UseBasicParsing -TimeoutSec 10
  $httpOk = ($r.StatusCode -eq 200); $httpDetail = "root HTTP $($r.StatusCode)"
} catch { $httpDetail = "root ERR $_" }
try {
  $api = Invoke-WebRequest "http://127.0.0.1:8001/api/runs?limit=1" -UseBasicParsing -TimeoutSec 10
  $httpDetail += " | /api/runs HTTP $($api.StatusCode)"
} catch { $httpDetail += " | /api/runs ERR" }
Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -Force -ErrorAction SilentlyContinue
Check "dashboard_http" $httpOk $httpDetail

# ===== summary =====
Write-Host "`n===== SUMMARY =====" -ForegroundColor Cyan
$failCount = 0
foreach ($k in $results.Keys) {
  $ok = $results[$k]
  if (-not $ok) { $failCount++ }
  $t = if ($ok) { "PASS" } else { "FAIL" }
  $c = if ($ok) { "Green" } else { "Red" }
  Write-Host ("  {0,-16} {1}" -f $k, $t) -ForegroundColor $c
}
if ($failCount -eq 0) {
  Write-Host "`nALL GREEN. Ready for MT5 setup (manual) then cutover." -ForegroundColor Green
} else {
  Write-Host "`n$failCount FAILED -- do NOT proceed to cutover. Paste output." -ForegroundColor Red
}
