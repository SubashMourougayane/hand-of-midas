"""Walk Oil Macro BT trades for Jun 11-18 2026 in JM data.

Pulls run_backtest() with bias_mode='neutral' (matches live VPS state),
filters to Jun 11-18 window, dumps each trade card. Prints alongside the
M3 bars covering sweep + engulfing + entry + exit so we can manually
verify ground truth.

This is INSURANCE: pre-Phase-0 ground-truth check before refactor.
Plan: Section 'Insurance walk' in user dialog 2026-06-19.
"""
from __future__ import annotations
import os
import sys
import importlib

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

# Module-clear pattern from run_filter_27 — make sure backend-oil is the active backend
for k in list(sys.modules.keys()):
    if k.startswith(("scanner", "config", "backtest", "strategies",
                     "backend.execution", "backend.strategies", "backend.backtest",
                     "backend.data")):
        del sys.modules[k]

pkg_path = os.path.join(ROOT, "backend-oil")
if pkg_path in sys.path:
    sys.path.remove(pkg_path)
sys.path.insert(0, pkg_path)
importlib.invalidate_caches()

module = importlib.import_module("backtest.engine")

print("Running Oil Macro BT on JM data (bias_mode=neutral, full history)...")
result = module.run_backtest(bias_mode="neutral")
print(f"  total trades: {len(result.trades)}")

# Filter to Jun 11-18 2026 window
window_trades = [
    t for t in result.trades
    if "2026-06-11" <= str(t.date)[:10] <= "2026-06-18"
]
print(f"  Jun 11-18 trades: {len(window_trades)}")
print()

for t in window_trades:
    print(f"=== {t.date} {t.direction} {t.strategy} ===")
    print(f"  entry  : {t.entry:.4f}")
    print(f"  sl     : {t.sl:.4f}")
    print(f"  tp     : {t.tp:.4f}")
    print(f"  exit   : {t.exit_price:.4f} ({t.status})")
    print(f"  bars   : {t.bars_held} ({t.hold_human})")
    print(f"  risk   : {t.risk:.4f}")
    print(f"  pnl/u  : {t.pnl_unit:.4f}  R:{t.r_mult:.2f}")
    print()
