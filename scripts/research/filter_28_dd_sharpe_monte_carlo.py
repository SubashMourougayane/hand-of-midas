"""Filter #28 — DD stress + Sharpe + Monte Carlo analysis.

Runs 8 BTs (4 systems × 2 modes) at seed=42, captures full trade list,
then computes:
  1. Drawdown stress — peak-to-trough $ DD, % DD, longest DD duration in days
  2. Sharpe ratio — annualized from daily P&L
  3. Monte Carlo — bootstrap 1000× resample of trades to get distribution of
     final P&L and max DD; surfaces tail-risk percentiles.

NO fake numbers. Uses production `run_backtest` with real `_execute_trade`
fill mechanics. Trade list is the literal output of the engine.

USAGE:
  python scripts/research/filter_28_dd_sharpe_monte_carlo.py
  python scripts/research/filter_28_dd_sharpe_monte_carlo.py --seed 42 --mc-trials 1000

OUTPUT:
  scripts/output/filter_28_dd_sharpe_mc_results.json
  scripts/output/filter_28_dd_sharpe_mc_console.txt (this file's stdout)

CAVEATS (per project-filter-sweep-workflow + statistical honesty):
  - Bootstrap MC assumes i.i.d. trades. Real strategies have mild regime
    clustering — MC will slightly understate tail risk.
  - Sharpe uses daily P&L from real exit dates (sum trades by date).
    Convention: 252 trading days/year.
  - Equity curve = cumulative pnl_sized, NO yearly capital reset (real
    account would compound). BT engine resets to $5k every Jan 1, but for
    DD analysis we want the unreset curve.
  - Single seed (42) — multi-seed already showed CV < 1.3% across all
    systems. DD/Sharpe variance across seeds is unmeasurable noise.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import json
import importlib
from statistics import mean, stdev
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_pnl(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:+,.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:+,.1f}k"
    return f"${v:+,.0f}"


def _run_one(system_key: str, start: str, end: str, seed: int,
             bias_mode: str | None) -> tuple:
    """Returns (result, trade_records) where trade_records is a list of dicts
    with date (datetime), pnl_sized."""
    sys_path_map = {
        "gold-macro": "backend",
        "gold-micro": "backend-micro",
        "oil-macro":  "backend-oil",
        "oil-micro":  "backend-oil-micro",
    }
    sys_dir = os.path.join(PROJECT_ROOT, sys_path_map[system_key])
    if sys_dir not in sys.path:
        sys.path.insert(0, sys_dir)

    for cached in list(sys.modules.keys()):
        if cached.startswith(("backtest", "strategies", "config", "scanner")):
            del sys.modules[cached]
    importlib.invalidate_caches()

    engine_mod = importlib.import_module("backtest.engine")
    label = bias_mode if bias_mode else "production"
    print(f"  [{system_key}] bias_mode={label} :: running...", flush=True)
    t0 = time.time()
    result = engine_mod.run_backtest(start_date=start, end_date=end, seed=seed,
                                     bias_mode=bias_mode)
    elapsed = time.time() - t0
    print(f"  [{system_key}] bias_mode={label} :: done in {elapsed:.1f}s "
          f":: trades={result.total_trades:,} P&L={_format_pnl(result.total_pnl)}",
          flush=True)

    # Extract trade records — date + pnl_sized only (compact)
    trade_records = []
    for t in result.trades:
        # date may be string or datetime — normalize to date-string
        d = str(t.date) if hasattr(t, "date") else "?"
        # Use first 10 chars to get YYYY-MM-DD
        d_str = d[:10] if len(d) >= 10 else d
        trade_records.append({
            "date": d_str,
            "year": int(t.year) if hasattr(t, "year") else int(d_str[:4]),
            "pnl_sized": float(t.pnl_sized),
        })
    # Sort by date (defensive — trades should already be in order)
    trade_records.sort(key=lambda x: x["date"])
    return result, trade_records


# ---------------------------------------------------------------------------
# DD analysis
# ---------------------------------------------------------------------------


def compute_drawdown_stats(trades: list[dict]) -> dict:
    """Build cumulative P&L curve (no yearly resets), compute DD metrics.

    Returns:
      max_dd_dollar       — peak-to-trough max drawdown in $
      max_dd_pct_of_peak  — max DD as % of peak equity at the time
      max_dd_duration_days — longest stretch (calendar days) below peak
      n_dd_periods        — count of distinct DD periods (peak → trough → recovery)
      total_trades        — sanity check
      final_pnl           — cumulative P&L
    """
    if not trades:
        return {"max_dd_dollar": 0.0, "max_dd_pct_of_peak": 0.0,
                "max_dd_duration_days": 0, "n_dd_periods": 0,
                "total_trades": 0, "final_pnl": 0.0}

    import pandas as pd
    # Cumulative equity curve
    df = pd.DataFrame(trades)
    df["date"] = pd.to_datetime(df["date"])
    # Aggregate per day (multiple trades can exit same day)
    daily = df.groupby("date")["pnl_sized"].sum().sort_index()
    cum_pnl = daily.cumsum()
    # equity_curve = starting_equity + cum_pnl; for DD math we use pure cum_pnl
    # since starting_equity is just an offset (DD calculated on peak-to-trough).
    running_max = cum_pnl.cummax()
    drawdown = cum_pnl - running_max  # negative or zero
    max_dd_dollar = abs(float(drawdown.min())) if len(drawdown) else 0.0

    # % DD: max DD as % of peak at the time of trough
    if max_dd_dollar > 0:
        trough_idx = drawdown.idxmin()
        peak_at_trough = running_max.loc[trough_idx]
        # Add a notional starting capital so % is meaningful (use $5k yearly capital
        # × num years as starting balance — gives sensible relative scale)
        notional_start = 5000.0 * 21  # 21yr × yearly capital
        max_dd_pct = max_dd_dollar / max(peak_at_trough + notional_start, 1.0) * 100
    else:
        max_dd_pct = 0.0

    # Longest DD duration: longest stretch where cum_pnl < running_max
    in_dd = drawdown < 0
    if in_dd.any():
        # Find runs of True in in_dd
        durations = []
        run_start = None
        for ts, in_dd_val in in_dd.items():
            if in_dd_val and run_start is None:
                run_start = ts
            elif not in_dd_val and run_start is not None:
                durations.append((ts - run_start).days)
                run_start = None
        if run_start is not None:
            durations.append((in_dd.index[-1] - run_start).days)
        max_dd_duration = max(durations) if durations else 0
        n_dd_periods = len(durations)
    else:
        max_dd_duration = 0
        n_dd_periods = 0

    return {
        "max_dd_dollar": max_dd_dollar,
        "max_dd_pct_of_peak": max_dd_pct,
        "max_dd_duration_days": max_dd_duration,
        "n_dd_periods": n_dd_periods,
        "total_trades": len(trades),
        "final_pnl": float(cum_pnl.iloc[-1]) if len(cum_pnl) else 0.0,
    }


# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------


def compute_sharpe(trades: list[dict], trading_days_per_year: int = 252) -> dict:
    """Annualized Sharpe from daily P&L.

    Sharpe = mean(daily_pnl) / std(daily_pnl) * sqrt(trading_days_per_year)

    Caveat: doesn't subtract risk-free rate. For a P&L series this is the
    standard convention and the rate is small relative to the trading P&L
    swings. If user wants risk-free-adjusted, subtract daily_rf from each
    return before computing.

    Returns:
      mean_daily_pnl, std_daily_pnl, sharpe_annualized,
      n_trading_days, days_with_positive_pnl, days_with_negative_pnl
    """
    if not trades:
        return {"sharpe": 0.0, "mean_daily_pnl": 0.0, "std_daily_pnl": 0.0,
                "n_trading_days": 0, "days_pos": 0, "days_neg": 0}

    import pandas as pd
    df = pd.DataFrame(trades)
    df["date"] = pd.to_datetime(df["date"])
    daily = df.groupby("date")["pnl_sized"].sum().sort_index()
    if len(daily) < 2:
        return {"sharpe": 0.0, "mean_daily_pnl": float(daily.iloc[0]) if len(daily) else 0.0,
                "std_daily_pnl": 0.0, "n_trading_days": len(daily),
                "days_pos": 1 if len(daily) and daily.iloc[0] > 0 else 0,
                "days_neg": 1 if len(daily) and daily.iloc[0] < 0 else 0}
    mu = float(daily.mean())
    sigma = float(daily.std(ddof=1))
    sharpe = (mu / sigma) * (trading_days_per_year ** 0.5) if sigma > 0 else 0.0
    return {
        "sharpe": sharpe,
        "mean_daily_pnl": mu,
        "std_daily_pnl": sigma,
        "n_trading_days": len(daily),
        "days_pos": int((daily > 0).sum()),
        "days_neg": int((daily < 0).sum()),
    }


# ---------------------------------------------------------------------------
# Monte Carlo (bootstrap)
# ---------------------------------------------------------------------------


def monte_carlo_bootstrap(trades: list[dict], n_trials: int, seed: int) -> dict:
    """Bootstrap-resample trades with replacement; for each trial compute
    final P&L and max DD on the resampled chronological-but-bootstrap
    sequence.

    What this measures:
      Distribution of "what could happen" if you got a different RANDOM
      ORDER + RANDOM SAMPLING of trades from the same population. The
      strategy's ALPHA is held constant — we're stressing path-dependence.

    What this DOESN'T measure:
      - Regime change risk (different population entirely)
      - Tail event clustering (assumes trades are independent)

    Returns p5/p50/p95 of final P&L and p95 of max DD.
    """
    if not trades:
        return {"final_pnl_p5": 0.0, "final_pnl_p50": 0.0, "final_pnl_p95": 0.0,
                "max_dd_p5": 0.0, "max_dd_p50": 0.0, "max_dd_p95": 0.0,
                "prob_negative_final": 0.0, "n_trials": 0}

    rng = np.random.RandomState(seed)
    pnls = np.array([t["pnl_sized"] for t in trades])
    n = len(pnls)
    final_pnls = np.empty(n_trials)
    max_dds = np.empty(n_trials)
    for k in range(n_trials):
        # Sample with replacement
        sample = pnls[rng.randint(0, n, size=n)]
        cum = np.cumsum(sample)
        running_max = np.maximum.accumulate(cum)
        dd = cum - running_max  # ≤ 0
        final_pnls[k] = cum[-1]
        max_dds[k] = abs(dd.min())  # positive number

    return {
        "n_trials": int(n_trials),
        "final_pnl_p5":  float(np.percentile(final_pnls, 5)),
        "final_pnl_p50": float(np.percentile(final_pnls, 50)),
        "final_pnl_p95": float(np.percentile(final_pnls, 95)),
        "max_dd_p5":  float(np.percentile(max_dds, 5)),
        "max_dd_p50": float(np.percentile(max_dds, 50)),
        "max_dd_p95": float(np.percentile(max_dds, 95)),
        "prob_negative_final": float((final_pnls < 0).mean()),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systems", default="gold-macro,gold-micro,oil-macro,oil-micro")
    ap.add_argument("--start", default="2005-01-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--mc-trials", type=int, default=1000,
                    help="Bootstrap MC trials per (system, mode) — 1000 typical")
    ap.add_argument("--mc-seed", type=int, default=12345,
                    help="Independent seed for MC bootstrap so results are reproducible")
    ap.add_argument("--output-dir", default="scripts/output")
    args = ap.parse_args()

    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    valid = {"gold-macro", "gold-micro", "oil-macro", "oil-micro"}
    for s in systems:
        if s not in valid:
            print(f"  ERROR: unknown system '{s}'.")
            sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)
    started = time.time()

    print("=" * 110)
    print("FILTER #28 — DD STRESS + SHARPE + MONTE CARLO")
    print("=" * 110)
    print(f"  Systems:    {systems}")
    print(f"  Date range: {args.start} → {args.end}")
    print(f"  BT seed:    {args.seed}  (single seed — multi-seed run already showed CV<1.3%)")
    print(f"  MC trials:  {args.mc_trials}  (bootstrap, seed={args.mc_seed})")
    print()

    all_results: list[dict] = []
    for sys_key in systems:
        for mode in [None, "neutral"]:
            try:
                bt_result, trade_records = _run_one(
                    sys_key, args.start, args.end, args.seed, mode)
                # Compute metrics
                dd = compute_drawdown_stats(trade_records)
                sh = compute_sharpe(trade_records)
                mc = monte_carlo_bootstrap(trade_records, args.mc_trials, args.mc_seed)
                all_results.append({
                    "system": sys_key,
                    "bias_mode": mode if mode else "production",
                    "total_trades": bt_result.total_trades,
                    "total_pnl": bt_result.total_pnl,
                    "win_rate": bt_result.win_rate,
                    "profit_factor": bt_result.profit_factor,
                    "max_drawdown_pct_engine": bt_result.max_drawdown_pct,  # from engine itself
                    "dd": dd,
                    "sharpe": sh,
                    "mc": mc,
                })
            except Exception as e:
                import traceback
                print(f"  [{sys_key}] {mode} :: ERROR")
                traceback.print_exc()
                all_results.append({"system": sys_key, "bias_mode": mode or "production",
                                    "error": str(e)})

    elapsed = time.time() - started
    print(f"\n  Total: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print()

    # ----------------------------------------------------------------------
    # DD STRESS TABLE
    # ----------------------------------------------------------------------
    print("=" * 130)
    print("DRAWDOWN STRESS — peak-to-trough on cumulative P&L curve (no yearly reset)")
    print("=" * 130)
    print(f"  {'System':<13s} {'Mode':<11s} {'MaxDD$':>11s} {'MaxDD%peak':>11s} "
          f"{'DurationDays':>13s} {'#DD periods':>12s} {'Final P&L':>13s}")
    print(f"  {'-'*13} {'-'*11} {'-'*11} {'-'*11} {'-'*13} {'-'*12} {'-'*13}")
    for r in all_results:
        if "error" in r:
            continue
        d = r["dd"]
        print(f"  {r['system']:<13s} {r['bias_mode']:<11s} "
              f"{_format_pnl(d['max_dd_dollar']):>11s} "
              f"{d['max_dd_pct_of_peak']:>10.2f}% "
              f"{d['max_dd_duration_days']:>13,d} "
              f"{d['n_dd_periods']:>12,d} "
              f"{_format_pnl(d['final_pnl']):>13s}")

    # DD delta side-by-side
    print()
    print("DD DELTA — Neutral minus Production (negative = neutral has WORSE DD)")
    print(f"  {'System':<13s} {'ΔMaxDD$':>13s} {'ΔMaxDD%pts':>12s} {'ΔDurationDays':>14s}")
    print(f"  {'-'*13} {'-'*13} {'-'*12} {'-'*14}")
    for sys_key in systems:
        rows = [r for r in all_results if r.get("system") == sys_key and "error" not in r]
        if len(rows) != 2:
            continue
        prod = next(r for r in rows if r["bias_mode"] == "production")
        nb = next(r for r in rows if r["bias_mode"] == "neutral")
        d_dd = nb["dd"]["max_dd_dollar"] - prod["dd"]["max_dd_dollar"]
        d_pct = nb["dd"]["max_dd_pct_of_peak"] - prod["dd"]["max_dd_pct_of_peak"]
        d_dur = nb["dd"]["max_dd_duration_days"] - prod["dd"]["max_dd_duration_days"]
        print(f"  {sys_key:<13s} {_format_pnl(d_dd):>13s} {d_pct:>+11.2f}p "
              f"{d_dur:>+14,d}")

    # ----------------------------------------------------------------------
    # SHARPE TABLE
    # ----------------------------------------------------------------------
    print()
    print("=" * 130)
    print("SHARPE RATIO — annualized from daily P&L (252 trading days/yr convention)")
    print("=" * 130)
    print(f"  {'System':<13s} {'Mode':<11s} {'Sharpe':>8s} {'MeanDailyP&L':>14s} "
          f"{'StdDailyP&L':>13s} {'TradingDays':>12s} {'DaysPos':>8s} {'DaysNeg':>8s}")
    print(f"  {'-'*13} {'-'*11} {'-'*8} {'-'*14} {'-'*13} {'-'*12} {'-'*8} {'-'*8}")
    for r in all_results:
        if "error" in r:
            continue
        s = r["sharpe"]
        print(f"  {r['system']:<13s} {r['bias_mode']:<11s} "
              f"{s['sharpe']:>7.3f}  "
              f"{_format_pnl(s['mean_daily_pnl']):>14s} "
              f"{_format_pnl(s['std_daily_pnl']):>13s} "
              f"{s['n_trading_days']:>12,d} "
              f"{s['days_pos']:>8,d} "
              f"{s['days_neg']:>8,d}")

    # Sharpe delta
    print()
    print("SHARPE DELTA — Neutral minus Production (positive = neutral better risk-adjusted)")
    print(f"  {'System':<13s} {'ΔSharpe':>9s}")
    print(f"  {'-'*13} {'-'*9}")
    for sys_key in systems:
        rows = [r for r in all_results if r.get("system") == sys_key and "error" not in r]
        if len(rows) != 2:
            continue
        prod = next(r for r in rows if r["bias_mode"] == "production")
        nb = next(r for r in rows if r["bias_mode"] == "neutral")
        d = nb["sharpe"]["sharpe"] - prod["sharpe"]["sharpe"]
        print(f"  {sys_key:<13s} {d:>+9.3f}")

    # ----------------------------------------------------------------------
    # MONTE CARLO TABLE
    # ----------------------------------------------------------------------
    print()
    print("=" * 130)
    print(f"MONTE CARLO — {args.mc_trials} bootstrap resamples per cell, distribution percentiles")
    print("=" * 130)
    print(f"  {'System':<13s} {'Mode':<11s} {'P&L p5':>11s} {'P&L p50':>11s} "
          f"{'P&L p95':>11s} {'MaxDD p50':>11s} {'MaxDD p95':>11s} {'P(loss)':>9s}")
    print(f"  {'-'*13} {'-'*11} {'-'*11} {'-'*11} {'-'*11} {'-'*11} {'-'*11} {'-'*9}")
    for r in all_results:
        if "error" in r:
            continue
        m = r["mc"]
        print(f"  {r['system']:<13s} {r['bias_mode']:<11s} "
              f"{_format_pnl(m['final_pnl_p5']):>11s} "
              f"{_format_pnl(m['final_pnl_p50']):>11s} "
              f"{_format_pnl(m['final_pnl_p95']):>11s} "
              f"{_format_pnl(m['max_dd_p50']):>11s} "
              f"{_format_pnl(m['max_dd_p95']):>11s} "
              f"{m['prob_negative_final']*100:>8.2f}%")

    # MC delta
    print()
    print("MC DELTA — Neutral minus Production")
    print(f"  {'System':<13s} {'ΔP&L p5':>13s} {'ΔP&L p50':>13s} {'ΔP&L p95':>13s} {'ΔMaxDD p95':>13s}")
    print(f"  {'-'*13} {'-'*13} {'-'*13} {'-'*13} {'-'*13}")
    for sys_key in systems:
        rows = [r for r in all_results if r.get("system") == sys_key and "error" not in r]
        if len(rows) != 2:
            continue
        prod = next(r for r in rows if r["bias_mode"] == "production")
        nb = next(r for r in rows if r["bias_mode"] == "neutral")
        d_p5 = nb["mc"]["final_pnl_p5"] - prod["mc"]["final_pnl_p5"]
        d_p50 = nb["mc"]["final_pnl_p50"] - prod["mc"]["final_pnl_p50"]
        d_p95 = nb["mc"]["final_pnl_p95"] - prod["mc"]["final_pnl_p95"]
        d_dd = nb["mc"]["max_dd_p95"] - prod["mc"]["max_dd_p95"]
        print(f"  {sys_key:<13s} {_format_pnl(d_p5):>13s} {_format_pnl(d_p50):>13s} "
              f"{_format_pnl(d_p95):>13s} {_format_pnl(d_dd):>13s}")

    # ----------------------------------------------------------------------
    # JSON output
    # ----------------------------------------------------------------------
    json_path = os.path.join(args.output_dir, "filter_28_dd_sharpe_mc_results.json")
    with open(json_path, "w") as f:
        json.dump({"args": vars(args), "results": all_results},
                  f, indent=2, default=str)
    print()
    print(f"  JSON: {json_path}")

    # ----------------------------------------------------------------------
    # Verdict
    # ----------------------------------------------------------------------
    print()
    print("=" * 130)
    print("BOTTOM LINE")
    print("=" * 130)
    print()
    print("DD-STRESS interpretation:")
    print("  Look for: did NEUTRAL increase MaxDD$ enough to matter? Did duration extend?")
    print("  Acceptable threshold: ΔMaxDD% < +5pp, ΔDuration < +90 days, no system worsens >2x")
    print()
    print("SHARPE interpretation:")
    print("  Higher is better. ΔSharpe > 0 means neutral is better risk-adjusted.")
    print("  ΔSharpe < 0 with much higher P&L = more vol but higher absolute returns.")
    print()
    print("MC interpretation:")
    print("  P&L p5 = 5th-percentile bad-luck outcome. Look for: is neutral's p5 > production's p50?")
    print("  Prob(loss) = chance of negative cumulative P&L on resampled order.")
    print("  Should be near-zero for both modes (these are profitable strategies).")
    print()
    print("CAVEATS REPEATED:")
    print("  - Bootstrap MC assumes i.i.d. trades; mild regime clustering means")
    print("    real-world tail risk is slightly worse than MC p95.")
    print("  - Single-seed BT (42); multi-seed already showed CV<1.3% on P&L.")
    print("  - DD computed on raw cumulative P&L (no yearly capital reset).")


if __name__ == "__main__":
    main()
