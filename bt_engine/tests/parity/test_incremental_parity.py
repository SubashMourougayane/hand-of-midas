"""Incremental SDR-001 strategy must produce identical events to the vectorized
generator on the same M1 slice. Engine driving = strategy.on_bar called per bar.

Uses a 1-week M1 slice (faster than full 7-year run) to verify the streaming
wrapper matches the master pipeline exactly.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
import pytest

from bt_engine.core.bar import Bar
from bt_engine.core.clock_bt import BacktestClock
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.sdr001.generator import generate_events_from_raw
from bt_engine.strategies.sdr001.strategy import SDR001Strategy


REPO_ROOT = Path(__file__).resolve().parents[3]
RAW = REPO_ROOT / "research-baseline" / "data" / "raw" / "XAUUSD.ecn_M1_201601040000_202606181903.csv"


pytestmark = pytest.mark.skipif(not RAW.is_file(), reason="baseline raw CSV missing")


def _load_raw_slice(start: str, end: str) -> pd.DataFrame:
    raw = pd.read_csv(RAW, sep="\t")
    raw["timestamp"] = pd.to_datetime(
        raw["<DATE>"].astype(str) + " " + raw["<TIME>"].astype(str),
        format="%Y.%m.%d %H:%M:%S",
        utc=True,
    )
    raw = raw.rename(
        columns={"<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
                 "<CLOSE>": "close", "<TICKVOL>": "volume"}
    )
    raw = raw[["timestamp", "open", "high", "low", "close", "volume"]]
    for c in ["open", "high", "low", "close", "volume"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw = raw.dropna()
    raw = raw[(raw["timestamp"] >= pd.Timestamp(start, tz="UTC")) & (raw["timestamp"] < pd.Timestamp(end, tz="UTC"))]
    return raw.sort_values("timestamp").reset_index(drop=True)


class _Provider:
    def __init__(self, raw: pd.DataFrame, symbol: str = "XAUUSD") -> None:
        self.symbol = symbol
        self.timeframe = "M1"
        self._frame = raw

    def history_up_to(self, t: pd.Timestamp) -> pd.DataFrame:
        return self._frame[self._frame["timestamp"] <= t].reset_index(drop=True)


def test_incremental_emits_same_zones_as_vectorized_on_slice() -> None:
    # Use a 3-day slice that we know contains real M1 bars + a few zones
    start = "2020-01-06"  # Monday
    end = "2020-01-09"
    raw = _load_raw_slice(start, end)
    assert len(raw) > 1000, f"slice too small: {len(raw)} bars"

    # Vectorized ground truth
    events = generate_events_from_raw(raw, start=pd.Timestamp(start, tz="UTC"),
                                       end=pd.Timestamp(end, tz="UTC"))
    expected_zones = sorted(events["zone_id"].astype(int).tolist())

    # Incremental: drive strategy.on_bar through the engine
    # Pre-load the full slice raw so the strategy's first-call precompute has data
    strat = SDR001Strategy(symbol="XAUUSD", sleeve1_filter=False, preloaded_raw=raw)
    bars = [
        Bar("XAUUSD", "M1", row.timestamp,
            float(row.open), float(row.high), float(row.low), float(row.close), float(row.volume))
        for row in raw.itertuples(index=False)
    ]
    provider = _Provider(raw, symbol="XAUUSD")
    emitted_zone_ids: list[int] = []
    deps = EngineDeps(
        clock=BacktestClock(iter(bars)),
        data_provider=provider,
        strategy=strat,
        execution=BTExecutionModel(),
        on_trade_open=lambda tr: emitted_zone_ids.append(int(tr.order.extra["zone_id"])),
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")

    emitted_sorted = sorted(emitted_zone_ids)
    # Compare sets (order can differ slightly due to fill timing)
    assert set(emitted_sorted) == set(expected_zones), (
        f"vectorized={expected_zones} incremental={emitted_sorted}"
    )
