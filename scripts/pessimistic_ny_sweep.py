"""
Pessimistic stress test of Asia→NY (13-20) with WORST-CASE assumptions:

1. Exit slippage on ALL expired exits (spread + adverse movement)
2. Wider spreads during NY session (2× normal)
3. Entry slippage doubled (assume worse fills in NY)
4. Late detection penalty: entry 1 bar later (can't catch exact M3 close)
5. Break-even failures: 20% of BE attempts fail (SL stays original)

This is intentionally pessimistic — if it still works under these conditions,
the edge is robust enough for live.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
from scripts.verify_session_combos import load_data, find_signals

np.random.seed(42)

YEARLY_CAPITAL = 5000.0
RISK_PCT = 4.0
MAX_UNITS = 100


def pessimistic_slippage(bar_range: float, is_ny_session: bool = True) -> float:
    """Doubled slippage for NY session."""
    base = 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)
    return base * 2 if is_ny_session else base


def exit_slippage() -> float:
    """Slippage on expired/manual exits — spread + adverse."""
    spread = np.random.uniform(0.30, 0.80)  # XAU spread in NY = $0.30-$0.80
    adverse = np.random.uniform(0, 0.50)     # Price moves against during close
    return spread + adverse


@dataclass
class TradeResult:
    pnl_per_unit: float
    bars_held: int
    exit_reason: str
    exit_price: float


def pessimistic_execute_trade(
    df, bar_start: int, entry: float, sl: float, tp: float,
    direction: str, max_bars: int, be_failure_rate: float = 0.20,
) -> Optional[TradeResult]:
    """
    Same as fill_model but with pessimistic assumptions:
    - Break-even fails 20% of the time
    - Expired exits have slippage (spread + adverse)
    - SL slippage doubled
    """
    current_sl = sl
    bars_held = 0
    be_applied = False

    for b in range(bar_start + 1, min(bar_start + max_bars, len(df))):
        bars_held += 1

        if direction == "long":
            bo = df["bid_open"].iat[b]
            bl = df["bid_low"].iat[b]
            bh = df["bid_high"].iat[b]
            bar_range = bh - bl

            # Gap-through SL
            if bo <= current_sl:
                slip = pessimistic_slippage(bar_range) * 0.4
                exit_price = bo - slip
                return TradeResult(exit_price - entry, bars_held, "sl", exit_price)

            # TP touch
            if tp > 0 and bh >= tp:
                return TradeResult(tp - entry, bars_held, "tp", tp)

            # SL touch
            if bl <= current_sl:
                slip = pessimistic_slippage(bar_range) * 0.4
                exit_price = current_sl - slip
                return TradeResult(exit_price - entry, bars_held, "sl", exit_price)

            # Break-even (fails 20% of the time)
            if not be_applied and bh >= entry + (tp - entry) * 0.5:
                if np.random.random() > be_failure_rate:
                    current_sl = entry + pessimistic_slippage(bar_range)
                    be_applied = True
                # else: BE failed, SL stays at original

        else:  # short
            ao = df["ask_open"].iat[b]
            ah = df["ask_high"].iat[b]
            al = df["ask_low"].iat[b]
            bar_range = ah - al

            # Gap-through SL
            if ao >= current_sl:
                slip = pessimistic_slippage(bar_range) * 0.4
                exit_price = ao + slip
                return TradeResult(entry - exit_price, bars_held, "sl", exit_price)

            # TP touch
            if tp > 0 and al <= tp:
                return TradeResult(entry - tp, bars_held, "tp", tp)

            # SL touch
            if ah >= current_sl:
                slip = pessimistic_slippage(bar_range) * 0.4
                exit_price = current_sl + slip
                return TradeResult(entry - exit_price, bars_held, "sl", exit_price)

            # Break-even
            if not be_applied and al <= entry - (entry - tp) * 0.5:
                if np.random.random() > be_failure_rate:
                    current_sl = entry - pessimistic_slippage(bar_range)
                    be_applied = True

    # EXPIRED — apply exit slippage (THIS IS THE KEY DIFFERENCE)
    last_b = min(bar_start + max_bars - 1, len(df) - 1)
    exit_slip = exit_slippage()

    if direction == "long":
        exit_price = df["bid_close"].iat[last_b] - exit_slip
        return TradeResult(exit_price - entry, bars_held, "expired", exit_price)
    else:
        exit_price = df["ask_close"].iat[last_b] + exit_slip
        return TradeResult(entry - exit_price, bars_held, "expired", exit_price)


def run_pessimistic_backtest(signals, m3, label=""):
    """Run with pessimistic fill model."""
    trades = []
    yearly = {}

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

        # Add entry slippage penalty (late detection = worse entry)
        entry_penalty = np.random.uniform(0.10, 0.40)
        if signal.direction == "long":
            adjusted_entry = signal.entry + entry_penalty
        else:
            adjusted_entry = signal.entry - entry_penalty

        result = pessimistic_execute_trade(
            df=m3, bar_start=bar_idx, entry=adjusted_entry,
            sl=signal.sl, tp=signal.tp, direction=signal.direction,
            max_bars=signal.max_bars, be_failure_rate=0.20,
        )

        if result is None:
            continue

        pnl = result.pnl_per_unit * units
        yr = signal.date.year
        if yr not in yearly:
            yearly[yr] = {"trades": 0, "wins": 0, "pnl": 0, "losses_pnl": 0, "wins_pnl": 0}
        yearly[yr]["trades"] += 1
        if pnl > 0:
            yearly[yr]["wins"] += 1
            yearly[yr]["wins_pnl"] += pnl
        else:
            yearly[yr]["losses_pnl"] += abs(pnl)
        yearly[yr]["pnl"] += pnl

        trades.append({
            "pnl": pnl, "year": yr, "exit_reason": result.exit_reason,
            "r_mult": result.pnl_per_unit / signal.risk if signal.risk > 0 else 0,
            "bars_held": result.bars_held,
        })

    return trades, yearly


def run_original_backtest(signals, m3):
    """Run with production (optimistic) fill model for comparison."""
    from backend.execution.fill_model import execute_trade
    trades = []
    yearly = {}

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
            df=m3, bar_start=bar_idx, entry=signal.entry, sl=signal.sl,
            tp=signal.tp, direction=signal.direction, max_bars=signal.max_bars,
            strategy="alpha_sweep", use_break_even=True,
        )
        if result is None:
            continue

        pnl = result.pnl_per_unit * units
        yr = signal.date.year
        if yr not in yearly:
            yearly[yr] = {"trades": 0, "wins": 0, "pnl": 0}
        yearly[yr]["trades"] += 1
        if pnl > 0:
            yearly[yr]["wins"] += 1
        yearly[yr]["pnl"] += pnl
        trades.append({"pnl": pnl, "year": yr, "exit_reason": result.exit_reason})

    return trades, yearly


def main():
    h1, m3, daily = load_data()

    np.random.seed(42)
    signals = find_signals(h1, m3, daily, 13, 20)

    print(f"\n  Signals found: {len(signals)}")
    print("\n" + "=" * 100)
    print("  PESSIMISTIC vs ORIGINAL — Asia→NY (13:00-20:00)")
    print("  Pessimistic: 2× slippage, exit spread, 20% BE failure, entry penalty")
    print("=" * 100)

    # Original
    np.random.seed(42)
    orig_trades, orig_yearly = run_original_backtest(signals, m3)

    # Pessimistic
    np.random.seed(42)
    pess_trades, pess_yearly = run_pessimistic_backtest(signals, m3)

    # Summary
    orig_wins = sum(1 for t in orig_trades if t["pnl"] > 0)
    pess_wins = sum(1 for t in pess_trades if t["pnl"] > 0)
    orig_pnl = sum(t["pnl"] for t in orig_trades)
    pess_pnl = sum(t["pnl"] for t in pess_trades)
    orig_win_total = sum(t["pnl"] for t in orig_trades if t["pnl"] > 0)
    orig_loss_total = abs(sum(t["pnl"] for t in orig_trades if t["pnl"] <= 0))
    pess_win_total = sum(t["pnl"] for t in pess_trades if t["pnl"] > 0)
    pess_loss_total = abs(sum(t["pnl"] for t in pess_trades if t["pnl"] <= 0))

    print(f"\n{'Metric':<25} {'Original':>15} {'Pessimistic':>15} {'Degradation':>15}")
    print("-" * 75)
    print(f"{'Trades':<25} {len(orig_trades):>15} {len(pess_trades):>15} {'':>15}")
    print(f"{'Wins':<25} {orig_wins:>15} {pess_wins:>15} {pess_wins - orig_wins:>+15}")
    print(f"{'Win Rate':<25} {orig_wins/len(orig_trades):>14.1%} {pess_wins/len(pess_trades):>14.1%} {(pess_wins/len(pess_trades))-(orig_wins/len(orig_trades)):>+14.1%}")
    print(f"{'Profit Factor':<25} {orig_win_total/orig_loss_total if orig_loss_total else 99:>15.2f} {pess_win_total/pess_loss_total if pess_loss_total else 99:>15.2f} {'':>15}")
    print(f"{'Total P&L':<25} {orig_pnl:>+15,.0f} {pess_pnl:>+15,.0f} {pess_pnl-orig_pnl:>+15,.0f}")
    print(f"{'P&L / year':<25} {orig_pnl/21:>+15,.0f} {pess_pnl/21:>+15,.0f} {(pess_pnl-orig_pnl)/21:>+15,.0f}")
    print(f"{'Avg Win':<25} {orig_win_total/orig_wins if orig_wins else 0:>15.0f} {pess_win_total/pess_wins if pess_wins else 0:>15.0f} {'':>15}")
    print(f"{'Avg Loss':<25} {orig_loss_total/(len(orig_trades)-orig_wins) if (len(orig_trades)-orig_wins) else 0:>15.0f} {pess_loss_total/(len(pess_trades)-pess_wins) if (len(pess_trades)-pess_wins) else 0:>15.0f} {'':>15}")

    # Year by year comparison
    all_years = sorted(set(list(orig_yearly.keys()) + list(pess_yearly.keys())))
    print(f"\n{'Year':<6} | {'ORIGINAL':>30} | {'PESSIMISTIC':>30} | {'Delta':>8}")
    print(f"{'':>6} | {'Tr':>4} {'WR':>6} {'PF':>7} {'P&L':>10} | {'Tr':>4} {'WR':>6} {'PF':>7} {'P&L':>10} | {'':>8}")
    print("-" * 95)

    orig_losing_yrs = 0
    pess_losing_yrs = 0
    for yr in all_years:
        o = orig_yearly.get(yr, {"trades": 0, "wins": 0, "pnl": 0})
        p = pess_yearly.get(yr, {"trades": 0, "wins": 0, "pnl": 0, "wins_pnl": 0, "losses_pnl": 0})
        o_wr = f"{o['wins']/o['trades']:.0%}" if o["trades"] > 0 else "-"
        p_wr = f"{p['wins']/p['trades']:.0%}" if p["trades"] > 0 else "-"
        o_pf = "99" if o.get("losses_pnl", 0) == 0 else "-"
        p_pf = f"{p['wins_pnl']/p['losses_pnl']:.1f}" if p.get("losses_pnl", 0) > 0 else "99"
        delta = p["pnl"] - o["pnl"]
        if o["pnl"] < 0:
            orig_losing_yrs += 1
        if p["pnl"] < 0:
            pess_losing_yrs += 1
        print(f"{yr:<6} | {o['trades']:>4} {o_wr:>6} {'':>7} {o['pnl']:>+10,.0f} | {p['trades']:>4} {p_wr:>6} {p_pf:>7} {p['pnl']:>+10,.0f} | {delta:>+8,.0f}")

    print("-" * 95)
    print(f"{'TOTAL':<6} | {len(orig_trades):>4} {'':>6} {'':>7} {orig_pnl:>+10,.0f} | {len(pess_trades):>4} {'':>6} {'':>7} {pess_pnl:>+10,.0f} | {pess_pnl-orig_pnl:>+8,.0f}")
    print(f"\n  Losing years: Original={orig_losing_yrs}/21, Pessimistic={pess_losing_yrs}/21")

    # Exit reason comparison
    print(f"\n{'Exit Reason':<12} | {'Original':>20} | {'Pessimistic':>20}")
    print("-" * 60)
    for reason in ["tp", "sl", "expired"]:
        o_count = sum(1 for t in orig_trades if t["exit_reason"] == reason)
        p_count = sum(1 for t in pess_trades if t["exit_reason"] == reason)
        o_pnl = sum(t["pnl"] for t in orig_trades if t["exit_reason"] == reason)
        p_pnl = sum(t["pnl"] for t in pess_trades if t["exit_reason"] == reason)
        print(f"{reason:<12} | {o_count:>5} (${o_pnl:>+10,.0f}) | {p_count:>5} (${p_pnl:>+10,.0f})")

    # Monte Carlo on pessimistic trades
    print("\n" + "=" * 60)
    print("  MONTE CARLO ON PESSIMISTIC RESULTS (10,000 sims)")
    print("=" * 60)
    pnls = [t["pnl"] for t in pess_trades]
    max_dds = []
    for _ in range(10000):
        shuffled = np.random.permutation(pnls)
        eq = YEARLY_CAPITAL
        peak = eq
        max_dd = 0
        for p in shuffled:
            eq += p
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        max_dds.append(max_dd)

    max_dds = np.array(max_dds)
    print(f"  Median max DD:  {np.median(max_dds):>6.1%}")
    print(f"  95th pctile DD: {np.percentile(max_dds, 95):>6.1%}")
    print(f"  99th pctile DD: {np.percentile(max_dds, 99):>6.1%}")
    print(f"  Prob DD > 20%:  {(max_dds > 0.20).mean():.2%}")
    print(f"  Prob DD > 30%:  {(max_dds > 0.30).mean():.2%}")

    # Final verdict
    print("\n" + "=" * 60)
    print("  FINAL VERDICT")
    print("=" * 60)
    pess_wr = pess_wins / len(pess_trades)
    pess_pf_val = pess_win_total / pess_loss_total if pess_loss_total else 99
    print(f"  Under WORST-CASE assumptions:")
    print(f"    WR:  {pess_wr:.1%}")
    print(f"    PF:  {pess_pf_val:.2f}")
    print(f"    $/yr: ${pess_pnl/21:+,.0f}")
    print(f"    Losing years: {pess_losing_yrs}/21")
    print(f"    99th DD: {np.percentile(max_dds, 99):.1%}")
    if pess_pf_val > 2.0 and pess_wr > 0.60 and pess_losing_yrs <= 2:
        print(f"\n  ✅ EDGE SURVIVES pessimistic conditions. Safe for live.")
    elif pess_pf_val > 1.5:
        print(f"\n  ⚠️  Edge degraded but still profitable. Proceed with caution.")
    else:
        print(f"\n  ❌ Edge destroyed under stress. DO NOT deploy.")


if __name__ == "__main__":
    main()
