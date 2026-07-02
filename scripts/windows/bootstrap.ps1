<#
  Hand of Midas — Windows VPS bootstrap (RDP, run as Administrator).

  Idempotent: safe to re-run. Installs deps, clones the repo, builds the SPA,
  creates the Postgres DB. Does NOT start live trading and does NOT touch MT5
  (that's a manual GUI step) — see docs/DEPLOY_CONTABO_WINDOWS.md.

  Usage (elevated PowerShell):
    Set-ExecutionPolicy -Scope Process Bypass -Force
    C:\GoldDigger\scripts\windows\bootstrap.ps1
  (clone first if the repo isn't present — the script will do it if $RepoRoot is empty)
#>
[CmdletBinding()]
param(
  [string]$RepoRoot = "C:\GoldDigger",
  [string]$RepoUrl  = "https://github.com/SubashMourougayane/hand-of-midas.git",
  [string]$Branch   = "fib-v2-clean",
  [string]$PgPassword = "midas"          # local Postgres superuser pw (localhost-only)
)
$ErrorActionPreference = "Stop"
function Info($m){ Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Have($c){ [bool](Get-Command $c -ErrorAction SilentlyContinue) }

# ── 0. winget presence ───────────────────────────────────────────────
if (-not (Have winget)) {
  throw "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."
}

# ── 1. Core deps via winget (skip if already present) ────────────────
Info "Installing dependencies (Python 3.11, Node 18 LTS, Git, PostgreSQL 15)"
$pkgs = @(
  @{ id="Python.Python.3.11";        probe="python" },
  @{ id="OpenJS.NodeJS.LTS";         probe="node" },
  @{ id="Git.Git";                   probe="git" },
  @{ id="PostgreSQL.PostgreSQL.15";  probe="psql" }
)
foreach ($p in $pkgs) {
  if (Have $p.probe) { Write-Host "  $($p.probe) already present — skip" -ForegroundColor DarkGray; continue }
  Write-Host "  winget install $($p.id)"
  winget install --id $p.id -e --silent --accept-package-agreements --accept-source-agreements
}
# Refresh PATH for this session so freshly-installed tools resolve.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")

# NSSM (service manager) — not on winget reliably; fetch static binary.
$nssmDir = "C:\nssm"
if (-not (Test-Path "$nssmDir\nssm.exe")) {
  Info "Fetching NSSM"
  $zip = "$env:TEMP\nssm.zip"
  Invoke-WebRequest "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zip
  Expand-Archive $zip -DestinationPath $env:TEMP\nssm -Force
  New-Item -ItemType Directory -Force -Path $nssmDir | Out-Null
  Copy-Item "$env:TEMP\nssm\nssm-2.24\win64\nssm.exe" "$nssmDir\nssm.exe" -Force
  # Put nssm on the machine PATH.
  $mp = [System.Environment]::GetEnvironmentVariable("Path","Machine")
  if ($mp -notlike "*$nssmDir*") {
    [System.Environment]::SetEnvironmentVariable("Path", "$mp;$nssmDir", "Machine")
    $env:Path += ";$nssmDir"
  }
}

# ── 2. Clone / update repo ───────────────────────────────────────────
Info "Repo → $RepoRoot ($Branch)"
if (-not (Test-Path "$RepoRoot\.git")) {
  git clone --branch $Branch $RepoUrl $RepoRoot
} else {
  git -C $RepoRoot fetch origin
  git -C $RepoRoot checkout $Branch
  git -C $RepoRoot pull --ff-only origin $Branch
}

# ── 3. Python deps (editable installs) ───────────────────────────────
Info "Python packages"
python -m pip install --upgrade pip
python -m pip install -e "$RepoRoot\bt_engine"
python -m pip install -e "$RepoRoot\dashboard_backend"

# ── 4. Frontend build ────────────────────────────────────────────────
Info "Frontend build (npm ci + build)"
Push-Location "$RepoRoot\dashboard"
npm ci
npm run build
Pop-Location
if (-not (Test-Path "$RepoRoot\dashboard\dist\index.html")) {
  throw "SPA build missing — dashboard\dist\index.html not found."
}

# ── 5. Postgres DB ───────────────────────────────────────────────────
Info "PostgreSQL database golddigger_bt"
$env:PGPASSWORD = $PgPassword
$exists = (& psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='golddigger_bt';" 2>$null)
if ($exists -ne "1") {
  & createdb -U postgres golddigger_bt
  Write-Host "  created golddigger_bt (restore the Mac dump next — see runbook)"
} else {
  Write-Host "  golddigger_bt already exists — skip create" -ForegroundColor DarkGray
}

Info "Bootstrap complete"
Write-Host @"
NEXT (see docs/DEPLOY_CONTABO_WINDOWS.md):
  1. Restore DB:   pg_restore -U postgres -d golddigger_bt --no-owner C:\path\to\golddigger_bt.dump
  2. Create .env:  copy .env.example .env  (fill DATABASE_URL etc.)
  3. Set DWX_DIR + start MT5 + attach DWX EA (manual GUI).
  4. Test dashboard: scripts\windows\run_dashboard.ps1
  5. DO NOT start live runners until Mac is stopped (cutover).
"@ -ForegroundColor Green
