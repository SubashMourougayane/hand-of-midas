"""Unit tests for streaming repos (RunRepo, TradeRepo, JournalRepo, BarWalkRepo, SignalRepo)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select

from bt_engine.db.models import (
    BtAccountSnapshot,
    BtBarWalk,
    BtJournalEvent,
    BtRun,
    BtSignal,
    BtTrade,
)
from bt_engine.db.engine import reset_engine_for_testing, session_scope
from bt_engine.db.repo import (
    AccountSnapshotRepo,
    BarWalkRepo,
    JournalRepo,
    RunRepo,
    SignalRepo,
    TradeRepo,
)


def _now() -> datetime:
    return datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)


def _make_trade(run_id: uuid.UUID, entry_ts: datetime | None = None) -> BtTrade:
    return BtTrade(
        trade_id=uuid.uuid4(),
        trade_ref=f"SDR001-2019-06-12-S-{uuid.uuid4().hex[:4]}",
        run_id=run_id,
        strategy_id="sdr001",
        symbol="XAUUSD",
        timeframe="M15",
        zone_id=42,
        zone_tf="15min",
        spec_name="m15_2c_1atr",
        direction="supply",
        side=-1,
        upper=1338.4,
        lower=1336.55,
        entry_timestamp=entry_ts or _now(),
        entry_price=1332.54,
        stop_price=1338.92,
        risk_units=6.38,
    )


def test_run_repo_create_and_close(db_session, run_id) -> None:
    repo = RunRepo(db_session)
    run = repo.create(
        run_id=run_id,
        ref="BT-20260629-SDR001-0001",
        mode="bt",
        strategy_id="sdr001",
        strategy_config={"foo": 1},
        symbol="XAUUSD",
        timeframe="M15",
        start_ts=_now(),
        data_provider="csv",
    )
    assert run.run_id == run_id

    fetched = db_session.get(BtRun, run_id)
    assert fetched is not None
    assert fetched.ref == "BT-20260629-SDR001-0001"
    assert fetched.end_ts is None

    end = _now()
    repo.close(run_id, end_ts=end)
    db_session.refresh(fetched)
    assert fetched.end_ts == end


def test_trade_repo_open_and_close(db_session, run_id) -> None:
    RunRepo(db_session).create(
        run_id=run_id, ref="r", mode="bt", strategy_id="sdr001",
        strategy_config={}, symbol="X", timeframe="M15",
        start_ts=_now(), data_provider="csv",
    )
    repo = TradeRepo(db_session)
    trade = _make_trade(run_id)
    repo.upsert_open(trade)
    fetched = db_session.get(BtTrade, trade.trade_id)
    assert fetched is not None
    assert fetched.exit_timestamp is None

    repo.close(
        trade.trade_id,
        exit_timestamp=_now(),
        exit_price=1335.0,
        exit_reason="TP",
        bars_held=12,
        bracket_1r_outcome=1.0,
        cost_r=0.02,
        gross_r=1.0,
        net_r=0.98,
    )
    db_session.refresh(fetched)
    assert fetched.exit_reason == "TP"
    assert fetched.net_r == 0.98


def test_trade_repo_close_persists_partial_tp_fields(db_session, run_id) -> None:
    """TradeRepo.close() must persist partial-TP outcome fields when supplied.
    Regression guard for Phase 7 audit finding: live path was dropping partial data.
    """
    RunRepo(db_session).create(
        run_id=run_id, ref="r-ptp", mode="bt", strategy_id="fib_v2_xau_ensemble_ptp1r",
        strategy_config={"partial_tp_at_r": 1.0, "partial_tp_pct": 0.5},
        symbol="X", timeframe="M5",
        start_ts=_now(), data_provider="csv",
    )
    repo = TradeRepo(db_session)
    trade = _make_trade(run_id)
    repo.upsert_open(trade)

    partial_ts = _now()
    repo.close(
        trade.trade_id,
        exit_timestamp=_now(),
        exit_price=1340.0,
        exit_reason="TP",
        bars_held=20,
        bracket_1r_outcome=2.5,
        cost_r=0.02,
        gross_r=2.5,
        net_r=2.48,
        partial_taken=True,
        partial_r=0.5,
        partial_fill_price=1335.0,
        partial_fill_ts=partial_ts,
    )
    fetched = db_session.get(BtTrade, trade.trade_id)
    db_session.refresh(fetched)
    assert fetched.partial_taken is True
    assert fetched.partial_r == 0.5
    assert fetched.partial_fill_price == 1335.0
    assert fetched.partial_fill_ts is not None


def test_trade_repo_close_omits_partial_when_not_supplied(db_session, run_id) -> None:
    """Baseline path (no partial_tp configured) must not touch partial columns."""
    RunRepo(db_session).create(
        run_id=run_id, ref="r-base", mode="bt", strategy_id="fib_v2_xau_ensemble",
        strategy_config={}, symbol="X", timeframe="M5",
        start_ts=_now(), data_provider="csv",
    )
    repo = TradeRepo(db_session)
    trade = _make_trade(run_id)
    repo.upsert_open(trade)
    repo.close(
        trade.trade_id,
        exit_timestamp=_now(), exit_price=1335.0, exit_reason="TP",
        bars_held=12, bracket_1r_outcome=1.0,
        cost_r=0.02, gross_r=1.0, net_r=0.98,
    )
    fetched = db_session.get(BtTrade, trade.trade_id)
    db_session.refresh(fetched)
    # Default-None — not set by repo, not overwritten.
    assert fetched.partial_taken is None
    assert fetched.partial_r is None


def test_journal_repo_insert(db_session, run_id) -> None:
    RunRepo(db_session).create(
        run_id=run_id, ref="r", mode="bt", strategy_id="sdr001",
        strategy_config={}, symbol="X", timeframe="M15",
        start_ts=_now(), data_provider="csv",
    )
    trade = _make_trade(run_id)
    TradeRepo(db_session).upsert_open(trade)
    repo = JournalRepo(db_session)
    repo.insert(
        trade_id=trade.trade_id,
        run_id=run_id,
        ts=_now(),
        event_type="ENTRY_FILL",
        detail={"price": 1332.54, "slip_bps": 0.0},
    )
    rows = db_session.execute(select(BtJournalEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "ENTRY_FILL"
    assert rows[0].detail["price"] == 1332.54


def test_bar_walk_repo_insert(db_session, run_id) -> None:
    RunRepo(db_session).create(
        run_id=run_id, ref="r", mode="bt", strategy_id="sdr001",
        strategy_config={}, symbol="X", timeframe="M15",
        start_ts=_now(), data_provider="csv",
    )
    trade = _make_trade(run_id)
    TradeRepo(db_session).upsert_open(trade)
    repo = BarWalkRepo(db_session)
    repo.insert(
        BtBarWalk(
            trade_id=trade.trade_id,
            run_id=run_id,
            bar_ts=_now(),
            phase="in_trade",
            open=1332.0,
            high=1333.0,
            low=1331.5,
            close=1332.5,
            mfe_r=0.5,
            mae_r=-0.1,
        )
    )
    rows = db_session.execute(select(BtBarWalk)).scalars().all()
    assert len(rows) == 1


def test_signal_repo_insert(db_session, run_id) -> None:
    RunRepo(db_session).create(
        run_id=run_id, ref="r", mode="bt", strategy_id="sdr001",
        strategy_config={}, symbol="X", timeframe="M15",
        start_ts=_now(), data_provider="csv",
    )
    repo = SignalRepo(db_session)
    repo.insert(run_id=run_id, ts=_now(), zone_id=42, status="taken")
    repo.insert(run_id=run_id, ts=_now(), zone_id=43, status="rejected_by_clean_top3", reason="rank_4")
    rows = db_session.execute(select(BtSignal)).scalars().all()
    assert len(rows) == 2


def test_account_snapshot_repo_unique_constraint(db_session, run_id) -> None:
    RunRepo(db_session).create(
        run_id=run_id, ref="r", mode="bt", strategy_id="sdr001",
        strategy_config={}, symbol="X", timeframe="M15",
        start_ts=_now(), data_provider="csv",
    )
    repo = AccountSnapshotRepo(db_session)
    ts = _now()
    repo.insert(run_id=run_id, ts=ts, balance=10000.0, equity=10000.0, open_pnl=0.0, open_position=0)
    rows = db_session.execute(select(BtAccountSnapshot)).scalars().all()
    assert len(rows) == 1
    assert rows[0].balance == 10000.0


def test_session_scope_context_manager(db_engine, run_id) -> None:
    reset_engine_for_testing(str(db_engine.url))
    with session_scope() as s:
        RunRepo(s).create(
            run_id=run_id,
            ref="scope-r",
            mode="bt",
            strategy_id="sdr001",
            strategy_config={},
            symbol="X",
            timeframe="M15",
            start_ts=_now(),
            data_provider="csv",
        )
    with session_scope() as s:
        assert s.get(BtRun, run_id) is not None
