# Restore the Mac Postgres dump into golddigger_bt on the VPS.
# Default dump path = the Downloads folder. Override with -DumpPath.
# Idempotent: --clean --if-exists drops existing objects first.
param(
  [string]$DumpPath = "$env:USERPROFILE\Downloads\golddigger_bt.dump",
  [string]$PgPassword = "postgres"
)
$ErrorActionPreference = "Stop"
$pgbin = "C:\Program Files\PostgreSQL\15\bin"
$env:PGPASSWORD = $PgPassword

if (-not (Test-Path $DumpPath)) {
  throw "Dump not found at $DumpPath  (pass -DumpPath 'C:\full\path\golddigger_bt.dump')"
}
$size = "{0:N1} MB" -f ((Get-Item $DumpPath).Length / 1MB)
Write-Host "Restoring $DumpPath ($size) into golddigger_bt ..." -ForegroundColor Cyan

# Ensure DB exists (no-op if present).
& "$pgbin\createdb.exe" -U postgres golddigger_bt 2>$null

# Restore. --no-owner: ignore Mac role 'subash'. --clean --if-exists: overwrite.
# -j 4: parallel restore (faster on the big bt_signals table).
& "$pgbin\pg_restore.exe" -U postgres -d golddigger_bt --no-owner --clean --if-exists -j 4 $DumpPath

Write-Host "`nRow counts:" -ForegroundColor Cyan
& "$pgbin\psql.exe" -U postgres -d golddigger_bt -c @"
SELECT
  (SELECT count(*) FROM bt_runs)            AS runs,
  (SELECT count(*) FROM bt_trades)          AS trades,
  (SELECT count(*) FROM bt_signals)         AS signals,
  (SELECT count(*) FROM bt_journal_events)  AS journal;
"@
Write-Host "`nExpected (Mac source): journal=170109. Compare above." -ForegroundColor Green
