"""DD circuit-breaker on H4 VWAP-mom-L, annual skim, base $1,000.

Circuit-breaker (intra-year, from the running equity peak SINCE last reset/high):
  - drawdown < HALVE_DD (20%)         → full risk
  - HALVE_DD ≤ dd < HALT_DD (35%)     → HALF risk
  - dd ≥ HALT_DD                       → HALT (0 risk) until equity recovers
  - re-arm to full when equity makes a NEW peak
Realized-only, causal: dd measured from equity known BEFORE sizing each trade.

Compares: no-breaker vs breaker, across 1/2/3/5% base risk, with annual skim to $1k.
Reports pocketed $, within-year maxDD, min equity, and skimmed-vs-DD trade-off.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.btc_sweep.sweep_all_families import frame, simulate, gen_vwap_mom

BASE = 1000.0
HALVE_DD = 0.20
HALT_DD = 0.35


def load():
    b = frame("4h")
    tr = simulate(gen_vwap_mom(b, side=1, sl=1.0), b, tp_mult=3.0, horizon=180).reset_index(drop=True)
    tr["ts"] = pd.to_datetime(tr["entry_ts"], utc=True)
    return tr.sort_values("ts").reset_index(drop=True)


def run(tr, base_risk, *, breaker: bool):
    eq = BASE
    cy = int(tr["ts"].iloc[0].year)
    peak = BASE            # running peak since last reset / new-high (breaker ref)
    pocket = 0.0
    path = []
    halted_trades = 0
    rows = []
    for _, t in tr.iterrows():
        yr = t["ts"].year
        if yr != cy:                       # annual skim + reset
            if eq > BASE:
                pocket += eq - BASE
            rows.append((cy, eq))
            eq = BASE; peak = BASE; cy = yr
        # circuit-breaker: risk scaled by current intra-year drawdown from peak
        if breaker:
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd >= HALT_DD:
                risk = 0.0; halted_trades += 1
            elif dd >= HALVE_DD:
                risk = base_risk * 0.5
            else:
                risk = base_risk
        else:
            risk = base_risk
        eq *= (1 + risk * t["net_r"])
        peak = max(peak, eq)               # re-arm on new high
        path.append(eq)
    if eq > BASE:
        pocket += eq - BASE
    rows.append((cy, eq))
    path = np.array(path)
    pk = np.maximum.accumulate(np.concatenate([[BASE], path]))
    # intra-year maxDD: reset peak each year (approximate via full-path here for headline)
    mdd_full = ((pk[1:] - path) / pk[1:]).max()
    return dict(pocket=pocket, min_eq=path.min(), maxdd=mdd_full,
                halted=halted_trades, rows=rows)


def main():
    tr = load()
    print("█"*76)
    print("  H4 VWAP-MOM-L · ANNUAL SKIM + DD CIRCUIT-BREAKER · base $1,000")
    print(f"  breaker: halve @ -{HALVE_DD:.0%} intra-yr DD, HALT @ -{HALT_DD:.0%}, re-arm on new high")
    print("█"*76)
    print(f"\n  {'risk':>5} {'mode':>10} {'pocketed$':>12} {'maxDD':>7} {'min_eq$':>9} {'halted':>7}")
    for risk in (0.01, 0.02, 0.03, 0.05):
        nb = run(tr, risk, breaker=False)
        wb = run(tr, risk, breaker=True)
        print(f"  {int(risk*100):>4}% {'no-breaker':>10} {nb['pocket']:>12,.0f} {nb['maxdd']:>6.0%} {nb['min_eq']:>9,.0f} {'-':>7}")
        print(f"  {int(risk*100):>4}% {'breaker':>10} {wb['pocket']:>12,.0f} {wb['maxdd']:>6.0%} {wb['min_eq']:>9,.0f} {wb['halted']:>7}")
    # detail at 3% breaker
    print("\n═══ 3% WITH BREAKER — year-end equity ═══")
    wb3 = run(tr, 0.03, breaker=True)
    for y, e in wb3["rows"]:
        print(f"    {y}: ${e:,.0f}  ({'skim +$%.0f' % (e-BASE) if e>BASE else 'down $%.0f' % (e-BASE)})")
    print(f"  total pocketed: ${wb3['pocket']:,.0f}   maxDD {wb3['maxdd']:.0%}   halted trades: {wb3['halted']}")


if __name__ == "__main__":
    main()
