"""Replay a single trade's bar-by-bar story from the DB for visualisation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import BtBarWalk, BtJournalEvent, BtTrade


@dataclass
class BarWalkStory:
    trade_ref: str
    trade_id: UUID
    direction: str
    side: int
    entry_timestamp: datetime
    entry_price: float
    stop_price: float
    take_profit_price: float | None
    risk_units: float
    exit_timestamp: datetime | None
    exit_price: float | None
    exit_reason: str | None
    net_r: float | None
    bars: list[dict[str, Any]]
    events: list[dict[str, Any]]


def replay_trade(session: Session, trade_ref: str) -> BarWalkStory:
    trade = session.execute(
        select(BtTrade).where(BtTrade.trade_ref == trade_ref)
    ).scalar_one_or_none()
    if trade is None:
        raise LookupError(f"Trade not found: {trade_ref}")

    bars_q = (
        select(BtBarWalk)
        .where(BtBarWalk.trade_id == trade.trade_id)
        .order_by(BtBarWalk.bar_ts)
    )
    bars = [
        {
            "bar_ts": b.bar_ts.isoformat(),
            "phase": b.phase,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "spread": b.spread,
            "distance_to_entry_r": b.distance_to_entry_r,
            "distance_to_stop_r": b.distance_to_stop_r,
            "distance_to_tp_r": b.distance_to_tp_r,
            "mfe_r": b.mfe_r,
            "mae_r": b.mae_r,
            "unrealised_r": b.unrealised_r,
        }
        for b in session.execute(bars_q).scalars()
    ]

    events_q = (
        select(BtJournalEvent)
        .where(BtJournalEvent.trade_id == trade.trade_id)
        .order_by(BtJournalEvent.ts, BtJournalEvent.event_id)
    )
    events = [
        {
            "ts": ev.ts.isoformat(),
            "event_type": ev.event_type,
            "detail": ev.detail,
        }
        for ev in session.execute(events_q).scalars()
    ]

    return BarWalkStory(
        trade_ref=trade.trade_ref,
        trade_id=trade.trade_id,
        direction=trade.direction,
        side=trade.side,
        entry_timestamp=trade.entry_timestamp,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        take_profit_price=trade.take_profit_price,
        risk_units=trade.risk_units,
        exit_timestamp=trade.exit_timestamp,
        exit_price=trade.exit_price,
        exit_reason=trade.exit_reason,
        net_r=trade.net_r,
        bars=bars,
        events=events,
    )


def story_to_dict(story: BarWalkStory) -> dict[str, Any]:
    d = asdict(story)
    d["trade_id"] = str(d["trade_id"])
    d["entry_timestamp"] = d["entry_timestamp"].isoformat() if d["entry_timestamp"] else None
    d["exit_timestamp"] = d["exit_timestamp"].isoformat() if d["exit_timestamp"] else None
    return d
