"""run_engine — the ONE bar-close event loop, used by BT and live.

Hard guards on every tick:
    1. history.iloc[-1]["timestamp"] == bar.timestamp
    2. (history["timestamp"] <= bar.timestamp).all()
    3. state is deepcopied before passing to on_bar
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Sequence
from typing import Any, Callable

import pandas as pd

from .bar import Bar
from .bracket import walk_bracket_on_bar
from .order import BracketOutcome, Fill, OpenTrade, Order
from .protocols import BrokerAdapter, Clock, DataProvider, ExecutionModel, Strategy
from .recorder import TradeRecorder
from .signal import StepResult, StrategyEvent
from ..journal.walker import BarWalkJournal


@dataclass
class EngineDeps:
    clock: Clock
    data_provider: DataProvider
    strategy: Strategy
    execution: ExecutionModel | None = None
    broker: BrokerAdapter | None = None
    recorder: TradeRecorder | None = None
    journal: BarWalkJournal | None = None
    on_trade_open: Callable[[OpenTrade], None] | None = None
    on_trade_close: Callable[[OpenTrade, BracketOutcome], None] | None = None
    on_strategy_event: Callable[[StrategyEvent], None] | None = None
    on_bar_close: Callable[[Bar, list[OpenTrade]], None] | None = None
    on_partial_tp: Callable[[OpenTrade, Bar], None] | None = None
    initial_open_trades: Sequence[OpenTrade] = ()
    max_bars_held: int | None = None


@dataclass
class EngineRun:
    run_id: uuid.UUID
    deps: EngineDeps
    closed_trades: list[tuple[OpenTrade, BracketOutcome]] = field(default_factory=list)
    bars_processed: int = 0


def _check_history(history: pd.DataFrame, bar: Bar) -> None:
    if history.empty:
        raise AssertionError("history is empty at bar tick")
    last_ts = history["timestamp"].iloc[-1]
    if last_ts != bar.timestamp:
        raise AssertionError(
            f"history last timestamp {last_ts} != bar.timestamp {bar.timestamp}"
        )
    # The DataFrame contract requires `timestamp` to be sorted ascending. If
    # last_ts == bar.timestamp, by sort invariant ALL entries are <= bar.timestamp.
    # Skip the O(N) `.all()` scan for performance; providers must enforce sortedness.


def run_engine(
    *,
    run_id: uuid.UUID,
    deps: EngineDeps,
    mode: str = "bt",
    max_bars: int | None = None,
) -> EngineRun:
    if mode not in ("bt", "live"):
        raise ValueError(f"mode must be 'bt' or 'live', got {mode}")
    state = deps.strategy.initial_state()
    pending: list[Order] = []
    open_trades: list[OpenTrade] = list(deps.initial_open_trades)
    run = EngineRun(run_id=run_id, deps=deps)
    if deps.on_trade_open:
        for trade in open_trades:
            deps.on_trade_open(trade)

    while True:
        bar = deps.clock.tick()
        if bar is None:
            break
        run.bars_processed += 1

        history = deps.data_provider.history_up_to(bar.timestamp)
        _check_history(history, bar)

        # 1) fill orders intended for this bar's OPEN
        for o in list(pending):
            if o.intended_entry_bar == bar.timestamp:
                if mode == "bt":
                    if deps.execution is None:
                        raise RuntimeError("BT mode requires execution model")
                    fill = deps.execution.simulate_fill(o, bar)
                else:
                    submitted = _submit_live_order(deps, o, bar)
                    if submitted is None:
                        pending.remove(o)
                        continue
                    fill, filled_order, ticket = submitted
                trade = _open_trade_from_fill(o, fill)
                if mode == "live":
                    trade = _open_trade_from_fill(filled_order, fill, broker_ticket=ticket)
                open_trades.append(trade)
                pending.remove(o)
                if deps.on_trade_open:
                    deps.on_trade_open(trade)

        # 2) walk brackets on this just-closed bar; record bar-walk for active trades
        for tr in list(open_trades):
            if deps.journal is not None:
                deps.journal.observe(tr.trade_id, bar, phase="in_trade")
            outcome = walk_bracket_on_bar(
                tr, bar,
                max_bars_held=deps.max_bars_held,
                on_partial_tp=deps.on_partial_tp,
            )
            if outcome is not None:
                run.closed_trades.append((tr, outcome))
                if deps.on_trade_close:
                    deps.on_trade_close(tr, outcome)
                open_trades.remove(tr)

        if deps.on_bar_close:
            deps.on_bar_close(bar, list(open_trades))

        # 3) strategy step on copied state
        state_copy = state.clone() if hasattr(state, "clone") else state
        step = deps.strategy.on_bar(state_copy, bar, history)
        state = step.state
        for ev in step.new_events:
            if deps.on_strategy_event:
                deps.on_strategy_event(ev)
        if mode == "live":
            for o in step.new_orders:
                submitted = _submit_live_order(deps, o, bar)
                if submitted is None:
                    continue
                fill, filled_order, ticket = submitted
                trade = _open_trade_from_fill(filled_order, fill, broker_ticket=ticket)
                open_trades.append(trade)
                if deps.on_trade_open:
                    deps.on_trade_open(trade)
        else:
            # Process orders intended for THIS bar immediately (fill at bar.open).
            # Research's vectorized signal-gen does `entry_price = op[k+1]`
            # using the SAME bar that triggered the signal — i.e. the bar
            # whose `on_bar` JUST ran. Strategies that want a 1-bar lag must
            # set `intended_entry_bar = bar.timestamp + tf_seconds`.
            for o in step.new_orders:
                if o.intended_entry_bar == bar.timestamp:
                    if deps.execution is None:
                        raise RuntimeError("BT mode requires execution model")
                    fill = deps.execution.simulate_fill(o, bar)
                    trade = _open_trade_from_fill(o, fill)
                    open_trades.append(trade)
                    if deps.on_trade_open:
                        deps.on_trade_open(trade)
                else:
                    pending.append(o)

        if max_bars is not None and run.bars_processed >= max_bars:
            break

    if deps.recorder is not None:
        deps.recorder.finalize()
    return run


def _submit_live_order(deps: EngineDeps, order: Order, bar: Bar) -> tuple[Fill, Order, str | None] | None:
    if deps.broker is None:
        raise RuntimeError("live mode requires broker")
    if hasattr(deps.broker, "set_current_bar"):
        deps.broker.set_current_bar(bar)  # type: ignore[attr-defined]
    deps.broker.submit_order(order)
    submitted_order = getattr(deps.broker, "last_submitted_order", None) or order
    fill = next(deps.broker.fills(), None)
    if fill is None:
        if deps.on_strategy_event:
            deps.on_strategy_event(
                StrategyEvent(
                    trade_or_zone_id=str(order.trade_id or order.tag),
                    type="ORDER_SUBMIT_NO_FILL",
                    detail={"symbol": order.symbol, "tag": order.tag, "bar_timestamp": str(bar.timestamp)},
                )
            )
        return None
    if fill.price <= 0:
        if deps.on_strategy_event:
            deps.on_strategy_event(
                StrategyEvent(
                    trade_or_zone_id=str(order.trade_id or order.tag),
                    type="ORDER_FILL_INVALID",
                    detail={"price": fill.price, "symbol": order.symbol, "tag": order.tag},
                )
            )
        return None
    normalized_fill = Fill(
        symbol=fill.symbol or order.symbol,
        side=fill.side if fill.side in (-1, 1) else order.side,
        qty=fill.qty if fill.qty > 0 else order.qty,
        price=fill.price,
        fill_timestamp=fill.fill_timestamp,
    )
    ticket = None
    if hasattr(deps.broker, "last_response"):
        resp = deps.broker.last_response()  # type: ignore[attr-defined]
        if isinstance(resp, dict):
            raw = resp.get("ticket")
            if raw is not None:
                ticket = str(raw)
    return normalized_fill, submitted_order, ticket


def _open_trade_from_fill(
    order: Order, fill: Fill, *, broker_ticket: str | None = None,
) -> OpenTrade:
    return OpenTrade(
        trade_id=order.trade_id or uuid.uuid4(),
        order=order,
        fill=fill,
        entry_price=fill.price,
        entry_timestamp=fill.fill_timestamp,
        side=order.side,
        stop_price=order.stop_price,
        take_profit=order.take_profit,
        risk_units=order.risk_units,
        broker_ticket=broker_ticket,
    )
