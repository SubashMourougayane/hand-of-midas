"""Streaming repos: TradeRepo, JournalRepo, BarWalkRepo, SignalRepo, AccountSnapshotRepo.

Same interface used by BT and live engine — only difference is who calls them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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

    def close_stale_live_runs(self, strategy_id: str, end_ts: datetime) -> int:
        """Mark any prior un-ended LIVE run for this strategy as ended.

        A force-killed runner (e.g. NSSM restart) never reaches its graceful
        close(), leaving orphaned open runs that inflate the dashboard's
        strategy count. Call on startup BEFORE creating the fresh run so only
        the newly-started run stays open for this strategy.
        """
        from sqlalchemy import update as _update
        res = self.s.execute(
            _update(BtRun)
            .where(BtRun.mode == "live")
            .where(BtRun.strategy_id == strategy_id)
            .where(BtRun.end_ts.is_(None))
            .values(end_ts=end_ts)
        )
        self.s.flush()
        return res.rowcount or 0


class TradeRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def upsert_open(self, trade: BtTrade) -> None:
        existing = self.s.get(BtTrade, trade.trade_id)
        if existing is None:
            self.s.add(trade)
        elif existing.run_id != trade.run_id:
            # Adopted positions use a deterministic trade_id (uuid5 of ticket),
            # so a restart re-adopts the SAME id. If the prior row sits on an
            # older (now-ended) run, re-point it to the CURRENT live run + keep
            # the freshest live fields, so the active-run dashboard shows it.
            existing.run_id = trade.run_id
            existing.strategy_id = trade.strategy_id
            existing.leg = trade.leg
            existing.broker_ticket = trade.broker_ticket
            existing.entry_timestamp = trade.entry_timestamp
            existing.raw_features = trade.raw_features
        self.s.flush()

    def risk_units_for_ticket(self, broker_ticket: str) -> float | None:
        """Original stop distance (risk_units) for a broker ticket, from the most
        recent row we have for it. Used when adopting a position whose broker SL
        has been trailed to breakeven (SL==entry → live stop distance 0): without
        the original risk the position would be dropped from adoption and stranded
        unmanaged. Returns None if we've never seen the ticket."""
        from sqlalchemy import select as _select
        if not broker_ticket:
            return None
        row = self.s.execute(
            _select(BtTrade.risk_units)
            .where(BtTrade.broker_ticket == str(broker_ticket))
            .where(BtTrade.risk_units.isnot(None))
            .order_by(BtTrade.entry_timestamp.desc())
            .limit(1)
        ).scalar_one_or_none()
        try:
            return float(row) if row is not None and float(row) > 0 else None
        except (TypeError, ValueError):
            return None

    def supersede_stale_open_ticket(
        self, broker_ticket: str, keep_trade_id: uuid.UUID, run_id: uuid.UUID
    ) -> int:
        """Close any OTHER still-open row for the same broker ticket.

        A live entry writes a RANDOM trade_id; a later re-adoption (after a leg
        restart) writes a DETERMINISTIC uuid5(ticket) id — a DIFFERENT row for
        the SAME broker position. Without this, the original row is orphaned on
        the now-ended run (dashboard-scoped-to-active-runs hides it; the position
        looks lost). Mark those stale duplicates closed (reason SUPERSEDED) so
        exactly ONE open row per ticket survives — the freshly-adopted one on the
        current run. Broker position itself is untouched (DB bookkeeping only).
        """
        from sqlalchemy import update as _update
        if not broker_ticket:
            return 0
        res = self.s.execute(
            _update(BtTrade)
            .where(BtTrade.broker_ticket == str(broker_ticket))
            .where(BtTrade.trade_id != keep_trade_id)
            .where(BtTrade.exit_timestamp.is_(None))
            .values(
                exit_timestamp=datetime.now(timezone.utc),
                exit_reason="SUPERSEDED",
            )
        )
        self.s.flush()
        return res.rowcount or 0

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
        partial_taken: bool | None = None,
        partial_r: float | None = None,
        partial_fill_price: float | None = None,
        partial_fill_ts: datetime | None = None,
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
        if partial_taken is not None:
            trade.partial_taken = partial_taken
        if partial_r is not None:
            trade.partial_r = partial_r
        if partial_fill_price is not None:
            trade.partial_fill_price = partial_fill_price
        if partial_fill_ts is not None:
            trade.partial_fill_ts = partial_fill_ts
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
