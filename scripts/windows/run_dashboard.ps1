# Launch the dashboard backend (FastAPI + mounted SPA) on Windows.
# Serves dashboard/dist on :8001. Run `npm run build` in dashboard/ first.
. (Join-Path $PSScriptRoot "_env.ps1")

$Port = if ($env:PORT) { $env:PORT } else { "8001" }
Set-Location $Repo
# Bind 127.0.0.1 — the reverse proxy (caddy) terminates TLS + auth publicly.
python -m uvicorn app.main:app --host 127.0.0.1 --port $Port @args
