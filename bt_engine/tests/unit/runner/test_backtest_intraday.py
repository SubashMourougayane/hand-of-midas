"""Smoke test for run_backtest_intraday — engine-driven M15 BT with buffered persistence."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bt_engine.db.engine import make_engine
from bt_engine.db.models import BtBarWalk, BtJournalEvent, BtRun, BtSignal, BtTrade
from bt_engine.runner.backtest import run_backtest_intraday


M5_PARQUET = Path("/tmp/oanda_xau_m5.parquet")

pytestmark = pytest.mark.skipif(
    not M5_PARQUET.is_file(), reason="/tmp/oanda_xau_m5.parquet not seeded"
)


TEST_DB_URL = os.environ.get(
    "BT_ENGINE_TEST_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt_test",
)


def _counts(session: Session, run_id: str) -> dict[str, int]:
    return {
        "trades": session.execute(
            select(func.count()).select_from(BtTrade).where(BtTrade.run_id == run_id)
        ).scalar_one(),
        "signals": session.execute(
            select(func.count()).select_from(BtSignal).where(BtSignal.run_id == run_id)
        ).scalar_one(),
        "journal": session.execute(
            select(func.count()).select_from(BtJournalEvent).where(BtJournalEvent.run_id == run_id)
        ).scalar_one(),
        "walk": session.execute(
            select(func.count()).select_from(BtBarWalk).where(BtBarWalk.run_id == run_id)
        ).scalar_one(),
    }


def test_run_backtest_intraday_persists_full_journal(db_session) -> None:
    """Engine-driven BT populates trades + signals + journal + bar_walk in one shot."""
    result = run_backtest_intraday(
        strategy="fib_v2_intraday_a",
        m5_parquet=M5_PARQUET,
        symbol="XAUUSD.ecn",
        timeframe="M15",
        cost_usd=0.65,
        db_url=TEST_DB_URL,
        max_bars=1500,
    )
    assert result.bars_processed == 1500
    assert result.trades_open >= 1
    assert result.signals > 0
    assert result.bar_walk_rows > 0

    engine = make_engine(TEST_DB_URL)
    with Session(engine) as s:
        run = s.get(BtRun, result.run_id)
        assert run is not None
        assert run.mode == "bt"
        assert run.strategy_id == "fib_v2_intraday_a"
        assert run.end_ts is not None

        counts = _counts(s, result.run_id)
        assert counts["trades"] == result.trades_open
        assert counts["signals"] == result.signals
        assert counts["walk"] == result.bar_walk_rows
        # Each trade contributes at least one journal event (ENTRY_FILL).
        assert counts["journal"] >= counts["trades"]


def test_run_backtest_intraday_with_equity_sizer(db_session) -> None:
    """Equity sizer wires through: qty > 0, pnl_usd populated per closed trade."""
    result = run_backtest_intraday(
        strategy="fib_v2_intraday_a",
        m5_parquet=M5_PARQUET,
        symbol="XAUUSD.ecn",
        timeframe="M15",
        cost_usd=0.65,
        use_equity_sizer=True,
        start_balance=10000.0,
        risk_pct=0.015,
        db_url=TEST_DB_URL,
        max_bars=1500,
    )
    assert result.net_usd is not None

    engine = make_engine(TEST_DB_URL)
    with Session(engine) as s:
        trades = s.execute(
            select(BtTrade).where(BtTrade.run_id == result.run_id)
        ).scalars().all()
        assert trades, "no trades emitted"
        for t in trades:
            rf = t.raw_features or {}
            # Every trade must have equity + qty snapshots for downstream $ PnL.
            assert "equity_at_entry" in rf
            assert "qty_lots" in rf
            if t.net_r is not None:
                assert "pnl_usd" in rf
