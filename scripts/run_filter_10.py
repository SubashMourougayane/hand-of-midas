"""Filter #10 — sl_buffer sweep on Oil Macro.

Audit memo claimed sl_buffer=0.03 puts SL inside the bid-ask spread.
Verification (see scripts/output/filter_10_audit_notes.md):
  - sl_buffer=0.03 is offset from sweep_wick, not entry
  - min_sl=0.10 floor guarantees SL ≥ spread distance
  - 7 closed Oil Macro SL trades show $0.0000 slippage in DB
  - Audit's "BT under-models exit slippage" claim was wrong

But this script measures it anyway — the audit's hypothesis might still
have a smaller version of the effect when wicks are tight. Sweep across
sl_buffer values: 0.03 (baseline) / 0.07 / 0.10 / 0.15.

Other 3 systems are run at baseline only as a regression check (their
generate_signals doesn't take sl_buffer kwarg — Oil Macro is the only
patched strategy for this filter). Their numbers MUST match Filter #7
ship baseline ($427k / $335k / $826k / $3.18M).
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

from backend.notify import send as tg_send
import httpx

OUT_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(OUT_DIR, exist_ok=True)

OIL_MACRO_THRESHOLDS = [0.03, 0.07, 0.10, 0.15]


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


def measure(label, module, **kwargs):
    t0 = time.time()
    result = module.run_backtest(**kwargs)
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
    print("=" * 72)
    print("FILTER #10 — sl_buffer sweep on Oil Macro")
    print(f"Thresholds: {OIL_MACRO_THRESHOLDS}")
    print("=" * 72)

    results = {
        "filter": 10,
        "name": "Spread-Inside SL — sl_buffer sweep on Oil Macro",
        "generated": datetime.now(timezone.utc).isoformat(),
        "thresholds": OIL_MACRO_THRESHOLDS,
        "oil_macro": {},
        "regression": {},
    }

    # Oil Macro sweep
    print("\n[Oil Macro — sl_buffer sweep]")
    oil_macro = reload_pkg("backend-oil")
    for thr in OIL_MACRO_THRESHOLDS:
        print(f"  sl_buffer={thr}...")
        r = measure(f"Oil Macro sl={thr}", oil_macro, sl_buffer=thr)
        pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "∞"
        print(f"    N={r['n']:>4d}  WR={r['wr']:5.1f}%  PF={pf_str:>5}  "
              f"P&L=${r['pnl']:>+12,.0f}  ({r['elapsed_s']:.1f}s)")
        results["oil_macro"][str(thr)] = r

    # Regression check — other 3 systems should all match baseline
    REGRESSION_EXPECTED = {
        "gold_macro": ("backend", 427598.0),
        "gold_micro": ("backend-micro", 334808.0),
        "oil_micro":  ("backend-oil-micro", 3177780.0),
    }
    print("\n[Regression — other 3 systems must match Filter #7 ship baseline]")
    for key, (pkg, expected) in REGRESSION_EXPECTED.items():
        print(f"  {key}...")
        mod = reload_pkg(pkg)
        r = measure(key, mod)
        delta = r["pnl"] - expected
        match = abs(delta) < 1
        marker = "✅" if match else "❌"
        print(f"    P&L=${r['pnl']:>+12,.0f}  expected ${expected:+,.0f}  "
              f"Δ=${delta:+,.0f}  {marker}")
        results["regression"][key] = {**r, "expected": expected, "delta": delta, "match": match}

    json_path = os.path.join(OUT_DIR, "filter_10_results.json")
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\n✓ wrote {json_path}")

    # Telegram (sync — fix for daemon-thread bug)
    lines = ["🧪 FILTER #10 — sl_buffer sweep on Oil Macro", ""]
    lines.append(f"Audit hypothesis: sl_buffer=0.03 too tight (spread~$0.10).")
    lines.append("Verified: SL is offset from sweep_wick (not entry), min_sl=0.10")
    lines.append("guarantees SL distance ≥ spread, 7 live SL trades = $0 slip.")
    lines.append("Measuring anyway to back the stash decision with numbers.")
    lines.append("")
    lines.append("Oil Macro 21-yr sweep:")

    baseline = results["oil_macro"]["0.03"]
    for thr in OIL_MACRO_THRESHOLDS:
        r = results["oil_macro"][str(thr)]
        pf = r["pf"] if r["pf"] != float("inf") else 0
        if thr == 0.03:
            lines.append(f"  sl=0.03 (baseline): PF {pf:.2f}  "
                         f"P&L ${r['pnl']:>+12,.0f}  N={r['n']}")
        else:
            d = r["pnl"] - baseline["pnl"]
            pct = (d / baseline["pnl"] * 100) if baseline["pnl"] else 0
            d_n = r["n"] - baseline["n"]
            emoji = "✅" if d > 0 else ("🟡" if pct > -2 else "❌")
            lines.append(f"  sl={thr}: PF {pf:.2f}  P&L ${r['pnl']:>+12,.0f}  "
                         f"Δ${d:+,.0f} ({pct:+.1f}%) ΔN={d_n:+d}  {emoji}")

    lines.append("")
    lines.append("Regression (other 3 systems — must match Filter #7 baseline):")
    for k, v in results["regression"].items():
        lines.append(f"  {k}: ${v['pnl']:>+12,.0f} Δ${v['delta']:+,.0f}  "
                     f"{'✅' if v['match'] else '❌'}")

    lines.append("")
    lines.append("Reply: ship 10 [sl_buffer=N] / stash 10 / next")

    msg = "\n".join(lines)
    print()
    print(msg)

    # Send synchronously — bypass notify.send() daemon-thread bug
    try:
        from backend import notify
        resp = httpx.post(notify.API_URL,
                          data={"chat_id": notify.CHAT_ID, "text": msg},
                          timeout=15)
        print(f"\nTelegram HTTP {resp.status_code}")
    except Exception as e:
        print(f"\nTelegram send failed: {e}")


if __name__ == "__main__":
    main()
