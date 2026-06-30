"""Pydantic response models for the live dashboard API."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class RunSummary(BaseModel):
    run_id: UUID
    run_ref: str
    mode: str
    strategy_id: str
    symbol: str
    timeframe: str
    start_ts: datetime
    end_ts: datetime | None
    git_sha: str | None


class TradeRow(BaseModel):
    trade_id: UUID
    trade_ref: str
    run_id: UUID
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
    bars_held: int | None
    net_r: float | None
    gross_r: float | None
    cost_r: float | None
    leg: str | None
    regime: str | None
    partial_taken: bool | None
    partial_r: float | None


class JournalRow(BaseModel):
    event_id: int
    trade_id: UUID
    ts: datetime
    event_type: str
    detail: dict[str, Any]


class SignalRow(BaseModel):
    signal_id: int
    run_id: UUID
    ts: datetime
    status: str
    reason: str | None
    zone_id: int | None
    detail: dict[str, Any] | None


class BarWalkRow(BaseModel):
    bar_ts: datetime
    phase: str
    open: float
    high: float
    low: float
    close: float
    mfe_r: float | None
    mae_r: float | None
    unrealised_r: float | None
    distance_to_entry_r: float | None
    distance_to_stop_r: float | None
    distance_to_tp_r: float | None


class AccountSnapshot(BaseModel):
    snap_id: int
    run_id: UUID
    ts: datetime
    balance: float | None
    equity: float | None
    open_pnl: float | None
    open_position: int | None


class FunnelBucket(BaseModel):
    status: str
    count: int


class ScanStatus(BaseModel):
    last_bar_processed: datetime | None
    bars_since_last_signal: int | None
    runs_running: list[RunSummary]


class WsEnvelope(BaseModel):
    channel: str  # "journal" | "signal" | "trade" | "account"
    run_id: UUID | None
    ts: datetime
    payload: dict[str, Any]
