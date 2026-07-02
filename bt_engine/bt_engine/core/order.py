"""Order, Fill, OpenTrade, BracketOutcome dataclasses — shared by BT and live."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pandas as pd


@dataclass(frozen=True)
class Order:
    symbol: str
    side: int  # +1 long, -1 short
    qty: float
    intended_entry_bar: pd.Timestamp  # bar OPEN timestamp the signal targets
    stop_price: float
    take_profit: float | None
    risk_units: float
    tag: str  # zone_id or similar
    bracket_kind: str  # "1R" | "partial_runner" | "close_based"
    trade_id: UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in (-1, 1):
            raise ValueError(f"side must be +1 or -1, got {self.side}")
        if self.qty <= 0:
            raise ValueError(f"qty must be > 0, got {self.qty}")
        if self.risk_units <= 0:
            raise ValueError(f"risk_units must be > 0, got {self.risk_units}")
        if self.intended_entry_bar.tzinfo is None:
            raise ValueError("intended_entry_bar must be timezone-aware (UTC).")


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: int
    qty: float
    price: float
    fill_timestamp: pd.Timestamp


@dataclass
class OpenTrade:
    trade_id: UUID
    order: Order
    fill: Fill
    entry_price: float
    entry_timestamp: pd.Timestamp
    side: int
    stop_price: float
    take_profit: float | None
    risk_units: float
    mfe_r: float = 0.0
    mae_r: float = 0.0
    bars_held: int = 0
    partial_taken: bool = False
    partial_filled_r: float = 0.0
    partial_fill_price: float | None = None
    partial_fill_timestamp: pd.Timestamp | None = None
    # Populated by live runner on ENTRY_FILL; None in BT / sim contexts.
    broker_ticket: str | None = None
    # BT-only: accumulated overnight swap in R units. Deducted from outcome_r at close.
    # Zero when swap model not configured.
    accrued_swap_r: float = 0.0


@dataclass(frozen=True)
class BracketOutcome:
    exit_timestamp: pd.Timestamp
    exit_price: float
    reason: str  # "TP" | "SL" | "TIMEOUT" | "MANUAL"
    bars_held: int
    bracket_1r_outcome: float  # in R
    event_type: str  # JournalEvent string
    detail: dict[str, Any] = field(default_factory=dict)
