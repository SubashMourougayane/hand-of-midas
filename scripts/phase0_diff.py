"""Phase 0 task 0.3 + 0.4 — diff BT signals vs live dry_run signals.

For each Micro system:
  - Load baseline_live_signals_<system>.json (already written)
  - Re-run BT for Jun 11-18 window only, capture full signal list (not just trades)
  - Match by (timestamp ± 6min, direction) — 6min = 2 M3 bars tolerance
  - Tabulate: matched / BT-only / live-only
  - Write baseline_parity_<system>.txt

Output: scripts/output/baseline_parity_<system>.txt + PARITY_BASELINE.md
"""
from __future__ import annotations
import os
import sys
import json
import importlib
from datetime import datetime, timezone

import pandas as pd

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, "scripts/output")


def get_bt_trades(label: str, pkg_dir: str, strategies=None):
    """Run BT, return trade list filtered to Jun 11-18."""
    print(f"  Running BT for {label}...")
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
    module = importlib.import_module("backtest.engine")

    kwargs = {"bias_mode": "neutral"}
    if strategies:
        kwargs["strategies"] = strategies
    result = module.run_backtest(**kwargs)
    window_trades = [
        t for t in result.trades
        if "2026-06-11" <= str(t.date)[:10] <= "2026-06-18"
    ]
    return window_trades


def parse_ts(ts):
    """Parse ISO timestamp, normalize to tz-aware UTC."""
    if isinstance(ts, str):
        s = ts.replace("Z", "+00:00")
        # handle ".000000Z" → ".000000+00:00"
        return pd.Timestamp(s).tz_convert("UTC") if pd.Timestamp(s).tzinfo else pd.Timestamp(s, tz="UTC")
    return pd.Timestamp(ts).tz_convert("UTC") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts, tz="UTC")


def diff_signals(label: str, bt_trades: list, live_signals: list,
                 tol_minutes: int = 6) -> dict:
    """Match BT trades to live signals by ±tol_minutes timestamp + same direction.

    A 'match' = same engulfing time within tolerance + same direction.
    Entry/SL/TP ARE expected to match within rounding (BT vs live use same
    formula). We log mismatches as a side check.
    """
    matched = []
    bt_only = list(bt_trades)
    live_only = list(live_signals)

    # Build index over live signals
    live_used = set()
    bt_unmatched = []

    for bt in bt_trades:
        bt_ts = parse_ts(bt.date)
        bt_dir = bt.direction.lower()
        match = None
        for i, ls in enumerate(live_signals):
            if i in live_used:
                continue
            ls_ts = parse_ts(ls["time"])
            ls_dir = ls["direction"].lower()
            if ls_dir != bt_dir:
                continue
            delta_min = abs((ls_ts - bt_ts).total_seconds() / 60)
            if delta_min <= tol_minutes:
                match = (i, ls, delta_min)
                break
        if match:
            i, ls, delta = match
            live_used.add(i)
            matched.append({
                "bt_time": str(bt.date), "live_time": ls["time"],
                "direction": bt_dir, "delta_min": delta,
                "bt_entry": bt.entry, "live_entry": ls["entry"],
                "bt_sl": bt.sl, "live_sl": ls["sl"],
                "bt_tp": bt.tp, "live_tp": ls["tp"],
                "bt_exit": bt.exit_price, "bt_pnl": bt.pnl_sized,
            })
        else:
            bt_unmatched.append(bt)

    live_unmatched = [ls for i, ls in enumerate(live_signals) if i not in live_used]

    return {
        "matched": matched,
        "bt_only": bt_unmatched,
        "live_only": live_unmatched,
    }


def write_parity_txt(label: str, output_name: str, bt_trades, live_signals, diff):
    out_path = os.path.join(OUT_DIR, output_name)
    with open(out_path, "w") as f:
        f.write(f"# Phase 0 baseline parity — {label}\n\n")
        f.write(f"Window: 2026-06-11 → 2026-06-18\n")
        f.write(f"BT bias_mode: neutral\n")
        f.write(f"Live BIAS_MODE env: neutral (per-system)\n\n")
        f.write(f"BT trades        : {len(bt_trades)}\n")
        f.write(f"Live signals     : {len(live_signals)}\n")
        f.write(f"Matched          : {len(diff['matched'])}\n")
        f.write(f"BT-only           : {len(diff['bt_only'])}\n")
        f.write(f"Live-only         : {len(diff['live_only'])}\n\n")
        f.write(f"Match rate (BT view)   : {len(diff['matched'])}/{len(bt_trades)} = {len(diff['matched'])/max(len(bt_trades),1)*100:.1f}%\n")
        f.write(f"Match rate (Live view) : {len(diff['matched'])}/{len(live_signals)} = {len(diff['matched'])/max(len(live_signals),1)*100:.1f}%\n\n")

        f.write("=== Matched signals ===\n")
        for m in diff["matched"]:
            entry_diff = abs(m["bt_entry"] - m["live_entry"])
            sl_diff = abs(m["bt_sl"] - m["live_sl"])
            tp_diff = abs(m["bt_tp"] - m["live_tp"])
            f.write(f"  BT={m['bt_time']} live={m['live_time']} {m['direction']} "
                   f"Δ{m['delta_min']:.0f}m  "
                   f"e_diff={entry_diff:.4f} sl_diff={sl_diff:.4f} tp_diff={tp_diff:.4f}\n")

        f.write("\n=== BT-only (BT fired, live didn't) ===\n")
        for t in diff["bt_only"]:
            f.write(f"  {t.date} {t.direction} entry={t.entry:.4f} sl={t.sl:.4f} tp={t.tp:.4f} "
                   f"exit={t.exit_price:.4f} pnl=${t.pnl_sized:.2f}\n")

        f.write("\n=== Live-only (live fired, BT didn't) ===\n")
        for s in diff["live_only"]:
            f.write(f"  {s['time']} {s['direction']} entry={s['entry']:.4f} sl={s['sl']:.4f} tp={s['tp']:.4f}\n")
    print(f"  wrote: {out_path}")


# ─── Gold Micro ────────────────────────────────────────────────
print("=" * 60)
print("Gold Micro — Phase 0 diff")
print("=" * 60)
with open(os.path.join(OUT_DIR, "baseline_live_signals_gold_micro.json")) as f:
    gold_live = json.load(f)["signals"]
gold_bt = get_bt_trades("Gold Micro", "backend-micro", strategies=["micro_alpha_sweep"])
print(f"  BT trades        : {len(gold_bt)}")
print(f"  Live dry_run sigs: {len(gold_live)}")

gold_diff = diff_signals("Gold Micro", gold_bt, gold_live)
print(f"  matched          : {len(gold_diff['matched'])}")
print(f"  BT-only          : {len(gold_diff['bt_only'])}")
print(f"  Live-only        : {len(gold_diff['live_only'])}")
write_parity_txt("Gold Micro", "baseline_parity_gold_micro.txt",
                 gold_bt, gold_live, gold_diff)

# ─── Oil Micro ─────────────────────────────────────────────────
print()
print("=" * 60)
print("Oil Micro — Phase 0 diff")
print("=" * 60)
with open(os.path.join(OUT_DIR, "baseline_live_signals_oil_micro.json")) as f:
    oil_live = json.load(f)["signals"]
oil_bt = get_bt_trades("Oil Micro", "backend-oil-micro")
print(f"  BT trades        : {len(oil_bt)}")
print(f"  Live dry_run sigs: {len(oil_live)}")

oil_diff = diff_signals("Oil Micro", oil_bt, oil_live)
print(f"  matched          : {len(oil_diff['matched'])}")
print(f"  BT-only          : {len(oil_diff['bt_only'])}")
print(f"  Live-only        : {len(oil_diff['live_only'])}")
write_parity_txt("Oil Micro", "baseline_parity_oil_micro.txt",
                 oil_bt, oil_live, oil_diff)


# ─── Save BT signal lists too (task 0.1 wants them as JSON) ────
def trades_to_json(trades):
    return [{
        "time": str(t.date), "direction": t.direction.lower(),
        "entry": t.entry, "sl": t.sl, "tp": t.tp,
        "exit": t.exit_price, "exit_reason": t.status,
        "pnl_unit": t.pnl_unit, "pnl_sized": t.pnl_sized,
        "bars_held": t.bars_held, "risk": t.risk, "r_mult": t.r_mult,
    } for t in trades]

with open(os.path.join(OUT_DIR, "baseline_bt_signals_gold_micro.json"), "w") as f:
    json.dump({"system": "Gold Micro", "window": "2026-06-11 → 2026-06-18",
               "bias_mode": "neutral", "trade_count": len(gold_bt),
               "signals": trades_to_json(gold_bt)}, f, indent=2)
with open(os.path.join(OUT_DIR, "baseline_bt_signals_oil_micro.json"), "w") as f:
    json.dump({"system": "Oil Micro", "window": "2026-06-11 → 2026-06-18",
               "bias_mode": "neutral", "trade_count": len(oil_bt),
               "signals": trades_to_json(oil_bt)}, f, indent=2)

# ─── PARITY_BASELINE.md ────────────────────────────────────────
md_path = os.path.join(ROOT, "docs/30-day-challenge/reports/PARITY_BASELINE.md")
with open(md_path, "w") as f:
    f.write("# Phase 0 — Live ↔ BT Signal Parity Baseline\n\n")
    f.write(f"**Date:** 2026-06-19\n")
    f.write(f"**Window:** Jun 11-18, 2026\n")
    f.write(f"**Data source:** JustMarkets MT5 (data/raw/{{XAU,BCO}}_USD_{{D,H1,M3}}.csv)\n")
    f.write(f"**BIAS_MODE:** neutral (matches live VPS state)\n\n")
    f.write("---\n\n")
    f.write("## Scope\n\n")
    f.write("Per [DECISION_2026-06-19_DROP_MACROS.md](DECISION_2026-06-19_DROP_MACROS.md): "
            "Macros dropped from refactor scope. Phase 0 covers only Gold Micro + Oil Micro.\n\n")
    f.write("Insurance walks (M3 OHLC ground-truth checks) completed for both systems before this baseline:\n")
    f.write("- Gold Micro Jun 17 02:15 SHORT — reconciled exact (F27 limit + plain SL)\n")
    f.write("- Oil Micro Jun 17 04:18 SHORT — reconciled exact (F27 + F7 partial + F5 BE_SL)\n\n")
    f.write("BT mechanics confirmed genuine. BT-as-oracle for refactor is sound.\n\n")
    f.write("---\n\n")
    f.write("## Method\n\n")
    f.write("- **0.1 BT signals**: ran each system's `run_backtest(bias_mode='neutral', strategies=['micro_alpha_sweep' | 'micro_alpha_sweep_oil'])` — captured trade list for window. JSON: `scripts/output/baseline_bt_signals_<system>.json`\n")
    f.write("- **0.2 Live dry_run signals**: replayed Jun 11-18 in 3-min ticks through each scheduler's `_run_micro_sweep_core(..., dry_run=True)`. Mocked DB calls (no positions, no recent signal cooldown). Per-system env vars set: `GOLD_MICRO_BIAS_MODE=neutral`, `OIL_MICRO_BIAS_MODE=neutral`. JSON: `scripts/output/baseline_live_signals_<system>.json`\n")
    f.write("- **0.3 Diff**: matched by (timestamp ± 6min, direction). TXT: `scripts/output/baseline_parity_<system>.txt`\n")
    f.write("- **0.4 Counts**: this document.\n\n")
    f.write("---\n\n")
    f.write("## Results\n\n")
    f.write("### Gold Micro\n\n")
    f.write("| Bucket | Count |\n|---|---|\n")
    f.write(f"| BT trades        | {len(gold_bt)} |\n")
    f.write(f"| Live dry_run sigs | {len(gold_live)} |\n")
    f.write(f"| Matched          | {len(gold_diff['matched'])} |\n")
    f.write(f"| BT-only           | {len(gold_diff['bt_only'])} |\n")
    f.write(f"| Live-only         | {len(gold_diff['live_only'])} |\n")
    f.write(f"\n**Match rate (BT view)**: {len(gold_diff['matched'])}/{len(gold_bt)} = {len(gold_diff['matched'])/max(len(gold_bt),1)*100:.1f}%\n")
    f.write(f"**Match rate (Live view)**: {len(gold_diff['matched'])}/{len(gold_live)} = {len(gold_diff['matched'])/max(len(gold_live),1)*100:.1f}%\n\n")

    f.write("### Oil Micro\n\n")
    f.write("| Bucket | Count |\n|---|---|\n")
    f.write(f"| BT trades        | {len(oil_bt)} |\n")
    f.write(f"| Live dry_run sigs | {len(oil_live)} |\n")
    f.write(f"| Matched          | {len(oil_diff['matched'])} |\n")
    f.write(f"| BT-only           | {len(oil_diff['bt_only'])} |\n")
    f.write(f"| Live-only         | {len(oil_diff['live_only'])} |\n")
    f.write(f"\n**Match rate (BT view)**: {len(oil_diff['matched'])}/{len(oil_bt)} = {len(oil_diff['matched'])/max(len(oil_bt),1)*100:.1f}%\n")
    f.write(f"**Match rate (Live view)**: {len(oil_diff['matched'])}/{len(oil_live)} = {len(oil_diff['matched'])/max(len(oil_live),1)*100:.1f}%\n\n")

    f.write("---\n\n")
    f.write("## Interpretation\n\n")
    f.write("These match-rates are the **pre-refactor baseline**. After Phase 2-5 refactor "
            "unifies live signal-gen with BT's, the same harness should report >95% match rate.\n\n")
    f.write("Per system breakdown of divergences in `scripts/output/baseline_parity_<system>.txt`. "
            "Cross-reference with [MASTER_RCA_LIVE_BT_PARITY.md](MASTER_RCA_LIVE_BT_PARITY.md) "
            "smoking guns:\n")
    f.write("- Gold Micro: D2 (config-key drift), D3 (window iteration), D4 (dedup keying)\n")
    f.write("- Oil Micro: D2 (rolling-window cadence), D4 (account-wide MT5 lock — N/A in dry_run since DB mocked), D5 (dedup keying), D9 (hardcoded `range(2, ...)`)\n\n")
    f.write("---\n\n")
    f.write("## Caveats\n\n")
    f.write("**dry_run mocked DB state** — no cooldown, no open-position blocker, no daily cap, no MT5 lock. "
            "Real live with non-empty DB would fire FEWER signals than the dry_run replay shows. "
            "This is acceptable because we're measuring the strategy-logic divergence, not the production-gate divergence. "
            "Gates wrap the call, they don't replace it.\n\n")
    f.write("**Tolerance ± 6min** — accounts for the fact that live's 3-min cron may catch a sweep one tick after "
            "BT's per-bar walk would. Tighter than 6min would falsely break parity on cron timing.\n")

print(f"\n  wrote: {md_path}")
