"""Unit tests for BarWalkJournal."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd
import pytest
from sqlalchemy import select

from bt_engine.core.bar import Bar
from bt_engine.db.models import BtBarWalk, BtJournalEvent, BtTrade
from bt_engine.db.repo import BarWalkRepo, JournalRepo, RunRepo, TradeRepo
from bt_engine.journal.walker import BarWalkJournal


def _bar(ts: str, *, o: float, h: float, l: float, c: float) -> Bar:
    return Bar("XAUUSD", "M15", pd.Timestamp(ts), o, h, l, c, 1000.0)


def _make_journal(db_session, run_id) -> BarWalkJournal:
    RunRepo(db_session).create(
        run_id=run_id, ref="r", mode="bt", strategy_id="sdr001",
        strategy_config={}, symbol="X", timeframe="M15",
        start_ts=datetime(2026, 6, 29, tzinfo=timezone.utc),
        data_provider="csv",
    )
    return BarWalkJournal(BarWalkRepo(db_session), JournalRepo(db_session))


def _insert_trade(db_session, run_id, side: int = 1) -> uuid.UUID:
    trade_id = uuid.uuid4()
    direction = "demand" if side > 0 else "supply"
    db_session.add(
        BtTrade(
            trade_id=trade_id,
            trade_ref=f"T-{trade_id.hex[:6]}",
            run_id=run_id,
            strategy_id="sdr001",
            symbol="XAUUSD",
            timeframe="M15",
            direction=direction,
            side=side,
            entry_timestamp=datetime(2026, 6, 29, tzinfo=timezone.utc),
            entry_price=1000.0,
            stop_price=990.0,
            risk_units=10.0,
        )
    )
    db_session.flush()
    return trade_id


def test_walker_records_pre_entry_bars(db_session, run_id) -> None:
    j = _make_journal(db_session, run_id)
    tid = _insert_trade(db_session, run_id)
    j.open_walk(trade_id=tid, run_id=run_id, side=1)
    j.observe(tid, _bar("2026-06-29T00:00:00Z", o=100, h=101, l=99, c=100.5), "pre_retest")
    rows = db_session.execute(select(BtBarWalk)).scalars().all()
    assert len(rows) == 1
    assert rows[0].distance_to_entry_r is None  # no entry yet
    assert rows[0].mfe_r is None


def test_walker_records_in_trade_bars_with_r_metrics(db_session, run_id) -> None:
    j = _make_journal(db_session, run_id)
    tid = _insert_trade(db_session, run_id)
    j.open_walk(trade_id=tid, run_id=run_id, side=1)
    j.update_entry(tid, entry_price=1000.0, stop_price=990.0, take_profit=1020.0, risk_units=10.0)
    # bar that goes 5R favorable
    j.observe(tid, _bar("2026-06-29T00:15:00Z", o=1000, h=1050, l=995, c=1040), "in_trade")
    rows = db_session.execute(select(BtBarWalk)).scalars().all()
    assert len(rows) == 1
    # close=1040, entry=1000, risk=10, side=+1 -> distance_to_entry_r = 4.0
    assert rows[0].distance_to_entry_r == pytest.approx(4.0)
    # high=1050 -> MFE = 5R
    assert rows[0].mfe_r == pytest.approx(5.0)
    # low=995 -> MAE = -0.5R
    assert rows[0].mae_r == pytest.approx(-0.5)


def test_walker_short_side_metrics(db_session, run_id) -> None:
    j = _make_journal(db_session, run_id)
    tid = _insert_trade(db_session, run_id, side=-1)
    j.open_walk(trade_id=tid, run_id=run_id, side=-1)
    j.update_entry(tid, entry_price=1000.0, stop_price=1010.0, take_profit=980.0, risk_units=10.0)
    # bar that ranges 1010-985, close 990 -> short favorable 1R
    j.observe(tid, _bar("2026-06-29T00:15:00Z", o=1000, h=1010, l=985, c=990), "in_trade")
    row = db_session.execute(select(BtBarWalk)).scalar_one()
    # close=990, entry=1000, side=-1 -> distance_to_entry_r = (990-1000)*-1/10 = 1.0
    assert row.distance_to_entry_r == pytest.approx(1.0)
    # MFE: low=985 -> (1000-985)/10 = 1.5R
    assert row.mfe_r == pytest.approx(1.5)
    # MAE: high=1010 -> (1000-1010)/10 = -1.0R
    assert row.mae_r == pytest.approx(-1.0)


def test_walker_close_walk_marks_closed(db_session, run_id) -> None:
    j = _make_journal(db_session, run_id)
    tid = _insert_trade(db_session, run_id)
    j.open_walk(trade_id=tid, run_id=run_id, side=1)
    assert j.is_open(tid)
    j.close_walk(tid)
    assert not j.is_open(tid)
    # observe after close is a no-op
    j.observe(tid, _bar("2026-06-29T00:15:00Z", o=100, h=101, l=99, c=100), "post_exit")
    rows = db_session.execute(select(BtBarWalk)).scalars().all()
    assert len(rows) == 0


def test_walker_event_inserts_journal_row(db_session, run_id) -> None:
    j = _make_journal(db_session, run_id)
    tid = _insert_trade(db_session, run_id)
    j.event(
        trade_id=tid,
        run_id=run_id,
        ts=datetime(2026, 6, 29, tzinfo=timezone.utc),
        event_type="ENTRY_FILL",
        detail={"price": 1000.0},
    )
    rows = db_session.execute(select(BtJournalEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "ENTRY_FILL"
