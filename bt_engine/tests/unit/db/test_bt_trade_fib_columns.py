"""Unit test: BtTrade ORM has fib columns and roundtrip-writes them to DB.

Uses golddigger_bt_test DB. Cleans up created run after test.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from bt_engine.db.engine import make_engine
from bt_engine.db.models import BtRun, BtTrade
from sqlalchemy.orm import Session


TEST_URL = os.environ.get(
    "BT_ENGINE_TEST_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt_test",
)


@pytest.fixture
def test_session():
    engine = make_engine(TEST_URL)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def test_bt_trade_fib_columns_present_in_schema(test_session: Session):
    cols = test_session.execute(text(
        "select column_name from information_schema.columns where table_name='bt_trades' "
        "and column_name in ('pivot_lb','regime','ext_target_pct','sl_buffer_pct','fib_diff','regime_at_entry','leg')"
    )).scalars().all()
    assert set(cols) == {"pivot_lb", "regime", "ext_target_pct", "sl_buffer_pct",
                          "fib_diff", "regime_at_entry", "leg"}


def test_bt_trade_fib_roundtrip(test_session: Session):
    """Write a BtTrade with fib columns; read back; verify."""
    run_id = uuid.uuid4()
    trade_id = uuid.uuid4()
    run_ref = f"TEST-FIB-{uuid.uuid4()}"
    trade_ref = f"FIB-{trade_id}"

    run = BtRun(
        run_id=run_id, ref=run_ref, mode="bt", strategy_id="fib_v2_xau_ensemble",
        strategy_config={"pivot_lb": 5, "ext": 1.618},
        symbol="XAUUSD.ecn", timeframe="M5",
        start_ts=datetime.now(timezone.utc), data_provider="oanda_parquet",
    )
    test_session.add(run)
    test_session.flush()

    trade = BtTrade(
        trade_id=trade_id, trade_ref=trade_ref, run_id=run_id,
        strategy_id="fib_v2_xau_ensemble", symbol="XAUUSD.ecn", timeframe="M5",
        direction="long", side=1,
        entry_timestamp=datetime.now(timezone.utc),
        entry_price=4000.0, stop_price=3990.0, risk_units=10.0,
        take_profit_price=4030.0,
        # Fib V2 columns
        pivot_lb=5, regime="bull_strong", ext_target_pct=1.618, sl_buffer_pct=0.02,
        fib_diff=15.0, regime_at_entry="bull_strong", leg="long_bull_strong",
    )
    test_session.add(trade)
    test_session.commit()

    # Read back.
    fetched = test_session.execute(
        select(BtTrade).where(BtTrade.trade_id == trade_id)
    ).scalar_one()
    assert fetched.pivot_lb == 5
    assert fetched.regime == "bull_strong"
    assert fetched.ext_target_pct == 1.618
    assert fetched.sl_buffer_pct == 0.02
    assert fetched.fib_diff == 15.0
    assert fetched.regime_at_entry == "bull_strong"
    assert fetched.leg == "long_bull_strong"

    # Cleanup.
    test_session.execute(text("DELETE FROM bt_runs WHERE run_id = :rid"), {"rid": run_id})
    test_session.commit()
