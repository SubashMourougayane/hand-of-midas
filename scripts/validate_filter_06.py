"""Selective ship validation for Filter #6.

Confirms:
  - Oil Macro: BT reads trail_after_be_pct=0.5 from config and produces shipped numbers
  - Other 3 systems: trail_after_be_pct=0.0 (legacy) — no leak

If the 3 unshipped systems' numbers match their post-Filter-#5 baseline (no trail),
the selective ship is wired correctly.
"""
from __future__ import annotations
import os, sys, json, time, importlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro (excluded)",  "pkg": "backend",            "expected_trail": 0.0},
    {"key": "gold_micro", "label": "Gold Micro (excluded)",  "pkg": "backend-micro",      "expected_trail": 0.0},
    {"key": "oil_macro",  "label": "Oil Macro (SHIPPED)",    "pkg": "backend-oil",        "expected_trail": 0.50},
    {"key": "oil_micro",  "label": "Oil Micro (excluded)",   "pkg": "backend-oil-micro",  "expected_trail": 0.0},
]


def run_one(label, pkg_dir):
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
    result = module.run_backtest()  # NO kwargs → uses configs
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
        "elapsed_s": elapsed,
    }


def main():
    print("=" * 70)
    print("FILTER #6 — Selective ship validation (no kwarg override)")
    print("=" * 70)

    results = {}
    for s in SYSTEMS:
        print(f"\n[{s['label']}]  expected trail_after_be_pct={s['expected_trail']}")
        r = run_one(s["label"], s["pkg"])
        pf = r["pf"]
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        print(f"  N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  P&L=${r['pnl']:>+12,.0f}  ({r['elapsed_s']:.1f}s)")
        results[s["key"]] = r

    print("\n" + "=" * 70)
    print("EXPECTED:")
    print("  Gold Macro: $346,196     (be 0.5, trail 0.0 — same as post-#5)")
    print("  Gold Micro: $252,265     (be 0.35, trail 0.0 — same as post-#5)")
    print("  Oil Macro:  $780,788     (be 0.35, trail 0.5 — Filter #6 SHIPPED)")
    print("  Oil Micro:  $2,125,672   (be 0.35, trail 0.0 — same as post-#5)")
    print("=" * 70)

    out = os.path.join(ROOT, "scripts/output/filter_06_validation.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"✓ wrote {out}")


if __name__ == "__main__":
    main()
