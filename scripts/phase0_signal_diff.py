"""Apples-to-apples diff: BT signal universe (generate_signals output) vs
live dry_run signals. Both are pre-execution-loop. This is the REAL parity test.
"""
from __future__ import annotations
import os, sys, json, importlib
from collections import defaultdict
import pandas as pd

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)
OUT_DIR = os.path.join(ROOT, "scripts/output")


def get_gold_micro_bt_signals():
    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies", "backend.backtest",
                         "backend.data")):
            del sys.modules[k]
    pkg_path = os.path.join(ROOT, "backend-micro")
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()
    engine = importlib.import_module("backtest.engine")
    data = engine._get_cached_data()
    strat = importlib.import_module("backend.strategies.micro_alpha_sweep")
    from backend.backtest.neutral_bias import NeutralBiasDict
    daily_bias = NeutralBiasDict()
    sigs = strat.generate_signals(data["gold_h1"], data["gold_m3"], daily_bias)
    start = pd.Timestamp("2026-06-11", tz="UTC")
    end = pd.Timestamp("2026-06-18 23:59:59", tz="UTC")
    return [s for s in sigs if start <= s.date <= end]


def get_oil_micro_bt_signals():
    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies", "backend.backtest",
                         "backend.data")):
            del sys.modules[k]
    pkg_path = os.path.join(ROOT, "backend-oil-micro")
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()
    engine = importlib.import_module("backtest.engine")
    data = engine._get_cached_data()
    from backend.backtest.neutral_bias import NeutralBiasDict
    daily_bias = NeutralBiasDict()
    sigs = engine.generate_signals(data["oil_h1"], data["oil_m3"], daily_bias)
    start = pd.Timestamp("2026-06-11", tz="UTC")
    end = pd.Timestamp("2026-06-18 23:59:59", tz="UTC")
    return [s for s in sigs if start <= s.date <= end]


def dedup_bt(bt_sigs):
    """BT signals can have duplicates (same engulfing detected by overlapping windows).
    Dedup by (timestamp, direction) — matches what live's global dedup keying does.
    """
    seen = set()
    out = []
    for s in bt_sigs:
        key = (str(s.date), s.direction)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def diff(bt_sigs, live_sigs, tol_min=2):
    """Match within ±tol_min minutes + same direction. tol_min=2 because both
    are M3 bar boundaries — should match exact or off by 1 bar at most.
    """
    matched = []
    bt_only = []
    used_live = set()

    for bt in bt_sigs:
        bt_ts = pd.Timestamp(bt.date)
        if bt_ts.tzinfo is None:
            bt_ts = bt_ts.tz_localize("UTC")
        bt_dir = bt.direction.lower()
        match = None
        for i, ls in enumerate(live_sigs):
            if i in used_live:
                continue
            ls_ts = pd.Timestamp(ls["time"].replace("Z", "+00:00") if isinstance(ls["time"], str) else ls["time"])
            if ls_ts.tzinfo is None:
                ls_ts = ls_ts.tz_localize("UTC")
            if ls["direction"].lower() != bt_dir:
                continue
            delta = abs((ls_ts - bt_ts).total_seconds() / 60)
            if delta <= tol_min:
                match = (i, ls, delta)
                break
        if match:
            i, ls, delta = match
            used_live.add(i)
            matched.append({"bt": bt, "live": ls, "delta_min": delta})
        else:
            bt_only.append(bt)

    live_only = [ls for i, ls in enumerate(live_sigs) if i not in used_live]
    return matched, bt_only, live_only


# ─── Gold Micro ───
print("=" * 60)
print("Gold Micro — signal-universe diff")
print("=" * 60)
gm_bt_raw = get_gold_micro_bt_signals()
print(f"  BT signal universe (raw, with overlap-window duplicates): {len(gm_bt_raw)}")
gm_bt = dedup_bt(gm_bt_raw)
print(f"  BT signal universe (deduped by ts+dir): {len(gm_bt)}")
with open(os.path.join(OUT_DIR, "baseline_live_signals_gold_micro.json")) as f:
    gm_live = json.load(f)["signals"]
print(f"  Live dry_run signals: {len(gm_live)}")

gm_matched, gm_bt_only, gm_live_only = diff(gm_bt, gm_live, tol_min=2)
print(f"  matched (±2min)    : {len(gm_matched)}")
print(f"  BT-only             : {len(gm_bt_only)}")
print(f"  Live-only           : {len(gm_live_only)}")

print("\n  BT-only signals (BT fires, live doesn't):")
for s in gm_bt_only:
    print(f"    {s.date} {s.direction} entry={s.entry:.2f} sl={s.sl:.2f}")
print("\n  Live-only signals (live fires, BT doesn't):")
for s in gm_live_only:
    print(f"    {s['time']} {s['direction']} entry={s['entry']} sl={s['sl']}")


# ─── Oil Micro ───
print()
print("=" * 60)
print("Oil Micro — signal-universe diff")
print("=" * 60)
om_bt_raw = get_oil_micro_bt_signals()
print(f"  BT signal universe (raw): {len(om_bt_raw)}")
om_bt = dedup_bt(om_bt_raw)
print(f"  BT signal universe (deduped): {len(om_bt)}")
with open(os.path.join(OUT_DIR, "baseline_live_signals_oil_micro.json")) as f:
    om_live = json.load(f)["signals"]
print(f"  Live dry_run signals: {len(om_live)}")

om_matched, om_bt_only, om_live_only = diff(om_bt, om_live, tol_min=2)
print(f"  matched (±2min)    : {len(om_matched)}")
print(f"  BT-only             : {len(om_bt_only)}")
print(f"  Live-only           : {len(om_live_only)}")

print("\n  BT-only signals (BT fires, live doesn't):")
for s in om_bt_only:
    print(f"    {s.date} {s.direction} entry={s.entry:.4f} sl={s.sl:.4f}")
print("\n  Live-only signals (live fires, BT doesn't):")
for s in om_live_only:
    print(f"    {s['time']} {s['direction']} entry={s['entry']} sl={s['sl']}")
