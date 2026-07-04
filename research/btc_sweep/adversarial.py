"""Adversarial battery on the BTC HTF survivors. Hostile checks — designed to KILL.

Candidates (from sweep_htf): long-biased H4 trend/momentum. Tests:
  1. +1-bar entry DELAY  — if edge vanishes when you enter 1 bar late, it was
     riding the signal bar itself (fragile/look-ahead-ish). Robust edge survives.
  2. Walk-forward IS/OOS  — split 2019-2022 (IS) vs 2023-2026 (OOS). OOS PF must
     hold ≥80% of IS PF, else it's curve-fit to the early regime.
  3. Bootstrap P(net<0)   — resample trades 5000× ; probability the edge is <=0.
  4. Buy-and-Hold benchmark — a LONG-ONLY BTC strat is worthless if it doesn't beat
     just holding. Compare strat net-R-scaled return vs B&H over the same window.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.btc_sweep.sweep_htf import (
    load_htf, simulate_htf, headline, gen_momentum, gen_macross,
)

RNG = np.random.default_rng(20260704)


def wf_split(tr: pd.DataFrame):
    t = pd.to_datetime(tr["entry_ts"], utc=True)  # normalise to tz-aware UTC
    cut = pd.Timestamp("2023-01-01", tz="UTC")
    return tr[(t < cut).values], tr[(t >= cut).values]


def bootstrap_p_neg(tr: pd.DataFrame, n=5000) -> float:
    r = tr["net_r"].astype(float).values
    if len(r) < 10:
        return 1.0
    sums = np.array([RNG.choice(r, len(r), replace=True).sum() for _ in range(n)])
    return float((sums <= 0).mean())


def pf(tr):
    r = tr["net_r"].astype(float)
    gw = r[r > 0].sum(); gl = -r[r < 0].sum()
    return gw / gl if gl > 0 else float("inf")


def buy_hold_return(b: pd.DataFrame) -> float:
    """Simple B&H total return over the window."""
    return float(b["close"].iloc[-1] / b["close"].iloc[0] - 1.0)


def test_candidate(name, b, gen_fn, gen_kwargs, tp, horizon):
    print(f"\n{'='*90}\nCANDIDATE: {name}")
    # baseline
    sig = gen_fn(b, **gen_kwargs)
    tr = simulate_htf(sig, b, tp_mult=tp, horizon_bars=horizon)
    h = headline(tr)
    print(f"  baseline           n={h['n']:>4d} PF={h['pf']:.2f} MAR={h['mar']:.2f} net={h['net']:+.1f}R pos={h['pos_years']} /yr={h['trades_per_year']:.0f}")

    # 1. +1 bar delay
    sig_d = sig.copy(); sig_d["entry_index"] = sig_d["entry_index"] + 1
    sig_d = sig_d[sig_d["entry_index"] < len(b) - 2]
    tr_d = simulate_htf(sig_d, b, tp_mult=tp, horizon_bars=horizon)
    h_d = headline(tr_d)
    delay_ok = h_d["pf"] >= 0.85 * h["pf"] if h["pf"] < 900 else True
    print(f"  +1-bar delay       PF={h_d['pf']:.2f} (base {h['pf']:.2f})  {'OK' if delay_ok else 'FRAGILE ✗'}")

    # 2. walk-forward
    is_, oos = wf_split(tr)
    pf_is, pf_oos = pf(is_), pf(oos)
    wf_ok = (len(oos) >= 10) and (pf_oos >= 0.8 * pf_is) and (pf_oos > 1.0)
    print(f"  WF IS/OOS          IS PF={pf_is:.2f} (n={len(is_)}) | OOS PF={pf_oos:.2f} (n={len(oos)})  {'OK' if wf_ok else 'FAIL ✗'}")

    # 3. bootstrap
    p_neg = bootstrap_p_neg(tr)
    boot_ok = p_neg <= 0.05
    print(f"  bootstrap P(net<=0)={p_neg:.3f}  {'OK' if boot_ok else 'FAIL ✗'}")

    # 4. buy-and-hold — strat annualised R vs B&H. A long strat must justify itself.
    bh = buy_hold_return(b)
    print(f"  buy&hold window ret={bh*100:+.0f}%   (strat is long-biased — must add value OVER just holding)")

    verdict = delay_ok and wf_ok and boot_ok
    print(f"  ADVERSARIAL VERDICT: {'SURVIVES core checks' if verdict else 'REJECTED'}")
    return {"name": name, "n": h["n"], "pf": h["pf"], "mar": h["mar"], "pos": h["pos_years"],
            "trades_yr": h["trades_per_year"], "delay_ok": delay_ok, "wf_ok": wf_ok,
            "pf_is": pf_is, "pf_oos": pf_oos, "p_neg": p_neg, "verdict": verdict}


def run():
    bH4 = load_htf("4h")
    bD1 = load_htf("1D")
    res = []
    # Most robust family: H4 momentum long (positive across many thr/sl/tp).
    res.append(test_candidate("H4 mom L thr0.05 sl1.5 tp2.0", bH4, gen_momentum,
                              dict(side=1, thr=0.05, atr_sl=1.5), 2.0, 180))
    res.append(test_candidate("H4 mom L thr0.1 sl1.5 tp3.0", bH4, gen_momentum,
                              dict(side=1, thr=0.1, atr_sl=1.5), 3.0, 180))
    # ★ macross candidates
    res.append(test_candidate("H4 macross L 20/100 sl1.5 tp4.0", bH4, gen_macross,
                              dict(side=1, fast=20, slow=100, atr_sl=1.5), 4.0, 180))
    # D1 momentum long (higher-conviction, lower freq)
    res.append(test_candidate("D1 mom L thr0.2 sl1.5 tp3.0", bD1, gen_momentum,
                              dict(side=1, thr=0.2, atr_sl=1.5), 3.0, 60))

    print(f"\n{'='*90}\nSUMMARY")
    surv = [r for r in res if r["verdict"]]
    for r in res:
        print(f"  {'✓' if r['verdict'] else '✗'} {r['name']:<38s} PF={r['pf']:.2f} OOS={r['pf_oos']:.2f} "
              f"P(neg)={r['p_neg']:.2f} /yr={r['trades_yr']:.0f} pos={r['pos']}")
    print(f"\n{len(surv)} of {len(res)} survive adversarial core checks.")
    pd.DataFrame(res).to_csv(Path(__file__).parent / "adversarial_results.csv", index=False)


if __name__ == "__main__":
    run()
