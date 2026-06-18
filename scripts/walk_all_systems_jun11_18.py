"""Walk all 3 remaining systems' BT trades for Jun 11-18 2026 in JM data.

Pulls run_backtest() with bias_mode='neutral' (matches live VPS state),
filters to Jun 11-18 window, dumps each trade card.

Pattern follows scripts/walk_oil_macro_jun17_18.py.
"""
from __future__ import annotations
import os
import sys
import importlib

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)


def run_for(label: str, pkg_dir: str):
    print(f"\n{'='*60}")
    print(f"=== {label} ({pkg_dir}) ===")
    print(f"{'='*60}")

    # Module-clear pattern from run_filter_27 — make sure correct backend is active
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

    if pkg_dir == "backend":
        module = importlib.import_module("backend.backtest.engine")
    else:
        module = importlib.import_module("backtest.engine")

    print(f"  Running BT (bias_mode=neutral, full history)...")
    result = module.run_backtest(bias_mode="neutral")
    print(f"  total trades: {len(result.trades)}")

    # Filter to Jun 11-18 2026 window
    window_trades = [
        t for t in result.trades
        if "2026-06-11" <= str(t.date)[:10] <= "2026-06-18"
    ]
    print(f"  Jun 11-18 trades: {len(window_trades)}\n")

    for t in window_trades:
        print(f"  {t.date} {t.direction} {t.strategy}")
        print(f"    entry={t.entry:.4f} sl={t.sl:.4f} tp={t.tp:.4f}")
        print(f"    exit={t.exit_price:.4f} ({t.status}) bars={t.bars_held} ({t.hold_human})")
        print(f"    risk={t.risk:.4f} pnl/u={t.pnl_unit:.4f} R={t.r_mult:.2f}")
        print()


# Gold Macro = backend
# Gold Micro = backend-micro
# Oil Micro = backend-oil-micro
run_for("Gold Macro", "backend")
run_for("Gold Micro", "backend-micro")
run_for("Oil Micro", "backend-oil-micro")
