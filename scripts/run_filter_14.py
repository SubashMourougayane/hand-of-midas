"""Filter #14 — prev=sweep-bar pollution / require_prev_reversal sweep.

Audit hypothesis: skip_first_bar=True makes engulfing search start at j=2,
with prev=relevant_m3[1]. Since relevant_m3 starts strictly after sweep_time,
relevant_m3[0] and [1] are M3 bars INSIDE the H1 sweep formation. So we're
using a sub-bar of the sweep itself as the engulfing predecessor — circular.

Fix: require prev to be reversal-direction relative to the sweep:
  - bullish-sweep (LONG): prev must be bearish (pc < po)
  - bearish-sweep (SHORT): prev must be bullish (pc > po)

That way the engulfing has something REAL to reverse, not just a continuation
of the sweep-recovery move.

Sweep: baseline (False) vs filter (True), 4 systems = 8 backtests.
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

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)

SYSTEMS = [
    {"key": "gold_macro", "label": "Gold Macro", "pkg": "backend"},
    {"key": "gold_micro", "label": "Gold Micro", "pkg": "backend-micro"},
    {"key": "oil_macro",  "label": "Oil Macro",  "pkg": "backend-oil"},
    {"key": "oil_micro",  "label": "Oil Micro",  "pkg": "backend-oil-micro"},
]


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


def measure(label, module, require_prev_reversal):
    t0 = time.time()
    result = module.run_backtest(require_prev_reversal=require_prev_reversal)
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


def main():
    print("=" * 72)
    print("FILTER #14 — prev=sweep-bar pollution / require_prev_reversal")
    print("=" * 72)

    results = {
        "filter": 14,
        "name": "Require engulfing prev to be reversal-direction",
        "generated": datetime.now(timezone.utc).isoformat(),
        "by_system": {},
    }

    for s in SYSTEMS:
        print(f"\n[{s['label']}]")
        module = reload_pkg(s["pkg"])
        for filter_on, label in [(False, "baseline"), (True, "filter")]:
            print(f"  {label}...")
            r = measure(label, module, filter_on)
            pf_str = f"{r['pf']:.2f}" if r['pf'] != float("inf") else "∞"
            print(f"    N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  "
                  f"P&L=${r['pnl']:>+12,.0f}  ({r['elapsed_s']:.1f}s)")
            results["by_system"].setdefault(s["key"], {"label": s["label"], "results": {}})
            results["by_system"][s["key"]]["results"][label] = r

    json_path = os.path.join(OUT_DIR, "filter_14_results.json")
    results_json = json.dumps(results, indent=2, default=lambda x: "inf" if x == float("inf") else str(x))
    results_json = results_json.replace("Infinity", '"inf"')
    with open(json_path, "w") as fh:
        fh.write(results_json)
    print(f"\n✓ wrote {json_path}")

    # Telegram (sync send)
    lines = ["🧪 FILTER #14 — prev=sweep-bar pollution", ""]
    lines.append("Audit: engulfing prev-bar (relevant_m3[1]) is inside the H1")
    lines.append("sweep formation, not a clean independent prior bar.")
    lines.append("")
    lines.append("Fix: require prev to be reversal-direction:")
    lines.append("  bullish-sweep needs bearish prev (pc < po)")
    lines.append("  bearish-sweep needs bullish prev (pc > po)")
    lines.append("")
    lines.append("BT 21-yr (4 systems × baseline/filter):")
    lines.append("")

    total_b = 0
    total_f = 0
    for s in SYSTEMS:
        sys_results = results["by_system"][s["key"]]["results"]
        b = sys_results["baseline"]
        f = sys_results["filter"]
        if b["n"] == 0:
            lines.append(f"  {s['label']}: no trades")
            continue
        pf_b = b["pf"] if b["pf"] != float("inf") else 0
        pf_f = f["pf"] if f["pf"] != float("inf") else 0
        d = f["pnl"] - b["pnl"]
        pct = (d / b["pnl"] * 100) if b["pnl"] else 0
        d_n = f["n"] - b["n"]
        n_pct = (d_n / b["n"] * 100) if b["n"] else 0
        emoji = "✅" if (d > 0 and pf_f >= pf_b) else ("🟡" if pct > -2 else "❌")
        total_b += b["pnl"]
        total_f += f["pnl"]
        lines.append(
            f"  {s['label']}: PF {pf_b:.2f}→{pf_f:.2f}  "
            f"ΔP&L=${d:+,.0f} ({pct:+.1f}%)  ΔN={d_n:+d} ({n_pct:+.1f}%)  {emoji}"
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
    lines.append("Reply: ship 14 [systems] / stash 14 / next")

    msg = "\n".join(lines)
    print()
    print(msg)

    # Sync Telegram (avoid daemon-thread bug)
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
