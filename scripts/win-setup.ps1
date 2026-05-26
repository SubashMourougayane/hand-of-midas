# Hand Of Midas — Windows VPS Setup Script
# Run in PowerShell as Administrator on Contabo VPS
# Prerequisites: Python installed, MT5 installed and logged in

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  HAND OF MIDAS — Windows VPS Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# --- 1. Find MT5 Terminal Path ---
Write-Host "[1/7] Finding MT5 installation..." -ForegroundColor Yellow
$terminalBase = "$env:APPDATA\MetaQuotes\Terminal"
$terminals = Get-ChildItem $terminalBase -Directory | Where-Object { $_.Name -ne "Common" }

if ($terminals.Count -eq 0) {
    Write-Host "  ERROR: No MT5 terminal found!" -ForegroundColor Red
    exit 1
}

$terminalDir = $terminals[0].FullName
$mql5Dir = "$terminalDir\MQL5"
$expertsDir = "$mql5Dir\Experts"
$commonFiles = "$terminalBase\Common\Files"

Write-Host "  Terminal: $terminalDir" -ForegroundColor Green
Write-Host "  MQL5: $mql5Dir" -ForegroundColor Green
Write-Host "  Common Files: $commonFiles" -ForegroundColor Green

# --- 2. Copy DWX EA ---
Write-Host ""
Write-Host "[2/7] Installing DWX_Server EA..." -ForegroundColor Yellow
$eaSource = "C:\hand-of-midas\mql5\DWX_Server.mq5"
$eaDest = "$expertsDir\DWX_Server.mq5"

if (Test-Path $eaSource) {
    Copy-Item $eaSource $eaDest -Force
    Write-Host "  Copied to: $eaDest" -ForegroundColor Green
    Write-Host "  >>> OPEN MetaEditor (F4), open DWX_Server.mq5, press F7 to compile <<<" -ForegroundColor Magenta
} else {
    Write-Host "  ERROR: $eaSource not found!" -ForegroundColor Red
}

# --- 3. Create DWX directories ---
Write-Host ""
Write-Host "[3/7] Creating DWX directories..." -ForegroundColor Yellow
$dwxDir = "$commonFiles\DWX"
$cmdDir = "$dwxDir\commands"
New-Item -ItemType Directory -Force -Path $dwxDir | Out-Null
New-Item -ItemType Directory -Force -Path $cmdDir | Out-Null
Write-Host "  Created: $dwxDir" -ForegroundColor Green
Write-Host "  Created: $cmdDir" -ForegroundColor Green

# --- 4. Create .env ---
Write-Host ""
Write-Host "[4/7] Creating .env configuration..." -ForegroundColor Yellow
$envPath = "C:\hand-of-midas\.env"
$dwxPath = $dwxDir -replace "\\", "/"

$envContent = @"
EXECUTOR=mt5
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/golddigger
DWX_DIR=$dwxPath
"@

Set-Content -Path $envPath -Value $envContent
Write-Host "  Written: $envPath" -ForegroundColor Green
Write-Host "  EXECUTOR=mt5" -ForegroundColor Green
Write-Host "  DWX_DIR=$dwxPath" -ForegroundColor Green

# --- 5. Install Python packages ---
Write-Host ""
Write-Host "[5/7] Installing Python packages..." -ForegroundColor Yellow
pip install fastapi uvicorn numpy pandas apscheduler psycopg2-binary python-dotenv httpx 2>&1 | Select-Object -Last 3

# --- 6. Setup PostgreSQL database ---
Write-Host ""
Write-Host "[6/7] Setting up PostgreSQL database..." -ForegroundColor Yellow
$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
if (Test-Path $psql) {
    & $psql -U postgres -c "CREATE DATABASE golddigger;" 2>&1 | Out-Null
    & $psql -U postgres -d golddigger -f "C:\hand-of-midas\database\schema.sql" 2>&1 | Select-Object -Last 3
    Write-Host "  Database 'golddigger' created and schema loaded" -ForegroundColor Green
} else {
    Write-Host "  PostgreSQL not found at default path. Install it or adjust path." -ForegroundColor Red
    Write-Host "  After installing, run:" -ForegroundColor Yellow
    Write-Host "    psql -U postgres -c `"CREATE DATABASE golddigger;`"" -ForegroundColor White
    Write-Host "    psql -U postgres -d golddigger -f C:\hand-of-midas\database\schema.sql" -ForegroundColor White
}

# --- 7. Summary ---
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SETUP COMPLETE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  NEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1. In MT5: MetaEditor (F4) -> Open DWX_Server.mq5 -> Compile (F7)" -ForegroundColor White
Write-Host "  2. In MT5: Drag DWX_Server onto XAUUSD.ecn chart" -ForegroundColor White
Write-Host "  3. Enable 'Algo Trading' button in MT5 toolbar" -ForegroundColor White
Write-Host "  4. Verify DWX files appear:" -ForegroundColor White
Write-Host "     dir $dwxDir" -ForegroundColor Gray
Write-Host ""
Write-Host "  TO START TRADING:" -ForegroundColor Yellow
Write-Host "  cd C:\hand-of-midas" -ForegroundColor White
Write-Host "  python -m uvicorn backend.main:app --host 0.0.0.0 --port 5053" -ForegroundColor White
Write-Host ""
Write-Host "  TO TEST DWX CONNECTION:" -ForegroundColor Yellow
Write-Host "  cd C:\hand-of-midas" -ForegroundColor White
Write-Host "  python -c `"from backend.execution.mt5_executor import get_dwx_status; print(get_dwx_status())`"" -ForegroundColor White
Write-Host ""
