"""Filter #6 — Trailing SL after BE pre/post backtest.

After BE arms, trail SL upward using high-water-mark of bar high (longs)
or low (shorts). SL only ratchets in favorable direction. Tests
trail_after_be_pct=0.5 vs current production behavior (0.0 = no trail).

Baseline = post-Filter-#5 (BE 0.35 for Gold Micro/Oil Macro/Oil Micro;
0.50 for Gold Macro). Filter ON adds trail_after_be_pct=0.5 on top.

For Filter #6 (fill-side), Live signal-gen is unchanged → no Live extraction.
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


def run_one(label, pkg_dir, trail_pct):
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
    result = module.run_backtest(trail_after_be_pct=trail_pct)
    elapsed = time.time() - t0

    trades = result.trades
    n = len(trades)
    if n == 0:
        return {"label": label, "n": 0, "wr": 0, "pf": 0, "pnl": 0, "elapsed_s": elapsed}
    wins = [t for t in trades if t.pnl_sized > 0]
    losses = [t for t in trades if t.pnl_sized <= 0]
    sum_win = sum(t.pnl_sized for t in wins)
    sum_loss = -sum(t.pnl_sized for t in losses)
    return {
        "label": label,
        "n": n,
        "wr": len(wins) / n * 100,
        "pf": sum_win / sum_loss if sum_loss > 0 else float("inf"),
        "pnl": sum(t.pnl_sized for t in trades),
        "wins": len(wins),
        "losses": len(losses),
        "elapsed_s": elapsed,
    }


def fmt(r):
    if r["n"] == 0:
        return "0 trades"
    pf = r["pf"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
    return f"N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  P&L=${r['pnl']:>+12,.0f}"


def main():
    print("=" * 70)
    print("FILTER #6 — Trailing SL after BE  (Pre/Post Backtest)")
    print("=" * 70)
    print("Baseline: post-Filter-#5 config (be 0.35 for 3 systems, 0.50 for Gold Macro)")
    print("Filter:   trail_after_be_pct=0.5 added on top")
    print("=" * 70)

    results = {"filter": 6, "name": "Trailing SL after BE",
               "generated": datetime.now(timezone.utc).isoformat(),
               "baseline": {}, "filter_a": {}}

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        print(f"  baseline (trail=0.0)...")
        b = run_one(s["label"], s["pkg"], 0.0)
        print(f"    {fmt(b)}  ({b['elapsed_s']:.1f}s)")
        results["baseline"][s["key"]] = b

        print(f"  filter   (trail=0.5)...")
        f = run_one(s["label"], s["pkg"], 0.5)
        print(f"    {fmt(f)}  ({f['elapsed_s']:.1f}s)")
        results["filter_a"][s["key"]] = f

    json_path = os.path.join(OUT_DIR, "filter_06_results.json")
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\n✓ wrote {json_path}")

    # Telegram summary
    lines = ["🧪 <b>FILTER #6 — Trailing SL after BE</b>", "",
             "Trail = 50% of high-water-mark from entry (post-BE only).", "",
             "BT 21-yr (all 4 systems, baseline = post-#5):"]
    total_b = 0
    total_f = 0
    for s in SYSTEMS:
        b = results["baseline"][s["key"]]
        f = results["filter_a"][s["key"]]
        if b["n"] == 0:
            lines.append(f"  {s['label']:11}: no trades")
            continue
        pf_b = b["pf"] if b["pf"] != float("inf") else 0
        pf_f = f["pf"] if f["pf"] != float("inf") else 0
        delta_pnl = f["pnl"] - b["pnl"]
        delta_n = f["n"] - b["n"]
        delta_pct = (delta_pnl / b["pnl"] * 100) if b["pnl"] else 0
        emoji = "✅" if (pf_f > pf_b and delta_pct > -2) else ("🟡" if delta_pct > -10 else "❌")
        total_b += b["pnl"]
        total_f += f["pnl"]
        lines.append(
            f"  {s['label']:11}: PF {pf_b:.2f}→{pf_f:.2f}  "
            f"ΔP&L=${delta_pnl:+,.0f} ({delta_pct:+.1f}%)  ΔN={delta_n:+d}  {emoji}"
        )

    delta_total = total_f - total_b
    pct = (delta_total / total_b * 100) if total_b else 0
    lines.append("")
    lines.append(f"Total ΔP&L: ${delta_total:+,.0f} ({pct:+.1f}%)")
    if pct >= 5:
        lines.append("Verdict: ✅ SHIP candidate")
    elif pct >= -2:
        lines.append("Verdict: 🟡 MARGINAL — call user judgment")
    else:
        lines.append("Verdict: ❌ STASH (P&L drops materially)")
    lines.append("")
    lines.append("Reply: ship 6 / stash 6 / next")

    msg = "\n".join(lines)
    print()
    print(msg)
    tg_send(msg)
    time.sleep(3)


if __name__ == "__main__":
    main()
