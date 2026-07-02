# Live D (SHORT) leg — fib_v2_intraday_d on JM-Demo2, M15, Model B 1.5% sizer.
# Shares ONE broker account with the A leg. Logs to logs\live_d.log.
. (Join-Path $PSScriptRoot "_env.ps1")

$LogDir = Join-Path $Repo "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Repo

python -m bt_engine.runner.cli live `
  --strategy fib_v2_intraday_d `
  --symbol XAUUSD.ecn `
  --timeframe M15 `
  --use-equity-sizer `
  --start-balance 5000.0 `
  --risk-pct 0.015 `
  --max-live-lot 2.0 `
  --max-open-positions 4 `
  --max-spread 0.50 `
  --max-entry-slip-ratio 1.15 `
  --poll-interval 1.0 `
  @args *>> (Join-Path $LogDir "live_d.log")
