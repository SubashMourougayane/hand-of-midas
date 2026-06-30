"""Shared harness for Phase 5 parity tests.

Runs FibV2EnsembleStrategy (or single-leg variant) through `run_engine(mode='bt')`
over an OANDA parquet, captures trades, returns DataFrame in the research output
shape so it can be compared row-for-row against research parquets.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Iterator

import pandas as pd

from bt_engine.core.bar import Bar
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.data.multi_tf_view import MultiTfHistoryView
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2 import (
    FibV2EnsembleStrategy,
    LegSpec,
    LONG_BULL_STRONG,
    SHORT_BEAR_STRONG,
)
from bt_engine.strategies.fib_v2.config import FibV2Config
from dataclasses import replace


HORIZON_BARS = 72 * 12 * 2  # research: max_hold_h=72, M5/h=12, doubled per research


class InMemoryProvider:
    """Minimal DataProvider matching the engine protocol.

    Optimized: stores frame internally and serves bars + history via fast
    pointer slicing (NO per-call `.where` filter). Sequential ticks expected.
    """

    def __init__(self, frame: pd.DataFrame, *, symbol: str, timeframe: str = "M5") -> None:
        self._df = frame.reset_index(drop=True)
        self.symbol = symbol
        self.timeframe = timeframe
        self._ts_arr = self._df["timestamp"].values
        self._tick_idx = 0  # synced by InMemoryClock

    def bars(self) -> Iterator[Bar]:
        # Use itertuples for ~10x speedup vs iterrows.
        for row in self._df.itertuples(index=False):
            yield Bar.from_row(symbol=self.symbol, timeframe=self.timeframe, row=row._asdict())

    def history_up_to(self, ts: pd.Timestamp) -> pd.DataFrame:
        """Return slice with timestamp <= ts. Uses searchsorted (O(log n))
        instead of boolean filter (O(n)). Returns a view to avoid copy.
        """
        # searchsorted on np.datetime64 array, side='right' returns index after last <= ts.
        ts_val = pd.Timestamp(ts).to_datetime64()
        end_idx = self._ts_arr.searchsorted(ts_val, side="right")
        return self._df.iloc[:end_idx]


class InMemoryClock:
    def __init__(self, provider: InMemoryProvider) -> None:
        self._iter = iter(provider.bars())

    def tick(self) -> Bar | None:
        try:
            return next(self._iter)
        except StopIteration:
            return None


def run_engine_capture_trades(
    *,
    m5_frame: pd.DataFrame,
    symbol: str,
    legs: Sequence[LegSpec],
    cost_usd: float,
    h1_frame: pd.DataFrame | None = None,
    partial_tp_at_r: float | None = None,
    partial_tp_pct: float = 0.5,
) -> pd.DataFrame:
    """Run the engine and return a DataFrame in the research shape:
    columns = [entry_ts, side, entry_price, stop_price, tp_price, risk_units,
               exit_index, bracket_r, cost_r, net_r, year].
    """
    provider = InMemoryProvider(m5_frame, symbol=symbol)
    clock = InMemoryClock(provider)
    mtf = MultiTfHistoryView(m5_frame)
    # If caller passed an external H1 frame (e.g. OANDA H1 parquet for exact
    # parity with research), override the derived H1 frame.
    if h1_frame is not None:
        h1 = h1_frame.copy()
        if h1["timestamp"].dt.tz is None:
            h1["timestamp"] = h1["timestamp"].dt.tz_localize("UTC")
        h1 = h1.sort_values("timestamp").reset_index(drop=True)
        mtf._h1 = h1
    cfg = FibV2Config()
    if partial_tp_at_r is not None:
        cfg = replace(cfg, partial_tp_at_r=partial_tp_at_r, partial_tp_pct=partial_tp_pct)
    strat = FibV2EnsembleStrategy(
        symbol=symbol, legs=tuple(legs), cost_usd=cost_usd,
        multi_tf_view=mtf, config=cfg,
    )

    closed_rows: list[dict] = []

    def _on_close(trade, outcome) -> None:
        gross_r = outcome.bracket_1r_outcome
        # Engine stores raw order extra including cost_r (set at signal time);
        # we recompute from actual fill (entry_price) for parity exactness.
        risk = trade.risk_units
        cost_r = cost_usd / risk if risk > 0 else 0.0
        net_r = gross_r - cost_r
        # Find exit_index = bars from entry to exit.
        closed_rows.append({
            "entry_ts": trade.entry_timestamp,
            "side": int(trade.side),
            "entry_price": float(trade.entry_price),
            "stop_price": float(trade.stop_price),
            "tp_price": float(trade.take_profit) if trade.take_profit is not None else None,
            "risk_units": float(risk),
            "exit_index": -1,  # not directly available; filled in via timestamp lookup
            "exit_ts": outcome.exit_timestamp,
            "bracket_r": float(gross_r),
            "cost_r": float(cost_r),
            "net_r": float(net_r),
            "exit_reason": outcome.reason,
            "year": pd.Timestamp(trade.entry_timestamp).year,
            "leg": trade.order.extra.get("leg") if hasattr(trade.order, "extra") else None,
        })

    deps = EngineDeps(
        clock=clock,
        data_provider=provider,
        strategy=strat,
        execution=BTExecutionModel(),
        broker=None,
        recorder=None,
        journal=None,
        on_trade_close=_on_close,
        max_bars_held=HORIZON_BARS,
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")

    if not closed_rows:
        return pd.DataFrame(columns=["entry_ts", "side", "entry_price", "stop_price",
                                       "tp_price", "risk_units", "exit_index",
                                       "bracket_r", "cost_r", "net_r", "year"])
    df = pd.DataFrame(closed_rows).sort_values("entry_ts").reset_index(drop=True)
    return df


def load_oanda_parquet(path: str | Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    return df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def normalize_research_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize research parquet for comparison (ensure UTC tz)."""
    df = df.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    df = df.sort_values("entry_ts").reset_index(drop=True)
    return df
