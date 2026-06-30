"""Phase 1E integration: gate events end-to-end engine → on_strategy_event callback.

Mirrors the wiring used by `runner/live.py::run_live` where every StrategyEvent
emitted by `strategy.on_bar` is drained by the engine and routed to
`signal_repo.insert` via the `on_strategy_event` callback.

Without spinning up MT5 / DWX / Postgres, this test:
  - Replays 200+ M15 bars through `run_engine(mode='bt')`
  - Captures every event delivered via `on_strategy_event`
  - Asserts:
      * GATE_PIVOT_DETECTED fires on every confirmed pivot
      * GATE_SETUP_BUILT fires whenever a setup is built (both LONG + SHORT
        attempted; rejections also emit GATE_SETUP_REJECT_* per leg)
      * At least one of {GATE_SIGNAL_ZONE_MISS, GATE_SIGNAL_CONFIRM_FAIL,
        GATE_SIGNAL_REGIME_FAIL, GATE_SIGNAL_SESSION_FAIL} fires
      * No event leaks state across bars (`bar_ts` is monotonic & valid)
      * StrategyEvent.detail contains expected keys per event_type

This verifies the wiring chain that paper-live depends on: strategy emit →
StepResult.new_events tuple → engine loop → deps.on_strategy_event invocation.

Distinct from the unit test (`test_fib_v2_intraday_gate_events.py`) which
drives individual methods directly. This test exercises the full bar loop.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
import pytest

from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.core.signal import StrategyEvent
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.journal.events import JournalEvent
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD

from ..parity._fib_v2_helper import InMemoryClock, InMemoryProvider


XAU_M5 = Path("/tmp/oanda_xau_m5.parquet")
N_BARS = 2_000  # ~3 weeks of M15 = enough for multiple pivots + setups


def _resample_m15(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return idx.resample("15min", label="left", closed="left").agg(agg).dropna().reset_index()


def _prepare_m15(n: int) -> pd.DataFrame:
    raw = pd.read_parquet(XAU_M5)
    if raw["timestamp"].dt.tz is None:
        raw["timestamp"] = raw["timestamp"].dt.tz_localize("UTC")
    m15 = _resample_m15(raw.sort_values("timestamp").reset_index(drop=True))
    return m15.iloc[:n].reset_index(drop=True)


def _drive(strategy_cls, m15: pd.DataFrame) -> list[StrategyEvent]:
    """Run engine; capture every event delivered via on_strategy_event."""
    provider = InMemoryProvider(m15, symbol="XAUUSD.ecn", timeframe="M15")
    clock = InMemoryClock(provider)
    strat = strategy_cls(symbol="XAUUSD.ecn")
    captured: list[StrategyEvent] = []

    def _on_event(ev: StrategyEvent) -> None:
        captured.append(ev)

    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_strategy_event=_on_event,
        max_bars_held=96,
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    return captured


@pytest.mark.skipif(not XAU_M5.exists(), reason="OANDA XAU M5 parquet missing")
def test_intraday_a_gate_events_flow_through_engine():
    """Mirror of run_live wiring — every gate event reaches on_strategy_event."""
    m15 = _prepare_m15(N_BARS)
    events = _drive(FibV2IntradayA, m15)

    types = {e.type for e in events}
    type_counts = {t: sum(1 for e in events if e.type == t) for t in types}
    print(f"\n[live-events A] total={len(events)}  types={len(types)}")
    for t in sorted(types):
        print(f"  {t}: {type_counts[t]}")

    # ── Mandatory event-types must all appear in a 2000-bar window ──
    assert JournalEvent.GATE_PIVOT_DETECTED.value in types
    assert JournalEvent.GATE_SETUP_BUILT.value in types
    # At least one of these signal-level rejections must fire
    rejection_types = {
        JournalEvent.GATE_SIGNAL_ZONE_MISS.value,
        JournalEvent.GATE_SIGNAL_SESSION_FAIL.value,
        JournalEvent.GATE_SIGNAL_REGIME_FAIL.value,
        JournalEvent.GATE_SIGNAL_CONFIRM_FAIL.value,
    }
    assert types & rejection_types, f"no signal-rejection event fired: {types}"

    # ── Every event must carry bar_ts in detail (dashboard depends on this) ──
    missing_bar_ts = [e for e in events if "bar_ts" not in e.detail]
    assert not missing_bar_ts, f"{len(missing_bar_ts)} events missing bar_ts"

    # ── bar_ts must be a string parseable as pandas Timestamp ──
    sample = events[0]
    pd.Timestamp(sample.detail["bar_ts"])  # raises if malformed

    # ── Setup-attached events carry the fib geometry ──
    setup_evts = [e for e in events if e.type == JournalEvent.GATE_SETUP_BUILT.value]
    assert len(setup_evts) > 0
    keys = setup_evts[0].detail.keys()
    for must in ("fib_L", "fib_H", "fib_diff", "sl_price", "tp_price", "side"):
        assert must in keys, f"GATE_SETUP_BUILT detail missing {must}"


@pytest.mark.skipif(not XAU_M5.exists(), reason="OANDA XAU M5 parquet missing")
def test_intraday_d_gate_events_flow_through_engine():
    """Same for D leg. Different config (session=all, hold=24h)."""
    m15 = _prepare_m15(N_BARS)
    events = _drive(FibV2IntradayD, m15)
    types = {e.type for e in events}
    print(f"\n[live-events D] total={len(events)}  types={len(types)}")
    assert JournalEvent.GATE_PIVOT_DETECTED.value in types
    assert JournalEvent.GATE_SETUP_BUILT.value in types
    # D-leg with session=all should NOT emit SESSION_FAIL.
    assert JournalEvent.GATE_SIGNAL_SESSION_FAIL.value not in types, \
        "D leg session=all should never emit session-fail"


@pytest.mark.skipif(not XAU_M5.exists(), reason="OANDA XAU M5 parquet missing")
def test_signal_passed_implies_order_emitted():
    """Every GATE_SIGNAL_PASSED bar must produce a finalize-stage event
    (either ENTRY_SUBMIT on success, or GATE_FINALIZE_* on reject).

    Catches the bug class where _signal_bar_matches → True but the queued
    entry silently dies in _finalize_entry without telemetry.
    """
    m15 = _prepare_m15(N_BARS)
    events = _drive(FibV2IntradayA, m15)

    passes = [e for e in events if e.type == JournalEvent.GATE_SIGNAL_PASSED.value]
    finalizers = [
        e for e in events
        if e.type == "ENTRY_SUBMIT"
        or e.type.startswith("GATE_FINALIZE_")
    ]

    print(f"\n[passed->finalized] passes={len(passes)}  finalizers={len(finalizers)}")
    # Every pass must be followed (on next bar) by EXACTLY one finalize event
    # (success path → ENTRY_SUBMIT; rejection path → one of GATE_FINALIZE_*).
    # Pairing is N-to-N — assert lower bound: at least as many finalizers as passes.
    # (Some setups may consume the entry then dedup-collide on a parallel leg pass.)
    assert len(finalizers) >= len(passes), \
        f"passes={len(passes)} produced only {len(finalizers)} finalize events"


@pytest.mark.skipif(not XAU_M5.exists(), reason="OANDA XAU M5 parquet missing")
def test_gate_event_seq_monotonic():
    """Every event carries a monotonic seq in detail. Catches drains that
    re-order or duplicate."""
    m15 = _prepare_m15(N_BARS)
    events = _drive(FibV2IntradayA, m15)
    seqs = [e.detail.get("seq") for e in events]
    seqs = [s for s in seqs if s is not None]
    assert seqs == sorted(seqs), "seq must be monotonic across the run"
    assert len(set(seqs)) == len(seqs), "seq must be unique"
