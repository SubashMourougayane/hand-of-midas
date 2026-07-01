"""DEPRECATED — use `python3 -m bt_engine.runner.cli bt --intraday` instead.

The new intraday BT runner (`bt_engine/runner/backtest.py::run_backtest_intraday`)
wires the same engine loop as live PLUS BarWalkJournal so the dashboard's
/journal page populates with real bar-walk rows. This script's remaining role
is historical — kept in case anyone needs the legacy invocation shape.

Original doc:

Seed intraday A + D backtests into bt_runs / bt_trades / bt_signals.

Runs the production-locked Fib V2 intraday A (LONG) and D (SHORT) on XAU M15
through the SAME bt_engine code path used by paper-live, persisting every
trade + every gate event to Postgres so the dashboard can render them.

A leg = LONG, lb=3, hold=12h, london_ny, PTP+1R, ext=2.618, sl_buf=0.02
D leg = SHORT, lb=3, hold=24h, all sessions, PTP+1R, ext=2.618, sl_buf=0.02
Cost = $0.65/trade (JustMarkets Raw Spread).

Reads XAU M5 from /tmp/oanda_xau_m5.parquet (21+ years), resamples to M15.

Usage:  python3 -m bt_engine.scripts.seed_intraday_ad_bt [--leg a|d|both]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.db.engine import make_engine
from bt_engine.db.models import BtRun, BtSignal, BtTrade, BtBarWalk, BtJournalEvent
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD

# Reuse the InMemory provider/clock used by parity helper.
from tests.parity._fib_v2_helper import InMemoryClock, InMemoryProvider


XAU_M5 = Path("/tmp/oanda_xau_m5.parquet")
DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)


def resample_m15(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return idx.resample("15min", label="left", closed="left").agg(agg).dropna().reset_index()


def seed_leg(leg: str) -> None:
    if leg == "a":
        StrategyCls = FibV2IntradayA
        strategy_id = "fib_v2_intraday_a"
        max_bars_held = 12 * 4 * 2  # 12h × 4 M15/h × 2 safety factor
    elif leg == "d":
        StrategyCls = FibV2IntradayD
        strategy_id = "fib_v2_intraday_d"
        max_bars_held = 24 * 4 * 2  # 24h × 4 × 2
    else:
        raise ValueError(f"unknown leg: {leg!r}")

    print(f"\n[{strategy_id}] loading XAU M5 + resampling to M15...")
    m5 = pd.read_parquet(XAU_M5)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").reset_index(drop=True)
    m15 = resample_m15(m5)
    print(f"  bars: M5={len(m5):,}  M15={len(m15):,}")
    print(f"  range: {m15.timestamp.min()} → {m15.timestamp.max()}")

    provider = InMemoryProvider(m15, symbol="XAUUSD.ecn", timeframe="M15")
    clock = InMemoryClock(provider)
    strat = StrategyCls(symbol="XAUUSD.ecn")

    run_id = uuid.uuid4()
    run_ref = f"BT-INTRADAY-{leg.upper()}-{run_id.hex[:8]}"

    engine_db = make_engine(DB_URL)
    Session = sessionmaker(bind=engine_db, expire_on_commit=False)
    with Session() as session:
        bt_run = BtRun(
            run_id=run_id,
            ref=run_ref,
            mode="bt",
            strategy_id=strategy_id,
            strategy_config={
                "pivot_lb": 3,
                "ext_target_pct": 2.618,
                "sl_buffer_pct": 0.02,
                "session": "london_ny" if leg == "a" else "all",
                "max_hold_h": 12 if leg == "a" else 24,
                "cost_usd": 0.65,
                "partial_tp_at_r": 1.0,
                "partial_tp_pct": 0.5,
                "min_risk_units": 0.50,
                "data_source": "oanda_m5_resampled_m15",
            },
            symbol="XAUUSD.ecn",
            timeframe="M15",
            start_ts=datetime.now(timezone.utc),
            data_provider="oanda_parquet",
        )
        session.add(bt_run)
        session.commit()
        print(f"  bt_run created: {run_ref}")

    # Buffer all inserts in memory and bulk-write at the end. Single-row commits
    # were the bottleneck (300k+ signals expected). Trade-off: dashboard can't
    # stream the BT in real-time, but BT is a one-shot anyway. We persist run +
    # all trades + all signals atomically at end.
    trade_open_buf: dict = {}    # trade_id -> dict (open fields)
    trade_close_buf: dict = {}   # trade_id -> dict (close fields, merged at end)
    signal_buf: list[dict] = []

    def _on_open(trade) -> None:
        leg_name = trade.order.extra.get("leg")
        regime = trade.order.extra.get("regime")
        cost_r = trade.order.extra.get("cost_r", 0.0)
        trade_ref = f"FIB-INTRADAY-{leg.upper()}-{trade.trade_id}"
        trade_open_buf[trade.trade_id] = dict(
            trade_id=trade.trade_id,
            trade_ref=trade_ref,
            run_id=run_id,
            strategy_id=strategy_id,
            symbol="XAUUSD.ecn",
            timeframe="M15",
            direction="long" if trade.side > 0 else "short",
            side=trade.side,
            entry_timestamp=trade.entry_timestamp.to_pydatetime(),
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            risk_units=trade.risk_units,
            take_profit_price=trade.take_profit,
            pivot_lb=3,
            regime=regime,
            ext_target_pct=2.618,
            sl_buffer_pct=0.02,
            fib_diff=trade.order.extra.get("fib_diff"),
            regime_at_entry=trade.order.extra.get("regime_at_entry"),
            leg=leg_name,
            partial_tp_at_r=1.0,
            partial_tp_pct=0.5,
            cost_r=cost_r,
            raw_features=trade.order.extra,
        )

    def _on_close(trade, outcome) -> None:
        cost_r = trade.order.extra.get("cost_r", 0.0)
        net_r = outcome.bracket_1r_outcome - cost_r
        partial_fill_ts = (
            trade.partial_fill_timestamp.to_pydatetime()
            if trade.partial_fill_timestamp is not None
            else None
        )
        trade_close_buf[trade.trade_id] = dict(
            exit_timestamp=outcome.exit_timestamp.to_pydatetime(),
            exit_price=outcome.exit_price,
            exit_reason=outcome.reason,
            bars_held=outcome.bars_held,
            bracket_1r_outcome=outcome.bracket_1r_outcome,
            gross_r=outcome.bracket_1r_outcome,
            net_r=net_r,
            partial_taken=trade.partial_taken,
            partial_r=trade.partial_filled_r,
            partial_fill_price=trade.partial_fill_price,
            partial_fill_ts=partial_fill_ts,
        )

    def _on_event(ev) -> None:
        detail = dict(ev.detail)
        event_ts = (
            detail.get("bar_ts")
            or detail.get("entry_timestamp")
            or detail.get("bar_timestamp")
        )
        try:
            ts_py = pd.Timestamp(event_ts).to_pydatetime() if event_ts else datetime.now(timezone.utc)
        except Exception:
            ts_py = datetime.now(timezone.utc)
        signal_buf.append(
            dict(
                run_id=run_id,
                ts=ts_py,
                status=ev.type,
                zone_id=None,
                reason=detail.get("reason") if ev.type.startswith("GATE_") else None,
                detail={"trade_or_zone_id": ev.trade_or_zone_id, **detail},
            )
        )
        if len(signal_buf) % 50_000 == 0:
            print(f"  buffered: {len(signal_buf):,} sig / {len(trade_open_buf):,} trades")

    deps = EngineDeps(
        clock=clock,
        data_provider=provider,
        strategy=strat,
        execution=BTExecutionModel(),
        broker=None,
        recorder=None,
        journal=None,
        on_trade_open=_on_open,
        on_trade_close=_on_close,
        on_strategy_event=_on_event,
        max_bars_held=max_bars_held,
    )

    print("  running engine (in-memory buffer; bulk DB flush at end)...")
    result = run_engine(run_id=run_id, deps=deps, mode="bt")
    print(
        f"  engine done: bars={result.bars_processed:,}  "
        f"trades_open={len(trade_open_buf):,}  signals={len(signal_buf):,}"
    )

    # Merge close fields into open buffer.
    for tid, cf in trade_close_buf.items():
        if tid in trade_open_buf:
            trade_open_buf[tid].update(cf)

    # Bulk insert trades.
    print(f"  bulk-inserting {len(trade_open_buf):,} trades...")
    with Session() as s:
        s.bulk_insert_mappings(BtTrade, list(trade_open_buf.values()))
        s.commit()

    # Bulk insert signals in chunks (psycopg2 has a 65k param limit).
    print(f"  bulk-inserting {len(signal_buf):,} signals (chunked)...")
    CHUNK = 5000
    with Session() as s:
        for i in range(0, len(signal_buf), CHUNK):
            s.bulk_insert_mappings(BtSignal, signal_buf[i : i + CHUNK])
            s.commit()
            if (i // CHUNK) % 10 == 0:
                print(f"    {min(i + CHUNK, len(signal_buf)):,} / {len(signal_buf):,}")

    # Stamp end_ts.
    with Session() as s:
        r = s.get(BtRun, run_id)
        if r is not None:
            r.end_ts = datetime.now(timezone.utc)
            s.commit()

    closed = sum(1 for v in trade_open_buf.values() if "net_r" in v)
    net_r_sum = sum(v.get("net_r") or 0 for v in trade_open_buf.values())
    print(
        f"  DONE: bars={result.bars_processed:,}  trades={len(trade_open_buf):,}  "
        f"closed={closed:,}  net_r={net_r_sum:+.1f}  signals={len(signal_buf):,}"
    )
    print(f"  run_id: {run_id}")
    print(f"  run_ref: {run_ref}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--leg", choices=("a", "d", "both"), default="both")
    args = p.parse_args()

    print(
        "\n[DEPRECATION] scripts/seed_intraday_ad_bt.py is superseded by:\n"
        "  python3 -m bt_engine.runner.cli bt --intraday "
        "--strategy fib_v2_intraday_a --timeframe M15\n"
        "The new CLI wires BarWalkJournal (populates /journal page) "
        "and follows the same code path as live.\n"
    )

    if args.leg in ("a", "both"):
        seed_leg("a")
    if args.leg in ("d", "both"):
        seed_leg("d")


if __name__ == "__main__":
    main()
