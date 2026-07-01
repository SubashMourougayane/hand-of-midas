"""Unit tests for BrokerReconciler: parse deals, retry on miss, idempotency."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from bt_engine.db.engine import make_engine
from bt_engine.db.models import BtRun, BtTrade
from bt_engine.runner.broker_reconciler import (
    ReconciliationResult,
    _parse_broker_time,
    _to_utc_dt,
    find_closed_deal,
    reconcile_trade,
    retry_unreconciled_trades,
)


TEST_DB_URL = os.environ.get(
    "BT_ENGINE_TEST_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt_test",
)


@dataclass
class _FakeBridge:
    """Fake DWX bridge for tests. call_count tracks read attempts."""
    deals: list[dict[str, Any]] = field(default_factory=list)
    call_count: int = 0
    deals_after_n_calls: int = 0
    _pending: list[dict[str, Any]] = field(default_factory=list)

    def closed_orders(self) -> list[dict[str, Any]]:
        self.call_count += 1
        if self.call_count >= self.deals_after_n_calls:
            return list(self._pending or self.deals)
        return []

    def prime(self, deals: list[dict[str, Any]], appear_at_call: int = 1) -> None:
        self._pending = deals
        self.deals_after_n_calls = appear_at_call


def _make_run_and_trade(session: Session, run_id, trade_id) -> None:
    run = BtRun(
        run_id=run_id, ref=f"TEST-{run_id.hex[:8]}", mode="live",
        strategy_id="test", strategy_config={}, symbol="XAUUSD.ecn",
        timeframe="M15",
        start_ts=datetime.now(timezone.utc),
        data_provider="test",
    )
    session.add(run)
    session.flush()
    session.add(BtTrade(
        trade_id=trade_id,
        trade_ref=f"TT-{trade_id.hex[:8]}",
        run_id=run_id, strategy_id="test",
        symbol="XAUUSD.ecn", timeframe="M15",
        direction="short", side=-1,
        entry_timestamp=datetime(2026, 7, 1, 11, 45, tzinfo=timezone.utc),
        entry_price=3977.04, stop_price=3983.04, risk_units=6.0,
        exit_timestamp=datetime(2026, 7, 1, 12, 45, tzinfo=timezone.utc),
        exit_price=3977.04, exit_reason="SL_BE",
    ))
    session.commit()


@pytest.fixture
def session():
    engine = make_engine(TEST_DB_URL)
    s = Session(engine)
    # Clean bt_trades / bt_runs before each test.
    from sqlalchemy import text as _t
    s.execute(_t("TRUNCATE bt_signals, bt_bar_walk, bt_journal_events, bt_trades, bt_runs CASCADE"))
    s.commit()
    yield s
    s.close()


def test_parse_broker_time_ea_format() -> None:
    dt = _parse_broker_time("2026.07.01 12:45:28")
    assert dt == datetime(2026, 7, 1, 12, 45, 28)


def test_parse_broker_time_empty_and_invalid() -> None:
    assert _parse_broker_time("") is None
    assert _parse_broker_time("nonsense") is None


def test_to_utc_dt_subtracts_server_offset() -> None:
    # Broker server = UTC+3. Broker time 12:45 → UTC 09:45.
    naive = datetime(2026, 7, 1, 12, 45, 0)
    utc = _to_utc_dt(naive, server_utc_offset_hours=3)
    assert utc == datetime(2026, 7, 1, 9, 45, 0, tzinfo=timezone.utc)


def test_find_closed_deal_matches_ticket() -> None:
    bridge = _FakeBridge(deals=[
        {"ticket": "111", "profit": 1.0},
        {"ticket": "222", "profit": -6.0},
    ])
    # deals_after_n_calls=0 -> return immediately
    bridge.deals_after_n_calls = 0
    bridge._pending = bridge.deals
    d = find_closed_deal(bridge, "222")
    assert d is not None
    assert d["profit"] == -6.0


def test_find_closed_deal_missing_returns_none() -> None:
    bridge = _FakeBridge(deals=[{"ticket": "111"}])
    bridge.deals_after_n_calls = 0
    bridge._pending = bridge.deals
    assert find_closed_deal(bridge, "999") is None


def test_reconcile_trade_persists_broker_columns(session) -> None:
    run_id = uuid.uuid4()
    trade_id = uuid.uuid4()
    _make_run_and_trade(session, run_id, trade_id)

    bridge = _FakeBridge()
    bridge.prime([{
        "ticket": "2115780920",
        "symbol": "XAUUSD.ecn", "type": "SELL", "volume": 0.01,
        "open_price": 3977.04, "close_price": 3983.04,
        "open_time": "2026.07.01 11:45:00",
        "close_time": "2026.07.01 12:45:28",
        "profit": -6.00, "swap": 0.0, "commission": -0.07,
        "deal_reason": "SL",
    }], appear_at_call=1)

    res = reconcile_trade(
        bridge=bridge, session=session,
        trade_id=trade_id, ticket="2115780920",
        server_utc_offset_hours=3, max_retries=3, backoff_s=0.01,
    )
    assert res.matched is True
    assert res.broker_gross_usd == -6.00
    assert res.broker_commission_usd == -0.07
    assert res.broker_swap_usd == 0.0
    assert res.broker_net_usd == pytest.approx(-6.07)
    assert res.broker_exit_reason == "SL"
    assert res.broker_close_ts == datetime(2026, 7, 1, 9, 45, 28, tzinfo=timezone.utc)

    session.expire_all()
    tr = session.get(BtTrade, trade_id)
    assert tr.broker_gross_usd == -6.00
    assert tr.broker_net_usd == pytest.approx(-6.07)
    assert tr.broker_exit_reason == "SL"
    assert tr.broker_reconciled_at is not None


def test_reconcile_trade_retries_when_deal_not_yet_in_file(session) -> None:
    run_id = uuid.uuid4()
    trade_id = uuid.uuid4()
    _make_run_and_trade(session, run_id, trade_id)

    bridge = _FakeBridge()
    bridge.prime([{
        "ticket": "T99", "profit": 1.42, "commission": -0.35, "swap": 0.0,
        "close_price": 3970.0, "close_time": "2026.07.01 12:45:28",
        "deal_reason": "TP",
    }], appear_at_call=4)  # only appears on 4th read

    res = reconcile_trade(
        bridge=bridge, session=session,
        trade_id=trade_id, ticket="T99",
        server_utc_offset_hours=0, max_retries=10, backoff_s=0.01,
    )
    assert res.matched is True
    assert res.broker_gross_usd == 1.42
    assert bridge.call_count == 4  # exactly the retry that succeeded


def test_reconcile_trade_gives_up_after_max_retries(session) -> None:
    run_id = uuid.uuid4()
    trade_id = uuid.uuid4()
    _make_run_and_trade(session, run_id, trade_id)

    bridge = _FakeBridge()
    # never primes -> closed_orders always returns []
    bridge.deals_after_n_calls = 999
    bridge._pending = []

    res = reconcile_trade(
        bridge=bridge, session=session,
        trade_id=trade_id, ticket="XYZ",
        max_retries=3, backoff_s=0.01,
    )
    assert res.matched is False
    # broker_ticket persisted for future retry, but no other broker_* set.
    session.expire_all()
    tr = session.get(BtTrade, trade_id)
    assert tr.broker_ticket == "XYZ"
    assert tr.broker_reconciled_at is None
    assert tr.broker_gross_usd is None


def test_reconcile_trade_is_idempotent_when_already_reconciled(session) -> None:
    run_id = uuid.uuid4()
    trade_id = uuid.uuid4()
    _make_run_and_trade(session, run_id, trade_id)
    # Mark trade as already reconciled with sentinel values.
    from sqlalchemy import update as _u
    session.execute(_u(BtTrade).where(BtTrade.trade_id == trade_id).values(
        broker_ticket="OLD", broker_gross_usd=-6.00, broker_net_usd=-6.07,
        broker_reconciled_at=datetime.now(timezone.utc),
    ))
    session.commit()

    bridge = _FakeBridge()
    bridge.deals_after_n_calls = 0
    bridge._pending = [{"ticket": "OLD", "profit": 999.99}]  # different value

    res = reconcile_trade(
        bridge=bridge, session=session,
        trade_id=trade_id, ticket="OLD",
        max_retries=3, backoff_s=0.01,
    )
    assert res.matched is True
    assert res.broker_gross_usd == -6.00  # NOT overwritten
    assert bridge.call_count == 0  # never read (short-circuited)


def test_retry_unreconciled_sweep_processes_pending(session) -> None:
    run_id = uuid.uuid4()
    tid1, tid2 = uuid.uuid4(), uuid.uuid4()
    _make_run_and_trade(session, run_id, tid1)
    # Second trade re-uses the same run — insert only the trade row.
    session.add(BtTrade(
        trade_id=tid2, trade_ref=f"TT-{tid2.hex[:8]}",
        run_id=run_id, strategy_id="test",
        symbol="XAUUSD.ecn", timeframe="M15",
        direction="long", side=1,
        entry_timestamp=datetime(2026, 7, 1, 11, 45, tzinfo=timezone.utc),
        entry_price=3980.0, stop_price=3975.0, risk_units=5.0,
        exit_timestamp=datetime(2026, 7, 1, 12, 45, tzinfo=timezone.utc),
        exit_price=3985.0, exit_reason="TP",
    ))
    session.commit()
    from sqlalchemy import update as _u
    session.execute(_u(BtTrade).where(BtTrade.trade_id == tid1).values(broker_ticket="A1"))
    session.execute(_u(BtTrade).where(BtTrade.trade_id == tid2).values(broker_ticket="A2"))
    session.commit()

    bridge = _FakeBridge()
    bridge.deals_after_n_calls = 0
    bridge._pending = [
        {"ticket": "A1", "profit": 5.0, "commission": 0.0, "swap": 0.0,
         "close_price": 100.0, "close_time": "2026.07.01 10:00:00",
         "deal_reason": "TP"},
        {"ticket": "A2", "profit": -3.0, "commission": 0.0, "swap": 0.0,
         "close_price": 101.0, "close_time": "2026.07.01 10:00:00",
         "deal_reason": "SL"},
    ]

    results = retry_unreconciled_trades(
        bridge=bridge, session=session, run_id=run_id,
        server_utc_offset_hours=0,
    )
    assert len(results) == 2
    assert all(r.matched for r in results)
    session.expire_all()
    tr1 = session.get(BtTrade, tid1)
    tr2 = session.get(BtTrade, tid2)
    assert tr1.broker_gross_usd == 5.0
    assert tr2.broker_gross_usd == -3.0
