"""Pull Gold Micro Jun 11-18 trades (JM, single-strategy, neutral)."""
from __future__ import annotations
import os
import sys
import importlib

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

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

module = importlib.import_module("backtest.engine")
print("Running Gold Micro BT (single-strategy, bias_mode=neutral)...")
result = module.run_backtest(strategies=["micro_alpha_sweep"], bias_mode="neutral")
print(f"  total trades: {len(result.trades)}")

window_trades = [t for t in result.trades if "2026-06-11" <= str(t.date)[:10] <= "2026-06-18"]
print(f"  Jun 11-18 trades: {len(window_trades)}\n")

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
