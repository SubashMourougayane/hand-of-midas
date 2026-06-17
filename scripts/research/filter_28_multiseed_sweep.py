"""Filter #28 — Multi-seed validation.

Runs the 4 systems × 2 modes (production / neutral) × N seeds matrix
to validate that the +$3.58M / 21yr finding from Path A & Path B is
robust to slippage RNG variability, not a single-seed luck artifact.

Per `project-filter-sweep-workflow`, multi-seed is the next mandatory
step before any per-system selective ship.

USAGE:
  python scripts/research/filter_28_multiseed_sweep.py
  python scripts/research/filter_28_multiseed_sweep.py --seeds 42,7,1337,2024,99
  python scripts/research/filter_28_multiseed_sweep.py --systems oil-micro
  python scripts/research/filter_28_multiseed_sweep.py --start 2010-01-01 --end 2020-12-31

OUTPUT:
  scripts/output/filter_28_multiseed_results.json (raw per-seed data)
  scripts/output/filter_28_multiseed_console.txt  (this script's stdout)
  scripts/output/filter_28_multiseed_summary.csv  (spreadsheet-friendly)

Design — what makes this honest:
  - Uses Path B's `bias_mode` kwarg (production-shipped path), NOT monkey-patch
  - Each seed is a TRUE independent run via `run_backtest(seed=X)` — no
    cached results, fresh module imports between systems
  - Per-seed P&L logged so you can see the full distribution, not just mean
  - Yearly W/L tracked PER SEED — if any seed flips a year from W to L,
    that's surfaced
  - Standard deviation + min/max per (system, mode) so confidence intervals
    are visible, not hidden behind averages
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import json
import importlib
from statistics import mean, stdev

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)


def _format_pnl(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:+,.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:+,.1f}k"
    return f"${v:+,.0f}"


def _run_one(system_key: str, start: str, end: str, seed: int,
             bias_mode: str | None) -> dict:
    sys_path_map = {
        "gold-macro": "backend",
        "gold-micro": "backend-micro",
        "oil-macro":  "backend-oil",
        "oil-micro":  "backend-oil-micro",
    }
    sys_dir = os.path.join(PROJECT_ROOT, sys_path_map[system_key])
    if sys_dir not in sys.path:
        sys.path.insert(0, sys_dir)

    # Clear cached per-system modules so the right system's engine loads
    for cached in list(sys.modules.keys()):
        if cached.startswith(("backtest", "strategies", "config", "scanner")):
            del sys.modules[cached]
    importlib.invalidate_caches()

    engine_mod = importlib.import_module("backtest.engine")
    label = bias_mode if bias_mode else "production"
    print(f"    [{system_key}] seed={seed} bias_mode={label} :: running...", flush=True)
    t0 = time.time()
    result = engine_mod.run_backtest(start_date=start, end_date=end, seed=seed,
                                     bias_mode=bias_mode)
    elapsed = time.time() - t0

    yearly: dict[int, dict] = {}
    for t in result.trades:
        y = t.year if hasattr(t, "year") else int(str(t.date)[:4])
        ya = yearly.setdefault(y, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        ya["trades"] += 1
        if t.pnl_sized > 0: ya["wins"] += 1
        elif t.pnl_sized < 0: ya["losses"] += 1
        ya["pnl"] += t.pnl_sized

    print(f"    [{system_key}] seed={seed} bias_mode={label} :: "
          f"done in {elapsed:.1f}s :: trades={result.total_trades:,} "
          f"PF={result.profit_factor:.2f} P&L={_format_pnl(result.total_pnl)}",
          flush=True)

    return {
        "system": system_key,
        "seed": seed,
        "bias_mode": label,
        "total_trades": result.total_trades,
        "wins": result.wins,
        "losses": result.losses,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "total_pnl": result.total_pnl,
        "max_drawdown_pct": result.max_drawdown_pct,
        "elapsed_s": elapsed,
        "yearly": yearly,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systems", default="gold-macro,gold-micro,oil-macro,oil-micro")
    ap.add_argument("--seeds", default="42,7,1337,2024,99")
    ap.add_argument("--start", default="2005-01-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--output-dir", default="scripts/output")
    args = ap.parse_args()

    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    valid = {"gold-macro", "gold-micro", "oil-macro", "oil-micro"}
    for s in systems:
        if s not in valid:
            print(f"  ERROR: unknown system '{s}'.")
            sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)
    total_runs = len(systems) * len(seeds) * 2
    started_at = time.time()

    print("=" * 110)
    print("FILTER #28 — MULTI-SEED VALIDATION")
    print("=" * 110)
    print(f"  Systems:   {systems}")
    print(f"  Seeds:     {seeds}")
    print(f"  Date range: {args.start} → {args.end}")
    print(f"  Total runs: {total_runs} ({len(systems)} systems × 2 modes × {len(seeds)} seeds)")
    print(f"  Method:    run_backtest(seed=X, bias_mode=...) — Path B kwarg")
    print()

    all_results: list[dict] = []
    run_i = 0
    for sys_key in systems:
        print(f"  ── {sys_key} ──")
        for seed in seeds:
            for mode in [None, "neutral"]:
                run_i += 1
                elapsed_total = time.time() - started_at
                eta = elapsed_total / run_i * (total_runs - run_i) if run_i > 0 else 0
                print(f"  [{run_i}/{total_runs}] elapsed={elapsed_total:.0f}s eta={eta:.0f}s", flush=True)
                try:
                    r = _run_one(sys_key, args.start, args.end, seed, mode)
                    all_results.append(r)
                except Exception as e:
                    import traceback
                    print(f"    [{sys_key}] seed={seed} {mode} :: ERROR")
                    traceback.print_exc()
                    all_results.append({"system": sys_key, "seed": seed,
                                        "bias_mode": mode or "production",
                                        "error": str(e)})
        print()

    elapsed_total = time.time() - started_at
    print(f"  Total elapsed: {elapsed_total:.0f}s ({elapsed_total/60:.1f}min)")
    print()

    # ============================================================
    # Per-seed detail table
    # ============================================================
    print("=" * 130)
    print("PER-SEED RESULTS — full P&L per (system, seed, mode)")
    print("=" * 130)
    print(f"  {'System':<13s} {'Seed':>6s} {'Mode':<11s} {'Trades':>8s} {'WR':>7s} "
          f"{'PF':>7s} {'Total P&L':>13s} {'MaxDD%':>8s}")
    print(f"  {'-'*13} {'-'*6} {'-'*11} {'-'*8} {'-'*7} {'-'*7} {'-'*13} {'-'*8}")
    for r in all_results:
        if "error" in r:
            print(f"  {r['system']:<13s} {r['seed']:>6d} {r['bias_mode']:<11s} ERROR: {r['error'][:50]}")
            continue
        wr_pct = r['win_rate'] * 100 if r['win_rate'] <= 1.0 else r['win_rate']
        print(f"  {r['system']:<13s} {r['seed']:>6d} {r['bias_mode']:<11s} "
              f"{r['total_trades']:>8,d} {wr_pct:>6.2f}% "
              f"{r['profit_factor']:>7.3f} {_format_pnl(r['total_pnl']):>13s} "
              f"{r['max_drawdown_pct']:>7.2f}%")

    # ============================================================
    # Per-(system, mode) seed distribution stats
    # ============================================================
    print()
    print("=" * 130)
    print("SEED DISTRIBUTION — mean / std / min / max / range across seeds")
    print("=" * 130)
    print(f"  {'System':<13s} {'Mode':<11s} {'N_seeds':>8s} {'mean P&L':>13s} "
          f"{'std P&L':>13s} {'min P&L':>13s} {'max P&L':>13s} {'range':>13s} "
          f"{'mean PF':>9s} {'mean WR':>9s}")
    print(f"  {'-'*13} {'-'*11} {'-'*8} {'-'*13} {'-'*13} {'-'*13} {'-'*13} {'-'*13} {'-'*9} {'-'*9}")
    cell_stats: dict[tuple, dict] = {}
    for sys_key in systems:
        for mode_label in ["production", "neutral"]:
            rows = [r for r in all_results
                    if r.get("system") == sys_key and r.get("bias_mode") == mode_label
                    and "error" not in r]
            if not rows:
                continue
            pnls = [r["total_pnl"] for r in rows]
            pfs = [r["profit_factor"] for r in rows]
            wrs = [(r["win_rate"] * 100 if r["win_rate"] <= 1.0 else r["win_rate"])
                   for r in rows]
            n = len(pnls)
            stats = {
                "n_seeds": n,
                "mean_pnl": mean(pnls),
                "std_pnl": stdev(pnls) if n > 1 else 0.0,
                "min_pnl": min(pnls),
                "max_pnl": max(pnls),
                "range_pnl": max(pnls) - min(pnls),
                "mean_pf": mean(pfs),
                "mean_wr": mean(wrs),
            }
            cell_stats[(sys_key, mode_label)] = stats
            print(f"  {sys_key:<13s} {mode_label:<11s} {n:>8d} "
                  f"{_format_pnl(stats['mean_pnl']):>13s} "
                  f"{_format_pnl(stats['std_pnl']):>13s} "
                  f"{_format_pnl(stats['min_pnl']):>13s} "
                  f"{_format_pnl(stats['max_pnl']):>13s} "
                  f"{_format_pnl(stats['range_pnl']):>13s} "
                  f"{stats['mean_pf']:>8.3f} {stats['mean_wr']:>8.2f}%")

    # ============================================================
    # Per-system delta (neutral - production) across seeds
    # ============================================================
    print()
    print("=" * 130)
    print("DELTA PER SEED — Neutral minus Production (per system × seed)")
    print("=" * 130)
    header = f"  {'System':<13s}"
    for seed in seeds:
        header += f" {f'seed={seed}':>13s}"
    header += f" {'mean Δ':>13s} {'std Δ':>13s} {'min Δ':>13s} {'max Δ':>13s}"
    print(header)
    print(f"  {'-'*13}" + "".join([f" {'-'*13}" for _ in seeds]) + f" {'-'*13} {'-'*13} {'-'*13} {'-'*13}")

    delta_summary: dict[str, dict] = {}
    grand_total_per_seed = {seed: 0.0 for seed in seeds}
    for sys_key in systems:
        deltas: list[float] = []
        row = f"  {sys_key:<13s}"
        for seed in seeds:
            prod_run = next((r for r in all_results
                             if r.get("system") == sys_key and r.get("seed") == seed
                             and r.get("bias_mode") == "production"
                             and "error" not in r), None)
            neutral_run = next((r for r in all_results
                                if r.get("system") == sys_key and r.get("seed") == seed
                                and r.get("bias_mode") == "neutral"
                                and "error" not in r), None)
            if not prod_run or not neutral_run:
                row += f" {'?':>13s}"
                continue
            d = neutral_run["total_pnl"] - prod_run["total_pnl"]
            deltas.append(d)
            grand_total_per_seed[seed] += d
            row += f" {_format_pnl(d):>13s}"
        if deltas:
            d_mean = mean(deltas)
            d_std = stdev(deltas) if len(deltas) > 1 else 0.0
            d_min = min(deltas)
            d_max = max(deltas)
            delta_summary[sys_key] = {
                "deltas": deltas, "mean": d_mean, "std": d_std,
                "min": d_min, "max": d_max,
            }
            row += (f" {_format_pnl(d_mean):>13s} {_format_pnl(d_std):>13s} "
                    f"{_format_pnl(d_min):>13s} {_format_pnl(d_max):>13s}")
        print(row)

    # Grand total per seed
    print(f"  {'-'*13}" + "".join([f" {'-'*13}" for _ in seeds]) + f" {'-'*13} {'-'*13} {'-'*13} {'-'*13}")
    total_row = f"  {'TOTAL':<13s}"
    grand_seed_totals = list(grand_total_per_seed.values())
    for seed in seeds:
        total_row += f" {_format_pnl(grand_total_per_seed[seed]):>13s}"
    if grand_seed_totals:
        total_row += (f" {_format_pnl(mean(grand_seed_totals)):>13s} "
                      f"{_format_pnl(stdev(grand_seed_totals) if len(grand_seed_totals) > 1 else 0):>13s} "
                      f"{_format_pnl(min(grand_seed_totals)):>13s} "
                      f"{_format_pnl(max(grand_seed_totals)):>13s}")
    print(total_row)

    # ============================================================
    # Per-year W/L per seed — does the 21W/0L pattern hold across seeds?
    # ============================================================
    print()
    print("=" * 130)
    print("PER-YEAR W/L PER SEED — does Neutral beat Production every year on every seed?")
    print("=" * 130)
    all_years: set[int] = set()
    for r in all_results:
        if "yearly" in r:
            all_years.update(r["yearly"].keys())
    years = sorted(all_years)

    yearly_consistency: dict[str, dict] = {}
    for sys_key in systems:
        per_seed_w = {seed: 0 for seed in seeds}
        per_seed_l = {seed: 0 for seed in seeds}
        per_seed_t = {seed: 0 for seed in seeds}  # ties
        any_year_loss_by_seed: dict[int, list[int]] = {}  # seed -> list of years where neutral lost
        for seed in seeds:
            prod_run = next((r for r in all_results
                             if r.get("system") == sys_key and r.get("seed") == seed
                             and r.get("bias_mode") == "production"
                             and "error" not in r), None)
            neutral_run = next((r for r in all_results
                                if r.get("system") == sys_key and r.get("seed") == seed
                                and r.get("bias_mode") == "neutral"
                                and "error" not in r), None)
            if not prod_run or not neutral_run:
                continue
            for y in years:
                pp = prod_run["yearly"].get(y, {"pnl": 0.0})["pnl"]
                np_ = neutral_run["yearly"].get(y, {"pnl": 0.0})["pnl"]
                d = np_ - pp
                if d > 0: per_seed_w[seed] += 1
                elif d < 0:
                    per_seed_l[seed] += 1
                    any_year_loss_by_seed.setdefault(seed, []).append(y)
                else: per_seed_t[seed] += 1
        yearly_consistency[sys_key] = {
            "per_seed_w": per_seed_w,
            "per_seed_l": per_seed_l,
            "per_seed_t": per_seed_t,
            "loss_years": any_year_loss_by_seed,
        }
        # Print compact line
        wl_line = " ".join([
            f"seed={seed}: {per_seed_w[seed]}W/{per_seed_l[seed]}L"
            + (f"/{per_seed_t[seed]}T" if per_seed_t[seed] else "")
            for seed in seeds
        ])
        print(f"  {sys_key:<13s}: {wl_line}")
        # Surface any seed where neutral LOST at least one year
        for seed, loss_years in any_year_loss_by_seed.items():
            print(f"    ⚠️  seed={seed} neutral LOST in {len(loss_years)} year(s): {loss_years}")

    # ============================================================
    # Final verdict
    # ============================================================
    print()
    print("=" * 130)
    print("MULTI-SEED VERDICT")
    print("=" * 130)
    if grand_seed_totals:
        cum_mean = mean(grand_seed_totals)
        cum_std = stdev(grand_seed_totals) if len(grand_seed_totals) > 1 else 0.0
        cum_min = min(grand_seed_totals)
        cum_max = max(grand_seed_totals)
        print(f"  Cumulative ΔP&L across all 4 systems, per seed:")
        for seed in seeds:
            print(f"    seed={seed:>5d}: {_format_pnl(grand_total_per_seed[seed])}")
        print(f"  Mean: {_format_pnl(cum_mean)}  ±  std: {_format_pnl(cum_std)}")
        print(f"  Range: [{_format_pnl(cum_min)} ... {_format_pnl(cum_max)}]")
        # Coefficient of variation
        if cum_mean > 0:
            cv = abs(cum_std / cum_mean) * 100
            print(f"  CV (std/mean): {cv:.1f}%  "
                  f"({'stable — ship-quality' if cv < 5 else 'wide — investigate' if cv > 15 else 'acceptable'})")
        # Worst-case seed
        worst = min(grand_seed_totals)
        print(f"  Worst seed delivered: {_format_pnl(worst)} cumulative across 4 systems")
        if worst > 0:
            print(f"  → ALL seeds positive — robust improvement")
        else:
            print(f"  ⚠️  At least one seed produced ≤ 0 cumulative delta — investigate")

    # ============================================================
    # JSON + CSV output
    # ============================================================
    json_path = os.path.join(args.output_dir, "filter_28_multiseed_results.json")
    with open(json_path, "w") as f:
        json.dump({
            "args": vars(args),
            "results": all_results,
            "delta_summary": delta_summary,
            "grand_total_per_seed": grand_total_per_seed,
            "yearly_consistency": yearly_consistency,
        }, f, indent=2, default=str)
    print()
    print(f"  JSON: {json_path}")

    csv_path = os.path.join(args.output_dir, "filter_28_multiseed_summary.csv")
    with open(csv_path, "w") as f:
        f.write("system,seed,bias_mode,total_trades,wins,losses,win_rate,"
                "profit_factor,total_pnl,max_drawdown_pct\n")
        for r in all_results:
            if "error" in r:
                continue
            wr = r['win_rate'] * 100 if r['win_rate'] <= 1.0 else r['win_rate']
            f.write(f"{r['system']},{r['seed']},{r['bias_mode']},"
                    f"{r['total_trades']},{r['wins']},{r['losses']},"
                    f"{wr:.2f},{r['profit_factor']:.4f},"
                    f"{r['total_pnl']:.4f},{r['max_drawdown_pct']:.4f}\n")
    print(f"  CSV:  {csv_path}")


if __name__ == "__main__":
    main()
