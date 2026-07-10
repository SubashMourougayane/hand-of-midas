#!/usr/bin/env python3
"""NO-STRICT A+D — risk-cliff + DECISION-BAR causal spot-check (log-heavy, auditable).

Post-COBRAX rigor: this script LOGS its own methodology + intermediate values so the
TEST ITSELF can be reviewed for correctness later, not just the result. Writes to both
stdout and a timestamped .log next to this file.

Two questions:
  1. CAUSAL — is no-strict a real (non-look-ahead) relaxation? (COBRAX's edge was a bias
     input timestamped AFTER the fill.) Checks, per trade, that the SIGNAL timestamp
     encoded in the order tag is STRICTLY BEFORE the fill timestamp, plus strict⊆no-strict
     superset structure. A look-ahead would surface as signal_ts >= fill_ts.
  2. RISK — live A+D is at 2% now. No-strict adds ~+6% trades (more variance); it craters
     at 3%. Does 2% stay off the ruin cliff, or does it need <=1.5%? Real EquitySizer
     exact path + Monte-Carlo ruin, STRICT vs NO-STRICT side by side.
"""
import sys, uuid, functools, re
from datetime import datetime, timezone
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
LOGF = open(f"/Users/subash/SUBASH/GoldDigger/research/cobrax/NOSTRICT_RISK_{datetime.now(timezone.utc):%Y%m%dT%H%M}Z.log", "w")

def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True); LOGF.write(s + "\n"); LOGF.flush()

_TS = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+\d:]*)")

def capture(Cls, frame_m15, hold_bars, label):
    """Run one leg; capture fill ts, side, risk, net_r, tag, and signal_ts parsed from tag."""
    prov = MemoryBarProvider(frame_m15, symbol=SYM, timeframe="M15"); clk = MemoryClock(prov)
    strat = Cls(symbol=SYM); rows = {}
    def _o(tr):
        tag = str(tr.order.tag or "")
        mt = _TS.search(tag)
        rows[tr.trade_id] = {
            "entry_ts": pd.Timestamp(tr.entry_timestamp), "risk": float(tr.risk_units),
            "side": int(tr.side), "tag": tag,
            "signal_ts": pd.Timestamp(mt.group(1)) if mt else None,
        }
    def _c(tr, oc):
        if tr.trade_id in rows:
            cr = float((tr.order.extra or {}).get("cost_r") or 0.0)
            rows[tr.trade_id]["exit_ts"] = pd.Timestamp(oc.exit_timestamp)
            rows[tr.trade_id]["net_r"] = oc.bracket_1r_outcome - cr
    deps = EngineDeps(clock=clk, data_provider=prov, strategy=strat, execution=BTExecutionModel(),
                      broker=None, recorder=None, journal=None, on_trade_open=_o, on_trade_close=_c,
                      max_bars_held=hold_bars)
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    out = [r for r in rows.values() if "net_r" in r and "exit_ts" in r and r["risk"] > 0]
    nets = [r["net_r"] for r in out]
    log(f"  [{label}] trades={len(out)} netR={sum(nets):+.1f} avgR={np.mean(nets):+.4f} "
        f"WR={100*np.mean([n>0 for n in nets]):.1f}% tag_sample={out[0]['tag'] if out else 'NA'}")
    return out

def causal_audit(trades, label):
    log(f"\n  --- DECISION-BAR CAUSAL AUDIT [{label}] ---")
    n = len(trades); no_sig = sum(1 for t in trades if t["signal_ts"] is None)
    have = [t for t in trades if t["signal_ts"] is not None]
    viol = [t for t in have if not (t["signal_ts"] < t["entry_ts"])]   # signal must be BEFORE fill
    ge_entry = [t for t in have if t["signal_ts"] >= t["entry_ts"]]
    # gap distribution signal->fill (should be >=1 M15 bar = 15min, positive)
    gaps = [(t["entry_ts"] - t["signal_ts"]).total_seconds() / 60.0 for t in have]
    log(f"    trades={n}  tag-encoded signal_ts present={len(have)} (missing={no_sig})")
    log(f"    signal_ts < fill_ts violations: {len(viol)}   (LOOK-AHEAD if >0)")
    log(f"    signal_ts >= fill_ts (decision at/after entry): {len(ge_entry)}")
    if gaps:
        g = np.array(gaps)
        log(f"    signal->fill gap (min): min={g.min():.0f} median={np.median(g):.0f} "
            f"max={g.max():.0f}  (>=15 expected; fill = next M15 open)")
        log(f"    fills at exactly +15min (next-bar-open): {100*np.mean(np.isclose(g,15)):.0f}%")
    return len(viol)

def overlap(strict, nostrict):
    log("\n  --- STRUCTURE: strict vs no-strict (superset expectation) ---")
    sset = {(t["signal_ts"], t["side"]) for t in strict if t["signal_ts"] is not None}
    nset = {(t["signal_ts"], t["side"]) for t in nostrict if t["signal_ts"] is not None}
    log(f"    strict signals={len(sset)}  no-strict signals={len(nset)}")
    log(f"    strict preserved in no-strict: {len(sset & nset)}/{len(sset)} "
        f"({100*len(sset & nset)/max(len(sset),1):.1f}%)")
    log(f"    NEW signals in no-strict (the +delta): {len(nset - sset)}")
    log(f"    strict-only (dropped by no-strict): {len(sset - nset)}  (should be ~0 if pure superset)")

def hist_path(trades, start, rp):
    sz = EquitySizer(EquitySizerConfig(start_balance=start, risk_pct=rp))
    ev = []
    for i, t in enumerate(trades):
        ev.append((t["entry_ts"], 0, i)); ev.append((t["exit_ts"], 1, i))
    ev.sort(key=lambda x: (x[0], x[1]))
    lots = {}; peak = start; maxdd = 0.0; min_eq = start
    for ts, kind, i in ev:
        t = trades[i]
        if kind == 0:
            lots[i] = sz.size_order(symbol=SYM, stop_distance=t["risk"], ts=pd.Timestamp(ts).to_pydatetime())
        else:
            sz.on_trade_closed(pnl_dollars=lots.get(i, 0.0) * CONTRACT * t["risk"] * t["net_r"],
                               close_ts=pd.Timestamp(ts).to_pydatetime())
            eq = sz.state.current_equity; peak = max(peak, eq); min_eq = min(min_eq, eq)
            if peak > 0: maxdd = max(maxdd, (peak - eq) / peak)
    banked = sum(h["skim_amount"] for h in sz.state.skim_history)
    return banked + sz.state.current_equity, min_eq, maxdd * 100

def mc_ruin(nets, rp, n=4000, ruin_frac=0.20, seed=0):
    rng = np.random.default_rng(seed); arr = np.asarray(nets); ruins = 0
    for _ in range(n):
        seq = rng.permutation(arr); eq = 1.0
        for r in seq:
            eq *= (1.0 + rp * r)
            if eq <= ruin_frac: ruins += 1; break
    return 100 * ruins / n

def risk_table(label, trades):
    nets = [t["net_r"] for t in trades]
    log(f"\n  === RISK-CLIFF [{label}]  (real EquitySizer, $5k start, 20yr exact path) ===")
    log(f"    {'risk':>5} | {'final $':>13} {'min-eq':>9} {'maxDD%':>7} | {'P(ruin@20%)':>11}")
    for rp in (0.015, 0.02, 0.025, 0.03):
        f5, meq, dd = hist_path(trades, 5000.0, rp)
        pr = mc_ruin(nets, rp)
        flag = "  <-- LIVE" if abs(rp - 0.02) < 1e-9 else ("  RUIN" if meq < 0 else "")
        log(f"    {rp*100:>4.1f}% | ${f5:>11,.0f} ${meq:>7,.0f} {dd:>6.1f}% | {pr:>9.1f}%{flag}")

if __name__ == "__main__":
    log("=" * 78)
    log(f"NO-STRICT A+D risk-cliff + causal audit   run={datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z")
    log("=" * 78)
    log("DATA: OANDA XAU M5 parquet -> resample M15 (label=left, closed=left).")
    m5 = pd.read_parquet(CB.XAU_M5)
    if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    frame = resample_m5_to(m5, "M15")
    log(f"  M5 rows={len(m5):,}  M15 bars={len(frame):,}  range={frame['timestamp'].iloc[0]} .. {frame['timestamp'].iloc[-1]}")
    log("  A hold=48 M15 (12h), D hold=96 M15 (24h). Cost from leg config. BTExecutionModel (fill=next M15 open).")

    A_s = functools.partial(FibV2IntradayA, strict_after=True)
    D_s = functools.partial(FibV2IntradayD, strict_after=True)
    A_n = functools.partial(FibV2IntradayA, strict_after=False)
    D_n = functools.partial(FibV2IntradayD, strict_after=False)

    log("\nGENERATING TRADES:")
    a_s = capture(A_s, frame, 48, "A strict"); d_s = capture(D_s, frame, 96, "D strict")
    a_n = capture(A_n, frame, 48, "A nostrict"); d_n = capture(D_n, frame, 96, "D nostrict")
    ad_s = sorted(a_s + d_s, key=lambda t: t["entry_ts"])
    ad_n = sorted(a_n + d_n, key=lambda t: t["entry_ts"])
    ns = [t["net_r"] for t in ad_s]; nn = [t["net_r"] for t in ad_n]
    log(f"\n  A+D STRICT  : trades={len(ad_s)} netR={sum(ns):+.1f} avgR={np.mean(ns):+.4f}")
    log(f"  A+D NOSTRICT: trades={len(ad_n)} netR={sum(nn):+.1f} avgR={np.mean(nn):+.4f}")
    log(f"  DELTA       : trades {len(ad_n)-len(ad_s):+d} ({100*(len(ad_n)-len(ad_s))/len(ad_s):+.1f}%)  "
        f"netR {sum(nn)-sum(ns):+.1f} ({100*(sum(nn)-sum(ns))/sum(ns):+.1f}%)")

    v = causal_audit(ad_n, "A+D nostrict")
    causal_audit(ad_s, "A+D strict")
    overlap(ad_s, ad_n)
    risk_table("A+D STRICT (live baseline)", ad_s)
    risk_table("A+D NO-STRICT", ad_n)

    log("\n" + "=" * 78)
    log(f"VERDICT INPUTS: nostrict look-ahead violations={v} (0 = causal). "
        "Compare NO-STRICT min-eq @2% vs STRICT @2%; if NO-STRICT min-eq at/below 0 or "
        "much worse -> needs <=1.5%. Judge from the tables above.")
    log("=" * 78)
    LOGF.close()
