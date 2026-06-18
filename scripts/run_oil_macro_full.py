"""Full-history Oil Macro BT on JM data (bias_mode=neutral).

Data starts 2019-05-22, so ~7 years through 2026-06-18.
"""
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

pkg_path = os.path.join(ROOT, "backend-oil")
if pkg_path in sys.path:
    sys.path.remove(pkg_path)
sys.path.insert(0, pkg_path)
importlib.invalidate_caches()

import time
module = importlib.import_module("backtest.engine")

print("Running Oil Macro full-history BT (bias_mode=neutral, JM data ~2019-05-22 → 2026-06-18)...")
t0 = time.time()
result = module.run_backtest(bias_mode="neutral")
elapsed = time.time() - t0
print(f"  elapsed: {elapsed:.1f}s")

print()
print("=" * 60)
print("Oil Macro — Full History (JM, bias_mode=neutral)")
print("=" * 60)
print(f"  total trades        : {result.total_trades}")
print(f"  wins                : {result.wins}")
print(f"  losses              : {result.losses}")
print(f"  win rate            : {result.win_rate*100:.2f}%")
print(f"  profit factor       : {result.profit_factor:.2f}")
print(f"  total P&L           : ${result.total_pnl:,.2f}")
print(f"  max drawdown        : {result.max_drawdown_pct:.2f}%")
print(f"  Filter #27 stats:")
print(f"    total signals     : {getattr(result, 'total_signals', 'n/a')}")
print(f"    filled signals    : {getattr(result, 'filled_signals', 'n/a')}")
print(f"    missed signals    : {getattr(result, 'missed_signals', 'n/a')}")
print(f"    would_have_won    : {getattr(result, 'would_have_won_count', 'n/a')}")

if result.trades:
    first = result.trades[0]
    last = result.trades[-1]
    print(f"  first trade         : {first.date}")
    print(f"  last trade          : {last.date}")

# Yearly breakdown
years = {}
for t in result.trades:
    y = t.year
    if y not in years:
        years[y] = {"n": 0, "wins": 0, "pnl": 0.0}
    years[y]["n"] += 1
    if t.pnl_sized > 0:
        years[y]["wins"] += 1
    years[y]["pnl"] += t.pnl_sized

print()
print(f"  {'Year':<6} {'Trades':<8} {'Wins':<6} {'WR%':<8} {'P&L':>12}")
for y in sorted(years.keys()):
    s = years[y]
    wr = s["wins"]/s["n"]*100 if s["n"] > 0 else 0
    print(f"  {y:<6} {s['n']:<8} {s['wins']:<6} {wr:<8.1f} ${s['pnl']:>10,.2f}")
