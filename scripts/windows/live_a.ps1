# Live A (LONG) leg — fib_v2_intraday_a on JM-Demo2, M15, Model B 1.5% sizer.
# Args mirror the Mac production launch exactly. Logs to logs\live_a.log.
. (Join-Path $PSScriptRoot "_env.ps1")

$LogDir = Join-Path $Repo "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Repo

# Flags mirror the Mac production procs EXACTLY (symbol/max-spread/poll-interval
# left at defaults, as production does). Balance 10000 = live sizer input.
python -m bt_engine.runner.cli live `
  --strategy fib_v2_intraday_a `
  --timeframe M15 `
  --use-equity-sizer `
  --start-balance 10000.0 `
  --risk-pct 0.015 `
  --max-live-lot 2.0 `
  --max-entry-slip-ratio 1.15 `
  --max-open-positions 4 `
  @args *>> (Join-Path $LogDir "live_a.log")
