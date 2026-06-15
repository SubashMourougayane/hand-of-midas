"""Filter #25 — bias_source sweep (prior_day vs asia vs pre_session vs lookahead_today).

Runs the real run_backtest() over 21yr CSVs for all 4 systems, 4 variants each.
Prior-day = baseline. Asia/pre_session = realistic alternatives. Lookahead =
ceiling (cheating; for sanity only).

Output:
  scripts/output/filter_25_results.json
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

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)


SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro", "pkg": "backend"},
    {"key": "gold_micro", "label": "Gold Micro", "pkg": "backend-micro"},
    {"key": "oil_macro",  "label": "Oil Macro",  "pkg": "backend-oil"},
    {"key": "oil_micro",  "label": "Oil Micro",  "pkg": "backend-oil-micro"},
]

VARIANTS = ["prior_day", "asia", "pre_session", "lookahead_today"]


def run_one(pkg_dir: str, bias_source: str) -> dict:
    """Run a single system × variant. Returns stats dict."""
    # Clear cached modules
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
    result = module.run_backtest(bias_source=bias_source)
    elapsed = time.time() - t0

    trades = result.trades
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": 0, "pf": 0, "pnl": 0, "elapsed_s": elapsed}
    wins = [t for t in trades if t.pnl_sized > 0]
    losses = [t for t in trades if t.pnl_sized <= 0]
    sum_win = sum(t.pnl_sized for t in wins)
    sum_loss = -sum(t.pnl_sized for t in losses)

    # Max drawdown — track equity curve via cumulative pnl
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.entry_time if hasattr(x, 'entry_time') else 0):
        eq += t.pnl_sized
        peak = max(peak, eq)
        dd = peak - eq
        max_dd = max(max_dd, dd)

    return {
        "n": n,
        "wr": len(wins) / n * 100,
        "pf": (sum_win / sum_loss) if sum_loss > 0 else float("inf"),
        "pnl": sum(t.pnl_sized for t in trades),
        "wins": len(wins),
        "losses": len(losses),
        "max_dd": max_dd,
        "elapsed_s": elapsed,
    }


def fmt(r):
    if r["n"] == 0:
        return "0 trades"
    pf = r["pf"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
    return f"N={r['n']:>5d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  P&L=${r['pnl']:>+12,.0f}  DD=${r['max_dd']:>9,.0f}"


def main():
    print("=" * 80)
    print("FILTER #25 — bias_source sweep")
    print("  prior_day (baseline) | asia | pre_session | lookahead_today (cheating)")
    print("=" * 80)

    results = {
        "filter": 25,
        "name": "bias_source",
        "generated": datetime.now(timezone.utc).isoformat(),
        "systems": {},
    }

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        results["systems"][s["key"]] = {}
        for variant in VARIANTS:
            print(f"  {variant:18s}...", end=" ", flush=True)
            try:
                r = run_one(s["pkg"], variant)
                print(fmt(r) + f"  ({r['elapsed_s']:.1f}s)")
                results["systems"][s["key"]][variant] = r
            except Exception as e:
                print(f"FAIL: {type(e).__name__}: {e}")
                results["systems"][s["key"]][variant] = {"error": str(e)}

    json_path = os.path.join(OUT_DIR, "filter_25_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n=> wrote {json_path}")

    # Summary table
    print("\n" + "=" * 80)
    print("SUMMARY (PF / P&L delta vs baseline)")
    print("=" * 80)
    for s in SYSTEMS:
        sys_data = results["systems"][s["key"]]
        if "error" in sys_data.get("prior_day", {}):
            print(f"\n{s['label']}: baseline failed")
            continue
        b = sys_data["prior_day"]
        if b.get("n", 0) == 0:
            print(f"\n{s['label']}: 0 baseline trades")
            continue
        print(f"\n{s['label']:12s}  baseline:  {fmt(b)}")
        for v in ("asia", "pre_session", "lookahead_today"):
            r = sys_data.get(v, {})
            if "error" in r or r.get("n", 0) == 0:
                print(f"               {v:18s} N/A or failed")
                continue
            d_pf = r["pf"] - b["pf"] if b["pf"] != float("inf") else 0
            d_pnl = r["pnl"] - b["pnl"]
            d_dd = r["max_dd"] - b["max_dd"]
            tag = "+" if d_pnl > 0 else "-"
            print(f"               {v:18s} {fmt(r)}  dPF={d_pf:+.2f}  dPnL=${d_pnl:+,.0f}  dDD=${d_dd:+,.0f}")


if __name__ == "__main__":
    main()
