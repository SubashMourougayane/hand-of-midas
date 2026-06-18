"""Overlap analysis: Oil Macro vs Oil Micro on JM data 2026 Jan-Jun.

Pulls both BT trade lists (bias_mode=neutral). Matches by timestamp ±15min
+ same direction. Tabulates: overlap, macro-only, micro-only, P&L of each.
"""
from __future__ import annotations
import os
import sys
import importlib
import pandas as pd

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)


def run_for(label: str, pkg_dir: str):
    print(f"  Running {label}...")
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
    result = module.run_backtest(bias_mode="neutral")
    return result


# Pull both
macro_result = run_for("Oil Macro", "backend-oil")
micro_result = run_for("Oil Micro", "backend-oil-micro")

# Filter to 2026 Jan-Jun
def filter_2026(trades):
    return [t for t in trades if str(t.date)[:4] == "2026"]

macro_trades = filter_2026(macro_result.trades)
micro_trades = filter_2026(micro_result.trades)

print()
print(f"Oil Macro 2026 trades: {len(macro_trades)}, P&L: ${sum(t.pnl_sized for t in macro_trades):,.2f}")
print(f"Oil Micro 2026 trades: {len(micro_trades)}, P&L: ${sum(t.pnl_sized for t in micro_trades):,.2f}")
print()

# Build lookup: (timestamp, direction) → trade
TOL_MIN = 15  # ± 15 minutes window

def to_ts(t):
    return pd.Timestamp(t.date)

# For each macro trade, find any micro trade within ± TOL_MIN minutes + same direction
overlap = []
macro_only = []

micro_used = set()  # micro trade indices already matched

for mt in macro_trades:
    mt_ts = to_ts(mt)
    mt_dir = mt.direction
    matched = None
    for i, ut in enumerate(micro_trades):
        if i in micro_used:
            continue
        ut_ts = to_ts(ut)
        ut_dir = ut.direction
        if ut_dir != mt_dir:
            continue
        delta_min = abs((ut_ts - mt_ts).total_seconds() / 60)
        if delta_min <= TOL_MIN:
            matched = (i, ut, delta_min)
            break
    if matched:
        i, ut, delta = matched
        micro_used.add(i)
        overlap.append((mt, ut, delta))
    else:
        macro_only.append(mt)

micro_only = [ut for i, ut in enumerate(micro_trades) if i not in micro_used]

# Tabulate
print(f"=== OVERLAP ANALYSIS (2026 Jan-Jun, ±{TOL_MIN}min, same direction) ===")
print()
print(f"  Overlap (both fire same setup): {len(overlap)}")
print(f"  Macro-only (Macro fires, Micro doesn't): {len(macro_only)}")
print(f"  Micro-only (Micro fires, Macro doesn't): {len(micro_only)}")
print()
print(f"  Redundancy from Macro's view: {len(overlap)}/{len(macro_trades)} = {len(overlap)/max(len(macro_trades),1)*100:.1f}%")
print(f"  Redundancy from Micro's view: {len(overlap)}/{len(micro_trades)} = {len(overlap)/max(len(micro_trades),1)*100:.1f}%")
print()

print("=== P&L BY BUCKET ===")
overlap_macro_pnl = sum(mt.pnl_sized for mt, _, _ in overlap)
overlap_micro_pnl = sum(ut.pnl_sized for _, ut, _ in overlap)
macro_only_pnl = sum(t.pnl_sized for t in macro_only)
micro_only_pnl = sum(t.pnl_sized for t in micro_only)

macro_only_wins = sum(1 for t in macro_only if t.pnl_sized > 0)
micro_only_wins = sum(1 for t in micro_only if t.pnl_sized > 0)

print(f"  Overlap MACRO leg P&L: ${overlap_macro_pnl:,.2f}")
print(f"  Overlap MICRO leg P&L: ${overlap_micro_pnl:,.2f}")
print()
print(f"  Macro-only ({len(macro_only)} trades, {macro_only_wins} wins):")
print(f"    P&L: ${macro_only_pnl:,.2f}")
print(f"    WR : {macro_only_wins/max(len(macro_only),1)*100:.1f}%")
print(f"    Avg: ${macro_only_pnl/max(len(macro_only),1):.2f}/trade")
print()
print(f"  Micro-only ({len(micro_only)} trades, {micro_only_wins} wins):")
print(f"    P&L: ${micro_only_pnl:,.2f}")
print(f"    WR : {micro_only_wins/max(len(micro_only),1)*100:.1f}%")
print(f"    Avg: ${micro_only_pnl/max(len(micro_only),1):.2f}/trade")
print()

print("=== INTERPRETATION ===")
print(f"If we DROP Oil Macro: lose ${macro_only_pnl:,.2f} from the macro-only signals.")
print(f"  (overlap signals would still be captured by Micro)")
print()
print(f"If we DROP Oil Micro: lose ${micro_only_pnl:,.2f} from the micro-only signals.")
print(f"  (overlap signals would still be captured by Macro)")
print()

# Show first 10 macro-only for sanity
print("=== Sample MACRO-ONLY signals (first 10) ===")
for t in macro_only[:10]:
    print(f"  {t.date} {t.direction} entry={t.entry:.4f} exit={t.exit_price:.4f} ({t.status}) pnl=${t.pnl_sized:>8.2f}")
