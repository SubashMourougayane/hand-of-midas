#!/usr/bin/env python3
"""EXIT-TARGET SWEEP — audit-proof (docs/EDGE_AUDIT_IRONCLAD.md).

Question (Subash): the fib TP (~2.6R) is too wide — only ~6% of trades reach it.
Do tighter targets / different partial structures raise PF? Measured PHYSICALLY.

METHOD (Gate 6: ONE source of truth): capture every real A+D trade from the engine
(entry idx, price, side, stop, risk). Then for each exit config, RE-WALK that trade's
ACTUAL forward M15 bars through the LIVE `walk_bracket_on_bar` — the exact live
bracket, physical fix in place. No MFE reconstruction, no research re-impl.

Gate 2 physical: bracket books runner at (1-pct) size (runner_frac).
Gate 4 regime: PF/netR reported PER YEAR + windows (cost_r moves with gold price).
Gate 5 flat-risk R-space: no Model-B, no compounding, no wipe. Pure edge.
Gate 0: the winner gets a hostile follow-up (delay + tail-dependence) before belief.

cost: $0.65/trade (same as live). strict engine. A hold 48, D hold 96.
"""
import sys, uuid, functools
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.core.bar import Bar
from bt_engine.core.order import Order, Fill, OpenTrade
from bt_engine.core.bracket import walk_bracket_on_bar
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD
from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to

SYM = "XAUUSD.ecn"
COST_USD = 0.65

m5 = pd.read_parquet("/tmp/oanda_xau_m5.parquet")
if m5["timestamp"].dt.tz is None: m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
FRAME = resample_m5_to(m5, "M15").reset_index(drop=True)
TS_LIST = [pd.Timestamp(t) for t in FRAME["timestamp"]]  # tz-aware
TS_INDEX = {t: i for i, t in enumerate(TS_LIST)}
HI = FRAME["high"].values; LO = FRAME["low"].values; CL = FRAME["close"].values
OP = FRAME["open"].values


def capture(Cls, hold):
    """Run the live strategy+engine, capture each trade's entry facts."""
    prov = MemoryBarProvider(FRAME, symbol=SYM, timeframe="M15"); clk = MemoryClock(prov)
    trades = []
    def _o(tr):
        trades.append({
            "entry_ts": pd.Timestamp(tr.entry_timestamp),
            "entry_price": float(tr.entry_price), "side": int(tr.side),
            "stop": float(tr.stop_price), "risk": float(tr.risk_units),
            "fib_tp": float(tr.take_profit) if tr.take_profit is not None else None,
            "hold": hold,
        })
    deps = EngineDeps(clock=clk, data_provider=prov, strategy=Cls(symbol=SYM),
                      execution=BTExecutionModel(), broker=None, on_trade_open=_o,
                      max_bars_held=hold)
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    return trades


def rewalk(tr, *, tp_r=None, use_fib_tp=False, partial_at=None, partial_pct=0.5,
           partial2_at=None, partial2_pct=0.0):
    """Re-walk one trade's forward bars through the LIVE bracket with a chosen
    exit config. Returns physical net_r (cost included). tp_r = fixed R target;
    use_fib_tp = keep the original fib target."""
    idx = TS_INDEX.get(tr["entry_ts"])
    if idx is None: return None
    entry = tr["entry_price"]; side = tr["side"]; risk = tr["risk"]; hold = tr["hold"]
    if use_fib_tp:
        tp_price = tr["fib_tp"]
    elif tp_r is not None:
        tp_price = entry + side * tp_r * risk
    else:
        tp_price = None
    extra = {}
    if partial_at is not None:
        extra["partial_tp_at_r"] = float(partial_at); extra["partial_tp_pct"] = float(partial_pct)
    order = Order(symbol=SYM, side=side, qty=1.0,
                  intended_entry_bar=pd.Timestamp(tr["entry_ts"]),
                  stop_price=tr["stop"], take_profit=tp_price, risk_units=risk,
                  tag="x", bracket_kind="1R", extra=extra)
    fill = Fill(SYM, side, 1.0, entry, pd.Timestamp(tr["entry_ts"]))
    ot = OpenTrade(trade_id=uuid.uuid4(), order=order, fill=fill, entry_price=entry,
                   entry_timestamp=fill.fill_timestamp, side=side, stop_price=tr["stop"],
                   take_profit=tp_price, risk_units=risk)
    # optional 2nd partial tier: emulate by lowering to a manual check each bar
    # Management starts at the FILL bar (idx = entry_timestamp bar, the K+1 open
    # fill), matching the engine which walks the bracket from that bar onward.
    end = min(len(FRAME) - 1, idx + hold)
    booked2 = 0.0
    for j in range(idx, end + 1):
        bar = Bar(SYM, "M15", TS_LIST[j], float(OP[j]), float(HI[j]),
                  float(LO[j]), float(CL[j]), 1.0)
        # 2nd-tier partial: bank pct2*trig2 R once MFE crosses trig2 (physical:
        # reduces nothing here — we add its R and shrink the runner via note below)
        if partial2_at is not None and booked2 == 0.0:
            mfe = (bar.high - entry) * side / risk
            if mfe >= partial2_at:
                booked2 = partial2_pct * partial2_at  # banked R fraction
        oc = walk_bracket_on_bar(ot, bar, max_bars_held=hold)
        if oc is not None:
            gross = oc.bracket_1r_outcome
            # if a 2nd tier banked, shrink the remaining runner by pct2 physically
            if partial2_at is not None and booked2 > 0.0:
                # remove pct2 of the runner's exit-R, add the banked tier
                # (approx: runner exit-R = gross - partial1_component)
                pass
            return gross + booked2 - COST_USD / risk
    # timeout fallthrough (shouldn't hit; walker caps at hold)
    return 0.0 - COST_USD / risk


def pf(x):
    x = np.asarray(x); w = x[x > 0].sum(); l = -x[x < 0].sum(); return w / l if l > 0 else 9.99


def evaluate(name, trades, **cfg):
    rows = []
    for tr in trades:
        r = rewalk(tr, **cfg)
        if r is not None:
            rows.append((pd.Timestamp(tr["entry_ts"]).year, r))
    df = pd.DataFrame(rows, columns=["yr", "net"])
    out = {"name": name, "n": len(df), "netR_all": df["net"].sum(), "pf_all": pf(df["net"])}
    for lbl, cut in [("2020+", 2020), ("2024+", 2024), ("2026", 2026)]:
        s = df[df.yr >= cut] if lbl != "2026" else df[df.yr == 2026]
        out[f"netR_{lbl}"] = s["net"].sum(); out[f"pf_{lbl}"] = pf(s["net"])
    return out, df


if __name__ == "__main__":
    print("Capturing A+D trades (live engine)...", flush=True)
    A = capture(functools.partial(FibV2IntradayA, strict_after=True), 48)
    D = capture(functools.partial(FibV2IntradayD, strict_after=True), 96)
    AD = A + D
    print(f"  captured {len(AD)} trades ({len(A)} A / {len(D)} D)\n", flush=True)

    configs = [
        ("BASELINE 50%@1R + fib TP", dict(use_fib_tp=True, partial_at=1.0, partial_pct=0.5)),
        ("NO partial, full fib TP",  dict(use_fib_tp=True)),
        ("NO partial, full 1R",      dict(tp_r=1.0)),
        ("NO partial, full 1.5R",    dict(tp_r=1.5)),
        ("NO partial, full 2R",      dict(tp_r=2.0)),
        ("NO partial, full 2.5R",    dict(tp_r=2.5)),
        ("NO partial, full 3R",      dict(tp_r=3.0)),
        ("50%@1R + full 2R",         dict(tp_r=2.0, partial_at=1.0, partial_pct=0.5)),
        ("50%@1R + full 2.5R",       dict(tp_r=2.5, partial_at=1.0, partial_pct=0.5)),
        ("50%@1R + full 3R",         dict(tp_r=3.0, partial_at=1.0, partial_pct=0.5)),
        ("50%@0.5R + full 1.5R",     dict(tp_r=1.5, partial_at=0.5, partial_pct=0.5)),
        ("50%@1.5R + fib TP",        dict(use_fib_tp=True, partial_at=1.5, partial_pct=0.5)),
    ]
    hdr = f"{'config':<28}{'n':>6}{'PF_all':>8}{'netR_all':>10}{'PF_20+':>8}{'PF_24+':>8}{'PF_26':>8}{'netR_26':>9}"
    print(hdr); print("-" * len(hdr))
    results = []
    for name, cfg in configs:
        out, _ = evaluate(name, AD, **cfg)
        results.append(out)
        print(f"{name:<28}{out['n']:>6}{out['pf_all']:>8.2f}{out['netR_all']:>+10.0f}"
              f"{out['pf_2020+']:>8.2f}{out['pf_2024+']:>8.2f}{out['pf_2026']:>8.2f}{out['netR_2026']:>+9.0f}", flush=True)
    print("\nRead: PF_24+ and PF_26 are the LIVE regime (expensive gold). All PHYSICAL, cost in.")
