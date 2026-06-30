#!/usr/bin/env bash
# Launch dashboard backend (+ mounted SPA) from anywhere.
# Always sets repo-root cwd + correct PYTHONPATH.
set -euo pipefail
REPO="/Users/subash/SUBASH/GoldDigger"
cd "$REPO"
export PYTHONPATH="$REPO/bt_engine:$REPO/dashboard_backend${PYTHONPATH:+:$PYTHONPATH}"
PORT="${PORT:-8001}"
# --reload watches `dashboard_backend/app` only. Pass --reload-dir for SPA hot-build.
exec python3 -m uvicorn app.main:app --port "$PORT" "$@"
