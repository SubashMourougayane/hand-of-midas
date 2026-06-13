"""Background watcher: pings Telegram when all 4 parity_audit_regimes processes finish.

Polls every 30s. Reads each system's JSON to summarize results in the ping.
Reuses backend/notify.py's Telegram client.
"""
import os
import sys
import time
import json
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.notify import send  # reuses existing Telegram path

OUT_DIR = os.path.join(ROOT, "scripts/output")
SYSTEMS = ["gold_micro", "oil_micro", "gold_macro", "oil_macro"]
LABELS = {"gold_micro": "Gold Micro", "oil_micro": "Oil Micro",
          "gold_macro": "Gold Macro", "oil_macro": "Oil Macro"}


def alive_count() -> int:
    """Count parity_audit_regimes Python processes currently running."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "parity_audit_regimes.py"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return len([l for l in out.stdout.splitlines() if l.strip()])
        return 0
    except Exception:
        return 0


def summarize_one(system_key: str) -> str:
    """Read scripts/output/parity_audit_regimes_<sys>.json and return a 1-line summary."""
    json_path = os.path.join(OUT_DIR, f"parity_audit_regimes_{system_key}.json")
    if not os.path.exists(json_path):
        return f"  {LABELS[system_key]:11}: (no result file)"
    try:
        with open(json_path) as f:
            results = json.load(f)
    except Exception as e:
        return f"  {LABELS[system_key]:11}: (parse error: {e})"
    if not results:
        return f"  {LABELS[system_key]:11}: (0 audits)"
    n = len(results)
    avg_parity = sum(r["parity_pct"] for r in results) / n
    avg_dir = sum(r["direction_agree_pct"] for r in results) / n
    avg_drift = sum(r["avg_entry_drift"] for r in results) / n
    bt_total = sum(r["bt_n"] for r in results)
    live_total = sum(r["live_n"] for r in results)
    return (
        f"  {LABELS[system_key]:11}: {n} regimes  "
        f"parity {avg_parity:.0f}%  dir-agree {avg_dir:.0f}%  "
        f"BT {bt_total} sigs  Live {live_total} sigs  "
        f"drift ${avg_drift:.4f}"
    )


def main():
    print("Watcher started. Polling every 30s for parity_audit_regimes processes.")
    poll_interval = 30
    started_alive = alive_count()
    print(f"Currently alive: {started_alive}")
    if started_alive == 0:
        print("No processes running. Exiting (nothing to wait for).")
        return

    last_alive = started_alive
    while True:
        n = alive_count()
        if n != last_alive:
            print(f"  alive count changed: {last_alive} → {n}")
            last_alive = n
        if n == 0:
            print("All processes finished. Building summary + sending Telegram.")
            break
        time.sleep(poll_interval)

    # Build summary
    lines = ["🔬 <b>PARITY AUDIT — REGIMES COMPLETE</b>", ""]
    for sk in SYSTEMS:
        lines.append(summarize_one(sk))
    lines.append("")
    lines.append("Reports: docs/PARITY_AUDIT_REGIMES_*.md")
    msg = "\n".join(lines)
    print(msg)
    send(msg)
    # Give the daemon thread a moment to flush before exiting
    time.sleep(3)
    print("Done.")


if __name__ == "__main__":
    main()
