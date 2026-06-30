"""Shared dependencies for FastAPI routes (settings, DB session)."""
from __future__ import annotations

import os
from typing import Iterator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from bt_engine.db.engine import make_engine, get_db_url


_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def session_factory() -> sessionmaker[Session]:
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _Session


def get_session() -> Iterator[Session]:
    """FastAPI dependency — yields a session that auto-closes after the request."""
    s = session_factory()()
    try:
        yield s
    finally:
        s.close()


def get_dsn_for_asyncpg() -> str:
    """asyncpg uses pg:// (no driver suffix) — translate from SQLAlchemy URL."""
    url = get_db_url()
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql://", 1)
    if url.startswith("postgresql+"):
        # Strip any driver suffix.
        scheme, rest = url.split("://", 1)
        return f"postgresql://{rest}"
    return url
