"""Shared pytest fixtures."""
from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from bt_engine.db.engine import make_engine
from bt_engine.db.migrate import apply_schema


TEST_DB_URL = os.environ.get(
    "BT_ENGINE_TEST_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt_test",
)


@pytest.fixture(scope="session")
def db_engine():
    engine = make_engine(TEST_DB_URL)
    apply_schema(TEST_DB_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    """Per-test session. Wipes bt_* tables before each test."""
    with db_engine.begin() as conn:
        # delete in FK-safe order
        for t in [
            "bt_account_snapshot",
            "bt_signals",
            "bt_bar_walk",
            "bt_journal_events",
            "bt_trades",
            "bt_runs",
        ]:
            conn.execute(text(f"DELETE FROM {t}"))
    Session = sessionmaker(bind=db_engine, expire_on_commit=False)
    s = Session()
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture
def run_id() -> uuid.UUID:
    return uuid.uuid4()
