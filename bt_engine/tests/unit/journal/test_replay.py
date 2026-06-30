"""Unit tests for replay_trade."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from bt_engine.db.models import BtBarWalk, BtJournalEvent, BtTrade
from bt_engine.db.repo import RunRepo
from bt_engine.journal.replay import replay_trade, story_to_dict


def _seed(db_session, run_id):
    RunRepo(db_session).create(
        run_id=run_id, ref="r", mode="bt", strategy_id="sdr001",
        strategy_config={}, symbol="X", timeframe="M15",
        start_ts=datetime(2026, 6, 29, tzinfo=timezone.utc),
        data_provider="csv",
    )
    tid = uuid.uuid4()
    entry_ts = datetime(2026, 6, 29, 14, 0, tzinfo=timezone.utc)
    db_session.add(
        BtTrade(
            trade_id=tid,
            trade_ref="SDR001-2026-06-29-D-0001",
            run_id=run_id,
            strategy_id="sdr001",
            symbol="XAUUSD",
            timeframe="M15",
            direction="demand",
            side=1,
            entry_timestamp=entry_ts,
            entry_price=1000.0,
            stop_price=990.0,
            take_profit_price=1020.0,
            risk_units=10.0,
            exit_timestamp=entry_ts + timedelta(minutes=45),
            exit_price=1020.0,
            exit_reason="TP",
            bars_held=3,
            bracket_1r_outcome=2.0,
            cost_r=0.02,
            gross_r=2.0,
            net_r=1.98,
        )
    )
    db_session.flush()
    for i in range(3):
        db_session.add(
            BtBarWalk(
                trade_id=tid,
                run_id=run_id,
                bar_ts=entry_ts + timedelta(minutes=15 * i),
                phase="in_trade",
                open=1000.0,
                high=1010.0 + i,
                low=995.0,
                close=1005.0 + i * 5,
                mfe_r=0.5 + i,
                mae_r=-0.5,
                unrealised_r=0.5 + i,
            )
        )
    db_session.add(
        BtJournalEvent(
            trade_id=tid,
            run_id=run_id,
            ts=entry_ts,
            event_type="ENTRY_FILL",
            detail={"price": 1000.0},
        )
    )
    db_session.add(
        BtJournalEvent(
            trade_id=tid,
            run_id=run_id,
            ts=entry_ts + timedelta(minutes=45),
            event_type="EXIT_TP",
            detail={"price": 1020.0},
        )
    )
    db_session.flush()
    return tid


def test_replay_returns_full_story(db_session, run_id) -> None:
    tid = _seed(db_session, run_id)
    story = replay_trade(db_session, "SDR001-2026-06-29-D-0001")
    assert story.trade_id == tid
    assert story.direction == "demand"
    assert story.net_r == 1.98
    assert len(story.bars) == 3
    assert len(story.events) == 2
    assert story.events[0]["event_type"] == "ENTRY_FILL"
    assert story.events[1]["event_type"] == "EXIT_TP"
    assert story.bars[0]["mfe_r"] == 0.5
    assert story.bars[-1]["close"] == 1015.0


def test_replay_unknown_trade_raises(db_session, run_id) -> None:
    import pytest

    with pytest.raises(LookupError):
        replay_trade(db_session, "SDR001-9999-99-99-X-9999")


def test_story_to_dict_is_json_friendly(db_session, run_id) -> None:
    import json

    _seed(db_session, run_id)
    story = replay_trade(db_session, "SDR001-2026-06-29-D-0001")
    d = story_to_dict(story)
    # must be JSON-serialisable
    json.dumps(d)
    assert isinstance(d["trade_id"], str)
    assert isinstance(d["entry_timestamp"], str)
