"""VS-table: BT engine (run_engine mode='bt') vs strategy code directly.

Both consume the same OANDA M5 → M15 data for Jun 23. If parity is real,
identical event stream + identical trades. Any drift = latent bug.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.core.signal import StrategyEvent
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD

from tests.parity._fib_v2_helper import InMemoryClock, InMemoryProvider


OANDA_M5 = Path("/tmp/oanda_xau_m5.parquet")


def load_m15() -> pd.DataFrame:
    m5 = pd.read_parquet(OANDA_M5)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").reset_index(drop=True)
    idx = m5.set_index("timestamp")
    m15 = idx.resample("15min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    return m15


def run_engine_capture(StrategyCls, m15, day_start, day_end, max_bars_held, label):
    """Full engine loop with execution model (mode='bt') — mimics real BT."""
    provider = InMemoryProvider(m15, symbol="XAUUSD.ecn", timeframe="M15")
    clock = InMemoryClock(provider)
    strat = StrategyCls(symbol="XAUUSD.ecn")
    events = []
    trades = []

    def _on_event(ev):
        bts = ev.detail.get("bar_ts")
        if not bts: return
        try:
            t = pd.Timestamp(bts)
            if t.tzinfo is None: t = t.tz_localize("UTC")
        except: return
        if day_start <= t < day_end:
            events.append((str(t), ev.type, ev.detail.get("leg", ""), ev.detail))

    def _on_open(tr):
        t = pd.Timestamp(tr.entry_timestamp)
        if t.tzinfo is None: t = t.tz_localize("UTC")
        if day_start <= t < day_end:
            trades.append({
                "entry_ts": str(t),
                "side": "LONG" if tr.side > 0 else "SHORT",
                "leg": tr.order.extra.get("leg", ""),
                "entry": tr.entry_price,
                "sl": tr.stop_price,
                "tp": tr.take_profit,
                "risk": tr.risk_units,
            })

    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_trade_open=_on_open,
        on_strategy_event=_on_event,
        max_bars_held=max_bars_held,
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    print(f"[BT {label}] events={len(events)} trades={len(trades)}")
    return events, trades


def run_strategy_direct(StrategyCls, m15, day_start, day_end, label):
    """Direct on_bar calls without engine wrapper — pure strategy loop.
    Simulates what a minimal-dependency runtime would see."""
    strat = StrategyCls(symbol="XAUUSD.ecn")
    state = strat.initial_state()
    from bt_engine.core.bar import Bar
    events = []
    trades = []  # from step.new_orders (won't have exit info)

    for i in range(len(m15)):
        row = m15.iloc[i]
        bar = Bar(
            symbol="XAUUSD.ecn", timeframe="M15",
            timestamp=row["timestamp"],
            open=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]),
            volume=float(row.get("volume", 0)),
        )
        history = m15.iloc[:i+1]
        step = strat.on_bar(state, bar, history)
        state = step.state
        # Filter events to day
        for ev in step.new_events:
            bts = ev.detail.get("bar_ts")
            if not bts: continue
            try:
                t = pd.Timestamp(bts)
                if t.tzinfo is None: t = t.tz_localize("UTC")
            except: continue
            if day_start <= t < day_end:
                events.append((str(t), ev.type, ev.detail.get("leg", ""), ev.detail))
        # Orders → treat as "would-be entries" (no execution model in this path)
        for o in step.new_orders:
            t = pd.Timestamp(o.intended_entry_bar)
            if t.tzinfo is None: t = t.tz_localize("UTC")
            if day_start <= t < day_end:
                trades.append({
                    "entry_ts": str(t),
                    "side": "LONG" if o.side > 0 else "SHORT",
                    "leg": o.extra.get("leg", ""),
                    "entry": None,  # not filled yet
                    "sl": o.stop_price,
                    "tp": o.take_profit,
                    "risk": o.risk_units,
                })
    print(f"[DIRECT {label}] events={len(events)} orders={len(trades)}")
    return events, trades


def print_vs(bt_events, direct_events, bt_trades, direct_trades, label):
    print(f"\n═══════ {label} ═══════")
    # Event type counts
    from collections import Counter
    bt_counts = Counter(e[1] for e in bt_events)
    dr_counts = Counter(e[1] for e in direct_events)
    all_types = sorted(set(bt_counts.keys()) | set(dr_counts.keys()))
    print(f"{'event_type':<40s} {'BT':>6s} {'DIRECT':>7s} {'diff':>5s}")
    total_diff = 0
    for t in all_types:
        b = bt_counts.get(t, 0)
        d = dr_counts.get(t, 0)
        diff = d - b
        total_diff += abs(diff)
        marker = "  ⚠" if diff != 0 else ""
        print(f"{t:<40s} {b:>6d} {d:>7d} {diff:>+5d}{marker}")
    print(f"total abs event drift: {total_diff}")

    # Trades
    print(f"\nTrades opened  BT: {len(bt_trades)}  DIRECT: {len(direct_trades)}")
    print(f"{'ts':<26s} {'side':<6s} {'BT_entry':>10s} {'DIR_entry':>10s} {'BT_sl':>10s} {'DIR_sl':>10s}")
    # Match by (ts, side, leg)
    def key(t): return (t["entry_ts"][:19], t["side"], t["leg"])
    bt_by = {key(t): t for t in bt_trades}
    dr_by = {key(t): t for t in direct_trades}
    all_keys = sorted(set(bt_by.keys()) | set(dr_by.keys()))
    for k in all_keys:
        b = bt_by.get(k)
        d = dr_by.get(k)
        ts, side, leg = k
        bt_entry = f"${b['entry']:.2f}" if b and b['entry'] else "—"
        dr_entry = f"${d['entry']:.2f}" if d and d['entry'] else "—"
        bt_sl = f"${b['sl']:.2f}" if b else "—"
        dr_sl = f"${d['sl']:.2f}" if d else "—"
        print(f"{ts:<26s} {side:<6s} {bt_entry:>10s} {dr_entry:>10s} {bt_sl:>10s} {dr_sl:>10s}")


def main():
    print("Loading OANDA M15…")
    m15 = load_m15()
    print(f"  {len(m15):,} bars")

    day_start = pd.Timestamp("2026-06-23", tz="UTC")
    day_end = day_start + pd.Timedelta(days=1)

    # A leg
    bt_a_ev, bt_a_tr = run_engine_capture(FibV2IntradayA, m15, day_start, day_end, 96, "A")
    dr_a_ev, dr_a_tr = run_strategy_direct(FibV2IntradayA, m15, day_start, day_end, "A")
    print_vs(bt_a_ev, dr_a_ev, bt_a_tr, dr_a_tr, "A LEG · JUN 23")

    # D leg
    bt_d_ev, bt_d_tr = run_engine_capture(FibV2IntradayD, m15, day_start, day_end, 192, "D")
    dr_d_ev, dr_d_tr = run_strategy_direct(FibV2IntradayD, m15, day_start, day_end, "D")
    print_vs(bt_d_ev, dr_d_ev, bt_d_tr, dr_d_tr, "D LEG · JUN 23")


if __name__ == "__main__":
    main()
