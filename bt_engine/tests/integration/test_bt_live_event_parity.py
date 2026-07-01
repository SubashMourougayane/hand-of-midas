"""3-way parity gate: research parquet ↔ BT engine ↔ live engine strategy path.

Prior parity tests cover research↔BT. This test locks BT↔live: same strategy
class, same bars, mode='bt' vs mode='live' with a mock broker that mirrors BT
fill semantics MUST produce identical strategy events + order streams.

If future refactors accidentally add a live-only side effect that isn't in BT
(e.g. filtering an event by mode), this test fails immediately.

Run scope: 500 XAU M15 bars — enough for real setups + at least one entry
attempt on the sample data.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterator

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.core.clock_bt import BacktestClock
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.core.order import Fill, Order
from bt_engine.data.memory_provider import MemoryBarProvider, MemoryClock, resample_m5_to
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies import registry


M5_PARQUET = Path("/tmp/oanda_xau_m5.parquet")


pytestmark = pytest.mark.skipif(
    not M5_PARQUET.is_file(),
    reason=f"XAU M5 parquet not available at {M5_PARQUET}",
)


class BTMirrorLiveBroker:
    """Mock live broker that mirrors BTExecutionModel exactly.

    Fills orders at current-bar open (matching BT's simulate_fill), records
    every order + fill, generates synthetic tickets. Ensures the mode='live'
    path exercises the same execution semantics as mode='bt' does — the only
    thing that should differ is the code path taken through engine.py, not
    the observable trade outcomes.
    """

    def __init__(self) -> None:
        self.submitted: list[Order] = []
        self._current_bar: Bar | None = None
        self._next_fill: Fill | None = None
        self._last_response: dict = {}
        self.last_submitted_order: Order | None = None
        self._ticket_seq = 0

    def set_current_bar(self, bar: Bar) -> None:
        self._current_bar = bar

    def submit_order(self, order: Order) -> str:
        self.submitted.append(order)
        self.last_submitted_order = order
        self._ticket_seq += 1
        ticket = f"MOCK-{self._ticket_seq}"
        if self._current_bar is None:
            raise RuntimeError("BTMirrorLiveBroker: set_current_bar must fire first")
        # Mirror BT's simulate_fill: fill at bar.open of order's target bar.
        exec_model = BTExecutionModel()
        fill = exec_model.simulate_fill(order, self._current_bar)
        self._next_fill = fill
        self._last_response = {"success": True, "ticket": ticket,
                                "price": fill.price, "volume": fill.qty}
        return ticket

    def cancel(self, order_id: str) -> None:
        pass

    def modify(self, ticket: str, *, sl: float, tp: float = 0.0) -> None:
        pass

    def close_partial(self, ticket: str, qty: float) -> None:
        pass

    def close_all(self) -> None:
        pass

    def last_response(self) -> dict:
        return self._last_response

    def fills(self) -> Iterator[Fill]:
        if self._next_fill is not None:
            yield self._next_fill
            self._next_fill = None

    def positions(self):
        return []


def _load_m15(n: int = 500) -> pd.DataFrame:
    m5 = pd.read_parquet(M5_PARQUET)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    m15 = resample_m5_to(m5, "M15")
    # Use a mid-range slice with real activity (avoid empty warmup edge).
    return m15.iloc[2000:2000 + n].reset_index(drop=True)


def _event_key(ev) -> tuple:
    """Normalize event to a comparable tuple.

    Excludes fields that legitimately differ between BT/live (fresh UUIDs
    per run for ENTRY_SUBMIT trade_id). Retains strategy-signal identity.
    """
    detail = dict(ev.detail or {})
    tzid = str(ev.trade_or_zone_id)
    # ENTRY_SUBMIT uses a fresh uuid.uuid4() per run — mask it. Gate events
    # use deterministic `gate_N` counter which stays stable.
    if ev.type == "ENTRY_SUBMIT":
        tzid = "<uuid>"
    return (
        tzid,
        ev.type,
        detail.get("bar_ts"),
        detail.get("leg"),
        detail.get("reason"),
    )


def _order_key(o: Order) -> tuple:
    """Normalize order to compare across BT vs live paths.

    Excludes trade_id (fresh UUID per run). Retains price/qty/side/tag identity
    — enough to prove strategy generated the SAME order semantics.
    """
    return (
        o.symbol,
        int(o.side),
        round(float(o.stop_price), 5),
        round(float(o.take_profit or 0), 5),
        round(float(o.risk_units), 5),
        str(o.intended_entry_bar),
        o.tag,
    )


def _run_capture(*, mode: str, frame: pd.DataFrame, strategy: str) -> dict:
    provider = MemoryBarProvider(frame, symbol="XAUUSD.ecn", timeframe="M15")
    clock = MemoryClock(provider)
    strat = registry.get(strategy, symbol="XAUUSD.ecn")

    events: list = []
    opened_trades: list[Order] = []

    def _on_event(ev) -> None:
        events.append(_event_key(ev))

    def _on_open(tr) -> None:
        opened_trades.append(_order_key(tr.order))

    if mode == "bt":
        deps = EngineDeps(
            clock=clock,
            data_provider=provider,
            strategy=strat,
            execution=BTExecutionModel(),
            broker=None,
            on_trade_open=_on_open,
            on_strategy_event=_on_event,
        )
    else:
        broker = BTMirrorLiveBroker()
        deps = EngineDeps(
            clock=clock,
            data_provider=provider,
            strategy=strat,
            execution=None,
            broker=broker,
            on_trade_open=_on_open,
            on_strategy_event=_on_event,
        )
    run = run_engine(run_id=uuid.uuid4(), deps=deps, mode=mode)
    return {"events": events, "orders": opened_trades, "bars": run.bars_processed}


def test_intraday_a_bt_matches_live_event_stream() -> None:
    frame = _load_m15(300)
    bt = _run_capture(mode="bt", frame=frame, strategy="fib_v2_intraday_a")
    live = _run_capture(mode="live", frame=frame, strategy="fib_v2_intraday_a")
    assert bt["bars"] == live["bars"], "engine consumed different bar counts"
    assert bt["events"] == live["events"], (
        f"event streams diverge: {len(bt['events'])} BT vs {len(live['events'])} live"
    )
    assert bt["orders"] == live["orders"], (
        f"order streams diverge: BT {len(bt['orders'])} vs live {len(live['orders'])}"
    )


def test_intraday_d_bt_matches_live_event_stream() -> None:
    frame = _load_m15(300)
    bt = _run_capture(mode="bt", frame=frame, strategy="fib_v2_intraday_d")
    live = _run_capture(mode="live", frame=frame, strategy="fib_v2_intraday_d")
    assert bt["bars"] == live["bars"]
    assert bt["events"] == live["events"]
    assert bt["orders"] == live["orders"]


def test_event_count_grows_with_bar_count() -> None:
    """Sanity: increasing bar window increases event count (proves test is not vacuous)."""
    small = _run_capture(mode="bt", frame=_load_m15(100), strategy="fib_v2_intraday_a")
    large = _run_capture(mode="bt", frame=_load_m15(400), strategy="fib_v2_intraday_a")
    assert len(large["events"]) > len(small["events"]), (
        f"suspicious: 100 bars → {len(small['events'])} events, "
        f"400 bars → {len(large['events'])}"
    )
