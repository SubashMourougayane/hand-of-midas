"""Run the REAL Gold Micro backtest engine twice — baseline and Filter A —
and report side-by-side numbers. This is the same engine that powers the
/backtest dashboard, so the baseline numbers should match what's shown
there (1851 trades / 68.3% WR / 2.43 PF / $241K).

Usage:
    python scripts/backtest_filter_a_pre_post.py
    python scripts/backtest_filter_a_pre_post.py --start 2006-01-01 --end 2026-05-21
"""
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend-micro"))

from backtest.engine import run_backtest


def fmt_result(r, label: str) -> str:
    n = len(r.trades)
    if n == 0:
        return f"{label}: 0 trades"
    wins = [t for t in r.trades if t.pnl_sized > 0]
    losses = [t for t in r.trades if t.pnl_sized <= 0]
    wr = len(wins) / n * 100
    total_pnl = sum(t.pnl_sized for t in r.trades)
    sum_win = sum(t.pnl_sized for t in wins)
    sum_loss = -sum(t.pnl_sized for t in losses)
    pf = sum_win / sum_loss if sum_loss > 0 else float("inf")
    avg_win = sum_win / len(wins) if wins else 0
    avg_loss = sum_loss / len(losses) if losses else 0
    by_strat = {}
    for t in r.trades:
        by_strat.setdefault(t.strategy, []).append(t)

    lines = [
        f"{label}",
        f"  Trades:       {n}",
        f"  Win Rate:     {wr:.1f}%   ({len(wins)}W / {len(losses)}L)",
        f"  Profit Factor:{pf:.2f}",
        f"  Total P&L:    ${total_pnl:,.0f}",
        f"  Avg Win:      ${avg_win:,.0f}",
        f"  Avg Loss:     ${avg_loss:,.0f}",
    ]
    if hasattr(r, "max_dd_pct") and r.max_dd_pct is not None:
        lines.append(f"  Max DD:       {r.max_dd_pct:.1f}%")
    lines.append(f"  By strategy:")
    for s, trs in sorted(by_strat.items()):
        s_wr = sum(1 for t in trs if t.pnl_sized > 0) / len(trs) * 100
        s_pnl = sum(t.pnl_sized for t in trs)
        s_win = sum(t.pnl_sized for t in trs if t.pnl_sized > 0)
        s_loss = -sum(t.pnl_sized for t in trs if t.pnl_sized <= 0)
        s_pf = s_win / s_loss if s_loss > 0 else float("inf")
        lines.append(f"    {s:25s}  N={len(trs):>5d}  WR={s_wr:5.1f}%  PF={s_pf:5.2f}  P&L=${s_pnl:>+10,.0f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--end", default="2026-05-21")
    ap.add_argument("--filter-min", type=int, default=15,
                    help="Filter A threshold (skip fires <N min into sweep H1 bar)")
    args = ap.parse_args()

    print(f"Window: {args.start} → {args.end}")
    print(f"Filter A threshold: {args.filter_min} min\n")

    print("Running BASELINE (skip_partial_min=0) ...")
    r0 = run_backtest(start_date=args.start, end_date=args.end, skip_partial_min=0)
    print()
    print("Running FILTER A (skip_partial_min=%d) ..." % args.filter_min)
    rA = run_backtest(start_date=args.start, end_date=args.end, skip_partial_min=args.filter_min)
    print()

    print("=" * 70)
    print(fmt_result(r0, "BASELINE"))
    print()
    print("=" * 70)
    print(fmt_result(rA, "FILTER A"))
    print()
    print("=" * 70)
    print("DELTA")
    n_delta = len(rA.trades) - len(r0.trades)
    pnl_delta = sum(t.pnl_sized for t in rA.trades) - sum(t.pnl_sized for t in r0.trades)
    print(f"  Trade count:  {n_delta:+d}")
    print(f"  P&L:          ${pnl_delta:+,.0f}")


if __name__ == "__main__":
    main()
