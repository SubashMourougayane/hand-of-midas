"""Selective ship validation for Filter #5.

Confirms:
  - Gold Micro / Oil Macro / Oil Micro: BT reads from config (now 0.35) and produces shipped numbers
  - Gold Macro: BT still uses 0.5 (excluded from ship)

If BT numbers match the original Filter #5 measurement (within slippage noise), the
selective ship is wired correctly. If Gold Macro's number changed, something
in our config refactor leaked across systems.
"""
from __future__ import annotations
import os, sys, json, time, importlib
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro (excluded)", "pkg": "backend",            "expected_be": 0.50},
    {"key": "gold_micro", "label": "Gold Micro (shipped)",  "pkg": "backend-micro",      "expected_be": 0.35},
    {"key": "oil_macro",  "label": "Oil Macro (shipped)",   "pkg": "backend-oil",        "expected_be": 0.35},
    {"key": "oil_micro",  "label": "Oil Micro (shipped)",   "pkg": "backend-oil-micro",  "expected_be": 0.35},
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
    result = module.run_backtest()  # NO kwarg → uses config (or hardcoded 0.5 for Gold Macro)
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
    print("FILTER #5 — Selective ship validation (no kwarg override)")
    print("=" * 70)

    results = {}
    for s in SYSTEMS:
        print(f"\n[{s['label']}]  expected be_trigger_pct={s['expected_be']}")
        r = run_one(s["label"], s["pkg"])
        pf = r["pf"]
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        print(f"  N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  P&L=${r['pnl']:>+10,.0f}  ({r['elapsed_s']:.1f}s)")
        results[s["key"]] = r

    print("\n" + "=" * 70)
    print("EXPECTED (from Filter #5 measurement):")
    print("  Gold Macro: N=2242, WR 65.4%, PF 2.56, $346,196  (be=0.5 baseline)")
    print("  Gold Micro: N=1911, WR 74.1%, PF 2.77, $252,265  (be=0.35 filter)")
    print("  Oil Macro:  N=1653, WR 60.4%, PF 2.94, $697,995  (be=0.35 filter)")
    print("  Oil Micro:  N=4601, WR 77.1%, PF 3.10, $2,125,672 (be=0.35 filter)")
    print("=" * 70)

    out = os.path.join(ROOT, "scripts/output/filter_05_validation.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"✓ wrote {out}")


if __name__ == "__main__":
    main()
