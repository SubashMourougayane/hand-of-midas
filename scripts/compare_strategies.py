"""
Head-to-head comparison: Original Alpha-Sweep vs Micro Alpha-Sweep.
Same data, same fill model, same slippage, same seed. Only difference: consolidation window.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from backend.backtest.engine import _get_cached_data, BacktestTrade, BacktestResult
from backend.strategies import alpha_sweep
from backend.strategies import micro_alpha_sweep
from backend.execution.fill_model import execute_trade
from backend.config import ALPHA_SWEEP, STRATEGY_RISK, MAX_UNITS, YEARLY_CAPITAL

SEED = 42
CAPITAL = 5000.0
RISK_PCT = STRATEGY_RISK["alpha_sweep"]  # 4%


def run_strategy(name, signal_generator, start_date="2020-01-01", end_date="2026-12-31"):
    """Run a strategy through the backtest engine and return results."""
    np.random.seed(SEED)

    data = _get_cached_data()
    gold_h1 = data["gold_h1"]
    gold_m3 = data["gold_m3"]
    gold_d = data["gold_d"]

    # Build daily bias (Variant C)
    daily_bias = {}
    for i in range(1, len(gold_d)):
        d = gold_d.index[i].date()
        prev_range = gold_d["mid_high"].iat[i - 1] - gold_d["mid_low"].iat[i - 1]
        if prev_range <= 0:
            daily_bias[d] = "neutral"
            continue
        body_pct = abs(gold_d["mid_close"].iat[i - 1] - gold_d["mid_open"].iat[i - 1]) / prev_range
        if body_pct < 0.4:
            daily_bias[d] = "neutral"
        elif gold_d["mid_close"].iat[i - 1] > gold_d["mid_open"].iat[i - 1]:
            daily_bias[d] = "bullish"
        else:
            daily_bias[d] = "bearish"

    # Generate signals
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"Generating signals...")
    signals = signal_generator(gold_h1, gold_m3, daily_bias)
    print(f"Total signals generated: {len(signals)}")

    # Filter by date range
    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC")
    signals = [s for s in signals if start_ts <= s.date <= end_ts]
    signals.sort(key=lambda s: s.date)
    print(f"Signals in range ({start_date} to {end_date}): {len(signals)}")

    # Execute through fill model
    trades = []
    equity = CAPITAL
    peak = CAPITAL
    consecutive_losses = 0

    # Track by year for per-year stats
    year_stats = {}

    for sig in signals:
        year = sig.date.year

        # Reset equity each year (flat comparison)
        if year not in year_stats:
            year_stats[year] = {"trades": 0, "wins": 0, "pnl": 0, "losses_list": []}
            equity = CAPITAL
            peak = CAPITAL
            consecutive_losses = 0

        # DD protection
        risk_mult = 1.0
        if consecutive_losses >= 3:
            risk_mult = 0.5

        # Position sizing
        risk_dollar = equity * (RISK_PCT / 100) * risk_mult
        units = min(risk_dollar / sig.risk, MAX_UNITS)
        if units < 1:
            continue

        # Find bar in M3 data
        bar_idx = gold_m3.index.get_indexer([sig.date], method="nearest")[0]
        if bar_idx < 0 or bar_idx >= len(gold_m3) - sig.max_bars:
            continue

        # Execute with fill model
        result = execute_trade(
            df=gold_m3,
            bar_start=bar_idx,
            entry=sig.entry,
            sl=sig.sl,
            tp=sig.tp,
            direction=sig.direction,
            max_bars=sig.max_bars,
            strategy=name,
            use_break_even=True,
        )

        if result is None:
            continue

        pnl_sized = result.pnl_per_unit * units
        equity += pnl_sized
        peak = max(peak, equity)

        is_win = result.pnl_per_unit > 0
        if is_win:
            consecutive_losses = 0
        else:
            consecutive_losses += 1

        year_stats[year]["trades"] += 1
        year_stats[year]["pnl"] += pnl_sized
        if is_win:
            year_stats[year]["wins"] += 1
        year_stats[year]["losses_list"].append(pnl_sized)

        trades.append({
            "date": sig.date,
            "year": year,
            "direction": sig.direction,
            "entry": sig.entry,
            "sl": sig.sl,
            "tp": sig.tp,
            "exit": result.exit_price,
            "exit_reason": result.exit_reason,
            "pnl_unit": result.pnl_per_unit,
            "pnl_sized": pnl_sized,
            "bars_held": result.bars_held,
            "risk": sig.risk,
            "r_mult": result.pnl_per_unit / sig.risk if sig.risk > 0 else 0,
        })

    # Compute aggregate stats
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["pnl_unit"] > 0)
    losses = total_trades - wins
    gross_wins = sum(t["pnl_sized"] for t in trades if t["pnl_sized"] > 0)
    gross_losses = abs(sum(t["pnl_sized"] for t in trades if t["pnl_sized"] < 0))
    total_pnl = sum(t["pnl_sized"] for t in trades)
    wr = (wins / total_trades * 100) if total_trades > 0 else 0
    pf = (gross_wins / gross_losses) if gross_losses > 0 else 999

    avg_win = gross_wins / wins if wins > 0 else 0
    avg_loss = gross_losses / losses if losses > 0 else 0
    rr = avg_win / avg_loss if avg_loss > 0 else 999

    # Exit reason breakdown
    exit_reasons = {}
    for t in trades:
        r = t["exit_reason"]
        if r not in exit_reasons:
            exit_reasons[r] = {"count": 0, "pnl": 0}
        exit_reasons[r]["count"] += 1
        exit_reasons[r]["pnl"] += t["pnl_sized"]

    # Print results
    print(f"\n--- RESULTS ---")
    print(f"Total trades:    {total_trades}")
    print(f"Wins:            {wins} ({wr:.1f}%)")
    print(f"Losses:          {losses}")
    print(f"Profit Factor:   {pf:.2f}")
    print(f"Total P&L:       ${total_pnl:,.0f}")
    print(f"Avg Winner:      ${avg_win:.2f}")
    print(f"Avg Loser:       ${avg_loss:.2f}")
    print(f"R:R Ratio:       {rr:.2f}")
    print(f"Trades/Year:     {total_trades / max(len(year_stats), 1):.0f}")

    print(f"\n--- EXIT REASONS ---")
    for reason, data in sorted(exit_reasons.items()):
        print(f"  {reason:10s}: {data['count']:4d} trades, P&L ${data['pnl']:,.0f}")

    print(f"\n--- YEAR BY YEAR ---")
    print(f"{'Year':>6} {'Trades':>7} {'WR':>6} {'PF':>7} {'P&L':>10}")
    for year in sorted(year_stats.keys()):
        ys = year_stats[year]
        y_wr = (ys["wins"] / ys["trades"] * 100) if ys["trades"] > 0 else 0
        y_wins_pnl = sum(p for p in ys["losses_list"] if p > 0)
        y_loss_pnl = abs(sum(p for p in ys["losses_list"] if p < 0))
        y_pf = y_wins_pnl / y_loss_pnl if y_loss_pnl > 0 else 999
        print(f"{year:>6} {ys['trades']:>7} {y_wr:>5.1f}% {y_pf:>6.2f} ${ys['pnl']:>9,.0f}")

    # Max consecutive losses
    max_consec = 0
    current_consec = 0
    for t in trades:
        if t["pnl_unit"] <= 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0
    print(f"\nMax consecutive losses: {max_consec}")

    return {"name": name, "trades": total_trades, "wr": wr, "pf": pf, "pnl": total_pnl, "rr": rr}


if __name__ == "__main__":
    # Run both on recent data (2020-2026) for head-to-head
    period = ("2020-01-01", "2026-12-31")

    r1 = run_strategy("Original Alpha-Sweep", alpha_sweep.generate_signals, *period)
    r2 = run_strategy("Micro Alpha-Sweep", micro_alpha_sweep.generate_signals, *period)

    print(f"\n\n{'='*60}")
    print(f"  HEAD-TO-HEAD COMPARISON ({period[0]} to {period[1]})")
    print(f"{'='*60}")
    print(f"{'Metric':<25} {'Original':>15} {'Micro':>15} {'Winner':>10}")
    print(f"{'-'*65}")
    print(f"{'Trades':<25} {r1['trades']:>15} {r2['trades']:>15} {'Micro' if r2['trades'] > r1['trades'] else 'Orig':>10}")
    print(f"{'Win Rate':<25} {r1['wr']:>14.1f}% {r2['wr']:>14.1f}% {'Micro' if r2['wr'] > r1['wr'] else 'Orig':>10}")
    print(f"{'Profit Factor':<25} {r1['pf']:>15.2f} {r2['pf']:>15.2f} {'Micro' if r2['pf'] > r1['pf'] else 'Orig':>10}")
    print(f"{'Total P&L':<25} ${r1['pnl']:>13,.0f} ${r2['pnl']:>13,.0f} {'Micro' if r2['pnl'] > r1['pnl'] else 'Orig':>10}")
    print(f"{'R:R Ratio':<25} {r1['rr']:>15.2f} {r2['rr']:>15.2f} {'Micro' if r2['rr'] > r1['rr'] else 'Orig':>10}")
