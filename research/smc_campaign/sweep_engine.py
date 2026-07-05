"""Shared sweep engine for all 12 SMC strategies.

A strategy provides a `setup_builder(mtf, **params) -> pd.DataFrame` returning columns:
    arm_ts, side(+1/-1), zone_lo, zone_hi, tp_price, sl_price
where the entry is a LIMIT into [zone_lo, zone_hi] (touch fills), TP/SL are prices,
and everything is known at arm_ts. The engine handles: M5 fill within wait window,
close-based bracket sim, headline/gate, live progress, running-best, leaderboard CSV.

Heavy logging throughout. Big-numbers audit is applied downstream on winners.
"""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.smc_campaign.framework import (
    MTF, _log, sim_price_bracket, headline, gate, print_headline, COST_USD,
)

OUT = Path("/Users/subash/SUBASH/GoldDigger/research/smc_campaign/results")
OUT.mkdir(parents=True, exist_ok=True)


def fill_setups(setups: pd.DataFrame, m5: pd.DataFrame, *, wait_bars: int,
                slip_atr: float = 0.05) -> pd.DataFrame:
    """Convert setups -> filled signals. Entry = limit into the zone edge nearest to
    price (long: zone_hi as the OTE-side cap; we use the specific entry_price the
    strategy put in 'entry_price' if present, else zone edge). Adds realistic slip.

    Required setup cols: arm_ts, side, entry_price, tp_price, sl_price.
    """
    m5_ts = m5["timestamp"].dt.tz_localize(None).values  # naive UTC for searchsorted
    m5_lo = m5["low"].values
    m5_hi = m5["high"].values
    m5_cl = m5["close"].values
    m5_atr = m5["atr14_lag"].values
    n5 = len(m5)
    arm_s = pd.to_datetime(setups["arm_ts"])
    if getattr(arm_s.dt, "tz", None) is not None:
        arm_s = arm_s.dt.tz_localize(None)
    arm = arm_s.values.astype("datetime64[ns]")
    starts = np.searchsorted(m5_ts, arm, side="left")
    m5_op = m5["open"].values
    side = setups["side"].to_numpy(dtype=np.float64)
    ent = setups["entry_price"].to_numpy(dtype=np.float64)
    tp = setups["tp_price"].to_numpy(dtype=np.float64)
    sl = setups["sl_price"].to_numpy(dtype=np.float64)
    arm_vals = setups["arm_ts"].values
    if "fill_mode" in setups.columns:
        market = (setups["fill_mode"].values == "market")
    else:
        market = np.zeros(len(setups), dtype=bool)

    m = len(setups)
    starts = starts.astype(np.int64)
    ok = (starts < n5 - 2) & (starts >= 0)
    atr_at = np.where(ok, m5_atr[np.clip(starts, 0, n5 - 1)], np.nan)
    ok &= np.isfinite(atr_at) & (atr_at > 0)

    W = wait_bars
    offs = np.arange(W + 1)
    idxw = np.minimum(starts[:, None] + offs[None, :], n5 - 1)   # [m, W+1]
    lo_w = m5_lo[idxw]; hi_w = m5_hi[idxw]; cl_w = m5_cl[idxw]
    long = side > 0

    # limit touch: long low<=entry ; short high>=entry
    touch = np.where(long[:, None], lo_w <= ent[:, None], hi_w >= ent[:, None])
    # stop break BEFORE touch invalidates: long close<stop ; short close>stop
    brk = np.where(long[:, None], cl_w < sl[:, None], cl_w > sl[:, None])

    def first(mask):
        any_ = mask.any(axis=1)
        return np.where(any_, mask.argmax(axis=1), W + 1)

    t_i = first(touch)
    b_i = first(brk)
    filled_limit = (t_i <= W) & (t_i < b_i)   # touch strictly before stop break (tie=stop wins)

    # market entry: fill at start bar
    fi = np.where(market, starts, starts + t_i)
    valid = ok & (market | filled_limit) & (fi < n5 - 2)

    fi = fi[valid]
    sd = side[valid]
    e = np.where(market[valid], m5_op[np.clip(fi, 0, n5 - 1)], ent[valid])
    t = tp[valid]; stop = sl[valid]
    atr_f = m5_atr[np.clip(starts[valid], 0, n5 - 1)]
    entry = e + slip_atr * atr_f * np.where(sd > 0, 1.0, -1.0)
    risk = np.abs(entry - stop)
    good = risk > 0
    return pd.DataFrame({
        "fill_index": fi[good], "arm_ts": arm_vals[valid][good], "side": sd[good],
        "entry_price": entry[good], "tp_price": t[good], "sl_price": stop[good],
        "risk_units": risk[good],
    })


def run_sweep(strategy_name: str, setup_builder, mtf: MTF, grid: dict, *,
              min_trades: int = 40, log_every: int = 500, base_pf: float = 1.15):
    """Generic grid sweep. setup_builder(mtf, **cfg) -> setups df (may be cached by the
    builder itself per structural key for speed)."""
    keys = list(grid)
    combos = list(itertools.product(*grid.values()))
    _log(f"=== SWEEP [{strategy_name}]: {len(combos):,} configs, {len(keys)} levers ===")
    _log("levers: " + ", ".join(f"{k}={len(v)}" for k, v in grid.items()))
    results = []
    t0 = time.time()
    best_pf = 0.0
    best = None
    passes = 0
    for ci, vals in enumerate(combos):
        cfg = dict(zip(keys, vals))
        try:
            setups = setup_builder(mtf, **cfg)
        except Exception as ex:
            if ci < 3:
                _log(f"  builder error @ {cfg}: {ex}")
            continue
        if setups is None or len(setups) < min_trades:
            if (ci + 1) % log_every == 0:
                _prog(ci, combos, t0, results, best_pf, passes)
            continue
        sig = fill_setups(setups, mtf.m5, wait_bars=cfg.get("wait_bars", 96),
                          slip_atr=cfg.get("slip_atr", 0.05))
        if len(sig) < min_trades:
            if (ci + 1) % log_every == 0:
                _prog(ci, combos, t0, results, best_pf, passes)
            continue
        tr = sim_price_bracket(sig, mtf.m5, horizon=cfg.get("horizon", 288))
        if len(tr) < min_trades:
            if (ci + 1) % log_every == 0:
                _prog(ci, combos, t0, results, best_pf, passes)
            continue
        h = headline(tr)
        g = gate(h)
        pos = int(h["pos_years"].split("/")[0])
        row = {**cfg, "n": h["n"], "per_yr": round(h["trades_per_year"]),
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
            _prog(ci, combos, t0, results, best_pf, passes)

    res = pd.DataFrame(results)
    path = OUT / f"{strategy_name}_leaderboard.csv"
    res.to_csv(path, index=False)
    _log(f"DONE [{strategy_name}] {len(res)} kept, {passes} gate-passes, "
         f"best PF={best_pf:.3f}, {time.time()-t0:.0f}s -> {path}")
    if len(res):
        top = res[res["n"] >= 100].sort_values("pf", ascending=False).head(8)
        _log(f"TOP by PF (n>=100):\n{top.to_string(index=False)}")
        gp = res[(res.gate_pass) & (res.per_yr >= 200)].sort_values("mar", ascending=False).head(6)
        if len(gp):
            _log(f"BEST full-gate INTRADAY by MAR:\n{gp.to_string(index=False)}")
    return res


def _prog(ci, combos, t0, results, best_pf, passes):
    done = ci + 1
    el = time.time() - t0
    rate = done / el if el else 0
    eta = (len(combos) - done) / rate if rate else 0
    _log(f"  {done:,}/{len(combos):,} ({100*done/len(combos):.0f}%) {el:.0f}s ETA{eta:.0f}s "
         f"kept={len(results):,} passes={passes} bestPF={best_pf:.3f}")
