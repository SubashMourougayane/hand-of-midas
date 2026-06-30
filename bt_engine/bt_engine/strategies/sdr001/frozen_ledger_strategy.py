"""FrozenLedgerStrategy — replays research-baseline frozen ledger through bt_engine.

This is the Phase-1 parity strategy. It does NOT re-derive zones from raw bars.
Instead, it loads `research-baseline/results/base/base_sleeve1_trades.csv` and emits
each row as a closed trade. The engine streams them through the journal/DB/CSV
recorder so the headline numbers (1032 trades, +256.11R, WR 63.86%, PF 1.68,
max DD -12.69R, 8/8 positive years) match by construction.

Future phases will replace this with an incremental, raw-data-driven port of the
intraday_edge_lab modules — keeping this strategy as the parity oracle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ...core.bar import Bar
from ...core.signal import StepResult
from ...core.state import StrategyState
from ..base import Strategy


@dataclass
class FrozenLedgerState(StrategyState):
    """Pre-computed events bucketed by entry_timestamp; pulled as bars arrive."""

    pending_by_ts: dict[pd.Timestamp, list[dict[str, Any]]] = field(default_factory=dict)
    emitted_trade_refs: set[str] = field(default_factory=set)


class FrozenLedgerStrategy(Strategy):
    """Replays the baseline frozen ledger.

    The strategy emits a 'closed-trade event' (not a live order) whenever the
    current bar timestamp matches a row's entry_timestamp. Engine wiring picks
    these up via the `closed_trade_events` field on the state.
    """

    strategy_id = "sdr001"

    def __init__(self, ledger_path: str | Path, *, symbol: str = "XAUUSD", timeframe: str = "M15") -> None:
        self.ledger_path = Path(ledger_path)
        self.symbol = symbol
        self.timeframe = timeframe
        self.config = {"ledger_path": str(ledger_path), "symbol": symbol, "timeframe": timeframe}
        self._events_by_ts: dict[pd.Timestamp, list[dict[str, Any]]] = self._load_ledger()

    def _load_ledger(self) -> dict[pd.Timestamp, list[dict[str, Any]]]:
        df = pd.read_csv(self.ledger_path)
        ts_cols = [
            "created_timestamp", "base_timestamp", "impulse_start_timestamp",
            "impulse_end_timestamp", "touch_timestamp", "entry_timestamp",
        ]
        for c in ts_cols:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
        # group by entry_timestamp
        out: dict[pd.Timestamp, list[dict[str, Any]]] = {}
        for _, row in df.iterrows():
            ts = row["entry_timestamp"]
            if pd.isna(ts):
                continue
            out.setdefault(ts, []).append(row.to_dict())
        return out

    @property
    def all_events(self) -> list[dict[str, Any]]:
        return [ev for evs in self._events_by_ts.values() for ev in evs]

    @property
    def entry_timestamps(self) -> list[pd.Timestamp]:
        return sorted(self._events_by_ts.keys())

    def initial_state(self) -> FrozenLedgerState:
        return FrozenLedgerState(
            pending_by_ts={ts: list(rows) for ts, rows in self._events_by_ts.items()}
        )

    def on_bar(
        self,
        state: FrozenLedgerState,
        bar: Bar,
        history: pd.DataFrame,
    ) -> StepResult:
        # Pop any ledger rows whose entry_timestamp matches this bar
        # The engine doesn't see these as Orders — it pulls them from
        # state.pending_by_ts via the runner. For Phase 1 we keep the
        # StepResult shape simple: no orders emitted, state mutates only via pop.
        rows = state.pending_by_ts.pop(bar.timestamp, [])
        if rows:
            for r in rows:
                tr_ref_key = (
                    str(r.get("zone_id")),
                    pd.Timestamp(r.get("entry_timestamp")).isoformat(),
                )
                state.emitted_trade_refs.add("|".join(tr_ref_key))
        return StepResult(state=state)

    def pop_events_for(self, state: FrozenLedgerState, ts: pd.Timestamp) -> list[dict[str, Any]]:
        return state.pending_by_ts.pop(ts, [])
