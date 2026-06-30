"""[DEPRECATED 2026-06-30] SDR001Strategy — replaced by fib_v2_xau_ensemble.

Kept for parity replay against the baseline sleeve1 ledger. Not the default
strategy anymore; production uses `fib_v2_xau_ensemble`. See plan at
/Users/subash/.claude/plans/ok-now-that-we-piped-fog.md and tracker at
bt_engine/docs/FIB_V2_TRACKER.md.

Original docstring:
SDR001Strategy — engine-compatible wrapper over the ported generator.

Streams M1 bars into a rolling history buffer; on each tick, calls the
vectorized `generate_events_from_raw` on the buffer, finds NEW events, and
emits Orders.

The historical sleeve1 zone-id whitelist is replay-only. It is deliberately
off by default for the raw strategy because future live zones cannot be matched
to a historical zone-id ledger.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ...core.bar import Bar
from ...core.order import Order
from ...core.signal import StepResult, StrategyEvent
from ...core.state import StrategyState
from ..base import Strategy
from .generator import SDR002_CLEAN_RULE, XAU_COST_USD, generate_events_from_raw


REPO_ROOT = Path(__file__).resolve().parents[4]
SLEEVE1_LEDGER = REPO_ROOT / "research-baseline" / "results" / "base" / "base_sleeve1_trades.csv"
LIVE_BLOCKED_FORWARD_FLAGS = {"orb_continuation", "orb_reversal", "orb_inside"}


@dataclass
class SDR001State(StrategyState):
    emitted_zone_ids: set[int] = field(default_factory=set)
    emitted_trade_keys: set[str] = field(default_factory=set)
    # raw bar buffer accumulated from on_bar calls
    bar_rows: list[dict[str, Any]] = field(default_factory=list)
    # pre-computed events indexed by entry_timestamp (filled lazily on first on_bar call)
    pending_events: dict[pd.Timestamp, list[dict[str, Any]]] = field(default_factory=dict)
    initialized: bool = False


class SDR001Strategy(Strategy):
    """Real SDR-001: vectorized generator wrapped for bar-by-bar engine driving.

    Parameters
    ----------
    symbol : str
        Trading symbol (e.g. "XAUUSD.ecn").
    sleeve1_filter : bool, default False
        If True, only emit zones whose `zone_id` is in the baseline sleeve1
        ledger (1032 zones). This reproduces the canonical baseline.
        If False, emit every confirmed event (~13.7k zones; -1110R unfiltered).
    forward_rule : tuple[str, ...] | None
        Optional forward boolean feature gate (e.g. ("cost_le_0p05", "ema8_aligned")).
        Applied after sleeve1 filter. Set sleeve1_filter=False to combine with this.
    history_lookback_bars : int
        Maximum M1 bars to retain in the rolling buffer. None = unlimited (BT).
    """

    strategy_id = "sdr001"

    def __init__(
        self,
        *,
        symbol: str = "XAUUSD",
        sleeve1_filter: bool = False,
        sleeve1_ledger_path: str | Path | None = None,
        forward_rule: tuple[str, ...] | None = None,
        history_lookback_bars: int | None = None,
        ignore_events_before: str | pd.Timestamp | None = None,
        preloaded_raw: pd.DataFrame | None = None,
    ) -> None:
        self.symbol = symbol
        self.config = {
            "symbol": symbol,
            "sleeve1_filter": sleeve1_filter,
            "forward_rule": list(forward_rule) if forward_rule else None,
            "history_lookback_bars": history_lookback_bars,
            "ignore_events_before": str(ignore_events_before) if ignore_events_before is not None else None,
        }
        self.sleeve1_filter = sleeve1_filter
        self.forward_rule = forward_rule
        self.history_lookback_bars = history_lookback_bars
        self.ignore_events_before = self._utc_timestamp(ignore_events_before)
        self._sleeve1_zone_ids: set[int] = (
            self._load_sleeve1_zones(sleeve1_ledger_path) if sleeve1_filter else set()
        )
        # Preload mode: caller supplies the full raw bar frame upfront so the
        # generator runs once and pre-computes the event ledger. Used for BT
        # parity tests where the engine simply ticks pre-known bars.
        self._preloaded_raw = preloaded_raw

    @staticmethod
    def _load_sleeve1_zones(path: str | Path | None) -> set[int]:
        p = Path(path) if path else SLEEVE1_LEDGER
        if not p.is_file():
            return set()
        df = pd.read_csv(p, usecols=["zone_id"])
        return set(int(z) for z in df["zone_id"])

    @staticmethod
    def _utc_timestamp(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
        if value is None:
            return None
        ts = pd.Timestamp(value)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    def initial_state(self) -> SDR001State:
        return SDR001State()

    def validate_for_live(self, *, timeframe: str) -> None:
        if timeframe.upper() != "M1":
            raise ValueError("SDR-001 live mode requires timeframe='M1' because it builds M5/M15 features internally.")
        if self.sleeve1_filter:
            raise ValueError("sleeve1_filter=True is replay-only and cannot be used in live mode.")
        blocked = sorted(LIVE_BLOCKED_FORWARD_FLAGS.intersection(self.forward_rule or ()))
        if blocked:
            raise ValueError(f"ORB forward flags are blocked for live use until causality is repaired: {blocked}")

    def _initialize_from_history(self, state: SDR001State, history: pd.DataFrame) -> None:
        """Pre-compute the full event ledger from the data provider's history once."""
        if history.empty:
            return
        events = generate_events_from_raw(history)
        if events.empty:
            state.initialized = True
            return
        events = events.copy()
        events["entry_timestamp"] = pd.to_datetime(events["entry_timestamp"], utc=True)
        if self.sleeve1_filter and self._sleeve1_zone_ids:
            events = events[events["zone_id"].astype(int).isin(self._sleeve1_zone_ids)]
        events = self._apply_forward_rule(events)
        if self.ignore_events_before is not None:
            events = events[events["entry_timestamp"] > self.ignore_events_before]
        for _, row in events.iterrows():
            ts = pd.Timestamp(row["entry_timestamp"])
            state.pending_events.setdefault(ts, []).append(row.to_dict())
        state.initialized = True

    def _apply_forward_rule(self, events: pd.DataFrame) -> pd.DataFrame:
        if not self.forward_rule or events.empty:
            return events
        missing = [flag for flag in self.forward_rule if flag not in events.columns]
        if missing:
            raise ValueError(f"forward_rule references missing SDR-001 feature flags: {missing}")
        mask = pd.Series(True, index=events.index)
        for flag in self.forward_rule:
            mask &= events[flag].fillna(False).astype(bool)
        return events[mask]

    def _events_from_streaming_history(self, state: SDR001State, history: pd.DataFrame) -> list[dict[str, Any]]:
        if history.empty:
            return []
        source = history
        if self.history_lookback_bars is not None and len(source) > self.history_lookback_bars:
            source = source.tail(self.history_lookback_bars).reset_index(drop=True)
        events = generate_events_from_raw(source)
        if events.empty:
            return []
        events = events.copy()
        events["entry_timestamp"] = pd.to_datetime(events["entry_timestamp"], utc=True)
        events = self._apply_forward_rule(events)
        if self.ignore_events_before is not None:
            events = events[events["entry_timestamp"] > self.ignore_events_before]
        rows: list[dict[str, Any]] = []
        for _, row in events.iterrows():
            row_dict = row.to_dict()
            key = str(row_dict.get("trade_key") or self._trade_key(row_dict))
            if key in state.emitted_trade_keys:
                continue
            rows.append(row_dict)
        return rows

    @staticmethod
    def _trade_key(row: dict[str, Any]) -> str:
        return f"{pd.Timestamp(row['entry_timestamp']).isoformat()}|{row['direction']}|{float(row['entry_price'])}"

    def on_bar(
        self,
        state: SDR001State,
        bar: Bar,
        history: pd.DataFrame,
    ) -> StepResult:
        bar_ts = pd.Timestamp(bar.timestamp).tz_convert("UTC") if bar.timestamp.tzinfo else pd.Timestamp(bar.timestamp, tz="UTC")
        new_rows: list[dict[str, Any]] = []

        if self._preloaded_raw is not None:
            # BT parity mode: precompute once from the caller's full historical slice.
            if not state.initialized:
                self._initialize_from_history(state, self._preloaded_raw)
            next_bar_ts = bar_ts + pd.Timedelta(minutes=1)
            ready_keys = [ts for ts in state.pending_events if ts == next_bar_ts]
            for ts in ready_keys:
                for row in state.pending_events.pop(ts):
                    key = str(row.get("trade_key") or self._trade_key(row))
                    if key in state.emitted_trade_keys:
                        continue
                    new_rows.append(row)
        else:
            # Streaming mode: recompute over causal history each closed bar and
            # emit newly discovered events only once. The stable trade key avoids
            # relying on rolling-window zone_id values.
            state.initialized = True
            for row in self._events_from_streaming_history(state, history):
                entry_ts = pd.Timestamp(row["entry_timestamp"])
                if entry_ts <= bar_ts:
                    new_rows.append(row)
        if not new_rows:
            return StepResult(state=state)

        orders: list[Order] = []
        events_out: list[StrategyEvent] = []
        for row in new_rows:
            zid = int(row["zone_id"])
            key = str(row.get("trade_key") or self._trade_key(row))
            state.emitted_trade_keys.add(key)
            state.emitted_zone_ids.add(zid)
            side = 1 if row["direction"] == "demand" else -1
            entry_ts = pd.Timestamp(row["entry_timestamp"])
            entry_price = float(row["entry_price"])
            stop_price = float(row["stop_price"])
            risk = float(row["risk_units"])
            tp = entry_price + side * risk  # 1R bracket
            tid = uuid.uuid4()
            orders.append(
                Order(
                    symbol=self.symbol,
                    side=side,
                    qty=1.0,
                    intended_entry_bar=entry_ts,
                    stop_price=stop_price,
                    take_profit=tp,
                    risk_units=risk,
                    tag=f"sdr001_zone_{zid}",
                    bracket_kind="1R",
                    trade_id=tid,
                    extra={
                        "zone_id": zid,
                        "direction": row["direction"],
                        "spec_name": row.get("spec_name", "m15_2c_1atr"),
                        "cost_r": float(row.get("cost_r", XAU_COST_USD / risk)),
                    },
                )
            )
            events_out.append(
                StrategyEvent(
                    trade_or_zone_id=str(tid),
                    type="ENTRY_SUBMIT",
                    detail={
                        "zone_id": zid,
                        "direction": row["direction"],
                        "entry_timestamp": entry_ts.isoformat(),
                        "entry_price": entry_price,
                        "stop_price": stop_price,
                        "risk_units": risk,
                    },
                )
            )

        return StepResult(state=state, new_orders=tuple(orders), new_events=tuple(events_out))


class SDR002CleanStrategy(SDR001Strategy):
    """Strictly causal XAU-SDR-002 candidate.

    The forward rule deliberately avoids ORB state and same-bar M15 EMA. Its
    EMA filter uses the previous fully closed M15 candle only.
    """

    strategy_id = "sdr002_clean"

    def __init__(self, **kwargs: Any) -> None:
        provided = tuple(kwargs.pop("forward_rule", ()) or ())
        if provided and provided != SDR002_CLEAN_RULE:
            raise ValueError("sdr002_clean uses a fixed promoted forward rule; use sdr001 for custom research rules.")
        kwargs.setdefault("sleeve1_filter", False)
        super().__init__(forward_rule=SDR002_CLEAN_RULE, **kwargs)
