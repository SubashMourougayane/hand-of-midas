"""
Stress test Asia→NY (13-20) results. Looking for:
1. Walk-forward: does it degrade in recent years vs early years?
2. Year-by-year breakdown: is one year carrying all the P&L?
3. Win streak analysis: are wins clustered (lucky run) or distributed?
4. Monte Carlo: shuffle trade order 10,000 times, check drawdown distribution
5. Average R:R — is PF high because of one massive winner?
6. Trade distribution by year — consistent or lumpy?
7. Sensitivity: what happens if we change thresholds slightly?
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import numpy as np
import pandas as pd
from scripts.verify_session_combos import load_data, find_signals, COMBOS
from backend.execution.fill_model import execute_trade
from backend.config import slippage

np.random.seed(42)

YEARLY_CAPITAL = 5000.0
RISK_PCT = 4.0
MAX_UNITS = 100


def get_trade_results(signals, m3):
    """Run all trades, return list of (pnl, r_mult, year, bars_held)."""
    trades = []
    for signal in signals:
        try:
            bar_idx = m3.index.get_loc(signal.date)
        except KeyError:
            continue

        equity = YEARLY_CAPITAL
        risk_dollar = equity * (RISK_PCT / 100)
        units = min(risk_dollar / signal.risk, MAX_UNITS)
        if units < 1:
            continue

        result = execute_trade(
            df=m3, bar_start=bar_idx, entry=signal.entry,
            sl=signal.sl, tp=signal.tp, direction=signal.direction,
            max_bars=signal.max_bars, strategy="alpha_sweep", use_break_even=True,
        )
        if result is None:
            continue

        pnl = result.pnl_per_unit * units
        r_mult = result.pnl_per_unit / signal.risk if signal.risk > 0 else 0
        trades.append({
            "pnl": pnl,
            "r_mult": r_mult,
            "year": signal.date.year,
            "bars_held": result.bars_held,
            "exit_reason": result.exit_reason,
            "direction": signal.direction,
        })
    return trades


def year_by_year(trades):
    """Print year-by-year breakdown."""
    print("\n" + "=" * 70)
    print("YEAR-BY-YEAR BREAKDOWN")
    print("=" * 70)
    print(f"{'Year':<6} {'Trades':>7} {'Wins':>6} {'WR':>7} {'PF':>7} {'P&L':>10} {'Max Streak':>11}")
    print("-" * 70)

    years = sorted(set(t["year"] for t in trades))
    for yr in years:
        yr_trades = [t for t in trades if t["year"] == yr]
        wins = sum(1 for t in yr_trades if t["pnl"] > 0)
        losses = len(yr_trades) - wins
        wr = wins / len(yr_trades) if yr_trades else 0
        total_win = sum(t["pnl"] for t in yr_trades if t["pnl"] > 0)
        total_loss = abs(sum(t["pnl"] for t in yr_trades if t["pnl"] <= 0))
        pf = total_win / total_loss if total_loss > 0 else 99
        pnl = sum(t["pnl"] for t in yr_trades)

        # Max consecutive wins
        streak = 0
        max_streak = 0
        for t in yr_trades:
            if t["pnl"] > 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

        print(f"{yr:<6} {len(yr_trades):>7} {wins:>6} {wr:>6.1%} {pf:>7.2f} {pnl:>+10,.0f} {max_streak:>11}")

    print("-" * 70)
    total = sum(t["pnl"] for t in trades)
    print(f"{'TOTAL':<6} {len(trades):>7} {sum(1 for t in trades if t['pnl']>0):>6} "
          f"{sum(1 for t in trades if t['pnl']>0)/len(trades):>6.1%} {'':>7} {total:>+10,.0f}")


def exit_reason_breakdown(trades):
    """How do trades exit?"""
    print("\n" + "=" * 50)
    print("EXIT REASON BREAKDOWN")
    print("=" * 50)
    reasons = {}
    for t in trades:
        r = t["exit_reason"]
        if r not in reasons:
            reasons[r] = {"count": 0, "pnl": 0}
        reasons[r]["count"] += 1
        reasons[r]["pnl"] += t["pnl"]

    for reason, data in sorted(reasons.items(), key=lambda x: -x[1]["count"]):
        pct = data["count"] / len(trades)
        print(f"  {reason:<12} {data['count']:>5} ({pct:>5.1%})  P&L: ${data['pnl']:>+10,.0f}")


def r_multiple_analysis(trades):
    """Check R:R distribution — is PF driven by outliers?"""
    print("\n" + "=" * 50)
    print("R-MULTIPLE DISTRIBUTION")
    print("=" * 50)
    r_mults = [t["r_mult"] for t in trades]
    wins = [r for r in r_mults if r > 0]
    losses = [r for r in r_mults if r <= 0]

    print(f"  Avg win R:   {np.mean(wins):>+.2f}R")
    print(f"  Avg loss R:  {np.mean(losses):>.2f}R")
    print(f"  Median win:  {np.median(wins):>+.2f}R")
    print(f"  Max win:     {max(r_mults):>+.2f}R")
    print(f"  Max loss:    {min(r_mults):>.2f}R")
    print(f"  Wins > 2R:   {sum(1 for r in wins if r > 2)} ({sum(1 for r in wins if r > 2)/len(trades):.1%})")
    print(f"  Losses > -1R:{sum(1 for r in losses if r < -1)} ({sum(1 for r in losses if r < -1)/len(trades):.1%})")

    # Check if top 10% of trades carry most P&L
    sorted_pnl = sorted([t["pnl"] for t in trades], reverse=True)
    top10_pnl = sum(sorted_pnl[:max(1, len(sorted_pnl)//10)])
    total_pnl = sum(sorted_pnl)
    print(f"\n  Top 10% trades carry: {top10_pnl/total_pnl:.1%} of total P&L")
    print(f"  Bottom 50% trades:   ${sum(sorted_pnl[len(sorted_pnl)//2:]):>+,.0f}")


def monte_carlo(trades, n_simulations=10000):
    """Shuffle trade order, measure DD distribution."""
    print("\n" + "=" * 50)
    print(f"MONTE CARLO ({n_simulations:,} simulations)")
    print("=" * 50)

    pnls = [t["pnl"] for t in trades]
    max_dds = []
    final_equities = []

    for _ in range(n_simulations):
        shuffled = np.random.permutation(pnls)
        equity = YEARLY_CAPITAL
        peak = equity
        max_dd = 0
        for pnl in shuffled:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        max_dds.append(max_dd)
        final_equities.append(equity)

    max_dds = np.array(max_dds)
    final_equities = np.array(final_equities)

    print(f"  Max DD percentiles:")
    print(f"    5th:   {np.percentile(max_dds, 5):>6.1%}")
    print(f"    25th:  {np.percentile(max_dds, 25):>6.1%}")
    print(f"    50th:  {np.percentile(max_dds, 50):>6.1%} (median)")
    print(f"    75th:  {np.percentile(max_dds, 75):>6.1%}")
    print(f"    95th:  {np.percentile(max_dds, 95):>6.1%}")
    print(f"    99th:  {np.percentile(max_dds, 99):>6.1%} (worst case)")
    print(f"\n  Probability of DD > 20%: {(max_dds > 0.20).mean():.1%}")
    print(f"  Probability of DD > 30%: {(max_dds > 0.30).mean():.1%}")
    print(f"  Probability of DD > 50%: {(max_dds > 0.50).mean():.1%}")
    print(f"\n  Final equity (starting $5000):")
    print(f"    Worst:  ${np.min(final_equities):>+,.0f}")
    print(f"    Median: ${np.median(final_equities):>+,.0f}")
    print(f"    Best:   ${np.max(final_equities):>+,.0f}")
    print(f"  Probability of net loss: {(final_equities < YEARLY_CAPITAL).mean():.2%}")


def walk_forward(trades):
    """Split into halves — does edge decay?"""
    print("\n" + "=" * 50)
    print("WALK-FORWARD: FIRST HALF vs SECOND HALF")
    print("=" * 50)
    mid = len(trades) // 2
    first = trades[:mid]
    second = trades[mid:]

    for label, subset in [("First half", first), ("Second half", second)]:
        wins = sum(1 for t in subset if t["pnl"] > 0)
        losses = len(subset) - wins
        wr = wins / len(subset) if subset else 0
        total_win = sum(t["pnl"] for t in subset if t["pnl"] > 0)
        total_loss = abs(sum(t["pnl"] for t in subset if t["pnl"] <= 0))
        pf = total_win / total_loss if total_loss > 0 else 99
        years_span = f"{subset[0]['year']}-{subset[-1]['year']}" if subset else "N/A"
        print(f"  {label} ({years_span}): {len(subset)} trades, WR={wr:.1%}, PF={pf:.2f}")


def sensitivity_test(h1, m3, daily):
    """Vary sweep threshold and min SL — does edge survive?"""
    print("\n" + "=" * 70)
    print("SENSITIVITY: VARYING PARAMETERS")
    print("=" * 70)
    print(f"{'Sweep Thresh':>13} {'Min SL':>7} {'Trades':>7} {'WR':>7} {'PF':>7}")
    print("-" * 50)

    import scripts.verify_session_combos as vc
    original_sweep = vc.SWEEP_THRESHOLD
    original_sl = vc.MIN_SL

    for sweep in [1.0, 1.5, 2.0, 2.5, 3.0]:
        for min_sl in [3.0, 5.0, 7.0]:
            vc.SWEEP_THRESHOLD = sweep
            vc.MIN_SL = min_sl
            np.random.seed(42)
            signals = find_signals(h1, m3, daily, 13, 20)
            trades = get_trade_results(signals, m3)
            if not trades:
                continue
            wins = sum(1 for t in trades if t["pnl"] > 0)
            wr = wins / len(trades)
            total_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
            total_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
            pf = total_win / total_loss if total_loss > 0 else 99
            print(f"  ${sweep:>5.1f}       ${min_sl:>4.1f}   {len(trades):>7} {wr:>6.1%} {pf:>7.2f}")

    vc.SWEEP_THRESHOLD = original_sweep
    vc.MIN_SL = original_sl


def main():
    h1, m3, daily = load_data()

    print("\n" + "=" * 70)
    print("  STRESS TEST: Asia → NY Session (13:00-20:00 UTC)")
    print("=" * 70)

    np.random.seed(42)
    signals = find_signals(h1, m3, daily, 13, 20)
    trades = get_trade_results(signals, m3)

    print(f"\n  Total signals: {len(signals)}, Executed trades: {len(trades)}")
    wins = sum(1 for t in trades if t["pnl"] > 0)
    print(f"  Wins: {wins}, Losses: {len(trades)-wins}, WR: {wins/len(trades):.1%}")

    year_by_year(trades)
    exit_reason_breakdown(trades)
    r_multiple_analysis(trades)
    walk_forward(trades)
    monte_carlo(trades)
    sensitivity_test(h1, m3, daily)

    print("\n" + "=" * 70)
    print("  VERDICT")
    print("=" * 70)
    print("  If year-by-year is consistent, walk-forward doesn't decay,")
    print("  R-multiples aren't outlier-driven, and sensitivity survives")
    print("  parameter changes — then the edge is REAL.")
    print("  If any of these fail — it's overfitting to specific conditions.")
    print("=" * 70)


if __name__ == "__main__":
    main()
