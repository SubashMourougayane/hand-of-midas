"""Friday day postmortem — analyzes all 4 services' logs for 2026-06-12.

Pulls log files via the debug API and parses structured single-line entries.
For each service: counts SCAN/SIGNAL/GATE/POSITION/EXIT/BROKER events,
extracts errors, lists trades, and builds an event timeline.

Usage:
    python scripts/friday_postmortem.py
"""
from __future__ import annotations
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlencode
import urllib.request
import json as _json

API_BASE = "https://midas.subashtrades.in"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVICES = ["gold", "oil", "micro", "oil-micro"]

# Rotated Friday files (4 per service, captured at 1048/1220/1324/1626 IST)
FRIDAY_FILES = {
    "gold":      ["gold.20260612-1048.log", "gold.20260612-1220.log", "gold.20260612-1324.log", "gold.20260612-1626.log"],
    "oil":       ["oil.20260612-1048.log", "oil.20260612-1220.log", "oil.20260612-1324.log", "oil.20260612-1626.log"],
    "micro":     ["micro.20260612-1048.log", "micro.20260612-1220.log", "micro.20260612-1324.log", "micro.20260612-1626.log"],
    "oil-micro": ["oil-micro.20260612-1048.log", "oil-micro.20260612-1220.log", "oil-micro.20260612-1324.log", "oil-micro.20260612-1626.log"],
}

# Plus include the live .log file but only Friday-dated lines
LIVE_FILES = {svc: f"{svc}.log" for svc in SERVICES}


LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s*\|\s*"
    r"(?P<level>\w+)\s*\|\s*"
    r"(?P<cat>\w+)\s*\|\s*"
    r"(?P<svc>\S+)\s*\|\s*"
    r"(?P<msg>\S+)(?:\s*\|\s*(?P<fields>.*))?$"
)


def fetch_log_raw(service: str, filename: str) -> str:
    """Fetch a log file via /debug/logs/raw."""
    url = f"{API_BASE}/api/{service}/debug/logs/raw?filename={filename}&lines=100000"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  fetch error for {service}/{filename}: {e}")
        return ""


def parse_lines(raw: str, friday_only: bool = False) -> list[dict]:
    """Parse structured log lines. friday_only filters to 2026-06-12 timestamps."""
    out = []
    for line in raw.split("\n"):
        m = LINE_RE.match(line)
        if not m:
            continue
        d = m.groupdict()
        if friday_only and not d["ts"].startswith("2026-06-12"):
            continue
        out.append(d)
    return out


def summarize(lines: list[dict], svc_label: str) -> dict:
    """Compute summary stats for a service's parsed lines."""
    cats = Counter()
    levels = Counter()
    msgs = Counter()       # msg → count
    cat_msgs = Counter()   # (cat, msg) → count
    by_hour = Counter()    # UTC hour → count
    errors = []            # ERROR/CRIT lines (full)
    signals_fired = []     # SIGNAL/fired events
    signals_executed = []  # SIGNAL/executed events
    signals_skipped = []   # SIGNAL/skipped events
    broker_events = Counter()  # broker action → count
    exit_events = []       # EXIT detected/ambiguous etc
    gate_rejects = Counter()  # gate_reason → count
    sweeps_detected = []
    be_arms = []
    max_hold_fires = []

    for ln in lines:
        cats[ln["cat"]] += 1
        levels[ln["level"]] += 1
        msgs[ln["msg"]] += 1
        cat_msgs[(ln["cat"], ln["msg"])] += 1
        try:
            hour = int(ln["ts"][11:13])
            by_hour[hour] += 1
        except Exception:
            pass

        if ln["level"] in ("ERROR", "CRIT"):
            errors.append(ln)

        cat_msg = (ln["cat"], ln["msg"])
        if cat_msg == ("SIGNAL", "fired"):
            signals_fired.append(ln)
        elif cat_msg == ("SIGNAL", "executed"):
            signals_executed.append(ln)
        elif cat_msg == ("SIGNAL", "skipped"):
            signals_skipped.append(ln)
        elif ln["cat"] == "BROKER":
            broker_events[ln["msg"]] += 1
        elif ln["cat"] == "EXIT":
            exit_events.append(ln)
        elif ln["cat"] == "GATE":
            gate_rejects[ln["msg"]] += 1
        elif cat_msg == ("SCAN", "sweep_detected"):
            sweeps_detected.append(ln)
        elif cat_msg == ("POSITION", "be_arm_triggered") or ln["msg"] == "be_progress" and "trigger" in (ln.get("fields") or ""):
            pass  # too noisy
        elif "max_hold" in ln["msg"].lower():
            max_hold_fires.append(ln)

    return {
        "label": svc_label,
        "total_lines": len(lines),
        "cats": cats,
        "levels": levels,
        "msgs_top": msgs.most_common(15),
        "cat_msgs_top": cat_msgs.most_common(20),
        "by_hour": by_hour,
        "errors": errors,
        "signals_fired_count": len(signals_fired),
        "signals_executed_count": len(signals_executed),
        "signals_skipped_count": len(signals_skipped),
        "signals_fired_sample": signals_fired[:10],
        "broker_events": broker_events,
        "exit_events": exit_events,
        "gate_rejects": gate_rejects,
        "sweeps_detected_count": len(sweeps_detected),
        "max_hold_fires_count": len(max_hold_fires),
    }


def main():
    print("=" * 70)
    print("Friday postmortem — 2026-06-12")
    print("=" * 70)
    all_summaries = {}

    for svc in SERVICES:
        print(f"\n→ {svc}")
        # Pull all Friday rotated files
        all_raw = ""
        for fn in FRIDAY_FILES[svc]:
            print(f"  fetching {fn}...")
            r = fetch_log_raw(svc, fn)
            all_raw += r + "\n"
        # Plus Friday-dated lines from live
        print(f"  fetching {LIVE_FILES[svc]}... (filtering to Friday only)")
        live_raw = fetch_log_raw(svc, LIVE_FILES[svc])
        # Filter for Friday lines in live file
        friday_live = "\n".join(l for l in live_raw.split("\n") if l.startswith("2026-06-12"))
        all_raw += friday_live + "\n"

        # Parse + summarize
        lines = parse_lines(all_raw, friday_only=True)
        summary = summarize(lines, svc)
        all_summaries[svc] = summary
        print(f"  total Friday lines: {summary['total_lines']}")
        print(f"  errors: {len(summary['errors'])}")
        print(f"  signals fired: {summary['signals_fired_count']}, executed: {summary['signals_executed_count']}, skipped: {summary['signals_skipped_count']}")
        print(f"  sweeps detected: {summary['sweeps_detected_count']}")
        print(f"  exit events: {len(summary['exit_events'])}")

    # Write report
    out_path = os.path.join(ROOT, "docs/FRIDAY_POSTMORTEM.md")
    write_report(all_summaries, out_path)
    print(f"\n✓ wrote {out_path}")


def write_report(summaries: dict, out_path: str):
    L = []
    L.append("# Friday Day Postmortem — 2026-06-12")
    L.append("")
    L.append(f"_Generated: {datetime.now(timezone.utc).isoformat()}_")
    L.append("")
    L.append("Coverage: 2026-06-12 from observability v2 deployment (~14:30 UTC) "
             "until midnight UTC. All 4 services.")
    L.append("")
    L.append("## Per-service summary")
    L.append("")
    L.append("| Service | Lines | Errors | Sigs fired | Executed | Skipped | Sweeps | Exits | Top gate reject |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for svc, s in summaries.items():
        top_gate = ""
        if s["gate_rejects"]:
            top_gate_msg, top_gate_n = s["gate_rejects"].most_common(1)[0]
            top_gate = f"{top_gate_msg} ({top_gate_n})"
        L.append(
            f"| **{s['label']}** | {s['total_lines']:,} | {len(s['errors'])} | "
            f"{s['signals_fired_count']} | {s['signals_executed_count']} | {s['signals_skipped_count']} | "
            f"{s['sweeps_detected_count']} | {len(s['exit_events'])} | {top_gate} |"
        )
    L.append("")

    L.append("## Linked trade postmortems (3 closes Friday)")
    L.append("")
    L.append("- [GD-MI-da28460d](trades/GD-MI-da28460d.md) — Gold Micro LONG SL **−$369.74** (13:36-13:43 UTC)")
    L.append("- [GD-MI-0b973d80](trades/GD-MI-0b973d80.md) — Gold Micro LONG SL **−$358.83** (14:18-14:23 UTC)")
    L.append("- [OIL-MI-aba3b668](trades/OIL-MI-aba3b668.md) — Oil Micro SHORT MAX_HOLD **+$458.80** (14:54-18:55 UTC)")
    L.append("")
    L.append("**Net Friday P&L: −$269.77** (3 trades, 1 win)")
    L.append("")

    for svc, s in summaries.items():
        L.append(f"## {s['label']} detailed breakdown")
        L.append("")
        L.append("### Category distribution")
        for cat, n in s["cats"].most_common():
            L.append(f"- {cat}: {n}")
        L.append("")
        L.append("### Level distribution")
        for lvl, n in s["levels"].most_common():
            L.append(f"- {lvl}: {n}")
        L.append("")
        L.append("### Top (category, message) pairs")
        for (cat, msg), n in s["cat_msgs_top"]:
            L.append(f"- `{cat}/{msg}`: {n}")
        L.append("")
        if s["gate_rejects"]:
            L.append("### Gate rejection histogram")
            for msg, n in s["gate_rejects"].most_common():
                L.append(f"- `{msg}`: {n}")
            L.append("")
        if s["broker_events"]:
            L.append("### Broker activity")
            for msg, n in s["broker_events"].most_common():
                L.append(f"- `{msg}`: {n}")
            L.append("")
        if s["exit_events"]:
            L.append("### Exit events")
            for e in s["exit_events"][:20]:
                f = e.get("fields") or ""
                L.append(f"- `{e['ts']}` `{e['msg']}`  {f[:120]}")
            if len(s["exit_events"]) > 20:
                L.append(f"- ... and {len(s['exit_events']) - 20} more")
            L.append("")
        if s["errors"]:
            L.append("### ⚠️ Errors")
            for e in s["errors"][:20]:
                f = e.get("fields") or ""
                L.append(f"- `{e['ts']}` `{e['cat']}/{e['msg']}`  {f[:200]}")
            if len(s["errors"]) > 20:
                L.append(f"- ... and {len(s['errors']) - 20} more")
            L.append("")
        L.append("### Activity by hour (UTC)")
        for hour in sorted(s["by_hour"]):
            n = s["by_hour"][hour]
            bar = "█" * min(60, n // 50)
            L.append(f"- {hour:02d}:00  {n:>6}  {bar}")
        L.append("")
        if s["signals_fired_sample"]:
            L.append("### Signal fires (samples, max 10)")
            for sig in s["signals_fired_sample"]:
                f = sig.get("fields") or ""
                L.append(f"- `{sig['ts']}` {f[:200]}")
            L.append("")
        L.append("---")
        L.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
