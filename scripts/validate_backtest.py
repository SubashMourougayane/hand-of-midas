#!/usr/bin/env python3
"""Validate backtest results match the source of truth (~$155k total PnL)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.backtest.engine import run_backtest

print("Running full portfolio backtest (V4+V7+V8, 2006-2026, $5k/yr)...")
print("This may take a few minutes (V4 processes M3 data)...")

result = run_backtest()

print(f"\n{'='*60}")
print(f"BACKTEST RESULTS")
print(f"{'='*60}")
print(f"Total Trades: {result.total_trades}")
print(f"Wins: {result.wins} | Losses: {result.losses}")
print(f"Win Rate: {result.win_rate:.1%}")
print(f"Profit Factor: {result.profit_factor:.2f}")
print(f"Total P&L: ${result.total_pnl:,.0f}")
print(f"Max Drawdown: {result.max_drawdown_pct:.1f}%")
print(f"{'='*60}")

# Strategy breakdown
from collections import defaultdict
strat_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
for t in result.trades:
    strat_stats[t.strategy]["trades"] += 1
    strat_stats[t.strategy]["pnl"] += t.pnl_sized
    if t.pnl_sized > 0:
        strat_stats[t.strategy]["wins"] += 1

print("\nPer-Strategy:")
for strat, s in strat_stats.items():
    wr = s["wins"] / s["trades"] if s["trades"] > 0 else 0
    print(f"  {strat}: {s['trades']} trades, {wr:.1%} WR, ${s['pnl']:+,.0f}")

# Validation
TARGET = 155022
tolerance = 0.15  # 15% tolerance (random slippage causes variance)
if abs(result.total_pnl - TARGET) / TARGET < tolerance:
    print(f"\n✓ PASS: ${result.total_pnl:,.0f} is within {tolerance:.0%} of target ${TARGET:,.0f}")
else:
    print(f"\n✗ FAIL: ${result.total_pnl:,.0f} deviates >{tolerance:.0%} from target ${TARGET:,.0f}")
    print(f"  Difference: ${result.total_pnl - TARGET:+,.0f} ({(result.total_pnl-TARGET)/TARGET*100:+.1f}%)")
