"""21-year BT-path vs LIVE-path parity run — combined A+D on full XAU history.

Runs the SAME strategy (fib_v2_intraday_a_plus_d) through run_engine TWICE:
  - mode='bt'   : BTExecutionModel.simulate_fill (fill at bar.open)
  - mode='live' : BTMirrorLiveBroker (mirrors simulate_fill exactly at bar.open)

The ONLY difference is the code path through engine.py (_submit_live_order +
broker.fills() vs direct simulate_fill). Execution semantics identical, so trade
outcomes MUST match. This proves research=BT=live code path over the full 21yr,
not just a 500-bar sample.

Captures per path: n_trades, sum_R, win%, PF, pos-years. Reports delta.
Zero look-ahead — reuses the audited engine + strategy unchanged.
"""
from __future__ import annotations
import sys, uuid, time
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "integration"))

from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.core.bar import Bar
from bt_engine.core.order import Fill, Order
from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies import registry

M5 = Path("/tmp/oanda_xau_m5.parquet")


class BTMirrorLiveBroker:
    """Live broker mirroring BT fill semantics exactly (fill at bar.open)."""
    def __init__(self):
        self._current_bar=None; self._next_fill=None; self._last={}; self.last_submitted_order=None; self._seq=0
    def set_current_bar(self,bar): self._current_bar=bar
    def submit_order(self,order):
        self.last_submitted_order=order; self._seq+=1; t=f"MOCK-{self._seq}"
        fill=BTExecutionModel().simulate_fill(order,self._current_bar)
        self._next_fill=fill
        self._last={"success":True,"ticket":t,"price":fill.price,"volume":fill.qty}
        return t
    def cancel(self,o): pass
    def modify(self,t,*,sl,tp=0.0): pass
    def close_partial(self,t,q): pass
    def close_all(self): pass
    def last_response(self): return self._last
    def fills(self):
        if self._next_fill is not None:
            yield self._next_fill; self._next_fill=None
    def positions(self): return []


def run_path(mode, frame, strategy, max_hold_bars):
    provider=MemoryBarProvider(frame,symbol="XAUUSD.ecn",timeframe="M15")
    clock=MemoryClock(provider)
    strat=registry.get(strategy,symbol="XAUUSD.ecn")
    closed=[]  # (entry_ts, side, leg, net_r)
    def on_close(tr,oc):
        cost_r=float((tr.order.extra or {}).get("cost_r") or 0.0)
        net_r=oc.bracket_1r_outcome-cost_r
        closed.append((str(tr.entry_timestamp), tr.side, (tr.order.extra or {}).get("leg"), net_r))
    if mode=="bt":
        deps=EngineDeps(clock=clock,data_provider=provider,strategy=strat,
                        execution=BTExecutionModel(),broker=None,
                        on_trade_close=on_close,max_bars_held=max_hold_bars)
    else:
        deps=EngineDeps(clock=clock,data_provider=provider,strategy=strat,
                        execution=None,broker=BTMirrorLiveBroker(),
                        on_trade_close=on_close,max_bars_held=max_hold_bars)
    run=run_engine(run_id=uuid.uuid4(),deps=deps,mode=mode)
    return closed, run.bars_processed


def summ(trades):
    if not trades: return dict(n=0)
    r=np.array([t[3] for t in trades])
    wr=100*(r>0).mean()
    prof=r[r>0].sum(); loss=-r[r<=0].sum()
    pf=prof/loss if loss>0 else float('inf')
    yrs=pd.to_datetime([t[0] for t in trades]).year
    g=pd.Series(r).groupby(yrs).sum()
    py=int((g>0).sum()); ty=len(g)
    return dict(n=len(r), sumR=round(float(r.sum()),2), wr=round(wr,2),
                pf=round(float(pf),4), posY=f"{py}/{ty}")


def main():
    t0=time.time()
    print(f"[{time.strftime('%H:%M:%S')}] loading full M5 -> M15", flush=True)
    m5=pd.read_parquet(M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"]=m5["timestamp"].dt.tz_localize("UTC")
    m5=m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame=resample_m5_to(m5,"M15")
    print(f"  M15 bars {len(frame):,}  {frame.timestamp.min()} -> {frame.timestamp.max()}", flush=True)

    max_hold=24*4*2
    print(f"\n[{time.strftime('%H:%M:%S')}] BT path...", flush=True)
    bt, nb_bt=run_path("bt",frame,"fib_v2_intraday_a_plus_d",max_hold)
    print(f"  BT done: {len(bt)} trades, {nb_bt} bars", flush=True)

    print(f"[{time.strftime('%H:%M:%S')}] LIVE path...", flush=True)
    lv, nb_lv=run_path("live",frame,"fib_v2_intraday_a_plus_d",max_hold)
    print(f"  LIVE done: {len(lv)} trades, {nb_lv} bars", flush=True)

    sb=summ(bt); sl=summ(lv)
    print("\n"+"="*70)
    print(f"{'METRIC':<12}{'BT PATH':>18}{'LIVE PATH':>18}{'DELTA':>18}")
    print("-"*70)
    for k in ["n","sumR","wr","pf"]:
        b=sb.get(k,0); l=sl.get(k,0)
        d=(l-b) if isinstance(b,(int,float)) else "-"
        print(f"{k:<12}{str(b):>18}{str(l):>18}{str(round(d,4) if isinstance(d,float) else d):>18}")
    print(f"{'posY':<12}{sb.get('posY','-'):>18}{sl.get('posY','-'):>18}{'':>18}")
    print("="*70)

    # trade-by-trade divergence
    setB=set((t[0],t[1],round(t[3],4)) for t in bt)
    setL=set((t[0],t[1],round(t[3],4)) for t in lv)
    only_bt=setB-setL; only_lv=setL-setB
    print(f"\nTrade-level: shared={len(setB&setL)}  only_BT={len(only_bt)}  only_LIVE={len(only_lv)}")
    if only_bt or only_lv:
        print("  DIVERGENCE examples (BT-only):", list(only_bt)[:3])
        print("  DIVERGENCE examples (LIVE-only):", list(only_lv)[:3])
    else:
        print("  PERFECT PARITY — every trade identical (ts, side, net_r).")
    print(f"\n[{time.strftime('%H:%M:%S')}] done in {time.time()-t0:.0f}s")

if __name__=="__main__":
    main()
