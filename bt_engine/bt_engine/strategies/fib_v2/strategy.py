"""FibV2EnsembleStrategy — production XAU + EUR Fib V2 ENSEMBLE.

Streams the research `gen_signals_with_regime` logic into incremental `on_bar`
form. Both LONG_BULL_STRONG and SHORT_BEAR_STRONG legs are evaluated each bar.

Causality contract (matches research):
  1. H1 pivots: detected via PivotTracker. Pivot at H1 bar i is emitted at the
     close of H1 bar i+lb (lb=5). confirm_ts = i+lb left-label.
  2. D1 regime: features lagged 1 day. At M5 bar t whose ts.floor('1D')=D,
     RegimeTracker.regime_for(t) returns features from the LAST closed D1 < D.
  3. Setup: built once both `last_L` (LONG: L_ts < H_ts) and `last_H` are known.
     fib_382, fib_786, fib_100 = L, tp = H + ext*diff, sl = L - sl_buf*diff.
  4. Per-bar scan: from setup_confirm_ts forward, capped at max_hold_bars.
     - Invalidation: long bar.close < fib_100 → drop setup.
     - Zone hit: fib_786 <= close <= fib_382 (long) AND session ok AND regime ok.
     - Confirmation candle: bullish engulfing OR lower-wick pinbar
       (use prev bar's open/close for engulfing).
     - If all pass → emit Order(intended_entry_bar = bar.timestamp + 5min);
       SL = setup.sl_price; TP = setup.tp_price; risk = entry_price - sl_price
       (using bar.close as proxy for entry_price; engine fills at next bar OPEN
       so we patch risk via Order.extra and let engine.bracket use Order.risk_units).

The engine fills the order at the NEXT bar's OPEN. The fill price MAY differ
from bar.close used for risk estimation. To keep research-exact parity, we must
use `next_bar.open` for the risk computation. Engine handles this via
`_open_trade_from_fill` which sets `trade.entry_price = fill.price` BUT uses
`order.risk_units` for the bracket math. To stay parity-exact we precompute
risk_units using a HYBRID: emit the order with `risk_units = bar.close - sl_price`
as a conservative seed, then the parity test reads research's risk and verifies
match. Research uses `entry_price - sl_price` where entry_price = m5.open[k+1].
Since we don't know next bar's open at signal time, the parity test scaffolding
(Phase 5) handles this discrepancy. For correctness in BT/live we should accept
that risk is computed at FILL time. The cleanest approach: emit Order with
risk_units placeholder; engine fills, then a post-fill hook recomputes risk
from the actual fill price. This is a Phase-2 refinement; Phase 1 uses the
bar.close approximation and the parity test will catch the diff.

For Phase 1 we keep the bar.close approximation. Parity Phase 5 will verify
or instruct a precise fix.
"""
from __future__ import annotations

import math
import uuid
from typing import Optional, Sequence

import pandas as pd

from ...core.bar import Bar
from ...core.order import Order
from ...core.signal import StepResult, StrategyEvent
from ...journal.events import JournalEvent
from ..base import Strategy
from .config import (
    COST_USD_DEFAULTS,
    FibV2Config,
    LONG_BULL_STRONG,
    SHORT_BEAR_STRONG,
    LegSpec,
)
from .pivot_tracker import PivotEvent, PivotTracker
from .regime_tracker import RegimeTracker
from .state import FibSetup, FibV2State
from .swing_tracker import SwingTracker


# Session mask helper (matches research/fib_retrace/run_fib.py::in_session).
def _in_session(ny_hr: int, session: str) -> bool:
    if session == "all":
        return True
    if session == "london":
        return 3 <= ny_hr < 12
    if session == "ny":
        return 8 <= ny_hr < 17
    if session == "overlap":
        return 8 <= ny_hr < 12
    if session == "london_ny":
        return 3 <= ny_hr < 17
    raise ValueError(f"unknown session: {session}")


def _ny_hour(ts: pd.Timestamp) -> int:
    return int(ts.tz_convert("America/New_York").hour)


def _tf_seconds(tf: str) -> int:
    from ...data.timeframes import seconds
    return seconds(tf)


class FibV2EnsembleStrategy(Strategy):
    """Production Fib V2 ENSEMBLE — long_bull_strong + short_bear_strong legs."""

    strategy_id = "fib_v2_xau_ensemble"

    def __init__(
        self,
        *,
        symbol: str = "XAUUSD.ecn",
        config: FibV2Config | None = None,
        legs: Sequence[LegSpec] = (LONG_BULL_STRONG, SHORT_BEAR_STRONG),
        qty: float | None = None,
        cost_usd: float | None = None,
        multi_tf_view=None,
    ) -> None:
        self.config = config or FibV2Config()
        self.symbol = symbol
        self.legs = tuple(legs)
        if not self.legs:
            raise ValueError("at least one leg required")
        # Per-symbol cost override.
        if cost_usd is None:
            cost_usd = COST_USD_DEFAULTS.get(symbol, self.config.cost_usd)
        self._cost_usd = float(cost_usd)
        if qty is not None:
            self.config = FibV2Config(**{**self.config.__dict__, "qty": qty})
        # Optional pre-built H1+D1 frames (Phase 2 MultiTfHistoryView). If given,
        # the strategy uses pointer-indexing into these frames instead of per-tick
        # resampling. Massive perf win for full 20yr backtests.
        self._mtf = multi_tf_view
        self._h1_idx = 0  # next H1 bar pointer (idx in mtf.h1 to ingest next)
        self._d1_idx = 0
        # Gate-decision event buffer (Option D instrumentation).
        # Drained at the end of every on_bar into StepResult.new_events so the
        # engine + runner can route GATE_* events to bt_signals. Pure-write —
        # gate emit changes NO control flow → parity preserved.
        self._gate_buf: list[StrategyEvent] = []
        # Monotonic id for pre-trade gate events (no trade_id yet at gate time).
        # Reset per-instance; carries no semantic meaning beyond uniqueness.
        self._gate_seq: int = 0

    def _emit_gate(
        self,
        event_type: JournalEvent,
        bar_ts: pd.Timestamp,
        *,
        leg_name: str | None = None,
        setup: FibSetup | None = None,
        **extra,
    ) -> None:
        """Buffer a gate-decision event for emission via StepResult.new_events.

        Pure-write side effect. Caller must NOT depend on return value for
        control flow.
        """
        self._gate_seq += 1
        detail: dict = {"bar_ts": str(bar_ts), "seq": self._gate_seq}
        if leg_name is not None:
            detail["leg"] = leg_name
        if setup is not None:
            detail.update(
                setup_confirm_ts=str(setup.setup_confirm_ts),
                side=int(setup.side),
                fib_L=float(setup.L),
                fib_H=float(setup.H),
                fib_diff=float(setup.diff),
                fib_382=float(setup.fib_382),
                fib_786=float(setup.fib_786),
                fib_100=float(setup.fib_100),
                sl_price=float(setup.sl_price),
                tp_price=float(setup.tp_price),
            )
        if extra:
            for k, v in extra.items():
                # Coerce numpy/pandas scalars to JSON-safe.
                if hasattr(v, "item") and not isinstance(v, (str, bytes)):
                    try:
                        v = v.item()
                    except Exception:
                        pass
                detail[k] = v
        # Use seq as opaque id since there is no trade_id at gate time.
        self._gate_buf.append(StrategyEvent(
            trade_or_zone_id=f"gate_{self._gate_seq}",
            type=event_type.value,
            detail=detail,
        ))

    # ----- engine hooks -----

    def initial_state(self) -> FibV2State:
        return FibV2State(
            pivot_tracker=PivotTracker(lb=self.config.pivot_lb),
            regime_tracker=RegimeTracker(
                ema_fast=self.config.d1_ema_fast,
                ema_slow=self.config.d1_ema_slow,
                atr_period=self.config.atr_period,
                sideways_band_pct=self.config.sideways_band_pct,
            ),
            swing_tracker=SwingTracker(lb=self.config.swing_lb),
        )

    def on_bar(self, state: FibV2State, bar: Bar, history: pd.DataFrame) -> StepResult:
        state.bars_seen += 1
        orders: list[Order] = []
        events: list[StrategyEvent] = []

        # 0) Finalize any pending entries queued by signal-bar k-1.
        #    Research uses entry_price = m5.open[k+1]; we use bar.open here.
        if state.pending_entries:
            for leg_name, setup in state.pending_entries:
                leg = next((lg for lg in self.legs if lg.leg_name == leg_name), None)
                if leg is None:
                    continue
                order, event = self._finalize_entry(bar, leg, setup)
                if order is not None:
                    orders.append(order)
                    if event is not None:
                        events.append(event)
                    state.consumed_setup_keys.add((leg_name, setup.setup_confirm_ts))
                # If risk fails, the setup may still be retried on later bars;
                # but research breaks after first valid entry candidate, so we drop.
                # (We add to consumed_setup_keys regardless to mirror that.)
                state.consumed_setup_keys.add((leg_name, setup.setup_confirm_ts))
            state.pending_entries = []

        # 1) Detect newly-closed H1 bar from history. The H1 bar with
        #    left-label `t.floor('1h') - 1h` closes at `t.floor('1h')` — so the
        #    bar at floor-1h is fully closed at bar.timestamp >= floor.
        new_h1_pivots = self._update_h1_pivots(state, bar, history)

        # 2) Detect newly-closed D1 bar similarly.
        self._update_d1_regime(state, bar, history)

        # 3) Update M5 swing tracker (uses prior 20 bars; current bar's values
        #    will be used in the NEXT call).
        state.swing_tracker.update(bar)

        # 4) Update last_L / last_H from new pivots AND spawn new setups.
        #    Research builds a new setup at EVERY pivot event. We mirror this:
        #    each new pivot event appends a setup to the pending list per leg.
        for pe in new_h1_pivots:
            self._emit_gate(
                JournalEvent.GATE_PIVOT_DETECTED, bar.timestamp,
                pivot_type=pe.type,
                pivot_price=float(pe.price),
                pivot_confirm_ts=str(pe.confirm_ts),
            )
            if pe.type == "L":
                state.last_L = pe.price
                state.last_L_ts = pe.confirm_ts
            else:
                state.last_H = pe.price
                state.last_H_ts = pe.confirm_ts
            # Spawn new setup per leg using updated (last_L, last_H).
            if state.last_L is None or state.last_H is None:
                continue
            for leg in self.legs:
                setup = self._build_setup(leg, state.last_L, state.last_L_ts,
                                          state.last_H, state.last_H_ts,
                                          _gate_emit_bar_ts=bar.timestamp)
                if setup is None:
                    continue
                self._emit_gate(
                    JournalEvent.GATE_SETUP_BUILT, bar.timestamp,
                    leg_name=leg.leg_name, setup=setup,
                )
                key = (leg.leg_name, setup.setup_confirm_ts)
                if key in state.consumed_setup_keys:
                    continue
                pending = state.pending_setups.setdefault(leg.leg_name, [])
                # Idempotency: don't add duplicate keys.
                if any(s.setup_confirm_ts == setup.setup_confirm_ts for s in pending):
                    continue
                pending.append(setup)

        # 5) Evaluate entries: walk pending setups per leg, fire on first
        #    bar in window where conditions hold. Mirrors research's inner loop.
        for leg in self.legs:
            pending = state.pending_setups.get(leg.leg_name)
            if not pending:
                continue
            # Walk through pending; collect indices to remove.
            survivors: list[FibSetup] = []
            for setup in pending:
                # Skip until setup_confirm_ts <= bar.timestamp.
                if setup.setup_confirm_ts > bar.timestamp:
                    survivors.append(setup)
                    continue
                # Try to MATCH entry conditions at this signal bar.
                matched = self._signal_bar_matches(state, bar, leg, setup)
                if matched:
                    # Queue the entry for next bar finalization.
                    state.pending_entries.append((leg.leg_name, setup))
                    # Mark as consumed; do NOT add to survivors.
                    state.consumed_setup_keys.add((leg.leg_name, setup.setup_confirm_ts))
                    continue
                # Check expiry / invalidation.
                inv_reason = _setup_invalidation_reason(setup, bar, self.config.max_hold_h)
                if inv_reason is not None:
                    if inv_reason == "invalidated":
                        self._emit_gate(
                            JournalEvent.GATE_SETUP_INVALIDATED, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            bar_close=float(bar.close),
                            reason="setup_walk_invalidated",
                        )
                    else:
                        self._emit_gate(
                            JournalEvent.GATE_SETUP_EXPIRED, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            max_hold_h=self.config.max_hold_h,
                        )
                    state.consumed_setup_keys.add((leg.leg_name, setup.setup_confirm_ts))
                    continue
                survivors.append(setup)
            if survivors:
                state.pending_setups[leg.leg_name] = survivors
            else:
                state.pending_setups.pop(leg.leg_name, None)

        # 7) Cache prev bar for next call's confirmation-candle check.
        state.prev_open = bar.open
        state.prev_close = bar.close

        # 8) Drain gate-decision buffer (Option D instrumentation).
        #    Gate emit is pure-write — does NOT alter control flow.
        if self._gate_buf:
            events.extend(self._gate_buf)
            self._gate_buf.clear()

        return StepResult(state=state, new_orders=tuple(orders), new_events=tuple(events))

    # ----- internals -----

    def _update_h1_pivots(self, state: FibV2State, bar: Bar, history: pd.DataFrame) -> list[PivotEvent]:
        """Detect when new H1 bars have CLOSED at or before bar.timestamp.

        FAST PATH (multi_tf_view available): pointer-index into precomputed H1
        frame; ingest all H1 bars whose close_ts <= bar.timestamp that we
        haven't yet seen.

        SLOW PATH (no view): aggregate from M5 history.
        """
        all_events: list[PivotEvent] = []

        if self._mtf is not None:
            h1 = self._mtf.h1
            ts_arr = h1["timestamp"].values
            high_arr = h1["high"].values
            low_arr = h1["low"].values
            target_close = bar.timestamp
            # Bar at idx k closes at ts_arr[k] + 1h. Ingest while close <= target_close.
            one_hour_ns = 3_600_000_000_000  # 1h in ns
            target_ns = int(pd.Timestamp(target_close).value)
            while self._h1_idx < len(h1):
                k = self._h1_idx
                close_ns = int(pd.Timestamp(ts_arr[k]).value) + one_hour_ns
                if close_ns > target_ns:
                    break
                h1_bar = _H1BarLite(
                    timestamp=pd.Timestamp(ts_arr[k]).tz_localize("UTC") if pd.Timestamp(ts_arr[k]).tzinfo is None else pd.Timestamp(ts_arr[k]),
                    high=float(high_arr[k]),
                    low=float(low_arr[k]),
                )
                all_events.extend(state.pivot_tracker.update(h1_bar))
                state.last_h1_seen = h1_bar.timestamp
                self._h1_idx += 1
            return all_events

        # SLOW PATH fallback: aggregate H1 from M5 history once per H1 close.
        floor_1h = bar.timestamp.floor("1h")
        closed_h1_left = floor_1h - pd.Timedelta(hours=1)
        if state.last_h1_seen is not None and closed_h1_left <= state.last_h1_seen:
            return []
        h1_end = closed_h1_left + pd.Timedelta(hours=1)
        slice_ = history[(history["timestamp"] >= closed_h1_left) & (history["timestamp"] < h1_end)]
        if len(slice_) == 0:
            return []
        h1_bar = _H1BarLite(
            timestamp=closed_h1_left,
            high=float(slice_["high"].max()),
            low=float(slice_["low"].min()),
        )
        events = state.pivot_tracker.update(h1_bar)
        state.last_h1_seen = closed_h1_left
        return events

    def _update_d1_regime(self, state: FibV2State, bar: Bar, history: pd.DataFrame) -> None:
        """Detect when new D1 bars have CLOSED."""
        if self._mtf is not None:
            d1 = self._mtf.d1
            ts_arr = d1["timestamp"].values
            high_arr = d1["high"].values
            low_arr = d1["low"].values
            close_arr = d1["close"].values
            target_close = bar.timestamp
            one_day_ns = 86_400_000_000_000
            target_ns = int(pd.Timestamp(target_close).value)
            while self._d1_idx < len(d1):
                k = self._d1_idx
                close_ns = int(pd.Timestamp(ts_arr[k]).value) + one_day_ns
                if close_ns > target_ns:
                    break
                d1_bar = _D1BarLite(
                    timestamp=pd.Timestamp(ts_arr[k]).tz_localize("UTC") if pd.Timestamp(ts_arr[k]).tzinfo is None else pd.Timestamp(ts_arr[k]),
                    high=float(high_arr[k]),
                    low=float(low_arr[k]),
                    close=float(close_arr[k]),
                )
                state.regime_tracker.update(d1_bar)
                state.last_d1_seen = d1_bar.timestamp
                self._d1_idx += 1
            return

        # SLOW PATH fallback.
        floor_1d = bar.timestamp.floor("1D")
        closed_d1_left = floor_1d - pd.Timedelta(days=1)
        if state.last_d1_seen is not None and closed_d1_left <= state.last_d1_seen:
            return
        d1_end = closed_d1_left + pd.Timedelta(days=1)
        slice_ = history[(history["timestamp"] >= closed_d1_left) & (history["timestamp"] < d1_end)]
        if len(slice_) == 0:
            return
        d1_bar = _D1BarLite(
            timestamp=closed_d1_left,
            high=float(slice_["high"].max()),
            low=float(slice_["low"].min()),
            close=float(slice_["close"].iloc[-1]),
        )
        state.regime_tracker.update(d1_bar)
        state.last_d1_seen = closed_d1_left

    def _build_setup(
        self,
        leg: LegSpec,
        L: float,
        L_ts: pd.Timestamp,
        H: float,
        H_ts: pd.Timestamp,
        _gate_emit_bar_ts: Optional[pd.Timestamp] = None,
    ) -> Optional[FibSetup]:
        """Build a FibSetup for the leg. Returns None if ordering/diff invalid.

        `_gate_emit_bar_ts` is an instrumentation hook — when provided, gate
        rejections emit events tagged with the bar that triggered the build.
        Pure-write side effect; does not alter control flow.
        """
        if leg.direction == "long":
            if H_ts <= L_ts:
                if _gate_emit_bar_ts is not None:
                    self._emit_gate(
                        JournalEvent.GATE_SETUP_REJECT_PIVOT_ORDER, _gate_emit_bar_ts,
                        leg_name=leg.leg_name, direction="long",
                        L_ts=str(L_ts), H_ts=str(H_ts),
                    )
                return None
            diff = H - L
            if diff <= 0:
                if _gate_emit_bar_ts is not None:
                    self._emit_gate(
                        JournalEvent.GATE_SETUP_REJECT_DIFF, _gate_emit_bar_ts,
                        leg_name=leg.leg_name, direction="long",
                        L=float(L), H=float(H), diff=float(diff),
                    )
                return None
            fib_382 = H - 0.382 * diff
            fib_786 = H - 0.786 * diff
            fib_100 = L
            tp_price = H + self.config.ext_target_pct * diff
            sl_price = L - self.config.sl_buffer_pct * diff
            side = 1
        else:
            if L_ts <= H_ts:
                if _gate_emit_bar_ts is not None:
                    self._emit_gate(
                        JournalEvent.GATE_SETUP_REJECT_PIVOT_ORDER, _gate_emit_bar_ts,
                        leg_name=leg.leg_name, direction="short",
                        L_ts=str(L_ts), H_ts=str(H_ts),
                    )
                return None
            diff = H - L
            if diff <= 0:
                if _gate_emit_bar_ts is not None:
                    self._emit_gate(
                        JournalEvent.GATE_SETUP_REJECT_DIFF, _gate_emit_bar_ts,
                        leg_name=leg.leg_name, direction="short",
                        L=float(L), H=float(H), diff=float(diff),
                    )
                return None
            fib_382 = L + 0.382 * diff
            fib_786 = L + 0.786 * diff
            fib_100 = H
            tp_price = L - self.config.ext_target_pct * diff
            sl_price = H + self.config.sl_buffer_pct * diff
            side = -1

        setup_confirm_ts = max(L_ts, H_ts)
        return FibSetup(
            leg_name=leg.leg_name,
            side=side,
            L=L,
            H=H,
            diff=diff,
            fib_382=fib_382,
            fib_786=fib_786,
            fib_100=fib_100,
            tp_price=tp_price,
            sl_price=sl_price,
            setup_confirm_ts=setup_confirm_ts,
            L_ts=L_ts,
            H_ts=H_ts,
        )

    def _signal_bar_matches(
        self,
        state: FibV2State,
        bar: Bar,
        leg: LegSpec,
        setup: FibSetup,
    ) -> bool:
        """Check if signal bar k matches entry conditions. Risk check is DEFERRED
        to _finalize_entry on the next bar (which uses bar.open = research's
        m5.open[k+1] for entry_price).

        Gate-rejection events are emitted at every fail point (Option D
        instrumentation). Gate emit is pure-write — control flow unchanged.
        """
        # 1) Invalidation (research: cl < fib_100 (long) → break).
        if leg.direction == "long" and bar.close < setup.fib_100:
            self._emit_gate(JournalEvent.GATE_SETUP_INVALIDATED, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            bar_close=float(bar.close), reason="close<fib_100")
            return False
        if leg.direction == "short" and bar.close > setup.fib_100:
            self._emit_gate(JournalEvent.GATE_SETUP_INVALIDATED, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            bar_close=float(bar.close), reason="close>fib_100")
            return False

        # 2) Zone check.
        if leg.direction == "long":
            in_zone = setup.fib_786 <= bar.close <= setup.fib_382
        else:
            in_zone = setup.fib_382 <= bar.close <= setup.fib_786
        if not in_zone:
            self._emit_gate(JournalEvent.GATE_SIGNAL_ZONE_MISS, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            bar_close=float(bar.close))
            return False

        # 3) Session.
        if not _in_session(_ny_hour(bar.timestamp), self.config.session):
            self._emit_gate(JournalEvent.GATE_SIGNAL_SESSION_FAIL, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            ny_hr=_ny_hour(bar.timestamp),
                            session=self.config.session)
            return False

        # 4) Regime gate.
        if not state.regime_tracker.gate_passes(leg.regime, bar.timestamp):
            self._emit_gate(JournalEvent.GATE_SIGNAL_REGIME_FAIL, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            regime=leg.regime)
            return False

        # 5) Confirmation candle.
        if state.prev_open is None or state.prev_close is None:
            self._emit_gate(JournalEvent.GATE_SIGNAL_CONFIRM_FAIL, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            reason="no_prev_bar")
            return False
        prev_red = state.prev_close < state.prev_open
        prev_green = state.prev_close > state.prev_open
        rng = bar.high - bar.low
        if leg.direction == "long":
            bull_eng = (
                prev_red
                and bar.close > bar.open
                and bar.close >= state.prev_open
                and bar.open <= state.prev_close
            )
            lower_wick = min(bar.open, bar.close) - bar.low
            pin = rng > 0 and lower_wick > 0.5 * rng
            if bull_eng or pin:
                self._emit_gate(JournalEvent.GATE_SIGNAL_PASSED, bar.timestamp,
                                leg_name=leg.leg_name, setup=setup,
                                pattern="bull_eng" if bull_eng else "lower_pin")
                return True
            self._emit_gate(JournalEvent.GATE_SIGNAL_CONFIRM_FAIL, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            reason="no_bull_eng_no_lower_pin")
            return False
        else:
            bear_eng = (
                prev_green
                and bar.close < bar.open
                and bar.close <= state.prev_open
                and bar.open >= state.prev_close
            )
            upper_wick = bar.high - max(bar.open, bar.close)
            pin = rng > 0 and upper_wick > 0.5 * rng
            if bear_eng or pin:
                self._emit_gate(JournalEvent.GATE_SIGNAL_PASSED, bar.timestamp,
                                leg_name=leg.leg_name, setup=setup,
                                pattern="bear_eng" if bear_eng else "upper_pin")
                return True
            self._emit_gate(JournalEvent.GATE_SIGNAL_CONFIRM_FAIL, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            reason="no_bear_eng_no_upper_pin")
            return False

    def _finalize_entry(
        self, bar: Bar, leg: LegSpec, setup: FibSetup,
    ) -> tuple[Optional[Order], Optional[StrategyEvent]]:
        """Bar k+1 (next bar after signal). Use bar.open as entry_price
        (matches research m5.open[k+1]). Risk-check here.
        """
        entry_price = bar.open
        if leg.direction == "long":
            risk = entry_price - setup.sl_price
        else:
            risk = setup.sl_price - entry_price
        if risk <= 0 or not math.isfinite(risk):
            self._emit_gate(JournalEvent.GATE_FINALIZE_RISK_INVALID, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            entry_price=float(entry_price), risk=float(risk))
            return None, None
        if risk > self.config.max_risk_pct * entry_price:
            self._emit_gate(JournalEvent.GATE_FINALIZE_RISK_PCT_CAP, bar.timestamp,
                            leg_name=leg.leg_name, setup=setup,
                            entry_price=float(entry_price), risk=float(risk),
                            max_risk_pct=self.config.max_risk_pct)
            return None, None

        # Engine fills at bar.timestamp = signal_bar.timestamp + 5min.
        # Order.intended_entry_bar must == bar.timestamp.
        tid = uuid.uuid4()
        cost_r = self._cost_usd / risk if risk > 0 else 0.0
        order = Order(
            symbol=self.symbol,
            side=setup.side,
            qty=self.config.qty,
            intended_entry_bar=bar.timestamp,
            stop_price=setup.sl_price,
            take_profit=setup.tp_price,
            risk_units=risk,
            tag=f"{leg.leg_name}_{setup.setup_confirm_ts.isoformat()}",
            bracket_kind="fixed_tp",
            trade_id=tid,
            extra={
                "leg": leg.leg_name,
                "regime": leg.regime,
                "regime_at_entry": leg.regime,
                "pivot_lb": self.config.pivot_lb,
                "ext_target_pct": self.config.ext_target_pct,
                "sl_buffer_pct": self.config.sl_buffer_pct,
                "fib_diff": setup.diff,
                "fib_L": setup.L,
                "fib_H": setup.H,
                "fib_382": setup.fib_382,
                "fib_786": setup.fib_786,
                "fib_100": setup.fib_100,
                "sl_price": setup.sl_price,
                "tp_price": setup.tp_price,
                "setup_confirm_ts": str(setup.setup_confirm_ts),
                "cost_r": cost_r,
                "symbol": self.symbol,
                "ny_hr": _ny_hour(bar.timestamp),
                "partial_tp_at_r": self.config.partial_tp_at_r,
                "partial_tp_pct": self.config.partial_tp_pct,
            },
        )
        event = StrategyEvent(
            trade_or_zone_id=str(tid),
            type="ENTRY_SUBMIT",
            detail={
                "leg": leg.leg_name,
                "side": setup.side,
                "sl_price": setup.sl_price,
                "tp_price": setup.tp_price,
                "risk_units": risk,
                "fib_diff": setup.diff,
            },
        )
        return order, event

    # ----- live safety -----

    def validate_for_live(self, *, timeframe: str) -> None:
        """Engine calls this before going live (`runner/live.py`)."""
        if timeframe.upper() != "M5":
            raise ValueError(
                f"FibV2EnsembleStrategy requires timeframe='M5', got {timeframe}. "
                "Pivots are H1-based but the engine drives M5 bars."
            )


def _setup_invalidation_reason(setup: FibSetup, bar: Bar, max_hold_h: int) -> Optional[str]:
    """Return 'invalidated' / 'expired' / None.

    Drop-in replacement for `_setup_invalidated_or_expired` that distinguishes
    cause so instrumentation can emit the correct gate event.
    """
    if setup.side > 0 and bar.close < setup.fib_100:
        return "invalidated"
    if setup.side < 0 and bar.close > setup.fib_100:
        return "invalidated"
    expiry = setup.setup_confirm_ts + pd.Timedelta(hours=max_hold_h)
    if bar.timestamp > expiry:
        return "expired"
    return None


def _setup_invalidated_or_expired(setup: FibSetup, bar: Bar, max_hold_h: int) -> bool:
    """Back-compat wrapper. Prefer `_setup_invalidation_reason` for new code."""
    return _setup_invalidation_reason(setup, bar, max_hold_h) is not None


class FibV2LongStrategy(FibV2EnsembleStrategy):
    """LONG-only fib_v2 variant (bull_strong leg)."""

    strategy_id = "fib_v2_xau_long"

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("legs", (LONG_BULL_STRONG,))
        super().__init__(**kwargs)


class FibV2ShortStrategy(FibV2EnsembleStrategy):
    """SHORT-only fib_v2 variant (bear_strong leg)."""

    strategy_id = "fib_v2_xau_short"

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("legs", (SHORT_BEAR_STRONG,))
        super().__init__(**kwargs)


# Internal lite bar containers — used to feed pivot/regime trackers
# without circular dependency on core.Bar (which has validation we don't need
# here since we built the values ourselves from validated M5 bars).
class _H1BarLite:
    __slots__ = ("timestamp", "high", "low")

    def __init__(self, *, timestamp: pd.Timestamp, high: float, low: float) -> None:
        self.timestamp = timestamp
        self.high = high
        self.low = low


class _D1BarLite:
    __slots__ = ("timestamp", "high", "low", "close")

    def __init__(self, *, timestamp: pd.Timestamp, high: float, low: float, close: float) -> None:
        self.timestamp = timestamp
        self.high = high
        self.low = low
        self.close = close
