"""TEMPORARY deploy exec server -- REMOVE AFTER DEPLOYMENT.

A minimal, token-authenticated HTTP endpoint that runs PowerShell commands on
the VPS so the deploy can be driven remotely without SSH. Pure stdlib (no deps).

SECURITY (this is a remote-code-execution channel -- treat it as one):
  * Requires the exact bearer token in the `X-Deploy-Token` header on every call.
  * Binds 0.0.0.0:<port> -- you must open that port in BOTH the Windows firewall
    AND the Contabo panel firewall for it to be reachable, and CLOSE it after.
  * Logs every command + client IP to deploy_exec.log.
  * Intended to run in the FOREGROUND during a deploy session, then Ctrl-C'd.
  * DELETE this file + close the firewall port when the deploy is done.

Run (elevated PowerShell, foreground):
  $env:DEPLOY_TOKEN="<token>"; python C:\GoldDigger\scripts\windows\deploy_exec_server.py --port 8799

Endpoints:
  GET  /ping                      -> {"ok": true}                (no auth; reachability test)
  POST /exec  {"cmd": "..."}      -> {"exit":N,"stdout":"...","stderr":"..."}  (auth required)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("DEPLOY_TOKEN", "")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy_exec.log")
MAX_SECONDS = 300


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line)
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
        # Auth.
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
            # Run via PowerShell. No shell string interpolation of untrusted data
            # beyond the command itself (which is the authenticated caller's).
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                capture_output=True, text=True, timeout=MAX_SECONDS,
            )
            self._send(200, {"exit": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        except subprocess.TimeoutExpired:
            self._send(504, {"error": f"timeout >{MAX_SECONDS}s"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def log_message(self, *a):  # silence default noisy logging
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    if not TOKEN:
        print("ERROR: set DEPLOY_TOKEN env var first.", file=sys.stderr)
        sys.exit(2)
    _log(f"deploy exec server starting on {args.host}:{args.port} (token set, len={len(TOKEN)})")
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Listening on {args.host}:{args.port}. Ctrl-C to stop. REMOVE after deploy.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
