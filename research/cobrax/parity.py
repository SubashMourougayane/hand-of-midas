#!/usr/bin/env python3
"""Phase 2 — COBRAX streaming↔research parity + known_at audit.

Compares the bt_engine streaming CobraxStrategy (run through the REAL run_engine, BT
mode, with CobraxLimitExecution) against the validated research engine on the SAME
XAU M5 bars, headline rr3 config.

Reported separately (so the port is judged independently of execution-model choices):
  A. ENTRY parity — do the two find the SAME trades? match research fills to streaming
     fills by (fill_ts, side); report exact + ±1-bar match, and entry/stop/tp agreement.
  B. R parity — count / net_R / PF for research(wick), research(close), streaming(close).
     bt_engine is CLOSE-based; research headline is WICK-based → research(close) is the
     apples-to-apples bracket for the streaming engine.
  C. known_at audit — sweep_ts <= mss_ts < fill_ts, fill = touch bar, no peek.

Usage: python3 parity.py [--bars N]   (default 200000 M5 bars ≈ 3yr, fast first pass)
"""
from __future__ import annotations
import sys, argparse
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research/cobrax")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
import cobrax as CB
import uuid
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock
from bt_engine.strategies.cobrax import CobraxStrategy, CobraxLimitExecution
from bt_engine.strategies.cobrax.config import make_cobrax_config


def pf(x):
    x = np.asarray(x); w = x[x > 0].sum(); loss = -x[x < 0].sum()
    return w / loss if loss else float("inf")


def summarize(name, nets):
    nets = np.asarray(nets, float)
    n = len(nets)
    print(f"  {name:<22} n={n:<5d} netR={nets.sum():>8.1f} PF={pf(nets):.3f} "
          f"avgR={nets.mean() if n else 0:+.3f} WR={100*(nets>0).mean() if n else 0:.1f}%")


def run_streaming(m5: pd.DataFrame, cfg):
    provider = MemoryBarProvider(m5, symbol="XAUUSD.ecn", timeframe="M5")
    clock = MemoryClock(provider)
    strat = CobraxStrategy(symbol="XAUUSD.ecn", config=cfg)
    closed = []
    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=CobraxLimitExecution(), broker=None, recorder=None, journal=None,
        on_trade_close=lambda tr, oc: closed.append((tr, oc)),
        max_bars_held=cfg.max_hold_bars,
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    rows = []
    for tr, oc in closed:
        cost_r = float(tr.order.extra.get("cost_r", 0.0))
        rows.append(dict(
            fill_ts=pd.Timestamp(tr.entry_timestamp), side=int(tr.side),
            entry_px=float(tr.entry_price), stop=float(tr.stop_price),
            tp=float(tr.take_profit), gross_r=float(oc.bracket_1r_outcome),
            net_r=float(oc.bracket_1r_outcome) - cost_r,
        ))
    return rows


def entry_parity(research, stream):
    rset = {(pd.Timestamp(t["fill_ts"]), t["side"]) for t in research}
    sset = {(r["fill_ts"], r["side"]) for r in stream}
    exact = rset & sset
    # ±1 bar match (5min) for research fills not exactly matched
    s_by_side = {}
    for r in stream:
        s_by_side.setdefault(r["side"], set()).add(r["fill_ts"])
    near = 0
    for ts, side in (rset - sset):
        cand = s_by_side.get(side, set())
        if (ts - pd.Timedelta("5min")) in cand or (ts + pd.Timedelta("5min")) in cand:
            near += 1
    print(f"  research fills={len(rset)}  streaming fills={len(sset)}")
    print(f"  exact (fill_ts,side) match : {len(exact)} "
          f"({100*len(exact)/max(len(rset),1):.1f}% of research)")
    print(f"  +±1-bar match              : {len(exact)+near} "
          f"({100*(len(exact)+near)/max(len(rset),1):.1f}% of research)")
    print(f"  streaming-only (not in research): {len(sset-rset)}")
    # entry/stop/tp agreement on exact matches
    rmap = {(pd.Timestamp(t['fill_ts']), t['side']): t for t in research}
    smap = {(r['fill_ts'], r['side']): r for r in stream}
    de = ds = dt = 0; ncmp = 0
    for k in exact:
        rt, st = rmap[k], smap[k]
        ncmp += 1
        de += abs(rt['entry_px'] - st['entry_px'])
        ds += abs(rt['stop'] - st['stop'])
        dt += abs(rt['tp'] - st['tp'])
    if ncmp:
        print(f"  on matched: mean|Δentry|={de/ncmp:.4f} |Δstop|={ds/ncmp:.4f} |Δtp|={dt/ncmp:.4f}")


def known_at_audit(research):
    v = 0
    for t in research:
        if not (t["sweep_ts"] <= t["sig_ts"]): v += 1
        if not (t["sig_ts"] < t["fill_ts"]): v += 1
        if not (t["fvg_ts"] <= t["fill_ts"]): v += 1
    print(f"  research known_at violations: {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=200_000)
    args = ap.parse_args()

    print(f"loading XAU M5 (first {args.bars:,} bars)...", flush=True)
    df = CB.load(CB.XAU_M5).iloc[: args.bars].reset_index(drop=True)
    base = CB.base_for("xau")  # headline: session=all, lb3, ote(.62,.79), bias_align, sweep

    print("research rr3 (wick + close brackets)...", flush=True)
    res_wick = CB.run(df, direction="both", cost=0.2, tp_mode="rr", tp_r=3.0,
                      **{k: v for k, v in base.items() if k not in ("tp_mode", "tp_r")})
    res_close = CB.run(df, direction="both", cost=0.2, tp_mode="rr", tp_r=3.0, bracket="close",
                       **{k: v for k, v in base.items() if k not in ("tp_mode", "tp_r")})

    print("streaming CobraxStrategy via run_engine (close-based)...", flush=True)
    cfg = make_cobrax_config(tp_mode="rr", tp_r=3.0, cost_usd=0.2)
    stream = run_streaming(df, cfg)

    print("\n=== A. ENTRY PARITY (port faithfulness) ===")
    entry_parity(res_wick, stream)
    print("\n=== B. R PARITY (count / netR / PF) ===")
    summarize("research WICK", [t["net_r"] for t in res_wick])
    summarize("research CLOSE", [t["net_r"] for t in res_close])
    summarize("streaming CLOSE", [r["net_r"] for r in stream])
    print("\n=== C. known_at audit ===")
    known_at_audit(res_wick)
