"""SQLAlchemy engine + session factory."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


DEFAULT_DB_URL = "postgresql+psycopg2://subash@localhost:5432/golddigger_bt"


def get_db_url() -> str:
    return os.environ.get("BT_ENGINE_DB_URL", DEFAULT_DB_URL)


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_db_url(), future=True, pool_pre_ping=True)


_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _Session


@contextmanager
def session_scope() -> Iterator[Session]:
    sf = get_session_factory()
    s = sf()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def reset_engine_for_testing(url: str) -> None:
    """Test helper — rebind the global engine to a different URL."""
    global _engine, _Session
    _engine = make_engine(url)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
