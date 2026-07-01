"""Bulk-buffered persistence for BT runs.

The streaming repos (repo.py) flush per-row which is fine for live (~30 rows/day)
but too slow for a 21-year BT with millions of gate events. This module wraps
them: BulkBarWalkRepo, BulkJournalRepo, BulkSignalRepo, BulkAccountSnapshotRepo
all buffer rows in memory and flush in chunks via `bulk_insert_mappings` at
`.finalize()`.

The engine sees the same API as the streaming repos (add / insert / bulk_insert),
so BarWalkJournal and the runner callbacks compose without change.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import (
    BtAccountSnapshot,
    BtBarWalk,
    BtJournalEvent,
    BtSignal,
    BtTrade,
)


CHUNK = 5000  # psycopg2 parameter cap keeps chunks small


@dataclass
class BulkStats:
    trades_open: int = 0
    trades_closed: int = 0
    journal_events: int = 0
    signals: int = 0
    bar_walk_rows: int = 0
    account_snapshots: int = 0


class BulkBarWalkRepo:
    """Buffered variant of BarWalkRepo — same insert/bulk_insert surface."""

    def __init__(self, session: Session) -> None:
        self.s = session
        self.buf: list[dict[str, Any]] = []

    def insert(self, row: BtBarWalk) -> None:
        self.buf.append(_bar_walk_to_dict(row))

    def bulk_insert(self, rows: list[BtBarWalk]) -> None:
        self.buf.extend(_bar_walk_to_dict(r) for r in rows)

    def flush(self) -> int:
        n = len(self.buf)
        for i in range(0, n, CHUNK):
            self.s.bulk_insert_mappings(BtBarWalk, self.buf[i : i + CHUNK])
            self.s.commit()
        self.buf.clear()
        return n


class BulkJournalRepo:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.buf: list[dict[str, Any]] = []

    def insert(
        self,
        *,
        trade_id: uuid.UUID,
        run_id: uuid.UUID,
        ts: datetime,
        event_type: str,
        detail: dict[str, Any],
    ) -> None:
        self.buf.append(
            dict(
                trade_id=trade_id,
                run_id=run_id,
                ts=ts,
                event_type=event_type,
                detail=detail,
            )
        )

    def flush(self) -> int:
        n = len(self.buf)
        for i in range(0, n, CHUNK):
            self.s.bulk_insert_mappings(BtJournalEvent, self.buf[i : i + CHUNK])
            self.s.commit()
        self.buf.clear()
        return n


class BulkSignalRepo:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.buf: list[dict[str, Any]] = []

    def insert(
        self,
        *,
        run_id: uuid.UUID,
        ts: datetime,
        status: str,
        zone_id: int | None = None,
        reason: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.buf.append(
            dict(
                run_id=run_id,
                ts=ts,
                zone_id=zone_id,
                status=status,
                reason=reason,
                detail=detail,
            )
        )

    def flush(self) -> int:
        n = len(self.buf)
        for i in range(0, n, CHUNK):
            self.s.bulk_insert_mappings(BtSignal, self.buf[i : i + CHUNK])
            self.s.commit()
        self.buf.clear()
        return n


class BulkTradeStore:
    """Buffers open + close fields for trades and bulk-inserts as one row."""

    def __init__(self, session: Session) -> None:
        self.s = session
        self.by_id: dict[uuid.UUID, dict[str, Any]] = {}
        self.stats = BulkStats()

    def open(self, trade_dict: dict[str, Any]) -> None:
        self.by_id[trade_dict["trade_id"]] = trade_dict
        self.stats.trades_open += 1

    def close(self, trade_id: uuid.UUID, close_fields: dict[str, Any]) -> None:
        if trade_id in self.by_id:
            self.by_id[trade_id].update(close_fields)
        self.stats.trades_closed += 1

    def flush(self) -> int:
        rows = list(self.by_id.values())
        for i in range(0, len(rows), CHUNK):
            self.s.bulk_insert_mappings(BtTrade, rows[i : i + CHUNK])
            self.s.commit()
        n = len(rows)
        self.by_id.clear()
        return n


class BulkAccountSnapshotRepo:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.buf: list[dict[str, Any]] = []

    def insert(
        self,
        *,
        run_id: uuid.UUID,
        ts: datetime,
        balance: float | None,
        equity: float | None,
        open_pnl: float | None,
        open_position: int | None,
    ) -> None:
        self.buf.append(
            dict(
                run_id=run_id,
                ts=ts,
                balance=balance,
                equity=equity,
                open_pnl=open_pnl,
                open_position=open_position,
            )
        )

    def flush(self) -> int:
        n = len(self.buf)
        for i in range(0, n, CHUNK):
            self.s.bulk_insert_mappings(BtAccountSnapshot, self.buf[i : i + CHUNK])
            self.s.commit()
        self.buf.clear()
        return n


def _bar_walk_to_dict(row: BtBarWalk) -> dict[str, Any]:
    return dict(
        trade_id=row.trade_id,
        run_id=row.run_id,
        bar_ts=row.bar_ts,
        phase=row.phase,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        spread=row.spread,
        distance_to_entry_r=row.distance_to_entry_r,
        distance_to_stop_r=row.distance_to_stop_r,
        distance_to_tp_r=row.distance_to_tp_r,
        mfe_r=row.mfe_r,
        mae_r=row.mae_r,
        unrealised_r=row.unrealised_r,
    )
