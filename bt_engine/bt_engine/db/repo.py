"""Streaming repos: TradeRepo, JournalRepo, BarWalkRepo, SignalRepo, AccountSnapshotRepo.

Same interface used by BT and live engine — only difference is who calls them.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .models import (
    BtAccountSnapshot,
    BtBarWalk,
    BtJournalEvent,
    BtRun,
    BtSignal,
    BtTrade,
)


class RunRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(
        self,
        *,
        run_id: uuid.UUID,
        ref: str,
        mode: str,
        strategy_id: str,
        strategy_config: dict[str, Any],
        symbol: str,
        timeframe: str,
        start_ts: datetime,
        data_provider: str,
        git_sha: str | None = None,
    ) -> BtRun:
        run = BtRun(
            run_id=run_id,
            ref=ref,
            mode=mode,
            strategy_id=strategy_id,
            strategy_config=strategy_config,
            symbol=symbol,
            timeframe=timeframe,
            start_ts=start_ts,
            data_provider=data_provider,
            git_sha=git_sha,
        )
        self.s.add(run)
        self.s.flush()
        return run

    def close(self, run_id: uuid.UUID, end_ts: datetime) -> None:
        run = self.s.get(BtRun, run_id)
        if run is None:
            raise LookupError(f"Run not found: {run_id}")
        run.end_ts = end_ts
        self.s.flush()


class TradeRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def upsert_open(self, trade: BtTrade) -> None:
        existing = self.s.get(BtTrade, trade.trade_id)
        if existing is None:
            self.s.add(trade)
        self.s.flush()

    def close(
        self,
        trade_id: uuid.UUID,
        *,
        exit_timestamp: datetime,
        exit_price: float,
        exit_reason: str,
        bars_held: int,
        bracket_1r_outcome: float,
        cost_r: float,
        gross_r: float,
        net_r: float,
    ) -> None:
        trade = self.s.get(BtTrade, trade_id)
        if trade is None:
            raise LookupError(f"Trade not found: {trade_id}")
        trade.exit_timestamp = exit_timestamp
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.bars_held = bars_held
        trade.bracket_1r_outcome = bracket_1r_outcome
        trade.cost_r = cost_r
        trade.gross_r = gross_r
        trade.net_r = net_r
        self.s.flush()


class JournalRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def insert(
        self,
        *,
        trade_id: uuid.UUID,
        run_id: uuid.UUID,
        ts: datetime,
        event_type: str,
        detail: dict[str, Any],
    ) -> None:
        ev = BtJournalEvent(
            trade_id=trade_id,
            run_id=run_id,
            ts=ts,
            event_type=event_type,
            detail=detail,
        )
        self.s.add(ev)
        self.s.flush()


class BarWalkRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def insert(self, row: BtBarWalk) -> None:
        self.s.add(row)
        self.s.flush()

    def bulk_insert(self, rows: list[BtBarWalk]) -> None:
        self.s.add_all(rows)
        self.s.flush()


class SignalRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

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
        sig = BtSignal(
            run_id=run_id,
            ts=ts,
            zone_id=zone_id,
            status=status,
            reason=reason,
            detail=detail,
        )
        self.s.add(sig)
        self.s.flush()


class AccountSnapshotRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

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
        snap = BtAccountSnapshot(
            run_id=run_id,
            ts=ts,
            balance=balance,
            equity=equity,
            open_pnl=open_pnl,
            open_position=open_position,
        )
        self.s.add(snap)
        self.s.flush()
