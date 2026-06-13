"""Filter #7 — selective ship validation (Variant A on all 4 systems).

Confirms each system's BT reads partial_tp_at_pct/size/arms_be from config
and produces variant-A numbers when run_backtest() is called WITHOUT kwarg
overrides. If numbers match the variant-A column from filter_07_results.json
(within slippage variance ~0.05%), the config-driven path is wired correctly.
"""
from __future__ import annotations
import os, sys, json, time, importlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro", "pkg": "backend",            "expected_pnl": 427598},
    {"key": "gold_micro", "label": "Gold Micro", "pkg": "backend-micro",      "expected_pnl": 334808},
    {"key": "oil_macro",  "label": "Oil Macro",  "pkg": "backend-oil",        "expected_pnl": 825879},
    {"key": "oil_micro",  "label": "Oil Micro",  "pkg": "backend-oil-micro",  "expected_pnl": 3177780},
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
    print("FILTER #7 — Variant A ship validation (no kwarg override)")
    print("=" * 70)
    print("Expected: each system reads partial_tp_at_pct=0.5, partial_tp_size=0.5,")
    print("          partial_arms_be=False from its config.")
    print("=" * 70)

    results = {}
    fail = False
    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        r = run_one(s["label"], s["pkg"])
        pf = r["pf"]
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        delta = r["pnl"] - s["expected_pnl"]
        delta_pct = delta / s["expected_pnl"] * 100 if s["expected_pnl"] else 0
        # Allow up to 0.1% variance from random slippage in _sl_slip
        ok = abs(delta_pct) <= 0.1
        marker = "✅" if ok else "❌"
        print(f"  N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  P&L=${r['pnl']:>+12,.0f}  ({r['elapsed_s']:.1f}s)")
        print(f"  expected ${s['expected_pnl']:+,}  Δ=${delta:+,.0f} ({delta_pct:+.3f}%)  {marker}")
        if not ok:
            fail = True
        results[s["key"]] = {**r, "expected_pnl": s["expected_pnl"], "delta": delta, "delta_pct": delta_pct, "ok": ok}

    print("\n" + "=" * 70)
    print("VERDICT: " + ("✅ ALL MATCH (config-driven path correct)" if not fail else "❌ MISMATCH — investigate before push"))
    print("=" * 70)

    out = os.path.join(ROOT, "scripts/output/filter_07_validation.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"✓ wrote {out}")

    sys.exit(0 if not fail else 1)


if __name__ == "__main__":
    main()
