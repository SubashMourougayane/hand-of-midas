"""Phase 5: Integration smoke for FibV2Intraday A + D.

Runs first 20k M15 bars of XAU through run_engine(mode='bt'). Verifies:
  - No exceptions
  - bars_processed matches input
  - All closed trades have risk_units >= 0.50 (min_risk gate working)
  - All trades have extra['leg'] matching expected leg name
  - No two trades from same strategy share (entry_ts, side) — dedup proven
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
import pytest

from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD

from ..parity._fib_v2_helper import InMemoryClock, InMemoryProvider


XAU_M5 = Path("/tmp/oanda_xau_m5.parquet")
N_BARS = 20_000


def _resample_m15(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return idx.resample("15min", label="left", closed="left").agg(agg).dropna().reset_index()


@pytest.mark.skipif(not XAU_M5.exists(), reason="OANDA XAU M5 parquet missing")
def test_intraday_a_smoke_run():
    raw = pd.read_parquet(XAU_M5)
    if raw["timestamp"].dt.tz is None:
        raw["timestamp"] = raw["timestamp"].dt.tz_localize("UTC")
    m15 = _resample_m15(raw.sort_values("timestamp").reset_index(drop=True))
    m15 = m15.iloc[:N_BARS].reset_index(drop=True)

    provider = InMemoryProvider(m15, symbol="XAUUSD.ecn", timeframe="M15")
    clock = InMemoryClock(provider)
    strat = FibV2IntradayA(symbol="XAUUSD.ecn")

    trades_closed = []
    def _on_close(tr, outcome):
        trades_closed.append((tr, outcome))

    # A leg: 12h hold cap → max_bars_held = 12 * 4 = 48 M15 bars. Doubled: 96.
    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_trade_close=_on_close,
        max_bars_held=96,
    )
    run = run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    print(f"\n[smoke A] bars_processed={run.bars_processed} closed_trades={len(trades_closed)}")

    assert run.bars_processed == N_BARS, f"expected {N_BARS} bars, got {run.bars_processed}"
    assert len(trades_closed) > 0, "no trades closed - signal generation broken"

    # Verify min_risk floor + leg metadata on every trade
    seen_keys = set()
    for tr, outcome in trades_closed:
        assert tr.risk_units >= 0.50, f"min_risk violated: {tr.risk_units} < 0.50"
        assert tr.order.extra["leg"] == "intraday_a_long"
        assert tr.order.extra["pivot_lb"] == 3
        # Dedup proof: no two trades share (entry_ts, side) within this strategy
        key = (tr.entry_timestamp, int(tr.side))
        assert key not in seen_keys, f"dedup violated: {key} appears twice"
        seen_keys.add(key)


@pytest.mark.skipif(not XAU_M5.exists(), reason="OANDA XAU M5 parquet missing")
def test_intraday_d_smoke_run():
    raw = pd.read_parquet(XAU_M5)
    if raw["timestamp"].dt.tz is None:
        raw["timestamp"] = raw["timestamp"].dt.tz_localize("UTC")
    m15 = _resample_m15(raw.sort_values("timestamp").reset_index(drop=True))
    m15 = m15.iloc[:N_BARS].reset_index(drop=True)

    provider = InMemoryProvider(m15, symbol="XAUUSD.ecn", timeframe="M15")
    clock = InMemoryClock(provider)
    strat = FibV2IntradayD(symbol="XAUUSD.ecn")

    trades_closed = []
    def _on_close(tr, outcome):
        trades_closed.append((tr, outcome))

    # D leg: 24h hold → max_bars_held = 24 * 4 = 96. Doubled: 192.
    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_trade_close=_on_close,
        max_bars_held=192,
    )
    run = run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")
    print(f"\n[smoke D] bars_processed={run.bars_processed} closed_trades={len(trades_closed)}")

    assert run.bars_processed == N_BARS
    assert len(trades_closed) > 0

    seen_keys = set()
    for tr, outcome in trades_closed:
        assert tr.risk_units >= 0.50, f"min_risk violated: {tr.risk_units}"
        assert tr.order.extra["leg"] == "intraday_d_short"
        assert tr.side == -1
        key = (tr.entry_timestamp, int(tr.side))
        assert key not in seen_keys, f"dedup violated: {key}"
        seen_keys.add(key)
