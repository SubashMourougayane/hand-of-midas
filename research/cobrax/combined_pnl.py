#!/usr/bin/env python3
"""Combined $ — A+D (production, strict) alone vs A+D + COBRAX, through ONE real
EquitySizer on the same 20yr OANDA XAU. Answers: does adding COBRAX make more money,
and at what concurrency/ruin cost? (never sum snapshots — interleave all legs on ONE account.)
"""
import sys, uuid
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/research/cobrax")
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
import cobrax as CB
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD
from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to
from bt_engine.runner.equity_sizer import EquitySizer, EquitySizerConfig, CONTRACT_SIZE

SYM = "XAUUSD.ecn"; CONTRACT = CONTRACT_SIZE[SYM]

def capture_leg(Cls, frame_m15, hold_bars):
    """Run one intraday leg on OANDA M15; capture entry_ts, exit_ts, risk(price), net_r."""
    prov = MemoryBarProvider(frame_m15, symbol=SYM, timeframe="M15"); clk = MemoryClock(prov)
    strat = Cls(symbol=SYM); rows = {}
    def _o(tr):
        rows[tr.trade_id] = {"entry_ts": pd.Timestamp(tr.entry_timestamp), "risk": float(tr.risk_units)}
    def _c(tr, oc):
        if tr.trade_id in rows:
            cr = float((tr.order.extra or {}).get("cost_r") or 0.0)
            rows[tr.trade_id]["exit_ts"] = pd.Timestamp(oc.exit_timestamp)
            rows[tr.trade_id]["net_r"] = oc.bracket_1r_outcome - cr
    deps = EngineDeps(clock=clk, data_provider=prov, strategy=strat, execution=BTExecutionModel(),
                      broker=None, recorder=None, journal=None, on_trade_open=_o, on_trade_close=_c,
                      max_bars_held=hold_bars)
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    return [r for r in rows.values() if "net_r" in r and "exit_ts" in r and r["risk"] > 0]

def cobrax_trades(df_m5, tp_r=3.0, cost=0.2):
    base = dict(CB.HEADLINE); base["exec_tf"] = 5; base["fvg_min"] = 0.3; base["tp_r"] = tp_r
    tr = CB.run(df_m5, direction="both", cost=cost, **base)
    return [{"entry_ts": t["fill_ts"], "exit_ts": t["exit_ts"], "risk": t["R_price"], "net_r": t["net_r"]}
            for t in tr if t["exit_ts"] > t["fill_ts"] and t["R_price"] > 0]

def sizer_pnl(trades, start, risk_pct):
    """Event-stream ONE account: size each entry from current equity, apply pnl at exit."""
    sz = EquitySizer(EquitySizerConfig(start_balance=start, risk_pct=risk_pct))
    ev = []
    for i, t in enumerate(trades):
        ev.append((pd.Timestamp(t["entry_ts"]), 0, i)); ev.append((pd.Timestamp(t["exit_ts"]), 1, i))
    ev.sort(key=lambda x: (x[0], x[1]))
    lots = {}; min_eq = start
    for ts, kind, i in ev:
        t = trades[i]
        if kind == 0:
            lots[i] = sz.size_order(symbol=SYM, stop_distance=t["risk"], ts=ts.to_pydatetime())
        else:
            pnl = lots.get(i, 0.0) * CONTRACT * t["risk"] * t["net_r"]
            sz.on_trade_closed(pnl_dollars=pnl, close_ts=ts.to_pydatetime())
            min_eq = min(min_eq, sz.state.current_equity)
    banked = sum(h["skim_amount"] for h in sz.state.skim_history)
    return banked + sz.state.current_equity, min_eq

if __name__ == "__main__":
    tp_r = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    print("loading M5 -> M15 ...", flush=True)
    m5 = pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame = resample_m5_to(m5, "M15"); df_m5 = CB.load(CB.XAU_M5)

    print("A leg ...", flush=True); a = capture_leg(FibV2IntradayA, frame, 48)
    print("D leg ...", flush=True); d = capture_leg(FibV2IntradayD, frame, 96)
    print(f"COBRAX rr{tp_r} ...", flush=True); cob = cobrax_trades(df_m5, tp_r=tp_r)
    ad = a + d
    print(f"  A={len(a)} D={len(d)} A+D={len(ad)}  COBRAX={len(cob)}")
    print(f"  net-R: A+D={sum(t['net_r'] for t in ad):.0f}  COBRAX={sum(t['net_r'] for t in cob):.0f}")

    print(f"\n  REAL EquitySizer — A+D alone  vs  A+D + COBRAX (rr{tp_r}, one account)")
    print(f"  {'risk':>6} {'start':>6} | {'A+D $':>13} {'minEq':>9} | {'A+D+COBRAX $':>14} {'minEq':>9} | {'uplift':>8}")
    for rp in (0.015, 0.025, 0.03):
        for st in (5000.0, 10000.0):
            ba, ma = sizer_pnl(ad, st, rp)
            bc, mc = sizer_pnl(ad + cob, st, rp)
            up = (bc - ba) / ba * 100 if ba else 0
            print(f"  {rp*100:>5.1f}% ${int(st/1000)}k | ${ba:>11,.0f} ${ma:>7,.0f} | ${bc:>12,.0f} ${mc:>7,.0f} | {up:>+6.1f}%")
