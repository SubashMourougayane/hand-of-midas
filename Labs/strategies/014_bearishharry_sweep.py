"""014 — bearishharry sweep across 6 pairs × parameter grid.

Runs the strategy from #013 with every combination of:
    sweep_lookback_hours ∈ {12, 24}                       (2)
    h1_confirmation      ∈ {rejection_wick, engulf}       (2)
    m15_entry            ∈ {engulf_close, ob_retest}      (2)   (currently identical impl)
    rr                   ∈ {1.5, 2.0, 3.0}                (3)
    symbol               ∈ EUR/GBP/USD_JPY/AUD/USD_CAD/XAU (6)

→ 144 backtests on the development window (2019-09-26..2023-12-31).

Then walk-forward: same 144 with Train (2019-09-26..2022-12-31) +
Validate (2023-01-01..2023-12-31) split. Configs whose Train PF passes
must also pass on Validate to be considered.

Output:
    Labs/results/sprint_4_dev.csv       — all 144 dev runs
    Labs/results/sprint_4_walkforward.csv — train/validate per config
    Labs/results/sprint_4.md            — summary + recommendations
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from dataclasses import asdict
from itertools import product
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.data_forex import SYMBOLS, ForexBundle, ForexPhase, get_forex
from Labs.shared.runner_forex import run_forex_strategy
from Labs.shared.safeguards import lookahead_audit, random_baseline

# Load #013 strategy module by importlib so we don't have to package it
_p = Path(__file__).resolve().parent / "013_bearishharry_forex.py"
_spec = importlib.util.spec_from_file_location("bh_strategy", _p)
_m = importlib.util.module_from_spec(_spec)
sys.modules["bh_strategy"] = _m
_spec.loader.exec_module(_m)
generate_signals = _m.generate_signals
BearishHarryConfig = _m.BearishHarryConfig


GRID = {
    "sweep_lookback_hours": [12, 24],
    "h1_confirmation":      ["rejection_wick", "engulf"],
    "m15_entry":            ["engulf_close", "ob_retest"],
    "rr":                   [1.5, 2.0, 3.0],
}


def _all_configs() -> list[BearishHarryConfig]:
    keys = list(GRID.keys())
    return [
        BearishHarryConfig(**dict(zip(keys, vals)))
        for vals in product(*GRID.values())
    ]


def _config_label(cfg: BearishHarryConfig) -> str:
    return (
        f"swp{cfg.sweep_lookback_hours}_"
        f"{cfg.h1_confirmation[:3]}_"
        f"{cfg.m15_entry[:5]}_"
        f"rr{cfg.rr}"
    )


def _slice_bundle(b: ForexBundle, start: pd.Timestamp, end: pd.Timestamp) -> ForexBundle:
    """Cut a bundle to a time window. Used for walk-forward."""
    return ForexBundle(
        symbol=b.symbol,
        d1=b.d1.loc[start:end],
        h4=b.h4.loc[start:end],
        h1=b.h1.loc[start:end],
        m15=b.m15.loc[start:end],
    )


def run_dev_grid() -> list[dict]:
    rows = []
    bundles = {sym: get_forex(sym) for sym in SYMBOLS}
    configs = _all_configs()
    print(f"Sprint 4 dev grid: {len(configs)} configs × {len(SYMBOLS)} pairs = {len(configs) * len(SYMBOLS)} runs")
    print()

    for sym in SYMBOLS:
        b = bundles[sym]
        for cfg in configs:
            fn = lambda d1_, h4_, h1_, m15_, c=cfg: generate_signals(d1_, h4_, h1_, m15_, c)
            r = run_forex_strategy(fn, b, config_label=_config_label(cfg))
            rows.append({
                "symbol": sym,
                "sweep_lookback_hours": cfg.sweep_lookback_hours,
                "h1_confirmation": cfg.h1_confirmation,
                "m15_entry": cfg.m15_entry,
                "rr": cfg.rr,
                "trades": r.total_trades,
                "wins": r.wins,
                "losses": r.losses,
                "win_rate": round(r.win_rate, 4),
                "pf": r.profit_factor,
                "pnl": r.total_pnl,
                "max_dd_pct": r.max_dd_pct_yearly_worst,
            })
        # progress per pair
        n_pos = sum(1 for r in rows if r["symbol"] == sym and r["pf"] >= 1.10 and r["trades"] >= 30)
        print(f"  {sym}: {n_pos}/{len(configs)} configs PF≥1.10 with ≥30 trades")
    return rows


def run_walk_forward(top_dev_rows: list[dict]) -> list[dict]:
    """Walk-forward only the configs that passed dev: PF ≥ 1.10 AND trades ≥ 30."""
    train_start = pd.Timestamp("2019-09-26")
    train_end   = pd.Timestamp("2022-12-31 23:59:59")
    val_start   = pd.Timestamp("2023-01-01")
    val_end     = pd.Timestamp("2023-12-31 23:59:59")

    rows: list[dict] = []
    for dev_row in top_dev_rows:
        sym = dev_row["symbol"]
        cfg = BearishHarryConfig(
            sweep_lookback_hours=dev_row["sweep_lookback_hours"],
            h1_confirmation=dev_row["h1_confirmation"],
            m15_entry=dev_row["m15_entry"],
            rr=dev_row["rr"],
        )
        full = get_forex(sym)
        train_b = _slice_bundle(full, train_start, train_end)
        val_b   = _slice_bundle(full, val_start,   val_end)
        fn = lambda d1_, h4_, h1_, m15_, c=cfg: generate_signals(d1_, h4_, h1_, m15_, c)
        rt = run_forex_strategy(fn, train_b)
        rv = run_forex_strategy(fn, val_b)
        rows.append({
            "symbol": sym,
            "config": _config_label(cfg),
            "train_trades": rt.total_trades,
            "train_pf": rt.profit_factor,
            "train_pnl": rt.total_pnl,
            "val_trades": rv.total_trades,
            "val_pf": rv.profit_factor,
            "val_pnl": rv.total_pnl,
            "train_wr": round(rt.win_rate, 3),
            "val_wr":   round(rv.win_rate, 3),
        })
    return rows


def safeguards_for(top_rows: list[dict]) -> list[dict]:
    """Run lookahead + random baseline on each survivor on its full-bundle window."""
    rows = []
    for tr in top_rows:
        sym = tr["symbol"]
        cfg = BearishHarryConfig(
            sweep_lookback_hours=tr["sweep_lookback_hours"],
            h1_confirmation=tr["h1_confirmation"],
            m15_entry=tr["m15_entry"],
            rr=tr["rr"],
        )
        b = get_forex(sym)
        fn = lambda d1_, h4_, h1_, m15_, c=cfg: generate_signals(d1_, h4_, h1_, m15_, c)
        # Lookahead audit needs the (d1, h1, m3) signature. Wrap.
        # data_forex bundle is (d1, h4, h1, m15); for Labs.shared.safeguards
        # which expects (d1, h1, m3), we pass (d1, h1, m15) and bake h4 into the closure.
        h4_const = b.h4
        fn3 = lambda d1_, h1_, m15_: generate_signals(d1_, h4_const, h1_, m15_, cfg)
        la = lookahead_audit(fn3, (b.d1, b.h1, b.m15))
        # random_baseline expects (d1, h1, m3) tuple too
        rb = random_baseline((b.d1, b.h1, b.m15), n_trades=2000)
        rows.append({
            "symbol": sym,
            "config": _config_label(cfg),
            "lookahead_pass": la.passed,
            "lookahead_mismatches": la.mismatches,
            "random_pnl_per_unit": rb.random_pnl,
            "random_pass": rb.passed,
        })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("# no rows\n")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    out_dir = _REPO_ROOT / "Labs" / "results"
    out_dir.mkdir(exist_ok=True, parents=True)

    print("=" * 72)
    print("Sprint 4 — bearishharry multi-TF strategy survey")
    print("=" * 72)
    print()

    # --- Phase 1: full dev grid ---
    dev_rows = run_dev_grid()
    write_csv(out_dir / "sprint_4_dev.csv", dev_rows)
    print(f"\nWrote {out_dir/'sprint_4_dev.csv'} ({len(dev_rows)} rows)")

    # --- Phase 2: pick survivors and walk-forward ---
    survivors = [r for r in dev_rows if r["pf"] >= 1.10 and r["trades"] >= 30]
    print(f"\n{len(survivors)} dev survivors (PF≥1.10 AND trades≥30):")
    for s in sorted(survivors, key=lambda x: -x["pf"]):
        print(f"  {s['symbol']:<8} {s['sweep_lookback_hours']:>3}h "
              f"{s['h1_confirmation']:<16} {s['m15_entry']:<13} "
              f"rr={s['rr']}  PF={s['pf']:.3f}  n={s['trades']:>3}  "
              f"P&L=${s['pnl']:>8,.2f}  DD={s['max_dd_pct']:.2f}%")

    if not survivors:
        print("\nNo dev survivors. Skipping walk-forward.")
        return

    # --- Phase 3: walk-forward ---
    print(f"\nRunning walk-forward on {len(survivors)} survivors...")
    wf_rows = run_walk_forward(survivors)
    write_csv(out_dir / "sprint_4_walkforward.csv", wf_rows)
    print(f"Wrote {out_dir/'sprint_4_walkforward.csv'}")

    print("\nWalk-forward results (config must pass BOTH train and val PF≥1.10):")
    for w in sorted(wf_rows, key=lambda x: -x["val_pf"]):
        verdict = "✓" if (w["train_pf"] >= 1.10 and w["val_pf"] >= 1.10) else "✗"
        print(f"  {verdict} {w['symbol']:<8} {w['config']:<32}  "
              f"Train PF={w['train_pf']:.2f} (n={w['train_trades']:>3})  "
              f"Val PF={w['val_pf']:.2f} (n={w['val_trades']:>3})")

    # --- Phase 4: safeguards on walk-forward survivors ---
    real_survivors = [
        wf_rows[i] for i, w in enumerate(wf_rows)
        if w["train_pf"] >= 1.10 and w["val_pf"] >= 1.10
    ]
    if not real_survivors:
        print("\nNo walk-forward survivors. Sprint 4 verdict: NO EDGE FOUND.")
        return

    # Map walk-forward survivors back to their full-grid rows for safeguards
    rs_meta = []
    for w in real_survivors:
        for d in survivors:
            if d["symbol"] == w["symbol"] and _config_label(BearishHarryConfig(
                sweep_lookback_hours=d["sweep_lookback_hours"],
                h1_confirmation=d["h1_confirmation"],
                m15_entry=d["m15_entry"],
                rr=d["rr"],
            )) == w["config"]:
                rs_meta.append(d)
                break

    print(f"\nRunning safeguards on {len(rs_meta)} walk-forward survivors...")
    sg_rows = safeguards_for(rs_meta)
    write_csv(out_dir / "sprint_4_safeguards.csv", sg_rows)
    for sg in sg_rows:
        la = "PASS" if sg["lookahead_pass"] else "FAIL"
        rb = "PASS" if sg["random_pass"] else "FAIL"
        print(f"  {sg['symbol']:<8} {sg['config']:<32}  "
              f"lookahead={la}  random_baseline={rb}")


if __name__ == "__main__":
    main()
