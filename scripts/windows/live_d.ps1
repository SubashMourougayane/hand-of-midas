# Live D (SHORT) leg — fib_v2_intraday_d on JM-Demo2, M15, Model B 1.5% sizer.
# Shares ONE broker account with the A leg. Logs to logs\live_d.log.
. (Join-Path $PSScriptRoot "_env.ps1")

$LogDir = Join-Path $Repo "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Repo

# Flags mirror the Mac production procs EXACTLY (symbol/max-spread/poll-interval
# left at defaults, as production does). Balance 10000 = live sizer input.
python -m bt_engine.runner.cli live `
  --strategy fib_v2_intraday_d `
  --timeframe M15 `
  --use-equity-sizer `
  --start-balance 10000.0 `
  --risk-pct 0.015 `
  --max-live-lot 2.0 `
  --max-entry-slip-ratio 1.15 `
  --max-open-positions 4 `
  @args *>> (Join-Path $LogDir "live_d.log")
