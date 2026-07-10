"""CobraxStrategy — streaming causal port of research/cobrax/cobrax.py.

Per closed M5 bar (on_bar):
  1. push the bar to the rolling window; update the HTF-bias tracker.
  2. run detect_setup_at (research sweep→MSS→FVG∩OTE inner logic) for THIS bar as the
     signal → ARM the setup (limit at the FVG edge, SL past the swept extreme, expiry
     `retrace_wait` bars out).
  3. for each armed setup, if THIS bar retraced into the limit (strictly after the FVG
     bar, before expiry), emit an Order filled AT the limit on this bar. Dedup fills by
     (fill_idx, side) — mirrors research `used=set((fi, iside))`.

Causal contract: sweep/MSS/FVG/OTE/bias all read CLOSED bars strictly before the fill
bar; the limit price is known at the FVG bar; the bracket walks from the NEXT bar (the
engine appends the trade after this bar's bracket step) — a deterministic 1-bar
conservatism vs research (never manufactures edge). Phase-2 parity measures the delta.
"""
from __future__ import annotations

import uuid
from typing import Optional

import numpy as np
import pandas as pd

from ...core.bar import Bar
from ...core.order import Order
from ...core.signal import StepResult
from .config import COBRAX_LONG_LEG, COBRAX_SHORT_LEG, CobraxConfig, make_cobrax_config
from .detectors import confirmed_pivots, detect_setup_at
from .htf_bias import HtfBiasTracker
from .state import ArmedSetup, CobraxState


class CobraxStrategy:
    strategy_id = "cobrax"

    def __init__(
        self,
        *,
        symbol: str = "XAUUSD.ecn",
        config: Optional[CobraxConfig] = None,
        **_runner_kwargs,  # absorb runner-only kwargs (e.g. ignore_events_before)
    ) -> None:
        self.symbol = symbol
        self.config = config or make_cobrax_config()
        # window must hold enough history to detect a setup at the newest bar:
        # sweep look-back + FVG scan + margin (the retrace fill checks the live bar
        # directly, so future fill bars need not be buffered).
        self.window = (
            self.config.sweep_lb + self.config.fvg_wait + 4 * self.config.mss_lb + 40
        )

    # ----- lifecycle -----

    def initial_state(self) -> CobraxState:
        return CobraxState(
            cfg=self.config,
            bias=HtfBiasTracker(tf_min=self.config.htf_tf_min, sma_period=20),
        )

    def validate_for_live(self, *, timeframe: str) -> None:
        if timeframe.upper() != self.config.base_tf.upper():
            raise ValueError(
                f"CobraxStrategy requires timeframe='{self.config.base_tf}', got {timeframe}."
            )

    # ----- per-bar -----

    def on_bar(self, state: CobraxState, bar: Bar, history: pd.DataFrame) -> StepResult:
        cfg = state.cfg
        cur_abs = state.push_bar(bar, maxlen=self.window)
        state.bias.update(bar)
        bias = state.bias.bias()

        m = len(state.win_idx) - 1  # local index of the current (newest) bar
        if m < 2 * cfg.mss_lb + 2:
            return StepResult(state)

        o = np.fromiter(state.win_o, dtype=float)
        h = np.fromiter(state.win_h, dtype=float)
        l = np.fromiter(state.win_l, dtype=float)
        c = np.fromiter(state.win_c, dtype=float)
        win_idx = list(state.win_idx)
        win_ts = list(state.win_ts)

        # 1) detect + arm a setup confirmed at this bar
        cp = confirmed_pivots(h, l, cfg.mss_lb)
        setup = detect_setup_at(o, h, l, c, cp, m, bias, cfg)
        if setup is not None:
            armed = ArmedSetup(
                side=setup.side,
                entry_level=setup.entry_level,
                stop=setup.stop,
                sweep_ext=setup.sweep_ext,
                fvg_abs_idx=win_idx[setup.fvg_i],
                expiry_abs_idx=win_idx[setup.fvg_i] + cfg.retrace_wait,
                setup_ts=win_ts[setup.mss_i],
                sweep_ts=win_ts[setup.sweep_i],
                fvg_ts=win_ts[setup.fvg_i],
            )
            if armed.key() not in state.armed_keys:
                state.armed.append(armed)
                state.armed_keys.add(armed.key())

        # 2) fill any armed setup retraced into on THIS bar (strictly after its FVG bar)
        orders: list[Order] = []
        survivors: list[ArmedSetup] = []
        for a in state.armed:
            if cur_abs > a.expiry_abs_idx:
                continue  # retrace window elapsed → drop
            if cur_abs <= a.fvg_abs_idx:
                survivors.append(a)
                continue  # fill must be strictly after the FVG bar
            touched = (
                (a.side < 0 and bar.high >= a.entry_level)
                or (a.side > 0 and bar.low <= a.entry_level)
            )
            if not touched:
                survivors.append(a)
                continue
            fkey = (cur_abs, a.side)
            if fkey in state.consumed_fill_keys:
                continue  # one fill per (bar, side)
            order = self._build_order(a, bar)
            if order is not None:
                state.consumed_fill_keys.add(fkey)
                orders.append(order)
            # filled (or rejected by a gate) → do not carry forward

        state.armed = survivors
        state.armed_keys = {a.key() for a in survivors}
        return StepResult(state, tuple(orders))

    # ----- order construction -----

    def _build_order(self, a: ArmedSetup, bar: Bar) -> Optional[Order]:
        cfg = self.config
        entry = float(a.entry_level)
        R = abs(entry - a.stop)
        if R < cfg.min_risk_units:
            return None
        if R > cfg.max_risk_pct * entry:  # untradeably-wide stop
            return None
        if cfg.tp_mode == "rr":
            tp = entry - cfg.tp_r * R if a.side < 0 else entry + cfg.tp_r * R
        else:  # next-liquidity target not yet ported — headline deploy uses rr
            raise NotImplementedError("tp_mode='nl' not yet ported; use tp_mode='rr'")
        leg = COBRAX_SHORT_LEG if a.side < 0 else COBRAX_LONG_LEG
        cost_r = float(cfg.cost_usd) / R if R > 0 else 0.0
        return Order(
            symbol=self.symbol,
            side=a.side,
            qty=1.0,  # placeholder; live equity sizer overrides
            intended_entry_bar=pd.Timestamp(bar.timestamp),
            stop_price=float(a.stop),
            take_profit=float(tp),
            risk_units=float(R),
            tag=f"{leg.leg_name}_{pd.Timestamp(bar.timestamp).isoformat()}",
            bracket_kind="fixed_tp",
            trade_id=uuid.uuid4(),
            extra={
                "limit_price": entry,
                "max_hold_bars": int(cfg.max_hold_bars),
                "cost_r": cost_r,
                "leg": leg.leg_name,
                "direction": leg.direction,
                "sweep_ts": str(a.sweep_ts),
                "setup_ts": str(a.setup_ts),
                "fvg_ts": str(a.fvg_ts),
            },
        )
