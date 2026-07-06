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
    _closed_orders_is_fresh,
    _parse_broker_time,
    _ticket_still_open,
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
    # Guard support (2026-07-02): staleness + still-open checks.
    open_tickets: set[str] = field(default_factory=set)   # tickets still live
    closed_orders_age_s: float = 0.0                       # mtime age of closed_orders.json
    open_orders_age_s: float = 0.0                         # mtime age of open_orders.json

    def closed_orders(self) -> list[dict[str, Any]]:
        self.call_count += 1
        if self.call_count >= self.deals_after_n_calls:
            return list(self._pending or self.deals)
        return []

    def open_orders(self) -> dict[str, Any]:
        return {str(t): {"symbol": "XAUUSD.ecn"} for t in self.open_tickets}

    def mtime(self, name: str) -> float:
        import time as _t
        if name == "closed_orders.json":
            return _t.time() - self.closed_orders_age_s
        if name == "open_orders.json":
            return _t.time() - self.open_orders_age_s
        return _t.time()

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


def test_find_closed_deal_aggregates_partial_and_final_close() -> None:
    """L99 audit suspect #5 regression: MT5 partial-close creates 2 deal rows
    for the same position_id. Reconciler must sum profit/comm/swap across them
    and use the LAST row's exit_reason + close_time as authoritative.
    """
    bridge = _FakeBridge(deals=[
        {"ticket": "555", "symbol": "XAUUSD.ecn", "type": "BUY", "volume": 0.01,
         "close_price": 4027.62, "close_time": "2026.07.01 15:54:28",
         "profit": -0.10, "swap": 0.0, "commission": -0.05,
         "deal_reason": "EXPERT"},
        {"ticket": "555", "symbol": "XAUUSD.ecn", "type": "BUY", "volume": 0.01,
         "close_price": 4027.60, "close_time": "2026.07.01 15:54:29",
         "profit": -0.08, "swap": 0.0, "commission": -0.05,
         "deal_reason": "SL"},
    ])
    bridge.deals_after_n_calls = 0
    bridge._pending = bridge.deals
    d = find_closed_deal(bridge, "555")
    assert d is not None
    assert d["profit"] == pytest.approx(-0.18)
    assert d["commission"] == pytest.approx(-0.10)
    assert d["volume"] == pytest.approx(0.02)
    assert d["deal_reason"] == "SL"  # last row wins
    assert d["close_time"] == "2026.07.01 15:54:29"
    assert d["_deal_count"] == 2


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


# ---------------------------------------------------------------------------
# Reconciler staleness guards (2026-07-02 incident).
#
# A stale closed_orders.json (observed >2h old) carried a ghost "closed" row for
# a ticket whose remainder was STILL OPEN after a partial-TP. Reconciling from it
# wrongly marked the live position closed. Two guards prevent recurrence:
#   1. never close a ticket still present in a FRESH open_orders.json
#   2. distrust closed_orders.json when its mtime is stale
# ---------------------------------------------------------------------------


def test_ticket_still_open_true_when_present_and_fresh() -> None:
    b = _FakeBridge(open_tickets={"2121027691"}, open_orders_age_s=2.0)
    assert _ticket_still_open(b, "2121027691") is True


def test_ticket_still_open_false_when_absent() -> None:
    b = _FakeBridge(open_tickets={"999"}, open_orders_age_s=2.0)
    assert _ticket_still_open(b, "2121027691") is False


def test_ticket_still_open_false_when_open_orders_stale() -> None:
    # open_orders too old to prove the position is still open -> don't block close.
    b = _FakeBridge(open_tickets={"2121027691"}, open_orders_age_s=999.0)
    assert _ticket_still_open(b, "2121027691") is False


def test_closed_orders_fresh_true_when_recent() -> None:
    assert _closed_orders_is_fresh(_FakeBridge(closed_orders_age_s=10.0)) is True


def test_closed_orders_fresh_false_when_stale() -> None:
    # 2.6h old -> the incident condition.
    assert _closed_orders_is_fresh(_FakeBridge(closed_orders_age_s=9500.0)) is False


def test_reconcile_defers_when_ticket_still_open(session) -> None:
    """GUARD 1: ticket live in fresh open_orders -> do NOT reconcile-close."""
    run_id = uuid.uuid4(); trade_id = uuid.uuid4()
    _make_run_and_trade(session, run_id, trade_id)
    bridge = _FakeBridge(open_tickets={"2121027691"}, open_orders_age_s=1.0,
                         closed_orders_age_s=1.0)
    bridge.prime([{"ticket": "2121027691", "profit": 401.64, "commission": -0.77,
                   "swap": 0.0, "close_price": 4131.71,
                   "close_time": "2026.07.02 18:15:13", "deal_reason": "EXPERT"}],
                 appear_at_call=0)
    res = reconcile_trade(bridge=bridge, session=session, trade_id=trade_id,
                          ticket="2121027691", server_utc_offset_hours=3,
                          max_retries=2, backoff_s=0.01)
    assert res.matched is False
    assert bridge.call_count == 0  # never even read closed_orders
    session.expire_all()
    tr = session.get(BtTrade, trade_id)
    assert tr.broker_reconciled_at is None  # NOT marked closed


def test_reconcile_skips_when_closed_orders_stale(session) -> None:
    """GUARD 2: stale closed_orders.json AND open_orders too stale to confirm the
    ticket is gone -> skip, retry later. (open_orders stale => cannot prove
    closure => the ghost-row risk the guard exists for is still live.)"""
    run_id = uuid.uuid4(); trade_id = uuid.uuid4()
    _make_run_and_trade(session, run_id, trade_id)
    bridge = _FakeBridge(open_tickets=set(), open_orders_age_s=9999.0,
                         closed_orders_age_s=9500.0)  # both stale
    bridge.prime([{"ticket": "T1", "profit": 5.0, "commission": 0.0, "swap": 0.0,
                   "close_price": 100.0, "close_time": "2026.07.01 10:00:00",
                   "deal_reason": "TP"}], appear_at_call=0)
    res = reconcile_trade(bridge=bridge, session=session, trade_id=trade_id,
                          ticket="T1", max_retries=2, backoff_s=0.01)
    assert res.matched is False
    session.expire_all()
    tr = session.get(BtTrade, trade_id)
    assert tr.broker_reconciled_at is None


def test_reconcile_proceeds_when_stale_but_ticket_confirmed_gone(session) -> None:
    """2026-07-06 fix: stale closed_orders.json is OK to trust when a FRESH
    open_orders.json positively confirms the ticket is gone (e.g. a weekend SL
    that closed while the book was quiet, so closed_orders never rewrote). This
    is what backfills broker_net_usd for exit_reason=BROKER_CLOSED trades that
    would otherwise stay $-NULL forever (the +$384 dashboard overstatement)."""
    run_id = uuid.uuid4(); trade_id = uuid.uuid4()
    _make_run_and_trade(session, run_id, trade_id)
    bridge = _FakeBridge(open_tickets=set(), open_orders_age_s=1.0,     # fresh
                         closed_orders_age_s=9500.0)                     # stale
    bridge.prime([{"ticket": "T1", "profit": 85.68, "commission": 0.0, "swap": 0.0,
                   "close_price": 4181.13, "close_time": "2026.07.06 01:07:11",
                   "deal_reason": "SL"}], appear_at_call=0)
    res = reconcile_trade(bridge=bridge, session=session, trade_id=trade_id,
                          ticket="T1", max_retries=2, backoff_s=0.01)
    assert res.matched is True
    assert res.broker_net_usd == 85.68
    session.expire_all()
    tr = session.get(BtTrade, trade_id)
    assert tr.broker_reconciled_at is not None


def test_reconcile_proceeds_when_fresh_and_not_open(session) -> None:
    """Both guards pass (ticket closed + closed_orders fresh) -> reconcile."""
    run_id = uuid.uuid4(); trade_id = uuid.uuid4()
    _make_run_and_trade(session, run_id, trade_id)
    bridge = _FakeBridge(open_tickets=set(), open_orders_age_s=1.0,
                         closed_orders_age_s=1.0)
    bridge.prime([{"ticket": "T2", "profit": 5.0, "commission": -0.07, "swap": 0.0,
                   "close_price": 100.0, "close_time": "2026.07.01 10:00:00",
                   "deal_reason": "TP"}], appear_at_call=0)
    res = reconcile_trade(bridge=bridge, session=session, trade_id=trade_id,
                          ticket="T2", server_utc_offset_hours=0,
                          max_retries=2, backoff_s=0.01)
    assert res.matched is True
    assert res.broker_gross_usd == 5.0


# ---------------------------------------------------------------------------
# GUARD 3 (F7): volume-completeness backstop for partial-TP positions.
#
# find_closed_deal aggregates all deals sharing the ticket, but the partial-close
# deal and the final-close deal do NOT land in closed_orders.json simultaneously.
# A reconcile firing in that window sees only the (usually profitable) partial and
# would bank it as the whole trade + lock it forever. That is the +$544-instead-
# of-+$5 overstatement (ticket 2125574587). GUARD 1 catches this when open_orders
# is FRESH; GUARD 3 is the backstop for when open_orders is STALE.
# ---------------------------------------------------------------------------


def _make_partial_trade(session: Session, run_id, trade_id, full_lots: float) -> None:
    """A trade whose FULL submitted size is recorded in raw_features.qty_lots."""
    run = BtRun(
        run_id=run_id, ref=f"TEST-{run_id.hex[:8]}", mode="live",
        strategy_id="test", strategy_config={}, symbol="XAUUSD.ecn",
        timeframe="M15", start_ts=datetime.now(timezone.utc), data_provider="test",
    )
    session.add(run)
    session.flush()
    session.add(BtTrade(
        trade_id=trade_id, trade_ref=f"TT-{trade_id.hex[:8]}",
        run_id=run_id, strategy_id="test",
        symbol="XAUUSD.ecn", timeframe="M15", direction="long", side=1,
        entry_timestamp=datetime(2026, 7, 3, 13, 30, tzinfo=timezone.utc),
        entry_price=4171.49, stop_price=4160.03, risk_units=11.46,
        exit_timestamp=datetime(2026, 7, 3, 16, 7, tzinfo=timezone.utc),
        exit_price=4160.03, exit_reason="SL",
        partial_taken=True,
        raw_features={"qty_lots": full_lots, "leg": "intraday_a_long"},
    ))
    session.commit()


def test_reconcile_defers_when_only_partial_volume_closed(session) -> None:
    """GUARD 3: full size 0.12 but only the 0.06 partial deal has landed (stale
    open_orders so GUARD 1 passed) -> defer, do NOT bank/lock the partial."""
    run_id = uuid.uuid4(); trade_id = uuid.uuid4()
    _make_partial_trade(session, run_id, trade_id, full_lots=0.12)
    bridge = _FakeBridge(open_tickets=set(), open_orders_age_s=999.0,  # stale -> GUARD 1 off
                         closed_orders_age_s=1.0)                       # fresh -> GUARD 2 off
    # Only the profitable partial deal present so far.
    bridge.prime([{"ticket": "2125574587", "symbol": "XAUUSD.ecn", "type": "BUY",
                   "volume": 0.06, "close_price": 4254.80,
                   "close_time": "2026.07.03 14:15:06",
                   "profit": 73.80, "swap": 0.0, "commission": 0.0,
                   "deal_reason": "TP"}], appear_at_call=0)
    res = reconcile_trade(bridge=bridge, session=session, trade_id=trade_id,
                          ticket="2125574587", server_utc_offset_hours=0,
                          max_retries=2, backoff_s=0.01)
    assert res.matched is False                 # deferred, not banked
    session.expire_all()
    tr = session.get(BtTrade, trade_id)
    assert tr.broker_ticket == "2125574587"     # ticket persisted for retry
    assert tr.broker_reconciled_at is None       # NOT locked
    assert tr.broker_net_usd is None             # phantom +73.80 NOT banked


def test_reconcile_banks_when_full_volume_closed(session) -> None:
    """GUARD 3: once BOTH deals landed (0.06 partial +73.80, 0.06 remainder
    -68.76) Σvol == 0.12 == full size -> bank the true net +5.04 + lock."""
    run_id = uuid.uuid4(); trade_id = uuid.uuid4()
    _make_partial_trade(session, run_id, trade_id, full_lots=0.12)
    bridge = _FakeBridge(open_tickets=set(), open_orders_age_s=999.0,
                         closed_orders_age_s=1.0)
    bridge.prime([
        {"ticket": "2125574587", "symbol": "XAUUSD.ecn", "type": "BUY",
         "volume": 0.06, "close_price": 4254.80, "close_time": "2026.07.03 14:15:06",
         "profit": 73.80, "swap": 0.0, "commission": 0.0, "deal_reason": "TP"},
        {"ticket": "2125574587", "symbol": "XAUUSD.ecn", "type": "BUY",
         "volume": 0.06, "close_price": 4160.03, "close_time": "2026.07.03 16:07:00",
         "profit": -68.76, "swap": 0.0, "commission": 0.0, "deal_reason": "SL"},
    ], appear_at_call=0)
    res = reconcile_trade(bridge=bridge, session=session, trade_id=trade_id,
                          ticket="2125574587", server_utc_offset_hours=0,
                          max_retries=2, backoff_s=0.01)
    assert res.matched is True
    assert res.broker_net_usd == pytest.approx(5.04)   # true net, not +73.80
    assert res.broker_exit_reason == "SL"              # last deal wins
    session.expire_all()
    tr = session.get(BtTrade, trade_id)
    assert tr.broker_reconciled_at is not None          # now safe to lock
    assert tr.broker_net_usd == pytest.approx(5.04)


def test_reconcile_no_full_size_skips_volume_check(session) -> None:
    """Backward-compat: a row with no qty_lots (old/dry-run) must still reconcile
    on a single closed deal exactly as before — GUARD 3 only fires when the full
    size is known."""
    run_id = uuid.uuid4(); trade_id = uuid.uuid4()
    _make_run_and_trade(session, run_id, trade_id)   # no raw_features.qty_lots
    bridge = _FakeBridge(open_tickets=set(), open_orders_age_s=999.0,
                         closed_orders_age_s=1.0)
    bridge.prime([{"ticket": "T3", "volume": 0.01, "profit": 5.0, "commission": 0.0,
                   "swap": 0.0, "close_price": 100.0,
                   "close_time": "2026.07.01 10:00:00", "deal_reason": "TP"}],
                 appear_at_call=0)
    res = reconcile_trade(bridge=bridge, session=session, trade_id=trade_id,
                          ticket="T3", server_utc_offset_hours=0,
                          max_retries=2, backoff_s=0.01)
    assert res.matched is True
    assert res.broker_gross_usd == 5.0
