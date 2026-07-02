# Restore the Mac Postgres dump into golddigger_bt on the VPS.
# Default dump path = the Downloads folder. Override with -DumpPath.
# DESTRUCTIVE + idempotent: DROPs golddigger_bt and recreates it fresh, so a
# re-run after a killed/partial restore always starts clean.
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
Write-Host "Restoring $DumpPath ($size) into a FRESH golddigger_bt ..." -ForegroundColor Cyan

# 1. Kick any open connections so DROP DATABASE can proceed.
Write-Host "Terminating open connections to golddigger_bt ..." -ForegroundColor DarkGray
& "$pgbin\psql.exe" -U postgres -d postgres -c @"
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE datname='golddigger_bt' AND pid <> pg_backend_pid();
"@ 2>$null

# 2. Drop + recreate fresh (wipes any partial data from a killed run).
& "$pgbin\dropdb.exe"   -U postgres --if-exists golddigger_bt
& "$pgbin\createdb.exe" -U postgres golddigger_bt

# 3. Restore into the empty DB. --no-owner: ignore Mac role 'subash'.
#    -j 4: parallel (faster on the big bt_signals table).
#    -v: verbose so each table/index prints as it loads (not a silent wait).
& "$pgbin\pg_restore.exe" -U postgres -d golddigger_bt --no-owner -j 4 -v $DumpPath

Write-Host "`nRow counts:" -ForegroundColor Cyan
& "$pgbin\psql.exe" -U postgres -d golddigger_bt -c @"
SELECT
  (SELECT count(*) FROM bt_runs)            AS runs,
  (SELECT count(*) FROM bt_trades)          AS trades,
  (SELECT count(*) FROM bt_signals)         AS signals,
  (SELECT count(*) FROM bt_journal_events)  AS journal;
"@
Write-Host "`nExpected (Mac source): journal=170109. Compare above." -ForegroundColor Green
