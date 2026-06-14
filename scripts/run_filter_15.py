"""Filter #15 — cooldown bypass race fix pre/post measurement.

Unlike kwarg-gated filters (#5/#6/#7/#16/#2), Filter #15 is a code-level
race-condition fix that can't be toggled at runtime. To measure pre/post
we checkout the pre-fix commit, run baseline, checkout post-fix HEAD,
run filter, compare.

Workflow expectation: numbers should be bit-identical because the bug
only manifests when execute_signal raises in live, which never happens
in the deterministic BT path. This script proves that empirically by
running both states.

Pre-fix commit:  bcf7fe8 (parent of #15 merge)
Post-fix HEAD:   midas-deploy current
"""
from __future__ import annotations
import os
import sys
import json
import time
import subprocess
import importlib
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.notify import send as tg_send

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)

PRE_FIX_COMMIT = "bcf7fe8"  # parent of #15 merge
POST_FIX_REF = "midas-deploy"

SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro", "pkg": "backend"},
    {"key": "gold_micro", "label": "Gold Micro", "pkg": "backend-micro"},
    {"key": "oil_macro",  "label": "Oil Macro",  "pkg": "backend-oil"},
    {"key": "oil_micro",  "label": "Oil Micro",  "pkg": "backend-oil-micro"},
]


def git_checkout(ref):
    """Checkout a git ref. Aborts if working tree is dirty (safety)."""
    r = subprocess.run(["git", "-C", ROOT, "status", "--porcelain"], capture_output=True, text=True)
    if r.stdout.strip():
        raise RuntimeError(f"Working tree dirty before checkout. stdout: {r.stdout!r}")
    r = subprocess.run(["git", "-C", ROOT, "checkout", ref], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Checkout failed: {r.stderr}")
    head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return head


def run_one(label, pkg_dir):
    """Run run_backtest() with no kwarg overrides — uses whatever the
    current checked-out code's default behavior is."""
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
    result = module.run_backtest()
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


def fmt(r):
    if r["n"] == 0:
        return "0 trades"
    pf = r["pf"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
    return f"N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  P&L=${r['pnl']:>+12,.0f}"


def main():
    print("=" * 70)
    print("FILTER #15 — Cooldown bypass race fix  (Pre/Post Backtest)")
    print("=" * 70)
    print(f"PRE-FIX:  {PRE_FIX_COMMIT} (parent of #15 merge)")
    print(f"POST-FIX: {POST_FIX_REF} (HEAD with fix shipped)")
    print()
    print("Race condition is live-only (BT can't raise execute_signal).")
    print("Expectation: numbers BIT-IDENTICAL across pre/post.")
    print("=" * 70)

    results = {"filter": 15, "name": "Cooldown bypass race fix",
               "generated": datetime.now(timezone.utc).isoformat(),
               "pre_fix_commit": PRE_FIX_COMMIT,
               "post_fix_ref": POST_FIX_REF,
               "baseline": {}, "filter_a": {}}

    # Phase 1: BASELINE (pre-fix code)
    pre_head = git_checkout(PRE_FIX_COMMIT)
    print(f"\n>>> Checked out PRE-FIX: {pre_head[:7]}")
    print(f"\n--- BASELINE (pre-fix) ---")
    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        b = run_one(s["label"], s["pkg"])
        print(f"    {fmt(b)}  ({b['elapsed_s']:.1f}s)")
        results["baseline"][s["key"]] = b

    # Phase 2: FILTER ON (post-fix code)
    post_head = git_checkout(POST_FIX_REF)
    print(f"\n>>> Checked out POST-FIX: {post_head[:7]}")
    print(f"\n--- FILTER ON (post-fix) ---")
    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        f = run_one(s["label"], s["pkg"])
        print(f"    {fmt(f)}  ({f['elapsed_s']:.1f}s)")
        results["filter_a"][s["key"]] = f

    json_path = os.path.join(OUT_DIR, "filter_15_results.json")
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\n✓ wrote {json_path}")

    # Telegram
    lines = ["🧪 <b>FILTER #15 — Cooldown bypass race fix</b>", "",
             f"PRE-fix:  {PRE_FIX_COMMIT} (parent of merge)",
             f"POST-fix: midas-deploy HEAD", "",
             "Race fix is live-only — BT can't trigger execute_signal raise.",
             "Expectation: numbers bit-identical (no BT impact).", "",
             "BT 21-yr pre/post comparison:"]

    total_b = 0
    total_f = 0
    all_match = True
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
        if abs(delta_pnl) > 1 or delta_n != 0:
            all_match = False
            emoji = "⚠️"
        else:
            emoji = "✅"
        total_b += b["pnl"]
        total_f += f["pnl"]
        lines.append(
            f"  {s['label']:11}: PF {pf_b:.2f}→{pf_f:.2f}  "
            f"ΔP&L=${delta_pnl:+,.0f} ({delta_pct:+.3f}%)  ΔN={delta_n:+d}  {emoji}"
        )

    delta_total = total_f - total_b
    pct = (delta_total / total_b * 100) if total_b else 0
    lines.append("")
    lines.append(f"Total ΔP&L: ${delta_total:+,.0f} ({pct:+.3f}%)")
    if all_match:
        lines.append("Verdict: ✅ BIT-IDENTICAL — race fix has zero BT impact (expected).")
        lines.append("         Live-only correctness benefit (prevents orphan-cascade)")
        lines.append("         when execute_signal raises mid-flight.")
    else:
        lines.append("Verdict: ⚠️ NUMBERS DIFFER — investigate before relying on the fix.")
    lines.append("")
    lines.append("Reply: ship 15 / revert 15 / next")

    msg = "\n".join(lines)
    print()
    print(msg)
    tg_send(msg)
    time.sleep(3)


if __name__ == "__main__":
    main()
