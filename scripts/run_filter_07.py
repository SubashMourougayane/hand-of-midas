"""Filter #7 — Partial TP at 50% pre/post backtest.

When price reaches halfway to TP, bank `partial_tp_size` of position at
the halfway level; remainder rides to full TP / SL / BE / trail / MAX_HOLD
under existing rules. Reported pnl_per_unit = size-weighted blend of both
legs so existing equity/sizing code is unchanged.

Two variants tested per system:
  Variant A: partial only (BE still on its original schedule).
  Variant B: partial + BE arms immediately on the partial bar.

Baseline = post-Filter-#5 (BE 0.35 for 3 systems, 0.50 for Gold Macro)
         + post-Filter-#6 (trail 0.50 on Oil Macro only).
Filter measures whether banking half at 50% beats letting it all ride.

For Filter #7 (fill-side), Live signal-gen is unchanged → no Live extraction.
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

# Filter #7 parameters (locked)
PARTIAL_AT_PCT = 0.5    # halfway between entry and TP
PARTIAL_SIZE = 0.5      # close 50% of position at halfway


def run_one(label, pkg_dir, *, partial_at, partial_sz, arms_be):
    """Reload modules per package, run real run_backtest with the kwargs."""
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
    result = module.run_backtest(
        partial_tp_at_pct=partial_at,
        partial_tp_size=partial_sz,
        partial_arms_be=arms_be,
    )
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
    print("FILTER #7 — Partial TP at 50%  (Pre/Post Backtest)")
    print("=" * 70)
    print(f"Partial trigger: {PARTIAL_AT_PCT * 100:.0f}% to TP")
    print(f"Partial size: {PARTIAL_SIZE * 100:.0f}% of position")
    print("Baseline: post-Filter-#5+#6 config (no partial)")
    print("Variant A: partial only, BE on original schedule")
    print("Variant B: partial + BE arms immediately on partial fire")
    print("=" * 70)

    results = {"filter": 7, "name": "Partial TP at 50%",
               "generated": datetime.now(timezone.utc).isoformat(),
               "params": {"partial_at_pct": PARTIAL_AT_PCT, "partial_size": PARTIAL_SIZE},
               "baseline": {}, "variant_a": {}, "variant_b": {}}

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")

        print(f"  baseline (no partial)...")
        b = run_one(s["label"], s["pkg"],
                    partial_at=0.0, partial_sz=0.0, arms_be=False)
        print(f"    {fmt(b)}  ({b['elapsed_s']:.1f}s)")
        results["baseline"][s["key"]] = b

        print(f"  variant A (partial only)...")
        a = run_one(s["label"], s["pkg"],
                    partial_at=PARTIAL_AT_PCT, partial_sz=PARTIAL_SIZE, arms_be=False)
        print(f"    {fmt(a)}  ({a['elapsed_s']:.1f}s)")
        results["variant_a"][s["key"]] = a

        print(f"  variant B (partial + BE-on-partial)...")
        v = run_one(s["label"], s["pkg"],
                    partial_at=PARTIAL_AT_PCT, partial_sz=PARTIAL_SIZE, arms_be=True)
        print(f"    {fmt(v)}  ({v['elapsed_s']:.1f}s)")
        results["variant_b"][s["key"]] = v

    json_path = os.path.join(OUT_DIR, "filter_07_results.json")
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\n✓ wrote {json_path}")

    # Telegram summary
    lines = ["🧪 <b>FILTER #7 — Partial TP at 50%</b>", "",
             "Bank 50% at halfway, remainder rides full TP/SL/BE/trail.", "",
             "BT 21-yr (all 4 systems):"]

    total_b = 0
    total_a = 0
    total_v = 0
    for s in SYSTEMS:
        b = results["baseline"][s["key"]]
        a = results["variant_a"][s["key"]]
        v = results["variant_b"][s["key"]]
        if b["n"] == 0:
            lines.append(f"  {s['label']:11}: no trades")
            continue
        pf_b = b["pf"] if b["pf"] != float("inf") else 0
        pf_a = a["pf"] if a["pf"] != float("inf") else 0
        pf_v = v["pf"] if v["pf"] != float("inf") else 0
        d_a = a["pnl"] - b["pnl"]
        d_v = v["pnl"] - b["pnl"]
        pct_a = (d_a / b["pnl"] * 100) if b["pnl"] else 0
        pct_v = (d_v / b["pnl"] * 100) if b["pnl"] else 0
        em_a = "✅" if (pf_a > pf_b and pct_a > -2) else ("🟡" if pct_a > -10 else "❌")
        em_v = "✅" if (pf_v > pf_b and pct_v > -2) else ("🟡" if pct_v > -10 else "❌")
        total_b += b["pnl"]
        total_a += a["pnl"]
        total_v += v["pnl"]
        lines.append(
            f"  <b>{s['label']}</b>"
        )
        lines.append(
            f"    base : PF {pf_b:.2f}  P&L ${b['pnl']:+,.0f}  N={b['n']}"
        )
        lines.append(
            f"    var-A: PF {pf_a:.2f}  ΔP&L ${d_a:+,.0f} ({pct_a:+.1f}%)  {em_a}"
        )
        lines.append(
            f"    var-B: PF {pf_v:.2f}  ΔP&L ${d_v:+,.0f} ({pct_v:+.1f}%)  {em_v}"
        )

    delta_a_total = total_a - total_b
    delta_v_total = total_v - total_b
    pct_a_total = (delta_a_total / total_b * 100) if total_b else 0
    pct_v_total = (delta_v_total / total_b * 100) if total_b else 0
    lines.append("")
    lines.append(f"Total ΔP&L var-A: ${delta_a_total:+,.0f} ({pct_a_total:+.1f}%)")
    lines.append(f"Total ΔP&L var-B: ${delta_v_total:+,.0f} ({pct_v_total:+.1f}%)")
    lines.append("")
    lines.append("Reply: ship 7 [variant] [systems] / stash 7 / next")

    msg = "\n".join(lines)
    print()
    print(msg)
    tg_send(msg)
    time.sleep(3)


if __name__ == "__main__":
    main()
