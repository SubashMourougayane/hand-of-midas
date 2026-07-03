"""Always-on debug exec server (token-auth PowerShell) for the Midas VPS.

Standing remote-admin channel so debugging doesn't need the RDP copy-paste dance.
Pure stdlib (no deps). Runs as an NSSM service (midas-debug-exec).

SECURITY MODEL (this IS a remote-code-execution channel — treat it as one):
  * Requires the exact bearer token in the `X-Deploy-Token` header on every /exec.
  * Token read from DEBUG_EXEC_TOKEN env (set in the NSSM service env, not in code).
  * Bind host is configurable; default 0.0.0.0 so a firewall rule controls reach.
    Prefer keeping port 8799 CLOSED in the firewall except when actively debugging.
  * NOT proxied through caddy — separate port, never on the public dashboard origin.
  * Every command + client IP logged to logs\debug_exec.log.
  * 300s per-command timeout.

Endpoints:
  GET  /ping                 -> {"ok": true}                 (no auth; reachability)
  POST /exec {"cmd":"..."}   -> {"exit":N,"stdout","stderr"} (auth required)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("DEBUG_EXEC_TOKEN", "")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs", "debug_exec.log")
MAX_SECONDS = 300


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    sys.stdout.write(line)
    sys.stdout.flush()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/ping":
            self._send(200, {"ok": True, "ts": datetime.now(timezone.utc).isoformat()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/exec":
            self._send(404, {"error": "not found"})
            return
        tok = self.headers.get("X-Deploy-Token", "")
        if not TOKEN or tok != TOKEN:
            _log(f"AUTH-FAIL from {self.client_address[0]}")
            self._send(401, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as e:
            self._send(400, {"error": f"bad json: {e}"})
            return
        cmd = payload.get("cmd", "")
        if not cmd:
            self._send(400, {"error": "no cmd"})
            return
        _log(f"EXEC from {self.client_address[0]}: {cmd}")
        try:
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                capture_output=True, text=True, timeout=MAX_SECONDS,
            )
            self._send(200, {"exit": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        except subprocess.TimeoutExpired:
            self._send(504, {"error": f"timeout >{MAX_SECONDS}s"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    if not TOKEN:
        print("ERROR: set DEBUG_EXEC_TOKEN env var first.", file=sys.stderr)
        sys.exit(2)
    _log(f"debug exec server starting on {args.host}:{args.port} (token len={len(TOKEN)})")
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Listening on {args.host}:{args.port}. Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
