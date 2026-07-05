"""Dedicated S1-SHORT mega-sweep — find a short edge to pair with the long S1.

Short-tailored levers vs the original long grid: arbitrary TP R-multiples (shorts
mean-revert, so 1R/1.5R may beat 3R), 3 trend modes (with-downtrend / off / fade-up),
finer fib + confluence. Heavy logging, leaderboard, running-best.
"""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.smc_campaign.framework import MTF, _log, sim_price_bracket, headline, gate
from research.smc_campaign.sweep_engine import fill_setups, OUT
from research.smc_campaign import strategies_fast as SF

GRID = dict(
    rule=["15min", "1h"],
    k=[2, 3, 4],
    ote=[0.5, 0.618, 0.705, 0.786],
    sl_buf=[0.05, 0.10, 0.25],
    tp_r=[1.0, 1.5, 2.0, 3.0],
    sweep_lb=[3, 6, 10],
    need_conf=[3, 4, 5],
    trend_mode=["down", "off", "fade"],
    session=["all", "kz"],
)


def main():
    mtf = MTF(); mtf.tf("4h")
    keys = list(GRID)
    combos = list(itertools.product(*GRID.values()))
    _log(f"=== S1-SHORT sweep: {len(combos):,} configs ===")
    _log("levers: " + ", ".join(f"{k}={len(v)}" for k, v in GRID.items()))
    results = []
    t0 = time.time(); best_pf = 0.0; passes = 0
    for ci, vals in enumerate(combos):
        cfg = dict(zip(keys, vals))
        try:
            setups = SF.price_s1_short(mtf, **cfg)
        except Exception as ex:
            if ci < 3:
                _log(f"  err {cfg}: {ex}")
            continue
        if setups is None or len(setups) < 40:
            if (ci + 1) % 1000 == 0:
                _prog(ci, combos, t0, results, best_pf, passes)
            continue
        sig = fill_setups(setups, mtf.m5, wait_bars=96, slip_atr=0.05)
        if len(sig) < 40:
            if (ci + 1) % 1000 == 0:
                _prog(ci, combos, t0, results, best_pf, passes)
            continue
        tr = sim_price_bracket(sig, mtf.m5, horizon=288)
        if len(tr) < 40:
            if (ci + 1) % 1000 == 0:
                _prog(ci, combos, t0, results, best_pf, passes)
            continue
        h = headline(tr); g = gate(h)
        row = {**cfg, "n": h["n"], "per_yr": round(h["trades_per_year"]),
               "pf": round(h["pf"], 3), "net_r": round(h["net"], 1),
               "mar": round(h["mar"], 2), "wr": round(h["wr"], 3),
               "dd": round(h["dd"], 1), "pos_years": h["pos_years"],
               "avg_rr": round(tr["rr"].mean(), 2), "gate_pass": g["ALL_PASS"]}
        results.append(row)
        if h["n"] >= 100 and h["pf"] > best_pf:
            best_pf = h["pf"]
            _log(f"  ** BEST PF={h['pf']:.3f} n={h['n']} /yr={h['trades_per_year']:.0f} "
                 f"MAR={h['mar']:.2f} pos={h['pos_years']} :: {cfg}")
        if g["ALL_PASS"]:
            passes += 1
            _log(f"  ★ GATE PASS PF={h['pf']:.3f} /yr={h['trades_per_year']:.0f} "
                 f"MAR={h['mar']:.2f} pos={h['pos_years']} :: {cfg}")
        if (ci + 1) % 1000 == 0:
            _prog(ci, combos, t0, results, best_pf, passes)

    res = pd.DataFrame(results)
    path = OUT / "S1_SHORT_leaderboard.csv"
    res.to_csv(path, index=False)
    _log(f"DONE [S1-SHORT] {len(res)} kept, {passes} gate-passes, best PF={best_pf:.3f}, "
         f"{time.time()-t0:.0f}s -> {path}")
    if len(res):
        c = ["rule", "k", "ote", "sl_buf", "tp_r", "sweep_lb", "need_conf", "trend_mode",
             "session", "n", "per_yr", "pf", "mar", "wr", "pos_years"]
        _log("TOP by PF (n>=100):\n" + res[res.n >= 100].sort_values("pf", ascending=False)[c].head(10).to_string(index=False))
        _log("TOP by MAR (n>=100):\n" + res[res.n >= 100].sort_values("mar", ascending=False)[c].head(6).to_string(index=False))
        hi = res[(res.per_yr >= 100) & (res.n >= 100)].sort_values("pf", ascending=False)
        if len(hi):
            _log("BEST with >=100/yr:\n" + hi[c].head(6).to_string(index=False))


def _prog(ci, combos, t0, results, best_pf, passes):
    done = ci + 1; el = time.time() - t0; rate = done / el if el else 0
    eta = (len(combos) - done) / rate if rate else 0
    _log(f"  {done:,}/{len(combos):,} ({100*done/len(combos):.0f}%) {el:.0f}s ETA{eta:.0f}s "
         f"kept={len(results):,} passes={passes} bestPF={best_pf:.3f}")


if __name__ == "__main__":
    main()
