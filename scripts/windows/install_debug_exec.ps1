<#
  Register the always-on debug exec server as an NSSM service (midas-debug-exec).
  Token is set in the service env (not in code, not in git). Run as Administrator.

  Usage:
    C:\GoldDigger\scripts\windows\install_debug_exec.ps1 -Token 'LONG_RANDOM_TOKEN'
  Omit -Token to auto-generate one (printed once).
#>
param(
  [string]$Token = "",
  [int]$Port = 8799
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_env.ps1")
$env:Path += ";C:\nssm"

# Resolve the real python (not the WindowsApps stub).
$PyExe = @(
  "C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe"
) + @((Get-Command python -All -ErrorAction SilentlyContinue).Source) |
  Where-Object { $_ -and (Test-Path $_) -and ($_ -notlike "*WindowsApps*") } | Select-Object -First 1
if (-not $PyExe) { throw "No real python.exe found." }

if (-not $Token) {
  $Token = -join ((48..57 + 65..90 + 97..122) | Get-Random -Count 40 | ForEach-Object { [char]$_ })
  Write-Host "Generated token (SAVE THIS, shown once):" -ForegroundColor Yellow
  Write-Host "  $Token" -ForegroundColor Yellow
}

$script = Join-Path $PSScriptRoot "debug_exec_server.py"
$LogDir = Join-Path $Repo "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$ErrorActionPreference = "SilentlyContinue"
& nssm status midas-debug-exec 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { & nssm stop midas-debug-exec 2>&1 | Out-Null; & nssm remove midas-debug-exec confirm 2>&1 | Out-Null }
$ErrorActionPreference = "Stop"

& nssm install midas-debug-exec $PyExe "`"$script`" --port $Port"
& nssm set midas-debug-exec AppDirectory $Repo
& nssm set midas-debug-exec Start SERVICE_AUTO_START
& nssm set midas-debug-exec AppExit Default Restart
& nssm set midas-debug-exec AppRestartDelay 5000
& nssm set midas-debug-exec AppEnvironmentExtra "DEBUG_EXEC_TOKEN=$Token" "PYTHONUTF8=1"
& nssm set midas-debug-exec AppStdout (Join-Path $LogDir "midas-debug-exec.out.log")
& nssm set midas-debug-exec AppStderr (Join-Path $LogDir "midas-debug-exec.err.log")
& nssm start midas-debug-exec

Write-Host ""
Write-Host "midas-debug-exec registered + started (auto-start on boot, port $Port)." -ForegroundColor Green
Write-Host "Firewall: OPEN port $Port only when actively debugging, then close it:" -ForegroundColor Yellow
Write-Host "  New-NetFirewallRule -DisplayName debug-exec -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow" -ForegroundColor Gray
Write-Host "  Remove-NetFirewallRule -DisplayName debug-exec   # to close" -ForegroundColor Gray
