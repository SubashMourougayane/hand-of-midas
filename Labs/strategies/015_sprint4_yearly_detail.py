"""015 — Per-year breakdown for the top Sprint-4 survivor on each pair.

Runs each pair's BEST walk-forward config on FULL dev window
(2019-09-26 → 2023-12-31) and prints year-by-year P&L, trades, WR, DD.

Capital convention: yearly reset to $5,000 starting capital, 4% risk per
trade, 5,000 unit cap. SAME convention as production engines.

So "yearly P&L" = what you'd have made trading $5K that year only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.data_forex import get_forex
from Labs.shared.runner_forex import run_forex_strategy

_p = Path(__file__).resolve().parent / "013_bearishharry_forex.py"
_spec = importlib.util.spec_from_file_location("bh_strategy", _p)
_m = importlib.util.module_from_spec(_spec)
sys.modules["bh_strategy"] = _m
_spec.loader.exec_module(_m)
generate_signals = _m.generate_signals
BearishHarryConfig = _m.BearishHarryConfig


# Top walk-forward survivor on each pair (highest val PF among rejection_wick,
# 12h, rr ≥ 1.5 configs). Source: Labs/results/sprint_4_walkforward.csv
TOPS = {
    "AUD_USD": dict(sweep_lookback_hours=12, h1_confirmation="engulf",         m15_entry="engulf_close", rr=2.0),
    "XAU_USD": dict(sweep_lookback_hours=12, h1_confirmation="rejection_wick", m15_entry="engulf_close", rr=3.0),
    "EUR_USD": dict(sweep_lookback_hours=12, h1_confirmation="rejection_wick", m15_entry="engulf_close", rr=3.0),
    "USD_CAD": dict(sweep_lookback_hours=12, h1_confirmation="rejection_wick", m15_entry="engulf_close", rr=3.0),
    "GBP_USD": dict(sweep_lookback_hours=12, h1_confirmation="rejection_wick", m15_entry="engulf_close", rr=3.0),
    "USD_JPY": dict(sweep_lookback_hours=12, h1_confirmation="rejection_wick", m15_entry="engulf_close", rr=2.0),
}


def main() -> None:
    print()
    print("=" * 92)
    print("  Sprint 4 — Top survivor per pair, per-year P&L (yearly $5K reset, 4% risk)")
    print("=" * 92)
    print(f"  {'Pair':<8} {'Year':<6} {'Trades':<8} {'Wins':<6} {'WR%':<8} "
          f"{'P&L':>14} {'DD%':>8} {'EndEquity':>12}")
    print("  " + "─" * 90)

    grand_total_pnl = 0.0
    grand_total_trades = 0
    per_pair_totals: dict[str, dict] = {}

    for sym, kw in TOPS.items():
        cfg = BearishHarryConfig(**kw)
        bundle = get_forex(sym)
        fn = lambda d1_, h4_, h1_, m15_, c=cfg: generate_signals(d1_, h4_, h1_, m15_, c)
        r = run_forex_strategy(fn, bundle)

        pair_pnl = 0.0
        pair_trades = 0
        for y in sorted(r.by_year.keys()):
            s = r.by_year[y]
            wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0.0
            print(f"  {sym:<8} {y:<6} {s['trades']:<8} {s['wins']:<6} {wr:<8.1f} "
                  f"${s['pnl']:>11,.2f}  {s['dd_pct']:>7.2f}  ${s['ending_equity']:>10,.2f}")
            pair_pnl += s["pnl"]
            pair_trades += s["trades"]
        worst_dd = max((s["dd_pct"] for s in r.by_year.values()), default=0.0)
        years = len(r.by_year)
        per_year_avg = pair_pnl / years if years else 0.0
        print(f"  {sym:<8} {'TOTAL':<6} {pair_trades:<8} {'':<6} {'':<8} "
              f"${pair_pnl:>11,.2f}  {worst_dd:>7.2f}  ({years}y → ${per_year_avg:,.2f}/yr)")
        print()
        per_pair_totals[sym] = {
            "trades": pair_trades, "pnl": pair_pnl, "years": years,
            "per_year": per_year_avg, "worst_dd": worst_dd,
        }
        grand_total_pnl += pair_pnl
        grand_total_trades += pair_trades

    print("=" * 92)
    print("  PORTFOLIO SUMMARY (assumes $5K capital allocated to EACH pair, yearly reset)")
    print("=" * 92)
    print(f"  {'Pair':<8} {'Trades':<8} {'Total P&L':>14} {'Avg/Year':>14} {'Worst DD%':>12}")
    print("  " + "─" * 60)
    for sym, t in per_pair_totals.items():
        print(f"  {sym:<8} {t['trades']:<8} ${t['pnl']:>11,.2f}  ${t['per_year']:>11,.2f}  {t['worst_dd']:>11.2f}")
    print("  " + "─" * 60)
    avg_years = sum(t["years"] for t in per_pair_totals.values()) / len(per_pair_totals)
    avg_per_year_per_pair = grand_total_pnl / (avg_years * len(per_pair_totals))
    print(f"  {'TOTAL':<8} {grand_total_trades:<8} ${grand_total_pnl:>11,.2f}  "
          f"${grand_total_pnl/avg_years:>11,.2f}  (across all 6 pairs combined)")
    print()
    print(f"  Capital required: 6 × $5K = $30K (yearly reset per pair)")
    print(f"  Aggregate per-year per-pair average: ${avg_per_year_per_pair:,.2f}")
    print(f"  Aggregate per-year ALL-PAIR portfolio: ${grand_total_pnl/avg_years:,.2f}")
    print()


if __name__ == "__main__":
    main()
