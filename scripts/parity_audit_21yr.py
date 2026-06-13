"""Full 21-yr parity audit — Live signal-gen vs Backtest signal-gen.

For each of the 4 systems:
  1. Run BT signal-gen (extract_backtest_signals) — produces list[SignalRecord]
  2. Run Live signal-gen (extract_live_signals via dry_run replay) — produces list[SignalRecord]
  3. Diff at signal layer: count, direction agreement, entry/SL/TP drift
  4. (Optional, much slower) Re-run both signal lists through real fill model
     for trade-level P&L comparison

Output: docs/PARITY_AUDIT_21YR.md with per-system table + diagnostic notes.

Usage:
    python scripts/parity_audit_21yr.py                   # full 21yr (slow — 30min+)
    python scripts/parity_audit_21yr.py --days 365        # last 1yr (faster smoke)
    python scripts/parity_audit_21yr.py --systems gold_micro,oil_micro
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.harness.parity.config import SYSTEMS
from tests.harness.parity.extractor import (
    extract_backtest_signals,
    extract_live_signals,
)
from tests.harness.parity.runner import _load_data, _build_daily_bias


def audit_one_system(system_key: str, days: int | None) -> dict:
    """Run BT + Live signal-gen on one system, return summary stats."""
    cfg = SYSTEMS[system_key]
    print(f"\n{'='*70}\n{cfg.label} ({system_key})\n{'='*70}")

    h1_full, m3_full, d_full = _load_data(cfg)
    daily_bias = _build_daily_bias(d_full)

    last_ts = m3_full.index[-1]
    if days:
        cutoff = last_ts - pd.Timedelta(days=days)
        h1_df = h1_full[h1_full.index >= cutoff]
        m3_df = m3_full[m3_full.index >= cutoff]
        live_lookback_cutoff = cutoff - pd.Timedelta(days=2)
        h1_for_live = h1_full[h1_full.index >= live_lookback_cutoff]
        m3_for_live = m3_full[m3_full.index >= live_lookback_cutoff]
        date_start = cutoff.date()
    else:
        # Full history
        h1_df = h1_full
        m3_df = m3_full
        h1_for_live = h1_full
        m3_for_live = m3_full
        date_start = m3_full.index[0].date()

    print(f"  M3 bars: {len(m3_df):,}  H1 bars: {len(h1_df):,}")
    print(f"  Window: {date_start} → {last_ts.date()}")

    # Backtest signals
    t0 = time.time()
    print(f"  [BT] running signal-gen...")
    bt_records = extract_backtest_signals(
        system_key=system_key,
        backtest_module_path=cfg.backtest_module_path,
        backtest_fn_name=cfg.backtest_fn_name,
        h1_df=h1_df,
        m3_df=m3_df,
        daily_bias=daily_bias,
    )
    bt_time = time.time() - t0
    print(f"  [BT] {len(bt_records)} signals in {bt_time:.1f}s")

    # Live signals
    t0 = time.time()
    print(f"  [LIVE] running signal-gen replay...")
    live_records = extract_live_signals(
        system_key=system_key,
        live_module_path=cfg.live_module_path,
        live_core_fn_name=cfg.live_core_fn_name,
        h1_df=h1_for_live,
        m3_df=m3_for_live,
        d_df=d_full,
        daily_bias=daily_bias,
        date_range_start=date_start,
        date_range_end=last_ts.date(),
        architecture=cfg.architecture,
    )
    live_time = time.time() - t0
    print(f"  [LIVE] {len(live_records)} signals in {live_time:.1f}s")

    # Diff
    bt_keys = {(r.timestamp.replace(second=0, microsecond=0), r.direction): r for r in bt_records}
    live_keys = {(r.timestamp.replace(second=0, microsecond=0), r.direction): r for r in live_records}
    in_both = bt_keys.keys() & live_keys.keys()
    bt_only = bt_keys.keys() - live_keys.keys()
    live_only = live_keys.keys() - bt_keys.keys()

    # Direction & price drift on overlapping
    direction_agree = 0
    entry_drifts = []
    sl_drifts = []
    tp_drifts = []
    for k in in_both:
        bt_r = bt_keys[k]
        live_r = live_keys[k]
        if bt_r.direction == live_r.direction:
            direction_agree += 1
        if bt_r.entry_price and live_r.entry_price:
            entry_drifts.append(abs(bt_r.entry_price - live_r.entry_price))
        if bt_r.sl_price and live_r.sl_price:
            sl_drifts.append(abs(bt_r.sl_price - live_r.sl_price))
        if bt_r.tp_price and live_r.tp_price:
            tp_drifts.append(abs(bt_r.tp_price - live_r.tp_price))

    parity_pct = (
        100.0 * (len(in_both) + (len(bt_only) + len(live_only)) * 0)
        / max(len(bt_keys), len(live_keys), 1)
    )
    direction_agree_pct = 100.0 * direction_agree / len(in_both) if in_both else 0.0

    return {
        "system": system_key,
        "label": cfg.label,
        "bt_signals": len(bt_records),
        "live_signals": len(live_records),
        "in_both": len(in_both),
        "bt_only": len(bt_only),
        "live_only": len(live_only),
        "parity_pct": parity_pct,
        "direction_agree_pct": direction_agree_pct,
        "avg_entry_drift": sum(entry_drifts) / len(entry_drifts) if entry_drifts else 0,
        "max_entry_drift": max(entry_drifts) if entry_drifts else 0,
        "avg_sl_drift": sum(sl_drifts) / len(sl_drifts) if sl_drifts else 0,
        "avg_tp_drift": sum(tp_drifts) / len(tp_drifts) if tp_drifts else 0,
        "bt_time_s": bt_time,
        "live_time_s": live_time,
        "window_start": str(date_start),
        "window_end": str(last_ts.date()),
    }


def write_results_md(results: list[dict], out_path: str):
    lines = [
        "# Parity Audit — 21yr Live ↔ Backtest",
        "",
        f"_Generated: {datetime.now(timezone.utc).isoformat()}_",
        "",
        "## Summary table",
        "",
        "| System | BT sigs | Live sigs | In both | BT only | Live only | Parity % | Direction agree | Avg entry drift | Max entry drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['label']} | {r['bt_signals']} | {r['live_signals']} | "
            f"{r['in_both']} | {r['bt_only']} | {r['live_only']} | "
            f"{r['parity_pct']:.1f}% | {r['direction_agree_pct']:.1f}% | "
            f"${r['avg_entry_drift']:.4f} | ${r['max_entry_drift']:.4f} |"
        )
    lines.append("")
    lines.append("## Per-system detail")
    lines.append("")
    for r in results:
        lines.append(f"### {r['label']}")
        lines.append("")
        lines.append(f"- Window: {r['window_start']} → {r['window_end']}")
        lines.append(f"- BT signals: {r['bt_signals']}  (run time {r['bt_time_s']:.1f}s)")
        lines.append(f"- Live signals: {r['live_signals']}  (run time {r['live_time_s']:.1f}s)")
        lines.append(f"- Parity: {r['parity_pct']:.1f}%  ({r['in_both']} in both / {r['bt_only']} BT-only / {r['live_only']} Live-only)")
        lines.append(f"- Direction agreement on overlap: {r['direction_agree_pct']:.1f}%")
        lines.append(f"- Avg entry drift: ${r['avg_entry_drift']:.4f}")
        lines.append(f"- Avg SL drift: ${r['avg_sl_drift']:.4f}")
        lines.append(f"- Avg TP drift: ${r['avg_tp_drift']:.4f}")
        lines.append("")
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"\n✓ wrote {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None,
                    help="Window in days. Default: full history (21yr).")
    ap.add_argument("--systems", default="gold_micro,oil_micro,gold_macro,oil_macro",
                    help="Comma-separated system keys")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs/PARITY_AUDIT_21YR.md"))
    args = ap.parse_args()

    keys = [k.strip() for k in args.systems.split(",")]

    results = []
    for k in keys:
        if k not in SYSTEMS:
            print(f"unknown system: {k}")
            continue
        try:
            r = audit_one_system(k, days=args.days)
            results.append(r)
        except Exception as e:
            import traceback
            print(f"  ERROR on {k}: {e}")
            print(traceback.format_exc())

    if results:
        write_results_md(results, args.out)


if __name__ == "__main__":
    main()
