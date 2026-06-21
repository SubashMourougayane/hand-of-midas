"""017 — bearishharry strategy on Brent oil (BCO_USD).

Same 24-config grid as Sprint 4 (014). Walk-forward + safeguards.
Then a yearly P&L breakdown for the top survivor so we can compare
to Gold/forex apples-to-apples.
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from itertools import product
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.data_forex import ForexBundle, get_forex
from Labs.shared.runner_forex import run_forex_strategy
from Labs.shared.safeguards import lookahead_audit, random_baseline

_p = Path(__file__).resolve().parent / "013_bearishharry_forex.py"
_spec = importlib.util.spec_from_file_location("bh", _p)
_m = importlib.util.module_from_spec(_spec)
sys.modules["bh"] = _m
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
    return [BearishHarryConfig(**dict(zip(keys, vals))) for vals in product(*GRID.values())]


def _config_label(cfg: BearishHarryConfig) -> str:
    return (
        f"swp{cfg.sweep_lookback_hours}_"
        f"{cfg.h1_confirmation[:3]}_"
        f"{cfg.m15_entry[:5]}_"
        f"rr{cfg.rr}"
    )


def _slice(b: ForexBundle, start: pd.Timestamp, end: pd.Timestamp) -> ForexBundle:
    return ForexBundle(
        symbol=b.symbol,
        d1=b.d1.loc[start:end],
        h4=b.h4.loc[start:end],
        h1=b.h1.loc[start:end],
        m15=b.m15.loc[start:end],
    )


def main() -> None:
    out_dir = _REPO_ROOT / "Labs" / "results"
    out_dir.mkdir(exist_ok=True, parents=True)
    bundle = get_forex("BCO_USD")
    print()
    print("=" * 78)
    print("  Sprint 4 extension — bearishharry on BCO_USD (Brent oil)")
    print("=" * 78)
    print(f"  Dev window: {bundle.m15.index[0]}  →  {bundle.m15.index[-1]}")
    print(f"  M15 bars: {len(bundle.m15):,}  H1: {len(bundle.h1):,}  D1: {len(bundle.d1)}")
    print()

    # --- Phase 1: dev grid ---
    configs = _all_configs()
    rows = []
    for cfg in configs:
        fn = lambda d1_, h4_, h1_, m15_, c=cfg: generate_signals(d1_, h4_, h1_, m15_, c)
        r = run_forex_strategy(fn, bundle, config_label=_config_label(cfg))
        rows.append({
            "symbol": "BCO_USD",
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

    survivors = [r for r in rows if r["pf"] >= 1.10 and r["trades"] >= 30]
    print(f"  Dev configs (24): {len(survivors)} pass PF≥1.10 + n≥30")
    for s in sorted(survivors, key=lambda x: -x["pf"]):
        print(f"    {s['sweep_lookback_hours']:>3}h {s['h1_confirmation']:<16} "
              f"{s['m15_entry']:<13} rr={s['rr']}  PF={s['pf']:.3f}  "
              f"n={s['trades']:>3}  P&L=${s['pnl']:>10,.2f}  DD={s['max_dd_pct']:.2f}%")

    # --- Phase 2: walk-forward ---
    train_start = pd.Timestamp("2019-09-26")
    train_end   = pd.Timestamp("2022-12-31 23:59:59")
    val_start   = pd.Timestamp("2023-01-01")
    val_end     = pd.Timestamp("2023-12-31 23:59:59")
    train_b = _slice(bundle, train_start, train_end)
    val_b   = _slice(bundle, val_start,   val_end)

    wf_rows = []
    for s in survivors:
        cfg = BearishHarryConfig(
            sweep_lookback_hours=s["sweep_lookback_hours"],
            h1_confirmation=s["h1_confirmation"],
            m15_entry=s["m15_entry"],
            rr=s["rr"],
        )
        fn = lambda d1_, h4_, h1_, m15_, c=cfg: generate_signals(d1_, h4_, h1_, m15_, c)
        rt = run_forex_strategy(fn, train_b)
        rv = run_forex_strategy(fn, val_b)
        wf_rows.append({
            "config": _config_label(cfg),
            "train_pf": rt.profit_factor, "train_trades": rt.total_trades, "train_pnl": rt.total_pnl,
            "val_pf":   rv.profit_factor, "val_trades":   rv.total_trades, "val_pnl":   rv.total_pnl,
        })

    wf_pass = [w for w in wf_rows if w["train_pf"] >= 1.10 and w["val_pf"] >= 1.10]
    print()
    print(f"  Walk-forward: {len(wf_pass)}/{len(wf_rows)} survivors pass BOTH train+val PF≥1.10")
    for w in sorted(wf_pass, key=lambda x: -x["val_pf"]):
        print(f"    ✓ {w['config']:<32}  Train PF={w['train_pf']:.2f} (n={w['train_trades']:>3})  "
              f"Val PF={w['val_pf']:.2f} (n={w['val_trades']:>3})")
    for w in sorted([x for x in wf_rows if x not in wf_pass], key=lambda x: -x["val_pf"]):
        print(f"    ✗ {w['config']:<32}  Train PF={w['train_pf']:.2f} (n={w['train_trades']:>3})  "
              f"Val PF={w['val_pf']:.2f} (n={w['val_trades']:>3})")

    # --- Phase 3: safeguards on walk-forward survivors ---
    if not wf_pass:
        print("\nNo walk-forward survivors — Sprint 4 Oil verdict: NO EDGE.")
        return

    print()
    print(f"  Running safeguards on {len(wf_pass)} walk-forward survivors...")
    for w in wf_pass:
        # Map back to cfg
        cfg = next(
            BearishHarryConfig(
                sweep_lookback_hours=s["sweep_lookback_hours"],
                h1_confirmation=s["h1_confirmation"],
                m15_entry=s["m15_entry"],
                rr=s["rr"],
            )
            for s in survivors
            if _config_label(BearishHarryConfig(
                sweep_lookback_hours=s["sweep_lookback_hours"],
                h1_confirmation=s["h1_confirmation"],
                m15_entry=s["m15_entry"],
                rr=s["rr"],
            )) == w["config"]
        )
        fn3 = lambda d1_, h1_, m15_, c=cfg, h4=bundle.h4: generate_signals(d1_, h4, h1_, m15_, c)
        la = lookahead_audit(fn3, (bundle.d1, bundle.h1, bundle.m15))
        rb = random_baseline((bundle.d1, bundle.h1, bundle.m15), n_trades=2000)
        la_label = "PASS" if la.passed else "FAIL"
        rb_label = "PASS" if rb.passed else "FAIL"
        print(f"    {w['config']:<32}  lookahead={la_label}  random_baseline={rb_label}")

    # --- Phase 4: per-year breakdown for top val-PF survivor ---
    top = max(wf_pass, key=lambda x: x["val_pf"])
    print()
    print("=" * 78)
    print(f"  Per-year detail for top BCO_USD survivor: {top['config']}")
    print("=" * 78)
    cfg = next(
        BearishHarryConfig(
            sweep_lookback_hours=s["sweep_lookback_hours"],
            h1_confirmation=s["h1_confirmation"],
            m15_entry=s["m15_entry"],
            rr=s["rr"],
        )
        for s in survivors
        if _config_label(BearishHarryConfig(
            sweep_lookback_hours=s["sweep_lookback_hours"],
            h1_confirmation=s["h1_confirmation"],
            m15_entry=s["m15_entry"],
            rr=s["rr"],
        )) == top["config"]
    )
    fn = lambda d1_, h4_, h1_, m15_, c=cfg: generate_signals(d1_, h4_, h1_, m15_, c)
    r = run_forex_strategy(fn, bundle)
    print(f"  {'Year':<6} {'Trades':<8} {'Wins':<6} {'WR%':<8} {'P&L':>14} {'DD%':>8} {'EndEquity':>12}")
    print("  " + "─" * 70)
    pair_pnl = 0.0
    pair_trades = 0
    for y in sorted(r.by_year.keys()):
        s = r.by_year[y]
        wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0.0
        print(f"  {y:<6} {s['trades']:<8} {s['wins']:<6} {wr:<8.1f} ${s['pnl']:>11,.2f}  "
              f"{s['dd_pct']:>7.2f}  ${s['ending_equity']:>10,.2f}")
        pair_pnl += s["pnl"]
        pair_trades += s["trades"]
    years = len(r.by_year)
    print("  " + "─" * 70)
    print(f"  TOTAL  {pair_trades:<8}        {'':<8} ${pair_pnl:>11,.2f}  "
          f"({years}y → ${pair_pnl/years:,.2f}/yr)  PF={r.profit_factor:.2f}")

    # Save dev grid CSV
    out_path = out_dir / "sprint_4_oil.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n  Wrote {out_path}")


if __name__ == "__main__":
    main()
