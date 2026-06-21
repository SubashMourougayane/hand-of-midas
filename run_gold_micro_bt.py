"""Run Gold Micro backtest with production engine. Print yearly + summary stats."""
import sys
import os
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "backend-micro"))

from backtest.engine import run_backtest as run_micro_bt


def print_results(name: str, result):
    print()
    print("=" * 80)
    print(f"  {name}")
    print("=" * 80)
    print(f"  Total trades       : {result.total_trades:,}")
    print(f"  Wins / Losses      : {result.wins:,} / {result.losses:,}")
    print(f"  Win rate           : {result.win_rate * 100:.2f} %")
    print(f"  Profit factor      : {result.profit_factor:.3f}")
    print(f"  Total P&L          : ${result.total_pnl:,.2f}")
    print(f"  Max DD             : {result.max_drawdown_pct:.2f} %")

    # Per-year breakdown — BacktestTrade has .year and .pnl_sized fields
    by_year = {}
    for t in result.trades:
        y = t.year
        s = by_year.setdefault(y, {"trades": 0, "wins": 0, "pnl": 0.0})
        s["trades"] += 1
        if t.pnl_sized > 0:
            s["wins"] += 1
        s["pnl"] += t.pnl_sized

    if by_year:
        print()
        print(f"  {'Year':<6} {'Trades':<8} {'Wins':<6} {'WR%':<8} {'P&L':>14}")
        print("  " + "─" * 50)
        for y in sorted(by_year):
            s = by_year[y]
            wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0.0
            print(f"  {y:<6} {s['trades']:<8} {s['wins']:<6} {wr:<8.1f} ${s['pnl']:>11,.2f}")
        years = len(by_year)
        total_pnl = sum(s["pnl"] for s in by_year.values())
        print("  " + "─" * 50)
        print(f"  TOTAL  {result.total_trades:<8}        {'':<8} ${total_pnl:>11,.2f}  "
              f"({years}y → ${total_pnl/years:,.2f}/yr)")


if __name__ == "__main__":
    print("Loading data + running Gold Micro alpha-sweep BT (full history 2006-2026)...")
    result = run_micro_bt(strategies=["micro_alpha_sweep"])
    print_results("Gold Micro Alpha-Sweep — production BT engine", result)
