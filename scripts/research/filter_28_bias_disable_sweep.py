"""
Filter #28 — Bias-disable BT sweep (Path A: monkey-patch).

Runs each of the 4 systems through its OWN production `run_backtest()`
twice:
  1. WITH bias filter (production default — baseline)
  2. NEUTRAL bias (every day forced to "neutral" via NeutralBiasDict)

Reports per-system: PF / WR / total_pnl / max_dd / trades / winning $ / yearly slice.

NO fake numbers. NO phantom fills. Real `_execute_trade`, real `_slippage`,
real CSV data. Only the daily_bias dict is patched.

USAGE:
  python scripts/research/filter_28_bias_disable_sweep.py
  python scripts/research/filter_28_bias_disable_sweep.py --systems gold,oil-micro
  python scripts/research/filter_28_bias_disable_sweep.py --start 2010-01-01 --end 2020-12-31

DESIGN:
  - The 3 systems with bias-check in strategy file (Gold/Gold-Micro/Oil-Macro)
    have `bias = daily_bias.get(date, "neutral")` lookups. NeutralBiasDict
    returns "neutral" for any key → bias filter goes silent.
  - Oil Micro has bias check INLINE in backtest/engine.py:generate_signals.
    Same NeutralBiasDict trick works because it also reads via .get().
  - We patch the bias dict at the point where `generate_signals` is called.
    The cleanest way: wrap each engine's `generate_signals` import with a
    lambda that intercepts the daily_bias arg.
  - Production `run_backtest` is invoked unchanged — same fill model, same
    slippage, same yearly capital reset, same RNG seed.

CAVEATS (per project-filter-sweep-workflow):
  - Single-seed only. NOT shippable.
  - Path B follow-up: add bias_mode kwarg to run_backtest for permanent toggle.
  - Multi-seed + DD stress + yearly slice required before any selective ship.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import json
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# NeutralBiasDict — returns "neutral" for ANY key, ignoring writes
# ---------------------------------------------------------------------------


class NeutralBiasDict(dict):
    """Behaves like a dict but `.get(key, default)` always returns "neutral".
    Mutations (assignment, update) are silently ignored — preserves the
    behavioural contract that the strategy expects (a daily_bias dict)
    while forcing every lookup to "neutral".
    """

    def get(self, key, default=None):
        return "neutral"

    def __getitem__(self, key):
        return "neutral"

    def __setitem__(self, key, value):
        # Silently ignore writes — engine code that does daily_bias[d] = "..."
        # would otherwise overwrite our neutral overrides on next assignment.
        pass

    def update(self, *args, **kwargs):
        # Same — preserve neutrality regardless of what engine tries to write.
        pass


# ---------------------------------------------------------------------------
# Per-system runner
# ---------------------------------------------------------------------------


def _patch_strategy_module(module_path_str: str, neutral: bool):
    """Monkey-patch a strategy module's generate_signals so the daily_bias
    arg is replaced by a NeutralBiasDict when neutral=True."""
    import importlib
    mod = importlib.import_module(module_path_str)
    if not neutral:
        # Restore original if we previously patched
        if hasattr(mod, "_filter28_original_generate_signals"):
            mod.generate_signals = mod._filter28_original_generate_signals
            delattr(mod, "_filter28_original_generate_signals")
        return

    # Save original (only once)
    if not hasattr(mod, "_filter28_original_generate_signals"):
        mod._filter28_original_generate_signals = mod.generate_signals

    original_fn = mod._filter28_original_generate_signals

    def patched_generate_signals(*args, **kwargs):
        # daily_bias is the LAST positional arg in all 4 strategy/engine signatures.
        # Replace it with NeutralBiasDict.
        if "daily_bias" in kwargs:
            kwargs["daily_bias"] = NeutralBiasDict()
        elif len(args) >= 3:
            args = list(args)
            args[2] = NeutralBiasDict()
            args = tuple(args)
        else:
            # Should never happen — strategy signatures are stable
            raise RuntimeError(
                f"NeutralBiasDict patch couldn't locate daily_bias arg in "
                f"{module_path_str}.generate_signals(args={len(args)} kwargs={list(kwargs)})"
            )
        return original_fn(*args, **kwargs)

    mod.generate_signals = patched_generate_signals


def _run_one_system(system_key: str, start: str, end: str, seed: int,
                    neutral: bool) -> dict:
    """Run a single system's run_backtest once. Returns dict with results."""
    sys_path_map = {
        "gold-macro": "backend",
        "gold-micro": "backend-micro",
        "oil-macro":  "backend-oil",
        "oil-micro":  "backend-oil-micro",
    }
    bt_module_map = {
        "gold-macro": "backend.backtest.engine",
        "gold-micro": "backend-micro.backtest.engine",  # actually loaded as backtest.engine via path injection
        "oil-macro":  "backend-oil.backtest.engine",
        "oil-micro":  "backend-oil-micro.backtest.engine",
    }
    # Where bias-filter lookup lives — the module whose generate_signals we patch
    strategy_module_map = {
        "gold-macro": "backend.strategies.alpha_sweep",
        "gold-micro": "backend.strategies.micro_alpha_sweep",
        "oil-macro":  "strategies.alpha_sweep",          # backend-oil/strategies (path-injected)
        "oil-micro":  "backtest.engine",                  # bias-check inlined in engine
    }

    sys_dir = os.path.join(PROJECT_ROOT, sys_path_map[system_key])
    if sys_dir not in sys.path:
        sys.path.insert(0, sys_dir)

    # Load the engine module fresh (each system has its own backtest/engine.py
    # but Python's module system uses 'backtest.engine' name for them all —
    # we must clear the cache between systems)
    import importlib
    # Strip any cached 'backtest', 'strategies', 'config' modules from
    # previous system runs — these are per-system-dir
    for cached in list(sys.modules.keys()):
        if cached.startswith(("backtest", "strategies", "config", "scanner")):
            del sys.modules[cached]
    # Re-importlib.invalidate_caches to be safe
    importlib.invalidate_caches()

    # Now import THIS system's engine
    engine_mod = importlib.import_module("backtest.engine")
    strat_mod = importlib.import_module(strategy_module_map[system_key])

    # Patch
    if neutral:
        if not hasattr(strat_mod, "_filter28_original_generate_signals"):
            strat_mod._filter28_original_generate_signals = strat_mod.generate_signals
        original_fn = strat_mod._filter28_original_generate_signals

        def patched_generate_signals(*args, **kwargs):
            if "daily_bias" in kwargs:
                kwargs["daily_bias"] = NeutralBiasDict()
            elif len(args) >= 3:
                args = list(args)
                args[2] = NeutralBiasDict()
                args = tuple(args)
            return original_fn(*args, **kwargs)
        strat_mod.generate_signals = patched_generate_signals

        # IMPORTANT: handle direct-import shape.
        # Oil-Macro's engine does `from strategies.alpha_sweep import generate_signals`
        # which binds a LOCAL reference inside the engine module. Patching
        # strat_mod.generate_signals does NOT reach the engine's local binding.
        # Solution: ALSO patch engine_mod.generate_signals if the engine
        # imported it directly (it'll have the attr).
        if hasattr(engine_mod, "generate_signals") and engine_mod is not strat_mod:
            if not hasattr(engine_mod, "_filter28_original_generate_signals"):
                engine_mod._filter28_original_generate_signals = engine_mod.generate_signals
            engine_mod.generate_signals = patched_generate_signals
        # Gold Macro / Gold Micro use module-attribute access
        # (alpha_sweep.generate_signals(...)) so patching strat_mod is enough.
        # Oil Micro: bias-check inlined in engine.py → strat_mod==engine_mod, patch above hits.

    # Run!
    print(f"  [{system_key}] {'NEUTRAL' if neutral else 'with-bias'} :: running run_backtest...")
    t0 = time.time()
    result = engine_mod.run_backtest(start_date=start, end_date=end, seed=seed)
    elapsed = time.time() - t0
    print(f"  [{system_key}] {'NEUTRAL' if neutral else 'with-bias'} :: done in {elapsed:.1f}s")

    # Yearly breakdown
    yearly: dict[int, dict] = {}
    for t in result.trades:
        y = t.year if hasattr(t, "year") else int(str(t.date)[:4])
        ya = yearly.setdefault(y, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        ya["trades"] += 1
        if t.pnl_sized > 0: ya["wins"] += 1
        elif t.pnl_sized < 0: ya["losses"] += 1
        ya["pnl"] += t.pnl_sized

    # Restore (so the next system gets unpatched code)
    if neutral and hasattr(strat_mod, "_filter28_original_generate_signals"):
        strat_mod.generate_signals = strat_mod._filter28_original_generate_signals
        delattr(strat_mod, "_filter28_original_generate_signals")

    return {
        "system": system_key,
        "neutral": neutral,
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


def _format_pnl(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:+,.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:+,.1f}k"
    return f"${v:+,.0f}"


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
            print(f"  ERROR: unknown system '{s}'. Valid: {sorted(valid)}")
            sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 100)
    print("FILTER #28 — BIAS-DISABLE SWEEP (Path A: monkey-patch)")
    print("=" * 100)
    print(f"  Systems: {systems}")
    print(f"  Date range: {args.start} → {args.end}")
    print(f"  Seed: {args.seed}")
    print(f"  Method: NeutralBiasDict → daily_bias[any_date] = 'neutral'")
    print()

    all_results: list[dict] = []
    for sys_key in systems:
        for neutral in [False, True]:
            try:
                r = _run_one_system(sys_key, args.start, args.end, args.seed, neutral)
                all_results.append(r)
            except Exception as e:
                import traceback
                print(f"  [{sys_key}] {'NEUTRAL' if neutral else 'with-bias'} :: ERROR")
                traceback.print_exc()
                all_results.append({
                    "system": sys_key, "neutral": neutral, "error": str(e),
                })

    # ---- Summary table ----
    print()
    print("=" * 110)
    print("RESULTS — per-system, with-bias vs neutral-bias")
    print("=" * 110)
    print(f"  {'System':<13s} {'Mode':<8s} {'Trades':>8s} {'Wins':>6s} {'WR':>6s} "
          f"{'PF':>6s} {'Total P&L':>14s} {'MaxDD%':>8s}")
    print(f"  {'-'*13} {'-'*8} {'-'*8} {'-'*6} {'-'*6} {'-'*6} {'-'*14} {'-'*8}")
    for r in all_results:
        if "error" in r:
            print(f"  {r['system']:<13s} {'NEUTRAL' if r['neutral'] else 'with-bias':<8s} ERROR: {r['error'][:60]}")
            continue
        # win_rate may come back as fraction (0.65) or percent (65.0); normalize
        wr_pct = r['win_rate'] * 100 if r['win_rate'] <= 1.0 else r['win_rate']
        print(f"  {r['system']:<13s} "
              f"{('NEUTRAL' if r['neutral'] else 'with-bias'):<8s} "
              f"{r['total_trades']:>8,d} "
              f"{r['wins']:>6,d} "
              f"{wr_pct:>5.1f}% "
              f"{r['profit_factor']:>6.2f} "
              f"{_format_pnl(r['total_pnl']):>14s} "
              f"{r['max_drawdown_pct']:>7.1f}%")

    # ---- Delta table ----
    print()
    print("=" * 110)
    print("DELTA — Neutral minus With-bias")
    print("=" * 110)
    print(f"  {'System':<13s} {'ΔTrades':>9s} {'ΔWR':>7s} {'ΔPF':>7s} {'Δ Total P&L':>16s} {'ΔMaxDD%':>9s}")
    print(f"  {'-'*13} {'-'*9} {'-'*7} {'-'*7} {'-'*16} {'-'*9}")
    grand_delta_pnl = 0.0
    for sys_key in systems:
        rows = [r for r in all_results if r.get("system") == sys_key and "error" not in r]
        if len(rows) != 2:
            continue
        with_bias = next(r for r in rows if not r["neutral"])
        neutral = next(r for r in rows if r["neutral"])
        d_trades = neutral["total_trades"] - with_bias["total_trades"]
        wb_wr_pct = with_bias["win_rate"] * 100 if with_bias["win_rate"] <= 1.0 else with_bias["win_rate"]
        nb_wr_pct = neutral["win_rate"] * 100 if neutral["win_rate"] <= 1.0 else neutral["win_rate"]
        d_wr = nb_wr_pct - wb_wr_pct
        d_pf = neutral["profit_factor"] - with_bias["profit_factor"]
        d_pnl = neutral["total_pnl"] - with_bias["total_pnl"]
        d_dd = neutral["max_drawdown_pct"] - with_bias["max_drawdown_pct"]
        grand_delta_pnl += d_pnl
        sign = "+" if d_pnl >= 0 else ""
        print(f"  {sys_key:<13s} {d_trades:>+9,d} {d_wr:>+6.1f}p {d_pf:>+7.2f} "
              f"{_format_pnl(d_pnl):>16s} {d_dd:>+8.1f}p")
    print(f"  {'-'*13} {'-'*9} {'-'*7} {'-'*7} {'-'*16} {'-'*9}")
    print(f"  {'TOTAL':<13s} {' ':>9s} {' ':>7s} {' ':>7s} {_format_pnl(grand_delta_pnl):>16s}")

    # ---- Yearly breakdown ----
    print()
    print("=" * 110)
    print("YEARLY P&L (Neutral minus With-bias) — positive = neutral wins, negative = with-bias wins")
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
                       if r.get("system") == sys_key and not r.get("neutral", False)
                       and "yearly" in r), None)
            nb = next((r for r in all_results
                       if r.get("system") == sys_key and r.get("neutral", False)
                       and "yearly" in r), None)
            if not wb or not nb:
                row += f" {'?':>13s}"
                continue
            wb_pnl = wb["yearly"].get(y, {"pnl": 0.0})["pnl"]
            nb_pnl = nb["yearly"].get(y, {"pnl": 0.0})["pnl"]
            d = nb_pnl - wb_pnl
            if d > 0:
                yearly_neutral_wins[sys_key] += 1
            elif d < 0:
                yearly_neutral_losses[sys_key] += 1
            row += f" {_format_pnl(d):>13s}"
        print(row)
    print(f"  {'-'*6}" + "".join([f" {'-'*13}" for _ in systems]))
    summary_row = f"  {'WIN/LOSS':<6s}"
    for sys_key in systems:
        w = yearly_neutral_wins[sys_key]
        l = yearly_neutral_losses[sys_key]
        summary_row += f" {f'{w}W/{l}L':>13s}"
    print(summary_row)

    # ---- JSON output ----
    json_path = os.path.join(args.output_dir, "filter_28_bias_disable_results.json")
    with open(json_path, "w") as f:
        json.dump({
            "args": vars(args),
            "results": all_results,
        }, f, indent=2, default=str)
    print()
    print(f"  JSON: {json_path}")

    # ---- Bottom line ----
    print()
    print("=" * 110)
    print("BOTTOM LINE — Filter #28")
    print("=" * 110)
    print(f"  Cumulative ΔP&L (NEUTRAL minus WITH-BIAS): {_format_pnl(grand_delta_pnl)}")
    print()
    print("  REMINDER: This is single-seed only. Per project-filter-sweep-workflow,")
    print("  to ship per-system needs:")
    print("    1. Multi-seed runs (slippage RNG variability)")
    print("    2. Yearly slice — confirm wins are not concentrated in vol-spike years")
    print("    3. DD stress — peak-to-trough drawdown comparison")
    print("    4. Parity harness check (live↔BT signal match)")
    print()
    print("  Next: Path B — add bias_mode kwarg to run_backtest in 4 engines for")
    print("  permanent toggle (instead of monkey-patch).")


if __name__ == "__main__":
    main()
