"""Parity Audit — multi-regime sample.

Runs Live↔BT parity audit across calendar windows representing different
market regimes (crisis, bull, bear, sideways, normal). Single self-contained
script with file-based logging that's tail-able from the local terminal.

CRITICAL DESIGN: This script does NOT reimplement signal extraction. It
delegates to the proven `tests/harness/parity/extractor.py` functions
(extract_live_signals, extract_backtest_signals) — same code path that
powers `test_22_parity`. Only the year-selection, logging, and reporting
layers are new here.

Year selection (default):
  2008    Crisis (GFC/Lehman)
  2011    EU debt crisis / Gold bull peak
  2013    Sideways / Gold bear
  2016    Brexit + Trump shock
  2020    COVID crash + recovery
  2022    Russia invasion / inflation
  2024    Normal year (baseline)
  2026YTD Current regime

Total default: 8 regimes × 4 systems = 32 audits.

Usage:
    python scripts/parity_audit_regimes.py
    tail -f scripts/output/parity_audit_regimes.log

Outputs:
  scripts/output/parity_audit_regimes.log    — per-second progress, tail-able
  docs/PARITY_AUDIT_REGIMES.md               — final summary table
  scripts/output/parity_audit_regimes.json   — raw data for follow-up analysis
"""
from __future__ import annotations
import os
import sys
import json
import time
import argparse
import logging
import traceback
from datetime import datetime, timezone

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Use the proven harness primitives — DO NOT reimplement.
from tests.harness.parity.config import SYSTEMS as HARNESS_SYSTEMS
from tests.harness.parity.extractor import (
    extract_backtest_signals,
    extract_live_signals,
)
from tests.harness.parity.runner import _load_data, _build_daily_bias


# ──────────────────────────────────────────────────────────────────────────
# Logging — tail-able file + stdout. Configured by main() based on --suffix.
# ──────────────────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(ROOT, "scripts/output")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("parity_regimes")
logger.setLevel(logging.DEBUG)


def setup_logging(suffix: str = "") -> str:
    """Configure logger with a per-suffix file. Returns log path.

    suffix: empty for default, or e.g. '_gold_micro' to create
    parity_audit_regimes_gold_micro.log when running parallel processes.
    """
    log_path = os.path.join(LOG_DIR, f"parity_audit_regimes{suffix}.log")
    logger.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S",
    )
    fh = logging.FileHandler(log_path, mode="w")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    logger.addHandler(sh)
    return log_path


# ──────────────────────────────────────────────────────────────────────────
# Regimes
# ──────────────────────────────────────────────────────────────────────────
REGIMES = [
    ("2008",    "GFC / Lehman crisis",              "2008-01-01", "2008-12-31"),
    ("2011",    "EU debt crisis / Gold bull peak",  "2011-01-01", "2011-12-31"),
    ("2013",    "Gold bear / sideways",             "2013-01-01", "2013-12-31"),
    ("2016",    "Brexit + Trump election shock",    "2016-01-01", "2016-12-31"),
    ("2020",    "COVID crash + recovery",           "2020-01-01", "2020-12-31"),
    ("2022",    "Russia invasion / inflation",      "2022-01-01", "2022-12-31"),
    ("2024",    "Normal year (baseline)",           "2024-01-01", "2024-12-31"),
    ("2026YTD", "Current regime",                   "2026-01-01", "2026-12-31"),
]


# ──────────────────────────────────────────────────────────────────────────
# Diff (mirrors what the harness does internally; small enough to keep here)
# ──────────────────────────────────────────────────────────────────────────
def diff_records(bt_records, live_records) -> dict:
    """Match BT and Live SignalRecord lists by (timestamp_floored_to_minute, direction)."""
    def key(r):
        return (r.timestamp.replace(second=0, microsecond=0), r.direction)
    bt_keys = {key(r): r for r in bt_records}
    live_keys = {key(r): r for r in live_records}
    in_both = bt_keys.keys() & live_keys.keys()
    bt_only = bt_keys.keys() - live_keys.keys()
    live_only = live_keys.keys() - bt_keys.keys()

    direction_agree = 0
    entry_drifts = []
    sl_drifts = []
    tp_drifts = []
    for k in in_both:
        b = bt_keys[k]
        l = live_keys[k]
        if b.direction == l.direction:
            direction_agree += 1
        if b.entry_price and l.entry_price:
            entry_drifts.append(abs(b.entry_price - l.entry_price))
        if b.sl_price and l.sl_price:
            sl_drifts.append(abs(b.sl_price - l.sl_price))
        if b.tp_price and l.tp_price:
            tp_drifts.append(abs(b.tp_price - l.tp_price))

    return {
        "bt_n": len(bt_records),
        "live_n": len(live_records),
        "in_both": len(in_both),
        "bt_only": len(bt_only),
        "live_only": len(live_only),
        "parity_pct": 100.0 * len(in_both) / max(len(bt_keys), len(live_keys), 1),
        "direction_agree_pct": 100.0 * direction_agree / max(len(in_both), 1),
        "avg_entry_drift": sum(entry_drifts) / len(entry_drifts) if entry_drifts else 0,
        "max_entry_drift": max(entry_drifts) if entry_drifts else 0,
        "avg_sl_drift": sum(sl_drifts) / len(sl_drifts) if sl_drifts else 0,
        "avg_tp_drift": sum(tp_drifts) / len(tp_drifts) if tp_drifts else 0,
    }


# ──────────────────────────────────────────────────────────────────────────
# Audit one (system, regime) — uses proven harness extractors
# ──────────────────────────────────────────────────────────────────────────
def audit_one(
    system_key: str,
    regime_label: str,
    regime_desc: str,
    start_date: str,
    end_date: str,
    h1_full: pd.DataFrame,
    m3_full: pd.DataFrame,
    d_full: pd.DataFrame,
    daily_bias: dict,
) -> dict | None:
    cfg = HARNESS_SYSTEMS[system_key]
    label = cfg.label

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"{label} | {regime_label} ({regime_desc}) | {start_date} → {end_date}")
    logger.info("=" * 70)

    # Slice data to the regime window
    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)  # inclusive end
    h1_win = h1_full[(h1_full.index >= start_ts) & (h1_full.index < end_ts)]
    m3_win = m3_full[(m3_full.index >= start_ts) & (m3_full.index < end_ts)]
    logger.info(f"  H1 window: {len(h1_win):,} bars   M3 window: {len(m3_win):,} bars")

    if len(h1_win) < 24 or len(m3_win) < 100:
        logger.warning(f"  insufficient data for {regime_label} on {label} — skipping")
        return None

    # BT signals — uses proven extract_backtest_signals
    t0 = time.time()
    logger.info("  [BT] generating signals via tests.harness.parity.extractor...")
    try:
        bt_records = extract_backtest_signals(
            system_key=system_key,
            backtest_module_path=cfg.backtest_module_path,
            backtest_fn_name=cfg.backtest_fn_name,
            h1_df=h1_win,
            m3_df=m3_win,
            daily_bias=daily_bias,
        )
    except Exception as e:
        logger.error(f"  [BT] FAILED: {e}")
        logger.error(traceback.format_exc())
        return None
    bt_time = time.time() - t0
    logger.info(f"  [BT] {len(bt_records)} signals in {bt_time:.1f}s")

    # Live signals — uses proven extract_live_signals
    # The harness wants h1/m3 with one-day prefix for first-day lookback realism.
    live_lookback_cutoff = start_ts - pd.Timedelta(days=2)
    h1_for_live = h1_full[(h1_full.index >= live_lookback_cutoff) & (h1_full.index < end_ts)]
    m3_for_live = m3_full[(m3_full.index >= live_lookback_cutoff) & (m3_full.index < end_ts)]

    t0 = time.time()
    logger.info("  [LIVE] generating signals via tests.harness.parity.extractor...")
    try:
        live_records = extract_live_signals(
            system_key=system_key,
            live_module_path=cfg.live_module_path,
            live_core_fn_name=cfg.live_core_fn_name,
            h1_df=h1_for_live,
            m3_df=m3_for_live,
            d_df=d_full,
            daily_bias=daily_bias,
            date_range_start=start_ts.date(),
            date_range_end=(end_ts - pd.Timedelta(seconds=1)).date(),
            architecture=cfg.architecture,
        )
    except Exception as e:
        logger.error(f"  [LIVE] FAILED: {e}")
        logger.error(traceback.format_exc())
        return None
    live_time = time.time() - t0
    logger.info(f"  [LIVE] {len(live_records)} signals in {live_time:.1f}s")

    # Diff
    d = diff_records(bt_records, live_records)
    logger.info(
        f"  Diff: parity={d['parity_pct']:.1f}%  "
        f"in_both={d['in_both']}  bt_only={d['bt_only']}  live_only={d['live_only']}  "
        f"dir_agree={d['direction_agree_pct']:.1f}%  "
        f"avg_entry_drift=${d['avg_entry_drift']:.4f}"
    )

    return {
        "system": system_key,
        "label": label,
        "regime": regime_label,
        "desc": regime_desc,
        "start": start_date,
        "end": end_date,
        "bt_time_s": bt_time,
        "live_time_s": live_time,
        **d,
    }


# ──────────────────────────────────────────────────────────────────────────
# Markdown report
# ──────────────────────────────────────────────────────────────────────────
def write_md_report(results: list[dict], suffix: str = ""):
    out = os.path.join(ROOT, f"docs/PARITY_AUDIT_REGIMES{suffix.upper()}.md")
    L = []
    L.append("# Parity Audit — Multi-Regime Sample (Live ↔ Backtest)")
    L.append("")
    L.append(f"_Generated: {datetime.now(timezone.utc).isoformat()}_")
    L.append("")
    L.append(
        "Sample years chosen to cover different market regimes. Signal extraction "
        "delegates to the proven `tests/harness/parity/extractor.py` functions "
        "(same code path as `test_22_parity`)."
    )
    L.append("")

    L.append("## Per-(system × regime) results")
    L.append("")
    L.append(
        "| System | Regime | Description | BT sigs | Live sigs | In both | "
        "BT only | Live only | Parity % | Direction agree | Avg entry drift |"
    )
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        L.append(
            f"| {r['label']} | {r['regime']} | {r['desc']} | "
            f"{r['bt_n']} | {r['live_n']} | {r['in_both']} | "
            f"{r['bt_only']} | {r['live_only']} | "
            f"{r['parity_pct']:.1f}% | {r['direction_agree_pct']:.1f}% | "
            f"${r['avg_entry_drift']:.4f} |"
        )
    L.append("")

    # Per-system aggregate
    L.append("## Per-system aggregate (across regimes)")
    L.append("")
    L.append(
        "| System | Regimes | Avg parity % | Avg dir agree % | Avg entry drift | "
        "Total BT sigs | Total Live sigs |"
    )
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    by_sys: dict[str, list] = {}
    for r in results:
        by_sys.setdefault(r["label"], []).append(r)
    for label, rs in by_sys.items():
        if not rs:
            continue
        avg_parity = sum(r["parity_pct"] for r in rs) / len(rs)
        avg_dir = sum(r["direction_agree_pct"] for r in rs) / len(rs)
        avg_drift = sum(r["avg_entry_drift"] for r in rs) / len(rs)
        total_bt = sum(r["bt_n"] for r in rs)
        total_live = sum(r["live_n"] for r in rs)
        L.append(
            f"| {label} | {len(rs)} | {avg_parity:.1f}% | {avg_dir:.1f}% | "
            f"${avg_drift:.4f} | {total_bt} | {total_live} |"
        )
    L.append("")

    # Per-regime aggregate (across systems)
    L.append("## Per-regime aggregate (across systems)")
    L.append("")
    L.append(
        "| Regime | Description | Systems | Avg parity % | Avg dir agree % | "
        "Total BT sigs | Total Live sigs |"
    )
    L.append("|---|---|---:|---:|---:|---:|---:|")
    by_regime: dict[str, list] = {}
    for r in results:
        by_regime.setdefault(r["regime"], []).append(r)
    for regime, rs in by_regime.items():
        if not rs:
            continue
        avg_parity = sum(r["parity_pct"] for r in rs) / len(rs)
        avg_dir = sum(r["direction_agree_pct"] for r in rs) / len(rs)
        total_bt = sum(r["bt_n"] for r in rs)
        total_live = sum(r["live_n"] for r in rs)
        desc = rs[0]["desc"]
        L.append(
            f"| {regime} | {desc} | {len(rs)} | {avg_parity:.1f}% | "
            f"{avg_dir:.1f}% | {total_bt} | {total_live} |"
        )
    L.append("")

    with open(out, "w") as f:
        f.write("\n".join(L))
    logger.info(f"\n✓ wrote {out}")


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--systems",
        default="gold_micro,oil_micro,gold_macro,oil_macro",
        help="comma-separated system keys",
    )
    ap.add_argument(
        "--regimes",
        default="2008,2011,2013,2016,2020,2022,2024,2026YTD",
        help="comma-separated regime labels (subset of REGIMES table above)",
    )
    ap.add_argument(
        "--suffix",
        default="",
        help="log/json file suffix (e.g. '_gold_micro' for parallel runs)",
    )
    args = ap.parse_args()

    sys_keys = [k.strip() for k in args.systems.split(",") if k.strip()]
    regime_keys = [k.strip() for k in args.regimes.split(",") if k.strip()]
    regimes = [r for r in REGIMES if r[0] in regime_keys]

    log_path = setup_logging(args.suffix)
    json_path = os.path.join(LOG_DIR, f"parity_audit_regimes{args.suffix}.json")

    logger.info("=" * 70)
    logger.info("PARITY AUDIT — REGIMES")
    logger.info("=" * 70)
    logger.info(f"Systems: {sys_keys}")
    logger.info(f"Regimes: {[r[0] for r in regimes]}")
    logger.info(f"Log file: {log_path}")
    logger.info(
        f"Tail it with:  tail -f {os.path.relpath(log_path, ROOT)}"
    )

    # Pre-load each system's data ONCE (avoid reloading per regime)
    # Cache key = (h1_csv, m3_csv, d_csv) since multiple systems can share data.
    data_cache: dict[tuple, dict] = {}
    for sk in sys_keys:
        if sk not in HARNESS_SYSTEMS:
            logger.warning(f"unknown system: {sk} — skipping")
            continue
        cfg = HARNESS_SYSTEMS[sk]
        cache_key = (cfg.h1_csv, cfg.m3_csv, cfg.daily_csv)
        if cache_key in data_cache:
            continue
        logger.info(f"loading {cfg.label} CSVs...")
        t0 = time.time()
        h1, m3, d = _load_data(cfg)
        bias = _build_daily_bias(d)
        data_cache[cache_key] = {"h1": h1, "m3": m3, "d": d, "bias": bias}
        logger.info(
            f"  loaded H1={len(h1):,} M3={len(m3):,} D={len(d):,} "
            f"in {time.time()-t0:.1f}s"
        )

    results = []
    overall_t0 = time.time()
    total = len(sys_keys) * len(regimes)
    n = 0

    for sk in sys_keys:
        if sk not in HARNESS_SYSTEMS:
            continue
        cfg = HARNESS_SYSTEMS[sk]
        cache_key = (cfg.h1_csv, cfg.m3_csv, cfg.daily_csv)
        cache = data_cache[cache_key]
        for label, desc, start, end in regimes:
            n += 1
            logger.info(f"\n[{n}/{total}] starting...")
            try:
                r = audit_one(
                    sk, label, desc, start, end,
                    cache["h1"], cache["m3"], cache["d"], cache["bias"],
                )
                if r:
                    results.append(r)
                    # Save partial after each audit so you can re-tail and see live-updating json
                    with open(json_path, "w") as f:
                        json.dump(results, f, indent=2, default=str)
            except Exception as e:
                logger.error(f"  FAILED: {e}")
                logger.error(traceback.format_exc())

    overall_time = time.time() - overall_t0
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"COMPLETE: {len(results)} audits in {overall_time/60:.1f} min")
    logger.info("=" * 70)

    write_md_report(results, suffix=args.suffix)


if __name__ == "__main__":
    main()
