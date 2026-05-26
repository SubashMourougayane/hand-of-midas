# Hand Of Midas - Windows VPS Setup Script
# Run: powershell -ExecutionPolicy Bypass -File scripts\win-setup.ps1

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  HAND OF MIDAS - Windows VPS Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 1. Find MT5
Write-Host "[1/7] Finding MT5 installation..." -ForegroundColor Yellow
$terminalBase = "$env:APPDATA\MetaQuotes\Terminal"
$terminals = Get-ChildItem $terminalBase -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "Common" -and $_.Name -ne "Community" }

if ($terminals.Count -eq 0) {
    Write-Host "  ERROR: No MT5 terminal found at $terminalBase" -ForegroundColor Red
    exit 1
}

$terminalDir = $terminals[0].FullName
$mql5Dir = "$terminalDir\MQL5"
$expertsDir = "$mql5Dir\Experts"
$commonFiles = "$terminalBase\Common\Files"

Write-Host "  Terminal: $terminalDir" -ForegroundColor Green
Write-Host "  Experts: $expertsDir" -ForegroundColor Green
Write-Host "  Common Files: $commonFiles" -ForegroundColor Green

# 2. Copy DWX EA
Write-Host ""
Write-Host "[2/7] Installing DWX_Server EA..." -ForegroundColor Yellow
$eaSource = "C:\hand-of-midas\mql5\DWX_Server.mq5"
$eaDest = "$expertsDir\DWX_Server.mq5"

if (Test-Path $eaSource) {
    Copy-Item $eaSource $eaDest -Force
    Write-Host "  Copied EA to: $eaDest" -ForegroundColor Green
    Write-Host "  NEXT: Open MetaEditor (F4), open DWX_Server.mq5, press F7 to compile" -ForegroundColor Magenta
} else {
    Write-Host "  ERROR: $eaSource not found!" -ForegroundColor Red
}

# 3. Create DWX directories
Write-Host ""
Write-Host "[3/7] Creating DWX directories..." -ForegroundColor Yellow
$dwxDir = "$commonFiles\DWX"
$cmdDir = "$dwxDir\commands"
New-Item -ItemType Directory -Force -Path $dwxDir | Out-Null
New-Item -ItemType Directory -Force -Path $cmdDir | Out-Null
Write-Host "  Created: $dwxDir" -ForegroundColor Green

# 4. Create .env
Write-Host ""
Write-Host "[4/7] Creating .env configuration..." -ForegroundColor Yellow
$envPath = "C:\hand-of-midas\.env"
$dwxPathForward = $dwxDir -replace "\\", "/"

$lines = @(
    "EXECUTOR=mt5",
    "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/golddigger",
    "DWX_DIR=$dwxPathForward"
)
$lines | Set-Content -Path $envPath
Write-Host "  Written: $envPath" -ForegroundColor Green
foreach ($l in $lines) { Write-Host "    $l" -ForegroundColor Gray }

# 5. Install Python packages
Write-Host ""
Write-Host "[5/7] Installing Python packages..." -ForegroundColor Yellow
$pipResult = pip install fastapi uvicorn numpy pandas apscheduler psycopg2-binary python-dotenv httpx 2>&1
$pipResult | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" }

# 6. Setup PostgreSQL
Write-Host ""
Write-Host "[6/7] Setting up PostgreSQL database..." -ForegroundColor Yellow
$psqlPaths = @(
    "C:\Program Files\PostgreSQL\17\bin\psql.exe",
    "C:\Program Files\PostgreSQL\16\bin\psql.exe",
    "C:\Program Files\PostgreSQL\15\bin\psql.exe"
)
$psql = $psqlPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($psql) {
    Write-Host "  Found psql: $psql" -ForegroundColor Green
    & $psql -U postgres -c "CREATE DATABASE golddigger;" 2>&1 | Out-Null
    $schemaFile = "C:\hand-of-midas\database\schema.sql"
    if (Test-Path $schemaFile) {
        & $psql -U postgres -d golddigger -f $schemaFile 2>&1 | Out-Null
        Write-Host "  Database golddigger created + schema loaded" -ForegroundColor Green
    } else {
        Write-Host "  Schema file not found: $schemaFile" -ForegroundColor Red
    }
} else {
    Write-Host "  PostgreSQL not found. Install it first, then re-run this script." -ForegroundColor Red
}

# 7. Summary
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SETUP COMPLETE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  MANUAL STEPS REMAINING:" -ForegroundColor Yellow
Write-Host "  1. MT5: MetaEditor (F4) - Open DWX_Server.mq5 - Compile (F7)" -ForegroundColor White
Write-Host "  2. MT5: Drag DWX_Server onto XAUUSD.ecn chart" -ForegroundColor White
Write-Host "  3. MT5: Enable Algo Trading button in toolbar" -ForegroundColor White
Write-Host "  4. Verify DWX files:" -ForegroundColor White
Write-Host "     dir `"$dwxDir`"" -ForegroundColor Gray
Write-Host ""
Write-Host "  START TRADING:" -ForegroundColor Yellow
Write-Host "  cd C:\hand-of-midas" -ForegroundColor White
Write-Host "  python -m uvicorn backend.main:app --host 0.0.0.0 --port 5053" -ForegroundColor White
Write-Host ""
Write-Host "  TEST DWX:" -ForegroundColor Yellow
Write-Host "  cd C:\hand-of-midas" -ForegroundColor White
Write-Host "  python -c ""from backend.execution.mt5_executor import get_dwx_status; print(get_dwx_status())""" -ForegroundColor White
Write-Host ""
