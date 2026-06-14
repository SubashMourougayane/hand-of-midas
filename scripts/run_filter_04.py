"""Filter #4 — Anti-Trend-Extension sweep.

Skip the entry if the prior 4-hour H1 close-to-close move has already exceeded
threshold * ATR_14 in the SAME direction as the entry (LONG entries skipped
when up-move is large; SHORT entries skipped when down-move is large).

Hypothesis: late entries into already-extended moves have poor EV. The H1
sweep's directional bias is a fade-trade signal, not a continuation signal,
so this filter targets the case where the fade is "too late."

Sweep across thresholds 0 (baseline) / 1.5 / 2.0 / 2.5 across all 4 systems.
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

import httpx
from backend import notify

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)


SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro", "pkg": "backend"},
    {"key": "gold_micro", "label": "Gold Micro", "pkg": "backend-micro"},
    {"key": "oil_macro",  "label": "Oil Macro",  "pkg": "backend-oil"},
    {"key": "oil_micro",  "label": "Oil Micro",  "pkg": "backend-oil-micro"},
]

THRESHOLDS = [0.0, 1.5, 2.0, 2.5]


def run_one(label, pkg_dir, *, threshold):
    """Reload modules per package, run real run_backtest with the kwarg."""
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
    result = module.run_backtest(anti_trend_threshold=threshold)
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
    pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
    return f"N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  P&L=${r['pnl']:>+12,.0f}"


def main():
    print("=" * 72)
    print("FILTER #4 — Anti-Trend-Extension Sweep")
    print("=" * 72)
    print(f"Lookback: 4 hours of H1 close-to-close move")
    print(f"Thresholds: {THRESHOLDS} (× ATR_14)")
    print(f"Direction: skip LONG when move > T*ATR up; skip SHORT when move < -T*ATR down")
    print("=" * 72)

    results = {"filter": 4, "name": "Anti-Trend-Extension",
               "generated": datetime.now(timezone.utc).isoformat(),
               "params": {"lookback_h": 4, "thresholds": THRESHOLDS},
               "by_system": {}}

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        results["by_system"][s["key"]] = {}
        for t in THRESHOLDS:
            tag = f"baseline" if t == 0 else f"T={t:.1f}"
            print(f"  {tag}...")
            r = run_one(s["label"], s["pkg"], threshold=t)
            print(f"    {fmt(r)}  ({r['elapsed_s']:.1f}s)")
            results["by_system"][s["key"]][str(t)] = r

    json_path = os.path.join(OUT_DIR, "filter_04_results.json")
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\nwrote {json_path}")

    # Telegram summary (sync httpx — daemon-thread workaround)
    lines = ["<b>FILTER #4 - Anti-Trend-Extension</b>", "",
             "Skip when prior 4hr H1 move already > T*ATR_14 same direction.", "",
             "BT 21-yr (all 4 systems):", ""]

    totals = {str(t): 0.0 for t in THRESHOLDS}

    for s in SYSTEMS:
        sys_data = results["by_system"][s["key"]]
        baseline = sys_data["0.0"]
        if baseline["n"] == 0:
            lines.append(f"  {s['label']:11}: no trades")
            continue
        lines.append(f"<b>{s['label']}</b>")
        b_pnl = baseline["pnl"]
        b_pf = baseline["pf"] if baseline["pf"] != float("inf") else 0
        lines.append(f"  base  : PF {b_pf:.2f}  P&L ${b_pnl:+,.0f}  N={baseline['n']}")
        totals["0.0"] += b_pnl

        for t in THRESHOLDS:
            if t == 0:
                continue
            r = sys_data[str(t)]
            pnl = r["pnl"]
            pf = r["pf"] if r["pf"] != float("inf") else 0
            d = pnl - b_pnl
            pct = (d / b_pnl * 100) if b_pnl else 0
            em = "OK " if (pf > b_pf and pct > -2) else ("/!\\ " if pct > -10 else "X  ")
            lines.append(f"  T={t:.1f} : PF {pf:.2f}  dP&L ${d:+,.0f} ({pct:+.1f}%) N={r['n']}  {em}")
            totals[str(t)] += pnl

    lines.append("")
    lines.append(f"<b>Total deltas vs baseline:</b>")
    base_total = totals["0.0"]
    for t in THRESHOLDS:
        if t == 0:
            continue
        d = totals[str(t)] - base_total
        pct = (d / base_total * 100) if base_total else 0
        lines.append(f"  T={t:.1f} : ${d:+,.0f} ({pct:+.1f}%)")
    lines.append("")
    lines.append("Reply: ship 4 [T] [systems] / stash 4 / next")

    msg = "\n".join(lines)
    print()
    print(msg)
    try:
        resp = httpx.post(notify.API_URL,
                          data={"chat_id": notify.CHAT_ID, "text": msg, "parse_mode": "HTML"},
                          timeout=20)
        print(f"telegram: HTTP {resp.status_code}")
    except Exception as e:
        print(f"telegram failed: {e}")


if __name__ == "__main__":
    main()
