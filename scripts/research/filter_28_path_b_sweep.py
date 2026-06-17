"""Filter #28 — Path B sweep (clean kwarg).

Same as Path A but uses the new `bias_mode` kwarg directly instead of
monkey-patching. Validates that Path B produces IDENTICAL numbers to
Path A.

Path A → Path B should match:
    Cumulative ΔP&L (NEUTRAL minus WITH-BIAS): +$3.58M
    Yearly W/L per system: 21W/0L for ALL 4 systems (84/84)

If they don't match, Path B has a bug and we don't ship it.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import json
import importlib

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
    print(f"  [{system_key}] bias_mode={label} :: running run_backtest...")
    t0 = time.time()
    result = engine_mod.run_backtest(start_date=start, end_date=end, seed=seed,
                                     bias_mode=bias_mode)
    elapsed = time.time() - t0
    print(f"  [{system_key}] bias_mode={label} :: done in {elapsed:.1f}s")

    yearly: dict[int, dict] = {}
    for t in result.trades:
        y = t.year if hasattr(t, "year") else int(str(t.date)[:4])
        ya = yearly.setdefault(y, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        ya["trades"] += 1
        if t.pnl_sized > 0: ya["wins"] += 1
        elif t.pnl_sized < 0: ya["losses"] += 1
        ya["pnl"] += t.pnl_sized

    return {
        "system": system_key,
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
    ap.add_argument("--start", default="2005-01-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output-dir", default="scripts/output")
    args = ap.parse_args()

    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    valid = {"gold-macro", "gold-micro", "oil-macro", "oil-micro"}
    for s in systems:
        if s not in valid:
            print(f"  ERROR: unknown system '{s}'.")
            sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 100)
    print("FILTER #28 — PATH B SWEEP (clean bias_mode kwarg)")
    print("=" * 100)
    print(f"  Systems: {systems}")
    print(f"  Date range: {args.start} → {args.end}")
    print(f"  Seed: {args.seed}")
    print(f"  Method: run_backtest(bias_mode='neutral')")
    print()

    all_results: list[dict] = []
    for sys_key in systems:
        for mode in [None, "neutral"]:
            try:
                r = _run_one(sys_key, args.start, args.end, args.seed, mode)
                all_results.append(r)
            except Exception as e:
                import traceback
                print(f"  [{sys_key}] {mode} :: ERROR")
                traceback.print_exc()
                all_results.append({"system": sys_key, "bias_mode": mode or "production",
                                    "error": str(e)})

    print()
    print("=" * 110)
    print("RESULTS — per-system, production vs neutral")
    print("=" * 110)
    print(f"  {'System':<13s} {'Mode':<11s} {'Trades':>8s} {'Wins':>6s} {'WR':>6s} "
          f"{'PF':>6s} {'Total P&L':>14s} {'MaxDD%':>8s}")
    print(f"  {'-'*13} {'-'*11} {'-'*8} {'-'*6} {'-'*6} {'-'*6} {'-'*14} {'-'*8}")
    for r in all_results:
        if "error" in r:
            print(f"  {r['system']:<13s} {r['bias_mode']:<11s} ERROR: {r['error'][:60]}")
            continue
        wr_pct = r['win_rate'] * 100 if r['win_rate'] <= 1.0 else r['win_rate']
        print(f"  {r['system']:<13s} {r['bias_mode']:<11s} "
              f"{r['total_trades']:>8,d} {r['wins']:>6,d} {wr_pct:>5.1f}% "
              f"{r['profit_factor']:>6.2f} {_format_pnl(r['total_pnl']):>14s} "
              f"{r['max_drawdown_pct']:>7.1f}%")

    print()
    print("=" * 110)
    print("DELTA — Neutral minus Production")
    print("=" * 110)
    print(f"  {'System':<13s} {'ΔTrades':>9s} {'ΔWR':>7s} {'ΔPF':>7s} {'Δ Total P&L':>16s} {'ΔMaxDD%':>9s}")
    print(f"  {'-'*13} {'-'*9} {'-'*7} {'-'*7} {'-'*16} {'-'*9}")
    grand_delta_pnl = 0.0
    for sys_key in systems:
        rows = [r for r in all_results if r.get("system") == sys_key and "error" not in r]
        if len(rows) != 2:
            continue
        prod = next(r for r in rows if r["bias_mode"] == "production")
        neutral = next(r for r in rows if r["bias_mode"] == "neutral")
        d_trades = neutral["total_trades"] - prod["total_trades"]
        prod_wr = prod["win_rate"] * 100 if prod["win_rate"] <= 1.0 else prod["win_rate"]
        nb_wr = neutral["win_rate"] * 100 if neutral["win_rate"] <= 1.0 else neutral["win_rate"]
        d_wr = nb_wr - prod_wr
        d_pf = neutral["profit_factor"] - prod["profit_factor"]
        d_pnl = neutral["total_pnl"] - prod["total_pnl"]
        d_dd = neutral["max_drawdown_pct"] - prod["max_drawdown_pct"]
        grand_delta_pnl += d_pnl
        print(f"  {sys_key:<13s} {d_trades:>+9,d} {d_wr:>+6.1f}p {d_pf:>+7.2f} "
              f"{_format_pnl(d_pnl):>16s} {d_dd:>+8.1f}p")
    print(f"  {'-'*13} {'-'*9} {'-'*7} {'-'*7} {'-'*16} {'-'*9}")
    print(f"  {'TOTAL':<13s} {' ':>9s} {' ':>7s} {' ':>7s} {_format_pnl(grand_delta_pnl):>16s}")

    # Yearly
    print()
    print("=" * 110)
    print("YEARLY P&L (Neutral minus Production)")
    print("=" * 110)
    all_years: set[int] = set()
    for r in all_results:
        if "yearly" in r:
            all_years.update(r["yearly"].keys())
    years = sorted(all_years)
    header = f"  {'Year':<6s}"
    for sys_key in systems:
        header += f" {sys_key[:11]:>13s}"
    print(header)
    yearly_neutral_wins = {sys_key: 0 for sys_key in systems}
    yearly_neutral_losses = {sys_key: 0 for sys_key in systems}
    for y in years:
        row = f"  {y:<6d}"
        for sys_key in systems:
            wb = next((r for r in all_results
                       if r.get("system") == sys_key and r.get("bias_mode") == "production"
                       and "yearly" in r), None)
            nb = next((r for r in all_results
                       if r.get("system") == sys_key and r.get("bias_mode") == "neutral"
                       and "yearly" in r), None)
            if not wb or not nb:
                row += f" {'?':>13s}"
                continue
            wb_pnl = wb["yearly"].get(y, {"pnl": 0.0})["pnl"]
            nb_pnl = nb["yearly"].get(y, {"pnl": 0.0})["pnl"]
            d = nb_pnl - wb_pnl
            if d > 0: yearly_neutral_wins[sys_key] += 1
            elif d < 0: yearly_neutral_losses[sys_key] += 1
            row += f" {_format_pnl(d):>13s}"
        print(row)
    print(f"  {'-'*6}" + "".join([f" {'-'*13}" for _ in systems]))
    summary_row = f"  {'WIN/LOSS':<6s}"
    for sys_key in systems:
        w = yearly_neutral_wins[sys_key]
        l = yearly_neutral_losses[sys_key]
        summary_row += f" {f'{w}W/{l}L':>13s}"
    print(summary_row)

    # JSON
    json_path = os.path.join(args.output_dir, "filter_28_path_b_results.json")
    with open(json_path, "w") as f:
        json.dump({"args": vars(args), "results": all_results},
                  f, indent=2, default=str)
    print()
    print(f"  JSON: {json_path}")
    print()
    print("=" * 110)
    print("PATH B BOTTOM LINE")
    print("=" * 110)
    print(f"  Cumulative ΔP&L (NEUTRAL minus PRODUCTION): {_format_pnl(grand_delta_pnl)}")
    print()
    print("  Compare to Path A:  +$3.58M  (84W/0L)")
    print("  → if numbers match, Path B is correct and shippable.")
    print("  → if numbers differ, Path B has a bug — DO NOT SHIP.")


if __name__ == "__main__":
    main()
