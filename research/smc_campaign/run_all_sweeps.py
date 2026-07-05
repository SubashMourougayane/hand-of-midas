"""Master sweep launcher (FAST) — universe-cached price_* fns, heavy logging.

Usage: python3 run_all_sweeps.py S1 S2 ...   (or 'all')
Each strategy's structural universe builds ONCE per (rule,k); configs only re-filter
+ re-price + fill + sim (all vectorised). Leaderboards -> results/<Sx>_leaderboard.csv.
"""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.smc_campaign.framework import (
    MTF, _log, sim_price_bracket, headline, gate,
)
from research.smc_campaign.sweep_engine import fill_setups, OUT
from research.smc_campaign import strategies_fast as SF
import pandas as pd


# (price_fn, grid). price_fn(mtf, **cfg) -> setups df.
GRIDS = {
    "S1": (SF.price_s1, dict(
        rule=["15min", "1h"], k=[2, 3, 4], ote=[0.5, 0.618, 0.705, 0.786],
        sl_buf=[0.05, 0.10, 0.25], tp_mode=["2R", "3R"], sweep_lb=[3, 6, 10],
        need_conf=[3, 4, 5], use_idm=[0, 1], h4_trend=[0, 1], session=["all", "kz"],
        sides=[(1,), (-1,), (1, -1)],
    )),
    "S2": (SF.price_s2, dict(
        rule=["15min", "1h"], k=[2, 3, 4], tp_mode=["2R", "3R", "swing"],
        sl_buf=[0.05, 0.10, 0.25, 0.5], h4_trend=[0, 1], sides=[(1,), (-1,), (1, -1)],
    )),
    "S3": (SF.price_s3, dict(
        rule=["15min", "1h"], k=[2, 3, 4], sl_buf=[0.05, 0.10, 0.25, 0.5],
        tp_mode=["2R", "3R"], h4_trend=[0, 1], sides=[(1,), (-1,), (1, -1)],
    )),
    "S4": (SF.price_s4, dict(
        rule=["15min", "1h"], k=[2, 3, 4], block=["breaker", "mitigation"],
        sl_buf=[0.05, 0.15, 0.3, 0.5], tp_mode=["2R", "3R"], h4_trend=[0, 1],
        sides=[(1,), (-1,), (1, -1)],
    )),
    "S5": (SF.price_s5, dict(
        rule=["15min", "1h"], k=[2, 3, 4], sl_buf=[0.1, 0.25, 0.5, 1.0],
        tp_mode=["2R", "3R"], h4_trend=[0, 1], sides=[(1,), (-1,), (1, -1)],
    )),
    "S6": (SF.price_s6, dict(
        sl_atr=[0.5, 1.0, 1.5, 2.0], tp_mode=["2R", "3R"], sides=[(1,), (-1,), (1, -1)],
    )),
    "S7": (SF.price_s7, dict(
        k=[2, 3, 4], sl_buf=[0.1, 0.25, 0.5], tp_mode=["2R", "3R"],
        sides=[(1,), (-1,), (1, -1)],
    )),
    "S8": (SF.price_s8, dict(
        k=[2, 3, 4], sl_buf=[0.1, 0.25, 0.5], tp_mode=["2R", "3R"],
        sides=[(1,), (-1,), (1, -1)],
    )),
    "S10": (SF.price_s10, dict(
        rule=["15min", "1h"], k=[2, 3, 4], ob_level=[65, 70, 75], os_level=[25, 30, 35],
        sl_buf=[0.1, 0.25, 0.5], tp_mode=["2R", "3R"], sides=[(1,), (-1,), (1, -1)],
    )),
    "S11": (SF.price_s11, dict(
        rule=["15min", "1h"], k=[2, 3, 4], fib=[0.5, 0.618, 0.705, 0.786],
        sl_buf=[0.05, 0.1, 0.25], tp_mode=["2R", "3R"], ema_confirm=[0, 1],
        sides=[(1,), (-1,), (1, -1)],
    )),
    "S12": (SF.price_s12, dict(
        rule=["15min", "1h"], k=[2, 3, 4], vol_mult=[1.2, 1.5, 2.0],
        use_rsi=[0, 1], h4_trend=[0, 1], sl_buf=[0.1, 0.25, 0.5],
        tp_mode=["2R", "3R"], sides=[(1,), (-1,), (1, -1)],
    )),
}

# per-strategy extra sim params (fixed, not swept)
WAIT = {"default": 96}
HORIZON = {"S6": 1152, "S8": 576, "default": 288}


def run_one(name, price_fn, grid, mtf, min_trades=40, log_every=1000):
    keys = list(grid)
    combos = list(itertools.product(*grid.values()))
    _log(f"\n########## {name}: {len(combos):,} configs ##########")
    _log("levers: " + ", ".join(f"{k}={len(v)}" for k, v in grid.items()))
    horizon = HORIZON.get(name, HORIZON["default"])
    results = []
    t0 = time.time()
    best_pf = 0.0; best = None; passes = 0
    for ci, vals in enumerate(combos):
        cfg = dict(zip(keys, vals))
        try:
            setups = price_fn(mtf, **cfg)
        except Exception as ex:
            if ci < 3:
                _log(f"  err @ {cfg}: {ex}")
            continue
        if setups is None or len(setups) < min_trades:
            if (ci + 1) % log_every == 0:
                _prog(name, ci, combos, t0, results, best_pf, passes)
            continue
        sig = fill_setups(setups, mtf.m5, wait_bars=96, slip_atr=0.05)
        if len(sig) < min_trades:
            if (ci + 1) % log_every == 0:
                _prog(name, ci, combos, t0, results, best_pf, passes)
            continue
        tr = sim_price_bracket(sig, mtf.m5, horizon=horizon)
        if len(tr) < min_trades:
            if (ci + 1) % log_every == 0:
                _prog(name, ci, combos, t0, results, best_pf, passes)
            continue
        h = headline(tr); g = gate(h)
        row = {**{k: (v if not isinstance(v, tuple) else str(v)) for k, v in cfg.items()},
               "n": h["n"], "per_yr": round(h["trades_per_year"]),
               "pf": round(h["pf"], 3), "net_r": round(h["net"], 1),
               "mar": round(h["mar"], 2), "wr": round(h["wr"], 3),
               "dd": round(h["dd"], 1), "pos_years": h["pos_years"],
               "avg_rr": round(tr["rr"].mean(), 2), "gate_pass": g["ALL_PASS"]}
        results.append(row)
        if h["n"] >= 100 and h["pf"] > best_pf:
            best_pf = h["pf"]; best = row
            _log(f"  ** BEST PF={h['pf']:.3f} n={h['n']} /yr={h['trades_per_year']:.0f} "
                 f"MAR={h['mar']:.2f} pos={h['pos_years']} :: {cfg}")
        if g["ALL_PASS"]:
            passes += 1
            _log(f"  ★ GATE PASS PF={h['pf']:.3f} /yr={h['trades_per_year']:.0f} "
                 f"MAR={h['mar']:.2f} pos={h['pos_years']} :: {cfg}")
        if (ci + 1) % log_every == 0:
            _prog(name, ci, combos, t0, results, best_pf, passes)

    res = pd.DataFrame(results)
    path = OUT / f"{name}_leaderboard.csv"
    res.to_csv(path, index=False)
    _log(f"DONE [{name}] {len(res)} kept, {passes} gate-passes, best PF={best_pf:.3f}, "
         f"{time.time()-t0:.0f}s -> {path}")
    if len(res):
        cols = [c for c in res.columns]
        top = res[res["n"] >= 100].sort_values("pf", ascending=False).head(6)
        _log(f"TOP by PF (n>=100):\n{top.to_string(index=False)}")
        gp = res[(res.gate_pass) & (res.per_yr >= 200)].sort_values("mar", ascending=False).head(5)
        if len(gp):
            _log(f"BEST full-gate INTRADAY by MAR:\n{gp.to_string(index=False)}")
    return res


def _prog(name, ci, combos, t0, results, best_pf, passes):
    done = ci + 1; el = time.time() - t0; rate = done / el if el else 0
    eta = (len(combos) - done) / rate if rate else 0
    _log(f"  [{name}] {done:,}/{len(combos):,} ({100*done/len(combos):.0f}%) {el:.0f}s "
         f"ETA{eta:.0f}s kept={len(results):,} passes={passes} bestPF={best_pf:.3f}")


def main():
    which = sys.argv[1:] or ["all"]
    if which == ["all"]:
        which = list(GRIDS)
    mtf = MTF()
    mtf.tf("4h")
    tot = sum(1 for _ in ())
    for name in which:
        if name not in GRIDS:
            _log(f"unknown {name}"); continue
        fn, grid = GRIDS[name]
        run_one(name, fn, grid, mtf)


if __name__ == "__main__":
    main()
