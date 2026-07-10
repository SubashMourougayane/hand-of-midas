"""CobraxStrategy — streaming causal port of research/cobrax/cobrax.py.

Faithful reproduction of research's VECTORIZED re-scan enumeration, causally:

  Per closed M5 bar (on_bar):
    1. update the HTF-bias tracker; push the bar + its bias to a rolling window.
    2. call fills_at_bar(m=newest) — enumerate signal bars i over the window (research's
       outer loop), reproduce the sweep→MSS→FVG∩OTE→retrace-fill chain, and return the
       trade(s) whose FIRST retrace touch lands EXACTLY on this bar, using the smallest
       signal i (== research's greedy `used=set((fi,side))` dedup). All candidate i for a
       fill at m lie within [m-(fvg_wait+retrace_wait), m], so a bounded window is exact.
    3. emit an Order for each — filled AT the FVG-edge limit on this bar (CobraxLimitExecution).

Causal contract: the fill touch is read from the JUST-CLOSED bar (h[m]/l[m]) — no forward
peek; sweep/MSS/FVG/OTE/bias are all strictly ≤ the fill bar. The engine appends the trade
AFTER this bar's bracket step, so the bracket walks from the NEXT bar — a deterministic
1-bar offset vs research measured in Phase-2 parity (never manufactures edge).
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
from .detectors import SetupCandidate, confirmed_pivots, fills_at_bar
from .htf_bias import HtfBiasTracker
from .state import CobraxState


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
        # signal-bar lookback for fills_at_bar: every candidate i for a fill at m lies in
        # [m-(fvg_wait+retrace_wait), m]; a small margin covers the MSS/sweep chain.
        self.lookback = self.config.fvg_wait + self.config.retrace_wait + 5
        # window must also hold each signal i's own sweep look-back + pivot confirmation.
        self.window = (
            self.config.sweep_lb + self.lookback + 4 * self.config.mss_lb + 40
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
        state.bias.update(bar)
        bias = state.bias.bias()
        state.push_bar(bar, bias=bias, maxlen=self.window)

        m = len(state.win_idx) - 1
        if m < cfg.sweep_lb + 2 * cfg.mss_lb + 2:
            return StepResult(state)

        o = np.fromiter(state.win_o, dtype=float)
        h = np.fromiter(state.win_h, dtype=float)
        l = np.fromiter(state.win_l, dtype=float)
        c = np.fromiter(state.win_c, dtype=float)
        bias_arr = np.fromiter(state.win_bias, dtype=int)
        win_ts = list(state.win_ts)

        cp = confirmed_pivots(h, l, cfg.mss_lb)
        setups = fills_at_bar(o, h, l, c, cp, bias_arr, cfg, m, lookback=self.lookback)

        orders: list[Order] = []
        for s in setups:
            order = self._build_order(s, bar, win_ts)
            if order is not None:
                orders.append(order)
        return StepResult(state, tuple(orders))

    # ----- order construction -----

    def _build_order(self, s: SetupCandidate, bar: Bar, win_ts: list) -> Optional[Order]:
        cfg = self.config
        entry = float(s.entry_level)
        R = abs(entry - s.stop)
        if R < cfg.min_risk_units:
            return None
        if R > cfg.max_risk_pct * entry:
            return None
        if cfg.tp_mode == "rr":
            tp = entry - cfg.tp_r * R if s.side < 0 else entry + cfg.tp_r * R
        else:
            raise NotImplementedError("tp_mode='nl' not yet ported; use tp_mode='rr'")
        leg = COBRAX_SHORT_LEG if s.side < 0 else COBRAX_LONG_LEG
        cost_r = float(cfg.cost_usd) / R if R > 0 else 0.0
        return Order(
            symbol=self.symbol,
            side=s.side,
            qty=1.0,  # placeholder; live equity sizer overrides
            intended_entry_bar=pd.Timestamp(bar.timestamp),
            stop_price=float(s.stop),
            take_profit=float(tp),
            risk_units=float(R),
            tag=f"{leg.leg_name}_{pd.Timestamp(bar.timestamp).isoformat()}",
            bracket_kind="fixed_tp",
            trade_id=uuid.uuid4(),
            extra={
                "limit_price": entry,
                "max_hold_bars": int(cfg.max_hold_bars),
                "bracket_wick": True,  # COBRAX SL/TP are hard levels (research + live server-side)
                "cost_r": cost_r,
                "leg": leg.leg_name,
                "direction": leg.direction,
                "sweep_ts": str(win_ts[s.sweep_i]),
                "setup_ts": str(win_ts[s.mss_i]),
                "fvg_ts": str(win_ts[s.fvg_i]),
            },
        )
