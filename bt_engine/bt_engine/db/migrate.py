"""Schema initialiser. Applies schema.sql (idempotent via IF NOT EXISTS).

Usage:
    python -m bt_engine.db.migrate init                 # default DB
    python -m bt_engine.db.migrate init --url <url>     # custom URL
    python -m bt_engine.db.migrate drop --yes           # drop all bt_* tables
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

from .engine import make_engine

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def apply_schema(url: str | None = None) -> None:
    sql = SCHEMA_PATH.read_text()
    engine = make_engine(url) if url else make_engine()
    with engine.begin() as conn:
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            conn.execute(text(stmt))


def drop_schema(url: str | None = None) -> None:
    engine = make_engine(url) if url else make_engine()
    tables = [
        "bt_account_snapshot",
        "bt_signals",
        "bt_bar_walk",
        "bt_journal_events",
        "bt_trades",
        "bt_runs",
    ]
    with engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bt_engine schema migrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser("init", help="Apply schema (idempotent)")
    init_p.add_argument("--url", default=None)

    drop_p = sub.add_parser("drop", help="Drop all bt_* tables")
    drop_p.add_argument("--url", default=None)
    drop_p.add_argument("--yes", action="store_true", required=False)

    args = parser.parse_args(argv)
    if args.cmd == "init":
        apply_schema(args.url)
        print("Schema applied.")
        return 0
    if args.cmd == "drop":
        if not args.yes:
            print("Refusing to drop without --yes flag.")
            return 1
        drop_schema(args.url)
        print("Schema dropped.")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
