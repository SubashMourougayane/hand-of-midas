# Shared environment for all Windows launchers. Dot-source this from the others.
# Resolves the repo root relative to this file — NO hardcoded machine path.
$ErrorActionPreference = "Stop"

# scripts/windows/_env.ps1  ->  repo root is two levels up.
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

# Python import path: bt_engine + dashboard_backend packages.
$env:PYTHONPATH = "$Repo\bt_engine;$Repo\dashboard_backend"

# DWX file-bridge dir for native Windows MT5 (override baked in code default).
# Adjust <user> if MT5 runs under a different Windows account than Administrator.
if (-not $env:DWX_DIR) {
  $env:DWX_DIR = "$env:APPDATA\MetaQuotes\Terminal\Common\Files\DWX"
}

# Postgres DSN — set here or in the machine environment. Falls back to code
# default (localhost/golddigger_bt) if unset.
# $env:BT_ENGINE_DB_URL = "postgresql+psycopg2://postgres:PASS@localhost:5432/golddigger_bt"

function Assert-Repo {
  if (-not (Test-Path (Join-Path $Repo "bt_engine\bt_engine\runner\cli.py"))) {
    throw "Repo root not found at $Repo — is this file under scripts/windows/ ?"
  }
}
Assert-Repo
