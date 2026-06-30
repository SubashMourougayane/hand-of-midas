"""Generators for run_ref, trade_ref."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd


def new_trade_id() -> uuid.UUID:
    return uuid.uuid4()


def new_run_id() -> uuid.UUID:
    return uuid.uuid4()


def make_run_ref(strategy_id: str, mode: str, when: datetime | None = None, seq: int = 1) -> str:
    """e.g. BT-20260629-SDR001-0001 or LIVE-20260629-SDR001-0001."""
    when = when or datetime.now(timezone.utc)
    prefix = "LIVE" if mode == "live" else "BT"
    return f"{prefix}-{when.strftime('%Y%m%d')}-{strategy_id.upper()}-{seq:04d}"


def make_trade_ref(strategy_id: str, entry_ts: pd.Timestamp, direction: str, seq: int) -> str:
    """e.g. SDR001-2019-06-12-S-0001."""
    dir_code = direction[0].upper()
    return (
        f"{strategy_id.upper()}-{entry_ts.strftime('%Y-%m-%d')}-{dir_code}-{seq:04d}"
    )
