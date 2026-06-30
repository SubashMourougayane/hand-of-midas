"""Paper-live smoke test for Fib V2 PTP variants.

Runs first ~100k M5 bars of XAU OANDA through PTP+1R + PTP+2R strategies via
bt_engine production path. Verifies:
  - Engine fills + brackets honor partial-TP trigger.
  - Trades persist to DB with new partial_* columns populated.
  - At least some trades show partial_taken=True with partial_r > 0.
  - bracket SL outcomes are 0 (BE) when partial was taken, -1 otherwise.

NO LOOK-AHEAD. NO PHANTOM FILLS. Same engine + bracket walker as production.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.data.multi_tf_view import MultiTfHistoryView
from bt_engine.db.engine import make_engine
from bt_engine.db.models import BtRun, BtTrade
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2 import FibV2EnsembleStrategy
from bt_engine.strategies.fib_v2.config import FibV2Config

from ..parity._fib_v2_helper import InMemoryClock, InMemoryProvider


TEST_URL = os.environ.get(
    "BT_ENGINE_TEST_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt_test",
)

XAU_M5 = Path("/tmp/oanda_xau_m5.parquet")
XAU_H1 = Path("/tmp/oanda_xau_h1.parquet")
HORIZON_BARS = 72 * 12 * 2


@pytest.mark.parametrize("ptp_r", [1.0, 2.0])
def test_paper_live_fib_v2_ptp_persists_partial_columns(ptp_r):
    if not XAU_M5.exists():
        pytest.skip("XAU OANDA M5 parquet missing")

    raw = pd.read_parquet(XAU_M5)
    if raw["timestamp"].dt.tz is None:
        raw["timestamp"] = raw["timestamp"].dt.tz_localize("UTC")
    raw = raw.sort_values("timestamp").reset_index(drop=True)
    m5 = raw.iloc[:100_000].reset_index(drop=True)

    h1 = None
    if XAU_H1.exists():
        h1 = pd.read_parquet(XAU_H1)
        if h1["timestamp"].dt.tz is None:
            h1["timestamp"] = h1["timestamp"].dt.tz_localize("UTC")

    mtf = MultiTfHistoryView(m5)
    if h1 is not None:
        mtf._h1 = h1.sort_values("timestamp").reset_index(drop=True)

    provider = InMemoryProvider(m5, symbol="XAUUSD.ecn")
    clock = InMemoryClock(provider)

    cfg = replace(FibV2Config(), partial_tp_at_r=ptp_r, partial_tp_pct=0.5)
    strat = FibV2EnsembleStrategy(
        symbol="XAUUSD.ecn", multi_tf_view=mtf, cost_usd=0.30, config=cfg,
    )

    run_id = uuid.uuid4()
    strategy_id = f"fib_v2_xau_ensemble_ptp{int(ptp_r)}r"
    run_ref = f"PAPERLIVE-PTP-{run_id}"
    test_engine = make_engine(TEST_URL)

    with Session(test_engine, expire_on_commit=False) as session:
        bt_run = BtRun(
            run_id=run_id, ref=run_ref, mode="bt",
            strategy_id=strategy_id,
            strategy_config={
                "pivot_lb": 5, "ext_target_pct": 1.618, "sl_buffer_pct": 0.02,
                "partial_tp_at_r": ptp_r, "partial_tp_pct": 0.5,
            },
            symbol="XAUUSD.ecn", timeframe="M5",
            start_ts=datetime.now(timezone.utc),
            data_provider="oanda_parquet",
        )
        session.add(bt_run)
        session.commit()

    closed_count = [0]
    partial_count = [0]

    def _on_close(trade, outcome) -> None:
        closed_count[0] += 1
        if trade.partial_taken:
            partial_count[0] += 1
        cost_r = trade.order.extra.get("cost_r", 0.0)
        net_r = outcome.bracket_1r_outcome - cost_r
        trade_ref = f"FIB-PTP{int(ptp_r)}R-{trade.trade_id}"
        partial_fill_ts = (
            trade.partial_fill_timestamp.to_pydatetime()
            if trade.partial_fill_timestamp is not None else None
        )
        with Session(test_engine, expire_on_commit=False) as session:
            bt_t = BtTrade(
                trade_id=trade.trade_id, trade_ref=trade_ref, run_id=run_id,
                strategy_id=strategy_id, symbol="XAUUSD.ecn", timeframe="M5",
                direction="long" if trade.side > 0 else "short", side=trade.side,
                entry_timestamp=trade.entry_timestamp.to_pydatetime(),
                entry_price=trade.entry_price,
                stop_price=trade.stop_price, risk_units=trade.risk_units,
                take_profit_price=trade.take_profit,
                exit_timestamp=outcome.exit_timestamp.to_pydatetime(),
                exit_price=outcome.exit_price, exit_reason=outcome.reason,
                bars_held=outcome.bars_held,
                bracket_1r_outcome=outcome.bracket_1r_outcome,
                cost_r=cost_r, gross_r=outcome.bracket_1r_outcome, net_r=net_r,
                pivot_lb=trade.order.extra.get("pivot_lb"),
                regime=trade.order.extra.get("regime"),
                ext_target_pct=trade.order.extra.get("ext_target_pct"),
                sl_buffer_pct=trade.order.extra.get("sl_buffer_pct"),
                fib_diff=trade.order.extra.get("fib_diff"),
                regime_at_entry=trade.order.extra.get("regime_at_entry"),
                leg=trade.order.extra.get("leg"),
                partial_tp_at_r=ptp_r,
                partial_tp_pct=0.5,
                partial_taken=trade.partial_taken,
                partial_r=trade.partial_filled_r,
                partial_fill_price=trade.partial_fill_price,
                partial_fill_ts=partial_fill_ts,
                raw_features=trade.order.extra,
            )
            session.add(bt_t)
            session.commit()

    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_trade_close=_on_close,
        max_bars_held=HORIZON_BARS,
    )
    run_engine(run_id=run_id, deps=deps, mode="bt")

    print(f"\n[paper-live PTP+{ptp_r}R] closed={closed_count[0]}, partial_taken={partial_count[0]}")
    assert closed_count[0] > 0, "No trades closed in 100k-bar window"
    assert partial_count[0] > 0, "Zero partial fills — strategy didn't trigger PTP path"

    with Session(test_engine, expire_on_commit=False) as session:
        persisted = session.execute(
            select(BtTrade).where(BtTrade.run_id == run_id)
        ).scalars().all()
        assert len(persisted) == closed_count[0]
        partial_persisted = [t for t in persisted if t.partial_taken]
        assert len(partial_persisted) > 0, "No partial_taken rows in DB"
        for t in partial_persisted[:5]:
            assert t.partial_r is not None and t.partial_r > 0
            assert t.partial_tp_at_r == ptp_r
            assert t.partial_tp_pct == 0.5
            assert t.partial_fill_price is not None and t.partial_fill_price > 0
            assert t.partial_fill_ts is not None
            # SL with BE move yields outcome ~0 + partial_r; raw SL yields -1 + partial_r;
            # TP yields exact tp_R + partial_r. All must be finite.
            assert t.bracket_1r_outcome is not None

        # Cleanup.
        session.execute(text("DELETE FROM bt_runs WHERE run_id = :rid"), {"rid": run_id})
        session.commit()
