"""BarWalkJournal — records every bar a trade observes from zone creation to exit.

Owned by the engine. Tracks MFE/MAE/unrealised in R incrementally; writes one row
to bt_bar_walk per bar per open trade.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..core.bar import Bar
from ..db.models import BtBarWalk
from ..db.repo import BarWalkRepo, JournalRepo


@dataclass
class WalkSession:
    trade_id: uuid.UUID
    run_id: uuid.UUID
    side: int  # +1 / -1
    entry_price: float | None
    stop_price: float | None
    take_profit: float | None
    risk_units: float | None
    mfe_r: float = 0.0
    mae_r: float = 0.0
    bars_recorded: int = 0
    closed: bool = False


class BarWalkJournal:
    """Per-trade bar walkthrough recorder. Computes MFE/MAE/unrealised in R per bar."""

    def __init__(self, walk_repo: BarWalkRepo, journal_repo: JournalRepo) -> None:
        self.walk_repo = walk_repo
        self.journal_repo = journal_repo
        self._open: dict[uuid.UUID, WalkSession] = {}

    def open_walk(
        self,
        *,
        trade_id: uuid.UUID,
        run_id: uuid.UUID,
        side: int,
        entry_price: float | None = None,
        stop_price: float | None = None,
        take_profit: float | None = None,
        risk_units: float | None = None,
    ) -> None:
        self._open[trade_id] = WalkSession(
            trade_id=trade_id,
            run_id=run_id,
            side=side,
            entry_price=entry_price,
            stop_price=stop_price,
            take_profit=take_profit,
            risk_units=risk_units,
        )

    def update_entry(
        self,
        trade_id: uuid.UUID,
        entry_price: float,
        stop_price: float,
        take_profit: float | None,
        risk_units: float,
    ) -> None:
        s = self._open.get(trade_id)
        if s is None:
            raise LookupError(f"No walk open for trade {trade_id}")
        s.entry_price = entry_price
        s.stop_price = stop_price
        s.take_profit = take_profit
        s.risk_units = risk_units

    def observe(self, trade_id: uuid.UUID, bar: Bar, phase: str) -> None:
        s = self._open.get(trade_id)
        if s is None or s.closed:
            return
        # compute R metrics only after entry is known
        d_entry_r = d_stop_r = d_tp_r = unreal_r = None
        if s.entry_price is not None and s.risk_units:
            sign = s.side
            d_entry_r = (bar.close - s.entry_price) * sign / s.risk_units
            if s.stop_price is not None:
                d_stop_r = (bar.close - s.stop_price) * sign / s.risk_units
            if s.take_profit is not None:
                d_tp_r = (bar.close - s.take_profit) * sign / s.risk_units
            # MFE/MAE off bar high/low against direction
            move_max = (bar.high - s.entry_price) * sign / s.risk_units if sign > 0 else (s.entry_price - bar.low) / s.risk_units
            move_min = (bar.low - s.entry_price) * sign / s.risk_units if sign > 0 else (s.entry_price - bar.high) / s.risk_units
            s.mfe_r = max(s.mfe_r, move_max)
            s.mae_r = min(s.mae_r, move_min)
            unreal_r = d_entry_r

        row = BtBarWalk(
            trade_id=trade_id,
            run_id=s.run_id,
            bar_ts=bar.timestamp.to_pydatetime() if hasattr(bar.timestamp, "to_pydatetime") else bar.timestamp,
            phase=phase,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            spread=bar.spread,
            distance_to_entry_r=d_entry_r,
            distance_to_stop_r=d_stop_r,
            distance_to_tp_r=d_tp_r,
            mfe_r=s.mfe_r if s.entry_price is not None else None,
            mae_r=s.mae_r if s.entry_price is not None else None,
            unrealised_r=unreal_r,
        )
        self.walk_repo.insert(row)
        s.bars_recorded += 1

    def event(
        self,
        *,
        trade_id: uuid.UUID,
        run_id: uuid.UUID,
        ts: datetime,
        event_type: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.journal_repo.insert(
            trade_id=trade_id,
            run_id=run_id,
            ts=ts,
            event_type=event_type,
            detail=detail or {},
        )

    def close_walk(self, trade_id: uuid.UUID) -> WalkSession | None:
        s = self._open.get(trade_id)
        if s is None:
            return None
        s.closed = True
        return s

    def is_open(self, trade_id: uuid.UUID) -> bool:
        s = self._open.get(trade_id)
        return s is not None and not s.closed
