"""Filter #5 — BE 50% → 35% pre/post backtest.

Runs `run_backtest()` 21-yr full history on all 4 systems, baseline
(be_trigger_pct=0.5) vs filter (be_trigger_pct=0.35). Same engine the
dashboard uses — no fake numbers.

For Filter #5 (fill-model BE pct change), Live signal-gen pre/post is NOT
measured because the filter is fill-side; signals are identical regardless.

Output:
  scripts/output/filter_05_results.json
  Telegram ping with summary
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


def run_one(sys_label: str, pkg_dir: str, be_pct: float) -> dict:
    """Run a single system's backtest. Returns dict with stats.

    Imports the run_backtest from backend(-X)/backtest/engine.py with the
    package directory on sys.path[0] so `from config import ...` resolves.
    """
    # Clear conflicting modules from prior runs.
    # Also clear backend.execution.* so the freshly-imported engine picks up
    # the right execute_trade signature (in case the shared module was already
    # imported with a different version on a previous run).
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
    result = module.run_backtest(be_trigger_pct=be_pct)
    elapsed = time.time() - t0

    trades = result.trades
    n = len(trades)
    if n == 0:
        return {"label": sys_label, "n": 0, "wr": 0, "pf": 0, "pnl": 0, "elapsed_s": elapsed}
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
        "elapsed_s": elapsed,
    }


def fmt(r: dict) -> str:
    if r["n"] == 0:
        return "0 trades"
    pf = r["pf"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
    return (f"N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  "
            f"P&L=${r['pnl']:>+10,.0f}")


def main():
    print("=" * 70)
    print("FILTER #5 — BE 50% → 35%  (Pre/Post Backtest)")
    print("=" * 70)

    results = {"filter": 5, "name": "BE 50% → 35%",
               "generated": datetime.now(timezone.utc).isoformat(),
               "baseline": {}, "filter_a": {}}

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        print(f"  baseline (be_trigger_pct=0.5)...")
        b = run_one(s["label"], s["pkg"], 0.5)
        print(f"    {fmt(b)}  ({b['elapsed_s']:.1f}s)")
        results["baseline"][s["key"]] = b

        print(f"  filter   (be_trigger_pct=0.35)...")
        f = run_one(s["label"], s["pkg"], 0.35)
        print(f"    {fmt(f)}  ({f['elapsed_s']:.1f}s)")
        results["filter_a"][s["key"]] = f

    # Save JSON
    json_path = os.path.join(OUT_DIR, "filter_05_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n✓ wrote {json_path}")

    # Telegram summary
    lines = ["🧪 <b>FILTER #5 — BE 50% → 35%</b>", "", "BT 21-yr (all 4 systems):"]
    for s in SYSTEMS:
        b = results["baseline"][s["key"]]
        f = results["filter_a"][s["key"]]
        if b["n"] == 0:
            lines.append(f"  {s['label']:11}: no trades")
            continue
        pf_b = b["pf"] if b["pf"] != float("inf") else 0
        pf_f = f["pf"] if f["pf"] != float("inf") else 0
        delta_pf = pf_f - pf_b
        delta_pnl = f["pnl"] - b["pnl"]
        delta_n = f["n"] - b["n"]
        pf_str = f"{pf_b:.2f}→{pf_f:.2f}"
        emoji = "✅" if (delta_pf > 0 and delta_pnl > 0) else ("🟡" if delta_pnl > -0.05 * abs(b["pnl"]) else "❌")
        lines.append(
            f"  {s['label']:11}: {pf_str}  "
            f"ΔP&L=${delta_pnl:+,.0f}  ΔN={delta_n:+d}  {emoji}"
        )

    # Verdict
    total_baseline_pnl = sum(results["baseline"][s["key"]]["pnl"] for s in SYSTEMS if results["baseline"][s["key"]]["n"])
    total_filter_pnl = sum(results["filter_a"][s["key"]]["pnl"] for s in SYSTEMS if results["filter_a"][s["key"]]["n"])
    delta_total = total_filter_pnl - total_baseline_pnl
    pct = (delta_total / total_baseline_pnl * 100) if total_baseline_pnl else 0
    lines.append("")
    lines.append(f"Total ΔP&L: ${delta_total:+,.0f} ({pct:+.1f}%)")
    if pct >= 5:
        lines.append("Verdict: ✅ SHIP candidate")
    elif pct >= -5:
        lines.append("Verdict: 🟡 MARGINAL — call user judgment")
    else:
        lines.append("Verdict: ❌ STASH (P&L drops materially)")
    lines.append("")
    lines.append("Reply: ship 5 / stash 5 / next")

    msg = "\n".join(lines)
    print()
    print(msg)
    tg_send(msg)
    time.sleep(3)


if __name__ == "__main__":
    main()
