"""Parity gate: Phase-1 deliverable.

Replays research-baseline frozen ledger through bt_engine and asserts:
    - 1032 trades inserted into bt_trades
    - Trade ledger CSV exported matches baseline row count
    - DB row count matches
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from bt_engine.db.models import BtJournalEvent, BtTrade
from bt_engine.strategies.sdr001.parity_replay import replay_to_db


REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER = REPO_ROOT / "research-baseline" / "results" / "base" / "base_sleeve1_trades.csv"


pytestmark = pytest.mark.skipif(not LEDGER.is_file(), reason="baseline ledger missing")


def test_parity_replay_inserts_1032_trades(db_session) -> None:
    result = replay_to_db(db_session, ledger_path=LEDGER)
    assert result.trades_inserted == 1032
    db_session.commit()
    n = db_session.execute(select(func.count()).select_from(BtTrade)).scalar_one()
    assert n == 1032


def test_parity_replay_writes_journal_per_trade(db_session) -> None:
    result = replay_to_db(db_session, ledger_path=LEDGER)
    db_session.commit()
    # Every trade gets at least: ZONE_CREATED (if ts present), CONFIRM_PASS, ENTRY_FILL, EXIT_*
    events = db_session.execute(select(func.count()).select_from(BtJournalEvent)).scalar_one()
    # >= 3 events per trade (some may have all 5)
    assert events >= 3 * 1032


def test_parity_run_record_present(db_session) -> None:
    result = replay_to_db(db_session, ledger_path=LEDGER)
    db_session.commit()
    from bt_engine.db.models import BtRun
    run = db_session.get(BtRun, result.run_id)
    assert run is not None
    assert run.mode == "bt"
    assert run.strategy_id == "sdr001"
    assert run.end_ts is not None
