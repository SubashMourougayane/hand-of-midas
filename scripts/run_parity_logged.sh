#!/usr/bin/env bash
# Run intraday parity tests with HEAVY logging:
#   - per-test name as it starts (pytest -v)
#   - live print() output unbuffered (-s -u)
#   - timestamped lines so we can see how long each test took
#   - tee to log file AND stdout so it's tail-able in another shell
#
# Usage:
#   scripts/run_parity_logged.sh                              # both A + D
#   scripts/run_parity_logged.sh tests/parity/test_parity_fib_v2_intraday_a.py
#
# Log file: /tmp/parity_<unix-ts>.log
set -euo pipefail
REPO="/Users/subash/SUBASH/GoldDigger"
cd "$REPO/bt_engine"

TARGET="${1:-tests/parity}"
TS=$(date +%s)
LOG="/tmp/parity_${TS}.log"

echo "[$(date)] parity log: $LOG" | tee "$LOG"
echo "[$(date)] target: $TARGET" | tee -a "$LOG"
echo "[$(date)] git: $(git rev-parse --short HEAD)" | tee -a "$LOG"
echo "----" | tee -a "$LOG"

# -v: show every test as it starts
# -s: don't capture stdout (so print() inside fixture/tests is live)
# -u: unbuffered Python so timing is real-time
# --durations=0: show every test's elapsed time at end
# 2>&1 | ts: prepend a UTC ms timestamp to every line (requires `moreutils` ts).
#   Fallback to awk timestamper if ts is missing.
if command -v ts >/dev/null 2>&1; then
  PYTHONUNBUFFERED=1 python3 -m pytest "$TARGET" -v -s --durations=0 \
    2>&1 | ts '[%Y-%m-%d %H:%M:%S]' | tee -a "$LOG"
else
  PYTHONUNBUFFERED=1 python3 -m pytest "$TARGET" -v -s --durations=0 \
    2>&1 | awk '{ cmd="date +\"%Y-%m-%d %H:%M:%S\""; cmd | getline t; close(cmd); print "[" t "] " $0; fflush() }' \
    | tee -a "$LOG"
fi

echo "----" | tee -a "$LOG"
echo "[$(date)] DONE" | tee -a "$LOG"
echo "log: $LOG"
