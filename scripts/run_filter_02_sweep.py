"""Filter #2 SWEEP — max per direction per day across thresholds [0, 2, 1].

0 = no cap (baseline / current production).
2 = max 2 same-direction sweeps per day.
1 = first-only (the original Filter #2 measurement).

Initial first-only run (max=1) was -32.6% aggregate. User requested
intermediate test at max=2 to see if the truly-redundant 3rd+ sweeps
are the bad ones, not the 2nd.
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

THRESHOLDS = [0, 2, 1]  # 0 = no cap (baseline), 2 = max 2/dir, 1 = first-only


def run_one(label, pkg_dir, max_per_direction):
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
    result = module.run_backtest(max_per_direction_per_day=max_per_direction)
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


def main():
    print("=" * 70)
    print(f"FILTER #2 SWEEP — max per direction per day: {THRESHOLDS}")
    print("=" * 70)
    print("0 = no cap (baseline). 2 = allow 2 same-direction. 1 = first-only.")
    print()

    results = {"filter": 2, "name": "Max per direction per day sweep",
               "generated": datetime.now(timezone.utc).isoformat(),
               "thresholds": THRESHOLDS, "by_system": {}}

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        results["by_system"][s["key"]] = {"label": s["label"], "results": {}}
        for thr in THRESHOLDS:
            label = "no-cap" if thr == 0 else f"max={thr}"
            print(f"  {label}...")
            r = run_one(s["label"], s["pkg"], thr)
            pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "∞"
            print(f"    N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  "
                  f"P&L=${r['pnl']:>+12,.0f}  ({r['elapsed_s']:.1f}s)")
            results["by_system"][s["key"]]["results"][str(thr)] = r

    json_path = os.path.join(OUT_DIR, "filter_02_sweep_results.json")
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\n✓ wrote {json_path}")

    # Telegram summary — per-system table + aggregate
    lines = ["🧪 <b>FILTER #2 SWEEP — max per direction per day</b>", "",
             "0 = no cap (baseline). 2 = allow 2/dir. 1 = first-only.", ""]

    aggregate_pnl = {str(thr): 0 for thr in THRESHOLDS}
    for s in SYSTEMS:
        lines.append(f"<b>{s['label']}</b>")
        sys_results = results["by_system"][s["key"]]["results"]
        baseline = sys_results["0"]
        baseline_pnl = baseline["pnl"]
        if baseline["n"] == 0:
            lines.append("  no trades")
            continue
        for thr in THRESHOLDS:
            r = sys_results[str(thr)]
            pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "∞"
            label = "no-cap" if thr == 0 else f"max={thr}"
            if thr == 0:
                lines.append(f"  {label:7}: PF {pf_str:>4}  P&L ${r['pnl']:>+10,.0f}  N={r['n']}  (baseline)")
            else:
                delta = r["pnl"] - baseline_pnl
                pct = (delta / baseline_pnl * 100) if baseline_pnl else 0
                emoji = "✅" if delta > 0 else ("🟡" if pct > -2 else "❌")
                lines.append(f"  {label:7}: PF {pf_str:>4}  P&L ${r['pnl']:>+10,.0f}  Δ${delta:+,.0f} ({pct:+.1f}%)  {emoji}")
            aggregate_pnl[str(thr)] += r["pnl"]
        lines.append("")

    lines.append("<b>TOTAL ΔP&L vs baseline:</b>")
    base_total = aggregate_pnl["0"]
    for thr in THRESHOLDS:
        label = "no-cap" if thr == 0 else f"max={thr}"
        if thr == 0:
            lines.append(f"  {label:7}: ${aggregate_pnl[str(thr)]:>+12,.0f}  (baseline)")
        else:
            d = aggregate_pnl[str(thr)] - base_total
            pct = (d / base_total * 100) if base_total else 0
            lines.append(f"  {label:7}: ${aggregate_pnl[str(thr)]:>+12,.0f}  Δ${d:+,.0f} ({pct:+.1f}%)")
    lines.append("")
    lines.append("Reply: ship 2 [max=N] [systems] / stash 2 / next")

    msg = "\n".join(lines)
    print()
    print(msg)
    tg_send(msg)
    time.sleep(3)


if __name__ == "__main__":
    main()
