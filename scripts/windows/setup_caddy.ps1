<#
  Publish the dashboard at https://midas.subashtrades.in via caddy
  (auto Let's Encrypt TLS + basic auth), running as an NSSM service.

  Prereqs: DNS A record midas.subashtrades.in -> 84.247.177.145 (already set),
  dashboard running on 127.0.0.1:8001 (midas-dashboard service).

  Usage (elevated PowerShell):
    C:\GoldDigger\scripts\windows\setup_caddy.ps1 -User midas -PlainPassword 'YOURSTRONGPASS'
  Omit -PlainPassword to be prompted (not echoed).
#>
param(
  [string]$User = "midas",
  [string]$PlainPassword = "",
  [string]$Domain = "midas.subashtrades.in"
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_env.ps1")
$env:Path += ";C:\nssm"

function Section($m){ Write-Host "`n=== $m ===" -ForegroundColor Cyan }

# 1. Install caddy (winget) if absent.
Section "Ensure caddy installed"
$caddy = (Get-Command caddy -ErrorAction SilentlyContinue).Source
if (-not $caddy) {
  winget install CaddyServer.Caddy -e --silent --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
  $caddy = (Get-Command caddy -ErrorAction SilentlyContinue).Source
}
if (-not $caddy) { throw "caddy not found after install. Check winget." }
Write-Host "  caddy: $caddy"

# 2. Firewall: open 80 + 443.
Section "Open firewall 80 + 443"
foreach ($p in 80,443) {
  $n = "midas-http-$p"
  if (-not (Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $n -Direction Inbound -Protocol TCP -LocalPort $p -Action Allow | Out-Null
    Write-Host "  opened $p"
  } else { Write-Host "  $p already open" }
}
Write-Host "  NOTE: also open 80+443 in the Contabo control-panel firewall if present." -ForegroundColor Yellow

# 3. Password hash.
Section "Basic-auth credential"
if (-not $PlainPassword) {
  $sec = Read-Host "Enter dashboard password for user '$User'" -AsSecureString
  $PlainPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
$hash = (& caddy hash-password --plaintext $PlainPassword).Trim()
Write-Host "  hash generated for user '$User'"

# 4. Write the runtime Caddyfile (with the real hash) next to the repo copy.
Section "Write Caddyfile"
$cf = Join-Path $Repo "scripts\windows\Caddyfile.runtime"
# Global block: disable the admin endpoint (port 2019) -- not needed as a
# service, and a restart loop collides on it. basic_auth (not deprecated basicauth).
@"
{
	admin off
}
$Domain {
	encode gzip zstd
	basic_auth {
		$User $hash
	}
	reverse_proxy 127.0.0.1:8001
}
"@ | Set-Content -Path $cf -Encoding ascii
Write-Host "  wrote $cf"

# 5. Register caddy as an NSSM service.
Section "Register caddy NSSM service"
$ErrorActionPreference = "SilentlyContinue"
& nssm status midas-caddy 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { & nssm stop midas-caddy 2>&1 | Out-Null; & nssm remove midas-caddy confirm 2>&1 | Out-Null }
# Kill any orphan caddy holding port 2019/80/443 from a prior restart loop.
Start-Sleep 2
Get-Process caddy -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 2
$ErrorActionPreference = "Stop"
$LogDir = Join-Path $Repo "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
& nssm install midas-caddy $caddy "run --config `"$cf`" --adapter caddyfile"
& nssm set midas-caddy AppDirectory $Repo
& nssm set midas-caddy Start SERVICE_AUTO_START
& nssm set midas-caddy AppExit Default Restart
& nssm set midas-caddy AppRestartDelay 5000
& nssm set midas-caddy AppStdout (Join-Path $LogDir "midas-caddy.out.log")
& nssm set midas-caddy AppStderr (Join-Path $LogDir "midas-caddy.err.log")
& nssm start midas-caddy
Start-Sleep 8

Section "Verify"
& nssm status midas-caddy
Write-Host "TLS cert provisioning can take ~30-60s on first run. Then browse:" -ForegroundColor Green
Write-Host "  https://$Domain  (user: $User)" -ForegroundColor Green
Write-Host "Tail cert progress: Get-Content $LogDir\midas-caddy.err.log -Tail 30" -ForegroundColor DarkGray
