"""[DEPRECATED 2026-06-30] EmaCrossStrategy — replaced by fib_v2_xau_ensemble.

Kept for reference / smoke tests. Not a production strategy. See plan at
/Users/subash/.claude/plans/ok-now-that-we-piped-fog.md.

Original docstring:
EmaCrossStrategy — simple incremental EMA-cross signal.

Demonstrates the Strategy ABC + incremental state pattern. Two EMAs (fast/slow)
updated bar-by-bar. Cross up = LONG, cross down = SHORT. Stop = entry ± k*ATR.
Take-profit = entry ± 2*k*ATR (1:2 R:R by default).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ...core.bar import Bar
from ...core.order import Order
from ...core.signal import StepResult, StrategyEvent
from ...core.state import StrategyState
from ..base import Strategy


@dataclass(frozen=True)
class EmaCrossConfig:
    fast: int = 12
    slow: int = 26
    atr_period: int = 14
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    qty: float = 1.0


@dataclass
class EmaCrossState(StrategyState):
    fast_ema: float | None = None
    slow_ema: float | None = None
    prev_diff: float | None = None
    prev_close: float | None = None
    atr_buf: list[float] = field(default_factory=list)
    atr: float | None = None
    bars_seen: int = 0
    in_position_side: int = 0  # 0=none, +1/-1


def _ema(prev: float | None, value: float, period: int) -> float:
    if prev is None:
        return value
    k = 2.0 / (period + 1.0)
    return value * k + prev * (1.0 - k)


def _true_range(prev_close: float | None, h: float, l: float) -> float:
    if prev_close is None:
        return h - l
    return max(h - l, abs(h - prev_close), abs(l - prev_close))


class EmaCrossStrategy(Strategy):
    strategy_id = "ema_cross"

    def __init__(self, config: EmaCrossConfig | None = None, *, symbol: str = "XAUUSD", qty: float | None = None) -> None:
        self.config = config or EmaCrossConfig()
        self.symbol = symbol
        if qty is not None:
            self.config = EmaCrossConfig(
                fast=self.config.fast, slow=self.config.slow,
                atr_period=self.config.atr_period,
                sl_atr_mult=self.config.sl_atr_mult, tp_atr_mult=self.config.tp_atr_mult,
                qty=qty,
            )

    def initial_state(self) -> EmaCrossState:
        return EmaCrossState()

    def on_bar(
        self,
        state: EmaCrossState,
        bar: Bar,
        history: pd.DataFrame,
    ) -> StepResult:
        state.bars_seen += 1
        # update ATR (Wilder-ish — rolling mean of TR for simplicity)
        tr = _true_range(state.prev_close, bar.high, bar.low)
        state.atr_buf.append(tr)
        if len(state.atr_buf) > self.config.atr_period:
            state.atr_buf.pop(0)
        if len(state.atr_buf) >= self.config.atr_period:
            state.atr = sum(state.atr_buf) / len(state.atr_buf)

        # update EMAs
        state.fast_ema = _ema(state.fast_ema, bar.close, self.config.fast)
        state.slow_ema = _ema(state.slow_ema, bar.close, self.config.slow)
        diff = state.fast_ema - state.slow_ema
        prev = state.prev_diff
        state.prev_diff = diff
        state.prev_close = bar.close

        # need warm-up + ATR before signalling
        if (
            state.bars_seen <= max(self.config.fast, self.config.slow)
            or state.atr is None
            or prev is None
        ):
            return StepResult(state=state)

        # cross detection on the JUST-closed bar; entry on NEXT bar open
        cross_up = prev <= 0 and diff > 0
        cross_down = prev >= 0 and diff < 0
        orders: tuple[Order, ...] = ()
        events: tuple[StrategyEvent, ...] = ()

        if cross_up and state.in_position_side <= 0:
            side = 1
            sl = bar.close - self.config.sl_atr_mult * state.atr
            tp = bar.close + self.config.tp_atr_mult * state.atr
            risk = abs(bar.close - sl)
            next_bar_ts = bar.timestamp + pd.Timedelta(seconds=_tf_seconds(bar.timeframe))
            tid = uuid.uuid4()
            orders = (
                Order(
                    symbol=self.symbol, side=side, qty=self.config.qty,
                    intended_entry_bar=next_bar_ts,
                    stop_price=sl, take_profit=tp, risk_units=risk,
                    tag=f"ema_cross_up_{bar.timestamp.isoformat()}",
                    bracket_kind="ATR",
                    trade_id=tid,
                ),
            )
            events = (
                StrategyEvent(
                    trade_or_zone_id=str(tid), type="ENTRY_SUBMIT",
                    detail={"side": 1, "fast": state.fast_ema, "slow": state.slow_ema, "atr": state.atr},
                ),
            )
            state.in_position_side = 1
        elif cross_down and state.in_position_side >= 0:
            side = -1
            sl = bar.close + self.config.sl_atr_mult * state.atr
            tp = bar.close - self.config.tp_atr_mult * state.atr
            risk = abs(sl - bar.close)
            next_bar_ts = bar.timestamp + pd.Timedelta(seconds=_tf_seconds(bar.timeframe))
            tid = uuid.uuid4()
            orders = (
                Order(
                    symbol=self.symbol, side=side, qty=self.config.qty,
                    intended_entry_bar=next_bar_ts,
                    stop_price=sl, take_profit=tp, risk_units=risk,
                    tag=f"ema_cross_dn_{bar.timestamp.isoformat()}",
                    bracket_kind="ATR",
                    trade_id=tid,
                ),
            )
            events = (
                StrategyEvent(
                    trade_or_zone_id=str(tid), type="ENTRY_SUBMIT",
                    detail={"side": -1, "fast": state.fast_ema, "slow": state.slow_ema, "atr": state.atr},
                ),
            )
            state.in_position_side = -1
        return StepResult(state=state, new_orders=orders, new_events=events)


def _tf_seconds(tf: str) -> int:
    from ...data.timeframes import seconds
    return seconds(tf)
