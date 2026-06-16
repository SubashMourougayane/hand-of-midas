"""Filter #27 — limit-order entry sweep.

Runs `run_backtest()` 21-yr full history on all 4 systems with limit-order
entry variants vs market-order baseline.

Per-system grid:
  baseline (market) +
  3 TTLs × (A + B + C×3 offsets) × 2 strictness modes = 30 variants
  = 31 variants/system × 4 systems = 124 BTs total
  ≈ 5.2 hours wall-clock (sequential, module-clear pattern keeps memory safe)

Same engine the dashboard uses — no fake numbers, no replay tools.
Per [[project-filter-sweep-workflow]] and [[feedback-no-auto-ship]]: real BT
pre/post, user decides ship/stash per system per variant.

Output:
  scripts/output/filter_27_results.json — flat schema for slicing
  Telegram digest with top variant per system

would_have_won_count is INFORMATIONAL LOOKAHEAD — surfaced in JSON + (info)
column only. NEVER use it to rank variants in ship decisions.
"""
from __future__ import annotations
import os
import sys
import json
import time
import platform
import socket
import subprocess
import importlib
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.notify import send as tg_send

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)

# Atomic write of partial JSON after each system, plus per-cell append-only log.
# If sweep crashes mid-run we lose at most one system's progress.
JSON_PATH = os.path.join(OUT_DIR, "filter_27_results.json")
JSONL_PATH = os.path.join(OUT_DIR, "filter_27_results.jsonl")  # append-only per-cell


def _save_json_atomic(path: str, obj: dict) -> None:
    """Write JSON via temp + rename (atomic) so an interrupted save can't
    leave a half-written file."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    os.replace(tmp, path)


def _append_jsonl(path: str, row: dict) -> None:
    """Append a single completed-cell row. Easy to tail / parse mid-run."""
    with open(path, "a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _git_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro", "pkg": "backend"},
    {"key": "gold_micro", "label": "Gold Micro", "pkg": "backend-micro"},
    {"key": "oil_macro",  "label": "Oil Macro",  "pkg": "backend-oil"},
    {"key": "oil_micro",  "label": "Oil Micro",  "pkg": "backend-oil-micro"},
]


def _build_variants():
    """Build the 31-variant grid: 1 baseline + 30 cells (3 TTL × 5 levels × 2 strict).

    TTLs in M3 bars: 1=3min, 2=6min, 5=15min.
    Levels:
      A  = signal.entry verbatim (offset_pct=0.0 sentinel)
      B  = engulfing close, no slippage offset (string sentinel "engulf_close")
      C1 = pullback 10% of risk (offset_pct=-0.10)
      C2 = pullback 20% of risk (offset_pct=-0.20)
      C3 = pullback 30% of risk (offset_pct=-0.30)
    Strictness:
      loose  = wick touch only
      strict = touch + close beyond limit (sustained, pessimistic)
    """
    variants = [{
        "name": "baseline",
        "kwargs": {"entry_mode": "market"},
    }]
    for ttl_min, ttl_bars in [(3, 1), (6, 2), (15, 5)]:
        for level_name, offset_pct in [
            ("A", 0.0),
            ("B", "engulf_close"),
            ("C10", -0.10),
            ("C20", -0.20),
            ("C30", -0.30),
        ]:
            for strict_name, strict in [("loose", False), ("strict", True)]:
                name = f"ttl{ttl_min}_{level_name}_{strict_name}"
                variants.append({
                    "name": name,
                    "kwargs": {
                        "entry_mode": "limit",
                        "limit_offset_pct": offset_pct,
                        "limit_ttl_bars": ttl_bars,
                        "limit_fill_strict": strict,
                    },
                })
    return variants


VARIANTS = _build_variants()


def run_one(sys_label: str, pkg_dir: str, kwargs: dict) -> dict:
    """Run a single system × variant. Returns stats dict."""
    # Clear cached modules from prior systems' imports — same pattern as
    # run_filter_05/07/25/26.
    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies", "backend.backtest",
                         "backend.data")):
            del sys.modules[k]
    pkg_path = os.path.join(ROOT, pkg_dir)
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()

    if pkg_dir == "backend":
        module = importlib.import_module("backend.backtest.engine")
    else:
        module = importlib.import_module("backtest.engine")

    t0 = time.time()
    result = module.run_backtest(**kwargs)
    elapsed = time.time() - t0

    trades = result.trades
    n = len(trades)
    missed = getattr(result, "missed_signals", 0)
    wwl = getattr(result, "would_have_won_count", 0)
    total_signals = getattr(result, "total_signals", n + missed)
    fill_rate = (n / total_signals * 100) if total_signals > 0 else 0.0

    if n == 0:
        return {
            "label": sys_label, "n": 0, "wr": 0.0, "pf": 0.0, "pnl": 0.0,
            "missed": missed, "wwl": wwl, "total_signals": total_signals,
            "fill_rate": fill_rate, "elapsed_s": elapsed,
        }
    wins = [t for t in trades if t.pnl_sized > 0]
    losses = [t for t in trades if t.pnl_sized <= 0]
    sum_win = sum(t.pnl_sized for t in wins)
    sum_loss = -sum(t.pnl_sized for t in losses)
    return {
        "label": sys_label,
        "n": n,
        "wr": len(wins) / n * 100,
        "pf": sum_win / sum_loss if sum_loss > 0 else float("inf"),
        "pnl": sum(t.pnl_sized for t in trades),
        "wins": len(wins),
        "losses": len(losses),
        "missed": missed,
        "wwl": wwl,
        "total_signals": total_signals,
        "fill_rate": fill_rate,
        "elapsed_s": elapsed,
    }


def fmt_pf(pf):
    return f"{pf:.2f}" if pf != float("inf") else "∞"


def main():
    print("=" * 90)
    print(f"FILTER #27 — LIMIT-ORDER ENTRY SWEEP  ({len(VARIANTS)} variants × {len(SYSTEMS)} systems = {len(VARIANTS) * len(SYSTEMS)} BTs)")
    print("=" * 90)
    print(f"  TTLs: 3 / 6 / 15 min  ·  Levels: A (entry), B (engulf-close), C10/20/30 (pullback)")
    print(f"  Strictness: loose (wick touch) / strict (touch + close beyond)")
    print(f"  Baseline = market entry, current production")
    print()

    sweep_started = datetime.now(timezone.utc)
    results = {
        "filter": 27,
        "name": "Limit-order entry sweep",
        "generated": sweep_started.isoformat(),
        "metadata": {
            "git_branch": _git_branch(),
            "git_commit": _git_rev(),
            "host": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "sweep_started_utc": sweep_started.isoformat(),
            "sweep_finished_utc": None,
            "elapsed_total_s": None,
            "n_systems": len(SYSTEMS),
            "n_variants": len(VARIANTS),
            "n_total_bts": len(SYSTEMS) * len(VARIANTS),
            "json_path": JSON_PATH,
            "jsonl_path": JSONL_PATH,
            "console_log": "/tmp/filter_27_run.log",
        },
        "systems": {s["key"]: {"label": s["label"], "variants": {}} for s in SYSTEMS},
    }

    # Truncate the per-cell jsonl on a fresh run (don't accumulate stale rows)
    if os.path.exists(JSONL_PATH):
        os.remove(JSONL_PATH)

    # Initial header dump so consumers can read metadata before any cells finish.
    _save_json_atomic(JSON_PATH, results)
    print(f"  metadata: branch={results['metadata']['git_branch']} "
          f"commit={results['metadata']['git_commit'][:8]} "
          f"host={results['metadata']['host']}")
    print(f"  intermediate save: after each system → {JSON_PATH}")
    print(f"  per-cell append: {JSONL_PATH}")

    total_runs = len(SYSTEMS) * len(VARIANTS)
    run_idx = 0

    for s in SYSTEMS:
        sys_started = time.time()
        print(f"\n[{s['label']}]")
        for v in VARIANTS:
            run_idx += 1
            cell_started = datetime.now(timezone.utc)
            print(f"  ({run_idx:>3}/{total_runs}) {v['name']:<24}...", end=" ", flush=True)
            try:
                r = run_one(s["label"], s["pkg"], v["kwargs"])
            except Exception as e:
                err_row = {"error": str(e), "exc_type": type(e).__name__}
                print(f"FAIL: {type(e).__name__}: {e}")
                results["systems"][s["key"]]["variants"][v["name"]] = err_row
                _append_jsonl(JSONL_PATH, {
                    "system": s["key"], "variant": v["name"],
                    "started_utc": cell_started.isoformat(),
                    **err_row,
                })
                continue
            print(
                f"N={r['n']:>4}  fill={r['fill_rate']:>5.1f}%  "
                f"WR={r['wr']:>5.1f}%  PF={fmt_pf(r['pf']):>5}  "
                f"P&L=${r['pnl']:>+10,.0f}  miss={r['missed']:>3}  "
                f"wwl={r['wwl']:>3}(info)  ({r['elapsed_s']:.0f}s)"
            )
            results["systems"][s["key"]]["variants"][v["name"]] = r
            _append_jsonl(JSONL_PATH, {
                "system": s["key"], "variant": v["name"],
                "started_utc": cell_started.isoformat(),
                **r,
            })
        # Intermediate save after each system completes — worst-case loss is one
        # system's progress (~75 min) instead of the whole 5.2hr sweep.
        sys_elapsed = time.time() - sys_started
        results["metadata"][f"system_{s['key']}_elapsed_s"] = round(sys_elapsed, 1)
        _save_json_atomic(JSON_PATH, results)
        print(f"  ✓ {s['label']} done in {sys_elapsed/60:.1f}min — saved partial JSON")

    sweep_finished = datetime.now(timezone.utc)
    results["metadata"]["sweep_finished_utc"] = sweep_finished.isoformat()
    results["metadata"]["elapsed_total_s"] = round((sweep_finished - sweep_started).total_seconds(), 1)
    _save_json_atomic(JSON_PATH, results)
    print(f"\n✓ final JSON written: {JSON_PATH}")
    print(f"  total wall-clock: {(sweep_finished - sweep_started).total_seconds() / 60:.1f}min")

    # Per-system summary: top-10 by ΔP&L vs baseline
    print()
    print("=" * 90)
    print("SUMMARY (top-10 per system by ΔP&L vs baseline)")
    print("=" * 90)

    digest_lines = ["🧪 <b>FILTER #27 — LIMIT ORDER SWEEP</b>", "", "Top variant per system:"]

    for s in SYSTEMS:
        sv = results["systems"][s["key"]]["variants"]
        baseline = sv.get("baseline", {})
        if not baseline or baseline.get("n", 0) == 0:
            print(f"\n[{s['label']}] no baseline trades — skipping")
            continue
        b_pnl = baseline["pnl"]
        # Build ranked list (excluding baseline). Skip errors/no-trade variants.
        ranked = []
        for name, r in sv.items():
            if name == "baseline" or "error" in r or r.get("n", 0) == 0:
                continue
            delta = r["pnl"] - b_pnl
            ranked.append((name, r, delta))
        ranked.sort(key=lambda x: x[2], reverse=True)

        print(f"\n[{s['label']}]  baseline: N={baseline['n']:>4} WR={baseline['wr']:>5.1f}% "
              f"PF={fmt_pf(baseline['pf']):>5} P&L=${b_pnl:>+,.0f}")
        print(f"  {'variant':<24} {'N':>4} {'fill%':>6} {'WR%':>5} {'PF':>5} "
              f"{'ΔP&L':>11} {'miss':>5} {'wwl(info)':>10}")
        for name, r, delta in ranked[:10]:
            print(
                f"  {name:<24} {r['n']:>4} {r['fill_rate']:>5.1f}% "
                f"{r['wr']:>4.1f}% {fmt_pf(r['pf']):>5} "
                f"${delta:>+10,.0f} {r['missed']:>5} {r['wwl']:>10}"
            )

        if ranked:
            top_name, top_r, top_delta = ranked[0]
            digest_lines.append(
                f"<b>{s['label']}</b>: {top_name}  "
                f"PF {baseline['pf']:.2f}→{top_r['pf']:.2f}  "
                f"ΔP&L=${top_delta:+,.0f}  fill={top_r['fill_rate']:.0f}%"
            )

    digest_lines.append("")
    digest_lines.append(f"{total_runs} BTs run · full table in scripts/output/filter_27_results.json")
    digest_lines.append("Reply: ship 27 [system] [variant] / stash 27 / next")
    msg = "\n".join(digest_lines)
    print()
    print(msg)
    tg_send(msg)
    time.sleep(3)


if __name__ == "__main__":
    main()
