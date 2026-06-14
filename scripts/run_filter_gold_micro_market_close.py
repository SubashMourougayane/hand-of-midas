"""Filter — Gold Micro market_close 21-22 UTC drop.

Background: backend/strategies/micro_alpha_sweep.py inherits a 21-22 UTC
'market closed' block from Oil Micro config. Gold Micro doesn't actually
close at this hour. Audit (2026-06-12) showed dropping the gate gains
~$27k on 21yr (+11.5% PF). Oil keeps the gate (regresses without it).

This run measures Gold Micro only: baseline vs disabled-market-close.
Oil systems untouched.
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


def run_one(*, disable_market_close: bool):
    """Reload modules and run Gold Micro backtest."""
    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies", "backend.backtest", "backend.data")):
            del sys.modules[k]
    pkg_path = os.path.join(ROOT, "backend-micro")
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()

    module = importlib.import_module("backtest.engine")
    t0 = time.time()
    result = module.run_backtest(disable_market_close=disable_market_close)
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
    print("FILTER — Gold Micro market_close 21-22 UTC drop")
    print("=" * 72)
    print("Hypothesis: removing the 21-22 UTC block on Gold Micro gains P&L.")
    print("Oil Micro NOT included (regresses per audit). Gold Macro NOT included")
    print("(uses full Asia-range strategy, no rolling-window market-close gate).")
    print("=" * 72)

    print("\n[Gold Micro]")
    print("  baseline (block 21-22 UTC)...")
    base = run_one(disable_market_close=False)
    print(f"    {fmt(base)}  ({base['elapsed_s']:.1f}s)")

    print("  disabled (no block)...")
    fix = run_one(disable_market_close=True)
    print(f"    {fmt(fix)}  ({fix['elapsed_s']:.1f}s)")

    delta_pnl = fix["pnl"] - base["pnl"]
    delta_pf = fix["pf"] - base["pf"]
    delta_n = fix["n"] - base["n"]
    pct_pnl = (delta_pnl / base["pnl"] * 100) if base["pnl"] else 0
    pct_pf = (delta_pf / base["pf"] * 100) if base["pf"] else 0

    results = {
        "filter": "gold_micro_market_close",
        "generated": datetime.now(timezone.utc).isoformat(),
        "system": "gold_micro",
        "baseline": base,
        "disabled": fix,
        "delta": {"pnl": delta_pnl, "pf": delta_pf, "n": delta_n,
                  "pct_pnl": pct_pnl, "pct_pf": pct_pf},
    }
    json_path = os.path.join(OUT_DIR, "filter_gold_micro_market_close_results.json")
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\nwrote {json_path}")

    em = "OK " if (delta_pnl > 0 and delta_pf > 0) else "/!\\ " if delta_pnl > 0 else "X  "

    msg = f"""<b>FILTER - Gold Micro market_close drop</b>

Drop the 21-22 UTC block on Gold Micro (inherited from Oil config).

<b>Gold Micro 21-yr:</b>
  baseline (block on)
    PF {base['pf']:.2f}   P&L ${base['pnl']:+,.0f}   N={base['n']}
  disabled (block off)
    PF {fix['pf']:.2f}   P&L ${fix['pnl']:+,.0f}   N={fix['n']}

<b>Delta:</b> {em}
  P&L: ${delta_pnl:+,.0f} ({pct_pnl:+.1f}%)
  PF:  {delta_pf:+.2f} ({pct_pf:+.1f}%)
  N:   {delta_n:+d}

Oil systems untouched (regress without the block per prior audit).

Reply: ship gold_micro_mc / stash / next"""

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
