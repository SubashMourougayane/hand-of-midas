"""SQLAlchemy ORM models for bt_* tables."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BtRun(Base):
    __tablename__ = "bt_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ref: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    strategy_id: Mapped[str] = mapped_column(String, nullable=False)
    strategy_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_provider: Mapped[str] = mapped_column(String, nullable=False)
    git_sha: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BtTrade(Base):
    __tablename__ = "bt_trades"

    trade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    trade_ref: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bt_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    strategy_id: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    zone_id: Mapped[int | None] = mapped_column(Integer)
    zone_tf: Mapped[str | None] = mapped_column(String)
    spec_name: Mapped[str | None] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[int] = mapped_column(Integer, nullable=False)
    upper: Mapped[float | None] = mapped_column(Float)
    lower: Mapped[float | None] = mapped_column(Float)
    created_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    base_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    impulse_start_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    impulse_end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    touch_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirm_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_price: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit_price: Mapped[float | None] = mapped_column(Float)
    risk_units: Mapped[float] = mapped_column(Float, nullable=False)
    exit_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(String)
    bars_held: Mapped[int | None] = mapped_column(Integer)
    bracket_1r_outcome: Mapped[float | None] = mapped_column(Float)
    cost_r: Mapped[float | None] = mapped_column(Float)
    gross_r: Mapped[float | None] = mapped_column(Float)
    net_r: Mapped[float | None] = mapped_column(Float)
    confluence_score: Mapped[float | None] = mapped_column(Float)
    clean_top3_rank: Mapped[int | None] = mapped_column(Integer)
    # --- Fib V2 ENSEMBLE columns (alembic 0002) ---
    pivot_lb: Mapped[int | None] = mapped_column(Integer)
    regime: Mapped[str | None] = mapped_column(String)
    ext_target_pct: Mapped[float | None] = mapped_column(Float)
    sl_buffer_pct: Mapped[float | None] = mapped_column(Float)
    fib_diff: Mapped[float | None] = mapped_column(Float)
    regime_at_entry: Mapped[str | None] = mapped_column(String)
    leg: Mapped[str | None] = mapped_column(String)
    # --- end fib v2 columns ---
    # --- Partial-TP safety net columns (alembic 0003) ---
    partial_tp_at_r: Mapped[float | None] = mapped_column(Float)
    partial_tp_pct: Mapped[float | None] = mapped_column(Float)
    partial_taken: Mapped[bool | None] = mapped_column(Boolean)
    partial_r: Mapped[float | None] = mapped_column(Float)
    partial_fill_price: Mapped[float | None] = mapped_column(Float)
    partial_fill_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # --- end partial-tp columns ---
    raw_features: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_bt_trades_run", "run_id"),
        Index("idx_bt_trades_entry_ts", "entry_timestamp"),
    )


class BtJournalEvent(Base):
    __tablename__ = "bt_journal_events"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bt_trades.trade_id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bt_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_bt_journal_trade", "trade_id"),
        Index("idx_bt_journal_ts", "ts"),
    )


class BtBarWalk(Base):
    __tablename__ = "bt_bar_walk"

    walk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bt_trades.trade_id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bt_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    bar_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    distance_to_entry_r: Mapped[float | None] = mapped_column(Float)
    distance_to_stop_r: Mapped[float | None] = mapped_column(Float)
    distance_to_tp_r: Mapped[float | None] = mapped_column(Float)
    mfe_r: Mapped[float | None] = mapped_column(Float)
    mae_r: Mapped[float | None] = mapped_column(Float)
    unrealised_r: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("trade_id", "bar_ts", name="uq_bar_walk_trade_ts"),
        Index("idx_bar_walk_trade_ts", "trade_id", "bar_ts"),
    )


class BtSignal(Base):
    __tablename__ = "bt_signals"

    signal_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bt_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    zone_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(String)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (Index("idx_signals_run_ts", "run_id", "ts"),)


class BtAccountSnapshot(Base):
    __tablename__ = "bt_account_snapshot"

    snap_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bt_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    balance: Mapped[float | None] = mapped_column(Float)
    equity: Mapped[float | None] = mapped_column(Float)
    open_pnl: Mapped[float | None] = mapped_column(Float)
    open_position: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (UniqueConstraint("run_id", "ts", name="uq_account_snap_run_ts"),)
