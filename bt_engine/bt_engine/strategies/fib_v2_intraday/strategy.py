"""FibV2 INTRADAY strategy — A+D production port (M15 base + M15 pivots).

100TH-TIME AUDIT CHECKLIST (verified per file):
  1. NO center-rolling pivots — PivotTracker(lb=3) emits at idx+lb (inherited).
  2. D1 features shift(1)-lagged — RegimeTracker (inherited, but regime='any' so gate is OFF).
  3. Phantom-fill prevention — entry at NEXT bar.open via base _finalize_entry queue (inherited).
  4. Bar-close timing — on_bar receives just-closed bar; PivotTracker fed directly with it
     (no floor("1h"), no last_h1_seen, no resample → eliminates the entire H1-derivation bug surface).
  5. Multi-pivot stacking — DEDUP via state.consumed_entry_keys on (entry_ts, side, leg_name).
  6. Min risk floor — min_risk_units=$0.50 gate in _finalize_entry rejects tiny stops.
  7. Session in NY hour only from bar.timestamp (inherited via _ny_hour).
  8. Cost double-count — cost_r computed ONCE in base _finalize_entry, engine reads from extra.
  9. Same-direction concurrent same-bar — blocked by dedup. Opposite-dir A+D allowed by design.
 10. Risk-pct cap — max_risk_pct=0.02 kept (inherited).

Design notes:
  - Subclass FibV2EnsembleStrategy. Reuse on_bar orchestration, _build_setup,
    _signal_bar_matches, regime/swing trackers, partial-TP wiring.
  - Override ONLY 3 methods: _update_h1_pivots, validate_for_live, _finalize_entry.
  - Override on_bar with a thin shim that pins state to self._current_state_ref
    so the overridden _finalize_entry can access consumed_entry_keys without
    changing the base class signature (wider blast radius).
  - Single-threaded engine = safe for the state ref pin.
"""
from __future__ import annotations

from typing import Optional, Sequence

import pandas as pd

from ...core.bar import Bar
from ...core.order import Order
from ...core.signal import StepResult, StrategyEvent
from ...journal.events import JournalEvent
from ..fib_v2.config import LegSpec
from ..fib_v2.pivot_tracker import PivotEvent
from ..fib_v2.state import FibSetup, FibV2State
from ..fib_v2.strategy import FibV2EnsembleStrategy

from .config import (
    FibV2IntradayConfig,
    INTRADAY_A_LEG,
    INTRADAY_D_LEG,
    make_intraday_a_config,
    make_intraday_d_config,
)


class FibV2IntradayBase(FibV2EnsembleStrategy):
    """Base class for intraday Fib V2 variants.

    Differences from FibV2EnsembleStrategy:
      - Pivot feed is direct: every M15 base bar IS a pivot input (no H1 aggregation).
      - validate_for_live accepts M15 (not M5).
      - _finalize_entry enforces min_risk_units floor + (entry_ts, side, leg_name) dedup.
    """

    strategy_id = "fib_v2_intraday_base"

    def __init__(
        self,
        *,
        symbol: str = "XAUUSD.ecn",
        intraday_config: FibV2IntradayConfig,
        legs: Sequence[LegSpec],
        qty: Optional[float] = None,
        cost_usd: Optional[float] = None,
    ) -> None:
        self._intraday_cfg = intraday_config
        # Force-route cost_usd from our config to override base's COST_USD_DEFAULTS map.
        # Without this, XAUUSD.ecn maps to $0.30 (OANDA backtest) instead of $0.65 (JustMarkets).
        # Only honor an explicit caller override (cost_usd kwarg) above our config.
        effective_cost = cost_usd if cost_usd is not None else intraday_config.base.cost_usd
        # Pass wrapped FibV2Config to the base. multi_tf_view=None — intraday
        # ingests pivots directly per-bar, never uses H1/D1 fast paths.
        super().__init__(
            symbol=symbol,
            config=intraday_config.base,
            legs=tuple(legs),
            qty=qty,
            cost_usd=effective_cost,
            multi_tf_view=None,
        )
        # Pinned during on_bar for _finalize_entry access. Cleared after.
        self._current_state_ref: Optional[FibV2State] = None

    # ----- OVERRIDE: pivot ingestion (M15 direct feed) -----

    def _update_h1_pivots(
        self, state: FibV2State, bar: Bar, history: pd.DataFrame,
    ) -> list[PivotEvent]:
        """Intraday: pivot_tf == base_tf == M15. Direct feed of just-closed bar.

        Causal contract:
          - on_bar receives a JUST-CLOSED M15 bar (engine guarantees this).
          - PivotTracker.update(bar) reads only bar.timestamp/high/low.
          - Confirmation lands at idx+lb naturally (lb=3 → 45min ahead).
          - No floor("1h"), no last_h1_seen, no resample → NO LOOK-AHEAD.
        """
        return state.pivot_tracker.update(bar)

    # ----- OVERRIDE: strict-after setup_confirm_ts for entry scan -----

    def _signal_bar_matches(
        self, state: FibV2State, bar: Bar, leg: LegSpec, setup: FibSetup,
    ) -> bool:
        """Match research's strict `searchsorted(..., side='right')` semantic.

        Research scans entries from FIRST bar AFTER setup_confirm_ts (idx +1).
        The base class allows match ON the confirm bar (>=). Intraday port
        enforces strict-after to match research bit-for-bit.

        Effect: setup created at bar K is eligible for entry starting bar K+1.
        """
        if bar.timestamp == setup.setup_confirm_ts:
            self._emit_gate(
                JournalEvent.GATE_SIGNAL_STRICT_AFTER_FAIL, bar.timestamp,
                leg_name=leg.leg_name, setup=setup,
            )
            return False
        return super()._signal_bar_matches(state, bar, leg, setup)

    # ----- OVERRIDE: live timeframe validation -----

    def validate_for_live(self, *, timeframe: str) -> None:
        expected = self._intraday_cfg.base_tf.upper()
        if timeframe.upper() != expected:
            raise ValueError(
                f"{self.__class__.__name__} requires timeframe='{expected}', got {timeframe}. "
                "Pivots are M15-based and the engine drives M15 bars."
            )

    # ----- OVERRIDE: _finalize_entry (min_risk floor + entry-bar dedup) -----

    def _finalize_entry(
        self, bar: Bar, leg: LegSpec, setup: FibSetup,
    ) -> tuple[Optional[Order], Optional[StrategyEvent]]:
        """Call base, then apply two production gates before returning order.

        Gate A: min_risk_units floor — reject broker-untradeable tiny stops.
        Gate B: (entry_ts, side, leg_name) dedup — reject multi-pivot stacking.

        Both gates run AFTER base risk-pct check, BEFORE order propagates to engine.
        """
        order, event = super()._finalize_entry(bar, leg, setup)
        if order is None:
            return None, None  # base rejected (risk_pct cap or risk<=0)

        # ─── Gate A: min risk floor ────────────────────────────────
        if order.risk_units < self._intraday_cfg.min_risk_units:
            self._emit_gate(
                JournalEvent.GATE_FINALIZE_MIN_RISK_FLOOR, bar.timestamp,
                leg_name=leg.leg_name, setup=setup,
                risk_units=float(order.risk_units),
                min_risk_units=self._intraday_cfg.min_risk_units,
            )
            return None, None

        # ─── Gate B: (entry_ts, side, leg_name) dedup ──────────────
        state = self._current_state_ref
        if state is None:
            # Defensive: should NEVER happen because on_bar shim pins state.
            # If it does, we still permit the order (don't silently drop).
            return order, event
        key = (bar.timestamp, int(setup.side), leg.leg_name)
        if key in state.consumed_entry_keys:
            self._emit_gate(
                JournalEvent.GATE_FINALIZE_DEDUP_COLLISION, bar.timestamp,
                leg_name=leg.leg_name, setup=setup,
                side=int(setup.side),
            )
            return None, None
        state.consumed_entry_keys.add(key)

        return order, event

    # ----- shim: expose state to _finalize_entry -----

    def on_bar(
        self, state: FibV2State, bar: Bar, history: pd.DataFrame,
    ) -> StepResult:
        """Pin state ref so overridden _finalize_entry can access consumed_entry_keys.

        Base class _finalize_entry signature doesn't take state. Rather than
        change the base signature (wider blast radius), we expose state via
        a per-call attribute. Single-threaded engine = safe.
        """
        self._current_state_ref = state
        try:
            return super().on_bar(state, bar, history)
        finally:
            self._current_state_ref = None  # clear after each bar


class FibV2IntradayA(FibV2IntradayBase):
    """A leg: LONG, lb=3, hold=12h, session=london_ny, regime=any, PTP+1R."""

    strategy_id = "fib_v2_intraday_a"

    def __init__(
        self,
        *,
        symbol: str = "XAUUSD.ecn",
        intraday_config: Optional[FibV2IntradayConfig] = None,
        qty: Optional[float] = None,
        cost_usd: Optional[float] = None,
        **_runner_kwargs,  # absorb runner-only kwargs (e.g. ignore_events_before)
    ) -> None:
        cfg = intraday_config or make_intraday_a_config()
        super().__init__(
            symbol=symbol,
            intraday_config=cfg,
            legs=(INTRADAY_A_LEG,),
            qty=qty,
            cost_usd=cost_usd,
        )


class FibV2IntradayD(FibV2IntradayBase):
    """D leg: SHORT, lb=3, hold=24h, session=all, regime=any, PTP+1R."""

    strategy_id = "fib_v2_intraday_d"

    def __init__(
        self,
        *,
        symbol: str = "XAUUSD.ecn",
        intraday_config: Optional[FibV2IntradayConfig] = None,
        qty: Optional[float] = None,
        cost_usd: Optional[float] = None,
        **_runner_kwargs,  # absorb runner-only kwargs (e.g. ignore_events_before)
    ) -> None:
        cfg = intraday_config or make_intraday_d_config()
        super().__init__(
            symbol=symbol,
            intraday_config=cfg,
            legs=(INTRADAY_D_LEG,),
            qty=qty,
            cost_usd=cost_usd,
        )
