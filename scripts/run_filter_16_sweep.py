"""Filter #16 — R:R lower bound SWEEP across thresholds [0.8, 1.0, 1.2, 1.5].

Initial filter at rr=1.5 was too aggressive (-$701k aggregate). User
requested intermediate threshold sweep to find the sweet spot — maybe
removing JUST the worst sub-1R geometry without cutting into 1.0-1.5R
winners is profitable.

Reuses the same kwarg-gated path as run_filter_16.py.
"""
from __future__ import annotations
import os
import sys
import json
import time
import importlib
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.notify import send as tg_send

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)


SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro", "pkg": "backend"},
    {"key": "gold_micro", "label": "Gold Micro", "pkg": "backend-micro"},
    {"key": "oil_macro",  "label": "Oil Macro",  "pkg": "backend-oil"},
    {"key": "oil_micro",  "label": "Oil Micro",  "pkg": "backend-oil-micro"},
]

THRESHOLDS = [0.8, 1.0, 1.2, 1.5]


def run_one(label, pkg_dir, rr_lower_bound):
    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies", "backend.backtest", "backend.data")):
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
    result = module.run_backtest(rr_lower_bound=rr_lower_bound)
    elapsed = time.time() - t0

    trades = result.trades
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": 0, "pf": 0, "pnl": 0, "elapsed_s": elapsed}
    wins = [t for t in trades if t.pnl_sized > 0]
    losses = [t for t in trades if t.pnl_sized <= 0]
    sum_win = sum(t.pnl_sized for t in wins)
    sum_loss = -sum(t.pnl_sized for t in losses)
    return {
        "n": n,
        "wr": len(wins) / n * 100,
        "pf": sum_win / sum_loss if sum_loss > 0 else float("inf"),
        "pnl": sum(t.pnl_sized for t in trades),
        "elapsed_s": elapsed,
    }


def fmt_cell(r, baseline_pnl):
    if r["n"] == 0:
        return "0 trades"
    pf = r["pf"] if r["pf"] != float("inf") else 0
    delta = r["pnl"] - baseline_pnl
    pct = (delta / baseline_pnl * 100) if baseline_pnl else 0
    return f"PF={pf:.2f} P&L=${r['pnl']:>+10,.0f} ({pct:+.1f}%) N={r['n']}"


def main():
    print("=" * 70)
    print(f"FILTER #16 SWEEP — R:R lower bound across {THRESHOLDS}")
    print("=" * 70)

    results = {"filter": 16, "name": "R:R lower bound sweep",
               "generated": datetime.now(timezone.utc).isoformat(),
               "thresholds": THRESHOLDS, "by_system": {}}

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        results["by_system"][s["key"]] = {"label": s["label"], "results": {}}
        for rr in THRESHOLDS:
            print(f"  rr_lower_bound={rr}...")
            r = run_one(s["label"], s["pkg"], rr)
            pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "∞"
            print(f"    N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  "
                  f"P&L=${r['pnl']:>+12,.0f}  ({r['elapsed_s']:.1f}s)")
            results["by_system"][s["key"]]["results"][str(rr)] = r

    json_path = os.path.join(OUT_DIR, "filter_16_sweep_results.json")
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\n✓ wrote {json_path}")

    # Telegram summary — per-system table with all thresholds
    lines = ["🧪 <b>FILTER #16 SWEEP — R:R lower bound</b>", "",
             f"Thresholds tested: {THRESHOLDS}", ""]

    # Per-system delta vs baseline (0.8)
    aggregate_pnl = {str(rr): 0 for rr in THRESHOLDS}
    for s in SYSTEMS:
        lines.append(f"<b>{s['label']}</b>")
        sys_results = results["by_system"][s["key"]]["results"]
        baseline = sys_results["0.8"]
        baseline_pnl = baseline["pnl"]
        if baseline["n"] == 0:
            lines.append("  no trades")
            continue
        for rr in THRESHOLDS:
            r = sys_results[str(rr)]
            pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "∞"
            if rr == 0.8:
                lines.append(f"  rr={rr}: PF {pf_str:>4}  P&L ${r['pnl']:>+10,.0f}  N={r['n']}  (baseline)")
            else:
                delta = r["pnl"] - baseline_pnl
                pct = (delta / baseline_pnl * 100) if baseline_pnl else 0
                emoji = "✅" if delta > 0 else ("🟡" if pct > -2 else "❌")
                lines.append(f"  rr={rr}: PF {pf_str:>4}  P&L ${r['pnl']:>+10,.0f}  Δ${delta:+,.0f} ({pct:+.1f}%)  {emoji}")
            aggregate_pnl[str(rr)] += r["pnl"]
        lines.append("")

    # Aggregate row
    lines.append("<b>TOTAL ΔP&L vs baseline:</b>")
    base_total = aggregate_pnl["0.8"]
    for rr in THRESHOLDS:
        if rr == 0.8:
            lines.append(f"  rr={rr}: ${aggregate_pnl[str(rr)]:>+12,.0f}  (baseline)")
        else:
            d = aggregate_pnl[str(rr)] - base_total
            pct = (d / base_total * 100) if base_total else 0
            lines.append(f"  rr={rr}: ${aggregate_pnl[str(rr)]:>+12,.0f}  Δ${d:+,.0f} ({pct:+.1f}%)")
    lines.append("")
    lines.append("Reply: ship 16 [rr=X] [systems] / stash 16 / next")

    msg = "\n".join(lines)
    print()
    print(msg)
    tg_send(msg)
    time.sleep(3)


if __name__ == "__main__":
    main()
