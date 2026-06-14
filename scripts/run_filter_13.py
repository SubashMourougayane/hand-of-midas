"""Filter #13 — Engulfing wick-vs-body asymmetry sweep.

Audit claim: engulfing detector uses pure body, ignores rejection wicks.
A bullish engulfing with a 2× body wick on top is structurally a top-wick
rejection, not a continuation. Reject these.

Implementation: wick_to_body_ratio_max kwarg in all 4 strategies.
For LONG (bullish): reject if upper_wick > body × ratio_max.
For SHORT (bearish): reject if lower_wick > body × ratio_max.

Sweep across: inf (baseline) / 1.0 / 0.5 (audit suggested) / 0.3 (tight).
"""
from __future__ import annotations
import os
import sys
import json
import time
import importlib
from datetime import datetime, timezone
import math

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

# Thresholds: float('inf') = no filter (baseline), then progressively tighter
THRESHOLDS = [float("inf"), 1.0, 0.5, 0.3]


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


def measure(label, module, ratio_max):
    t0 = time.time()
    result = module.run_backtest(wick_to_body_ratio_max=ratio_max)
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


def fmt_thr(thr):
    if thr == float("inf") or (isinstance(thr, str) and thr == "inf"):
        return "no-filter"
    return f"ratio={thr}"


def main():
    print("=" * 72)
    print("FILTER #13 — Engulfing wick-vs-body asymmetry sweep")
    print(f"Thresholds: {[fmt_thr(t) for t in THRESHOLDS]}")
    print("=" * 72)

    results = {
        "filter": 13,
        "name": "Engulfing wick-vs-body asymmetry",
        "generated": datetime.now(timezone.utc).isoformat(),
        "thresholds": [str(t) for t in THRESHOLDS],
        "by_system": {},
    }

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        results["by_system"][s["key"]] = {"label": s["label"], "results": {}}
        module = reload_pkg(s["pkg"])
        for thr in THRESHOLDS:
            label = fmt_thr(thr)
            print(f"  {label}...")
            r = measure(label, module, thr)
            pf_str = f"{r['pf']:.2f}" if r['pf'] != float("inf") else "∞"
            print(f"    N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  "
                  f"P&L=${r['pnl']:>+12,.0f}  ({r['elapsed_s']:.1f}s)")
            results["by_system"][s["key"]]["results"][str(thr)] = r

    json_path = os.path.join(OUT_DIR, "filter_13_results.json")
    # Convert inf -> "inf" for JSON
    results_json = json.dumps(results, indent=2, default=lambda x: "inf" if x == float("inf") else str(x))
    # Replace any remaining Infinity
    results_json = results_json.replace("Infinity", '"inf"')
    with open(json_path, "w") as fh:
        fh.write(results_json)
    print(f"\n✓ wrote {json_path}")

    # Telegram (sync send — bypass daemon-thread bug in notify.send())
    lines = ["🧪 FILTER #13 — Engulfing wick-vs-body asymmetry", ""]
    lines.append("Skip engulfing candles where rejection-wick > body × ratio.")
    lines.append("LONG: upper_wick / body. SHORT: lower_wick / body.")
    lines.append("Lower ratio = stricter filter.")
    lines.append("")
    lines.append("BT 21-yr (4 systems × 4 thresholds):")
    lines.append("")

    aggregate_pnl = {str(t): 0 for t in THRESHOLDS}

    for s in SYSTEMS:
        lines.append(f"<b>{s['label']}</b>")
        sys_results = results["by_system"][s["key"]]["results"]
        baseline = sys_results[str(THRESHOLDS[0])]  # inf = no filter
        baseline_pnl = baseline["pnl"]
        if baseline["n"] == 0:
            lines.append("  no trades")
            continue
        for thr in THRESHOLDS:
            r = sys_results[str(thr)]
            pf = r["pf"] if r["pf"] != float("inf") else 0
            label = fmt_thr(thr)
            if thr == THRESHOLDS[0]:
                lines.append(f"  {label}: PF {pf:.2f}  P&L ${r['pnl']:>+10,.0f}  N={r['n']}  (baseline)")
            else:
                d = r["pnl"] - baseline_pnl
                pct = (d / baseline_pnl * 100) if baseline_pnl else 0
                d_n = r["n"] - baseline["n"]
                emoji = "✅" if d > 0 else ("🟡" if pct > -2 else "❌")
                lines.append(f"  {label}: PF {pf:.2f}  P&L ${r['pnl']:>+10,.0f}  Δ${d:+,.0f} ({pct:+.1f}%) ΔN={d_n:+d}  {emoji}")
            aggregate_pnl[str(thr)] += r["pnl"]
        lines.append("")

    lines.append("<b>TOTAL ΔP&L vs baseline:</b>")
    base_total = aggregate_pnl[str(THRESHOLDS[0])]
    for thr in THRESHOLDS:
        label = fmt_thr(thr)
        if thr == THRESHOLDS[0]:
            lines.append(f"  {label}: ${aggregate_pnl[str(thr)]:>+12,.0f}  (baseline)")
        else:
            d = aggregate_pnl[str(thr)] - base_total
            pct = (d / base_total * 100) if base_total else 0
            lines.append(f"  {label}: ${aggregate_pnl[str(thr)]:>+12,.0f}  Δ${d:+,.0f} ({pct:+.1f}%)")
    lines.append("")
    lines.append("Reply: ship 13 [ratio=N] [systems] / stash 13 / next")

    msg = "\n".join(lines)
    print()
    print(msg)

    # Sync Telegram (avoid daemon-thread bug)
    try:
        from backend import notify as nf
        resp = httpx.post(nf.API_URL,
                          data={"chat_id": nf.CHAT_ID, "text": msg, "parse_mode": "HTML"},
                          timeout=15)
        print(f"\nTelegram HTTP {resp.status_code}")
        if resp.status_code != 200:
            # Retry without parse_mode (HTML tags may have rejected)
            resp = httpx.post(nf.API_URL,
                              data={"chat_id": nf.CHAT_ID, "text": msg},
                              timeout=15)
            print(f"Retry without HTML: HTTP {resp.status_code}")
    except Exception as e:
        print(f"\nTelegram send failed: {e}")


if __name__ == "__main__":
    main()
