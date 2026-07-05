"""QML Bearish deep sweep — the PDF's designated uptrend-SHORT (pg18).

'In uptrend Market if Market makes LL with MSS then price reverses on QML Zone.'
QML zone = the swing HIGH (head) just before the MSS-down. Short at that premium head,
SL above it, target the downside. This is the book's answer to shorting gold's uptrend.

S5's coarse grid found PF 1.66 @ n=117 — worth a proper hunt. Short-tailored levers:
entry offset into the head zone, TP R-multiples, session, sl_buf, k, rule, h4 context.
"""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.smc_campaign.framework import MTF, _log, sim_price_bracket, headline, gate
from research.smc_campaign.sweep_engine import fill_setups, OUT
from research.smc_campaign import primitives as P
from research.smc_campaign import strategies_fast as SF

_UNIV = {}


def qml_universe(mtf, rule, k):
    """QML bearish head zones. side=-1 only (short in/after uptrend). Carries head price,
    risk scale (head->MSS-break), arm_ts, ny_hr, h4up."""
    key = (rule, k)
    if key in _UNIV:
        return _UNIV[key]
    tfm = SF._TFM[rule]; df = mtf.tf(rule)
    sw = P.find_swings(df, k=k, tf_min=tfm)
    ev = P.structure_events(df, sw, tf_min=tfm)
    mss = [e for e in ev if e.kind == "CHOCH" and e.dir < 0]  # down MSS
    highs = [s for s in sw if s.kind == "H"]
    rows = []
    for m in mss:
        prev = [s for s in highs if s.confirm_ts <= m.confirm_ts]
        if not prev:
            continue
        head = prev[-1]
        rref = abs(head.price - m.level)
        if rref <= 0:
            continue
        rows.append((m.confirm_ts, head.price, rref))
    u = pd.DataFrame(rows, columns=["arm_ts", "head", "rref"])
    if len(u):
        u["h4up"] = SF._h4_up_at(mtf, u["arm_ts"])
        u["ny_hr"] = SF._ny_hour(u["arm_ts"])
    _UNIV[key] = u
    return u


def qml_price(mtf, *, rule, k, entry_off, sl_buf, tp_r, session, ctx):
    """entry_off: fraction of rref BELOW the head where the short limit sits (0=at head).
    ctx: 'up'(only when h4 up = true QML uptrend-short), 'off'(any), 'down'."""
    u = qml_universe(mtf, rule, k)
    if len(u) == 0:
        return u
    m = pd.Series(True, index=u.index)
    if ctx == "up":
        m &= u["h4up"] == 1
    elif ctx == "down":
        m &= u["h4up"] == 0
    if session == "kz":
        m &= (u["ny_hr"] >= 2) & (u["ny_hr"] <= 11)
    s = u[m]
    if len(s) == 0:
        return s
    head = s["head"].values; rref = s["rref"].values
    entry = head - entry_off * rref            # limit slightly below head (into premium)
    ssl = head                                  # SL above the head
    sl = ssl + sl_buf * rref
    risk = np.abs(entry - sl)
    tp = entry - tp_r * risk
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": np.full(len(s), -1.0),
                         "entry_price": entry, "tp_price": tp, "sl_price": sl})


GRID = dict(
    rule=["15min", "1h"], k=[2, 3, 4],
    entry_off=[0.0, 0.1, 0.25],
    sl_buf=[0.05, 0.1, 0.25],
    tp_r=[1.0, 1.5, 2.0, 3.0],
    session=["all", "kz"],
    ctx=["up", "off", "down"],
)


def main():
    mtf = MTF(); mtf.tf("4h")
    keys = list(GRID); combos = list(itertools.product(*GRID.values()))
    _log(f"=== QML-BEARISH sweep: {len(combos):,} configs ===")
    results = []; t0 = time.time(); best_pf = 0.0; passes = 0
    for ci, vals in enumerate(combos):
        cfg = dict(zip(keys, vals))
        setups = qml_price(mtf, **cfg)
        if setups is None or len(setups) < 40:
            continue
        sig = fill_setups(setups, mtf.m5, wait_bars=96, slip_atr=0.05)
        if len(sig) < 40:
            continue
        tr = sim_price_bracket(sig, mtf.m5, horizon=288)
        if len(tr) < 40:
            continue
        h = headline(tr); g = gate(h)
        results.append({**cfg, "n": h["n"], "per_yr": round(h["trades_per_year"]),
                        "pf": round(h["pf"], 3), "mar": round(h["mar"], 2),
                        "wr": round(h["wr"], 3), "pos_years": h["pos_years"],
                        "gate_pass": g["ALL_PASS"]})
        if h["n"] >= 100 and h["pf"] > best_pf:
            best_pf = h["pf"]
            _log(f"  ** BEST PF={h['pf']:.3f} n={h['n']} /yr={h['trades_per_year']:.0f} "
                 f"MAR={h['mar']:.2f} pos={h['pos_years']} :: {cfg}")
        if g["ALL_PASS"]:
            passes += 1
            _log(f"  ★ GATE PASS :: {cfg} PF={h['pf']:.3f} /yr={h['trades_per_year']:.0f} MAR={h['mar']:.2f}")
    res = pd.DataFrame(results)
    res.to_csv(OUT / "QML_SHORT_leaderboard.csv", index=False)
    _log(f"DONE [QML-SHORT] {len(res)} kept, {passes} gate-passes, best PF={best_pf:.3f}, {time.time()-t0:.0f}s")
    if len(res):
        c = ["rule", "k", "entry_off", "sl_buf", "tp_r", "session", "ctx", "n", "per_yr", "pf", "mar", "wr", "pos_years"]
        _log("TOP by PF (n>=100):\n" + res[res.n >= 100].sort_values("pf", ascending=False)[c].head(10).to_string(index=False))
        _log("TOP by MAR (n>=100):\n" + res[res.n >= 100].sort_values("mar", ascending=False)[c].head(6).to_string(index=False))


if __name__ == "__main__":
    main()
