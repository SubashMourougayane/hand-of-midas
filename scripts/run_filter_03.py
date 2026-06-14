"""Filter #3 — TP Feasibility Check sweep.

Audit: at signal time, check whether TP is reachable in the time remaining
before MAX_HOLD or session-close (21 UTC).
  expected_distance = (mins_remaining / 60) × ATR_H1
  skip if expected_distance < required_distance × tp_feasibility_factor

Sweep across factor values: 0 (baseline) / 0.5 / 0.7 / 0.9 / 1.0
Per audit's suggested test range.
"""
from __future__ import annotations
import os, sys, json, time, importlib
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import httpx

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)

SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro", "pkg": "backend"},
    {"key": "gold_micro", "label": "Gold Micro", "pkg": "backend-micro"},
    {"key": "oil_macro",  "label": "Oil Macro",  "pkg": "backend-oil"},
    {"key": "oil_micro",  "label": "Oil Micro",  "pkg": "backend-oil-micro"},
]

THRESHOLDS = [0.0, 0.5, 0.7, 0.9, 1.0]


def reload_pkg(pkg_dir):
    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies",
                         "backend.backtest", "backend.data")):
            del sys.modules[k]
    pkg_path = os.path.join(ROOT, pkg_dir)
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()
    if pkg_dir == "backend":
        return importlib.import_module("backend.backtest.engine")
    return importlib.import_module("backtest.engine")


def measure(module, factor):
    t0 = time.time()
    result = module.run_backtest(tp_feasibility_factor=factor)
    elapsed = time.time() - t0
    trades = result.trades
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": 0, "pf": 0, "pnl": 0, "elapsed_s": elapsed}
    wins = [t for t in trades if t.pnl_sized > 0]
    losses = [t for t in trades if t.pnl_sized <= 0]
    sum_win = sum(t.pnl_sized for t in wins)
    sum_loss = -sum(t.pnl_sized for t in losses)
    pf = sum_win / sum_loss if sum_loss > 0 else float("inf")
    return {
        "n": n,
        "wr": len(wins) / n * 100,
        "pf": pf,
        "pnl": sum(t.pnl_sized for t in trades),
        "elapsed_s": elapsed,
    }


def fmt_factor(f):
    if f == 0.0:
        return "no-filter"
    return f"factor={f}"


def main():
    print("=" * 72)
    print(f"FILTER #3 — TP Feasibility sweep across {THRESHOLDS}")
    print("=" * 72)

    results = {
        "filter": 3,
        "name": "TP Feasibility Check",
        "generated": datetime.now(timezone.utc).isoformat(),
        "thresholds": THRESHOLDS,
        "by_system": {},
    }

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        module = reload_pkg(s["pkg"])
        results["by_system"][s["key"]] = {"label": s["label"], "results": {}}
        for f in THRESHOLDS:
            label = fmt_factor(f)
            print(f"  {label}...")
            r = measure(module, f)
            pf_str = f"{r['pf']:.2f}" if r['pf'] != float("inf") else "∞"
            print(f"    N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  "
                  f"P&L=${r['pnl']:>+12,.0f}  ({r['elapsed_s']:.1f}s)")
            results["by_system"][s["key"]]["results"][str(f)] = r

    json_path = os.path.join(OUT_DIR, "filter_03_results.json")
    results_json = json.dumps(results, indent=2, default=lambda x: "inf" if x == float("inf") else str(x))
    results_json = results_json.replace("Infinity", '"inf"')
    with open(json_path, "w") as fh:
        fh.write(results_json)
    print(f"\n✓ wrote {json_path}")

    # Telegram (sync)
    lines = ["🧪 FILTER #3 — TP Feasibility Check sweep", ""]
    lines.append("Skip if expected_distance < required × factor.")
    lines.append("expected = (mins_remaining / 60) × ATR_H1.")
    lines.append("mins_remaining = min(MAX_BARS×3, mins_to_session_close=21UTC).")
    lines.append("")
    lines.append("BT 21-yr (4 systems × 5 thresholds = 20 BTs):")
    lines.append("")

    aggregate_pnl = {str(t): 0 for t in THRESHOLDS}
    for s in SYSTEMS:
        lines.append(f"<b>{s['label']}</b>")
        sys_results = results["by_system"][s["key"]]["results"]
        baseline = sys_results["0.0"]
        baseline_pnl = baseline["pnl"]
        if baseline["n"] == 0:
            lines.append("  no trades")
            continue
        for f in THRESHOLDS:
            r = sys_results[str(f)]
            pf = r["pf"] if r["pf"] != float("inf") else 0
            label = fmt_factor(f)
            if f == 0.0:
                lines.append(f"  {label:9}: PF {pf:.2f}  P&L ${r['pnl']:>+10,.0f}  N={r['n']}  (baseline)")
            else:
                d = r["pnl"] - baseline_pnl
                pct = (d / baseline_pnl * 100) if baseline_pnl else 0
                emoji = "✅" if d > 0 else ("🟡" if pct > -2 else "❌")
                lines.append(f"  {label:9}: PF {pf:.2f}  P&L ${r['pnl']:>+10,.0f}  Δ${d:+,.0f} ({pct:+.1f}%)  {emoji}")
            aggregate_pnl[str(f)] += r["pnl"]
        lines.append("")

    lines.append("<b>TOTAL ΔP&L vs baseline:</b>")
    base_total = aggregate_pnl["0.0"]
    for f in THRESHOLDS:
        label = fmt_factor(f)
        if f == 0.0:
            lines.append(f"  {label:9}: ${aggregate_pnl[str(f)]:>+12,.0f}  (baseline)")
        else:
            d = aggregate_pnl[str(f)] - base_total
            pct = (d / base_total * 100) if base_total else 0
            lines.append(f"  {label:9}: ${aggregate_pnl[str(f)]:>+12,.0f}  Δ${d:+,.0f} ({pct:+.1f}%)")
    lines.append("")
    lines.append("Reply: ship 3 [factor=N] [systems] / stash 3 / next")

    msg = "\n".join(lines)
    print()
    print(msg)

    try:
        from backend import notify as nf
        resp = httpx.post(nf.API_URL,
                          data={"chat_id": nf.CHAT_ID, "text": msg},
                          timeout=15)
        print(f"\nTelegram HTTP {resp.status_code}")
    except Exception as e:
        print(f"\nTelegram send failed: {e}")


if __name__ == "__main__":
    main()
