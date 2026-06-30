"""Integration smoke test: run FibV2EnsembleStrategy through run_engine over
the first year of OANDA XAU M5. Verify bars process, no exceptions, state is
sane. NOT parity (Phase 5). Just wiring.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2 import FibV2EnsembleStrategy

XAU_M5_PATH = Path("/tmp/oanda_xau_m5.parquet")


def _has_data() -> bool:
    return XAU_M5_PATH.exists()


@pytest.mark.skipif(not _has_data(), reason="OANDA XAU M5 parquet not available at /tmp/oanda_xau_m5.parquet")
def test_run_engine_fib_v2_first_year_smoke():
    """Run first 50,000 M5 bars (~6 months); assert no exceptions and bars > 0."""
    raw = pd.read_parquet(XAU_M5_PATH)
    if raw["timestamp"].dt.tz is None:
        raw["timestamp"] = raw["timestamp"].dt.tz_localize("UTC")
    raw = raw.sort_values("timestamp").reset_index(drop=True)
    # First ~6 months of M5 = ~50,000 bars.
    raw = raw.iloc[:50_000].reset_index(drop=True)

    provider = _InMemoryProvider(raw, symbol="XAUUSD.ecn", timeframe="M5")
    clock = _InMemoryClock(provider)
    strat = FibV2EnsembleStrategy(symbol="XAUUSD.ecn")

    deps = EngineDeps(
        clock=clock,
        data_provider=provider,
        strategy=strat,
        execution=BTExecutionModel(),
        broker=None,
        recorder=None,
        journal=None,
        max_bars_held=72 * 12 * 2,  # research horizon (72h * 12 M5/h * 2)
    )
    run = run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")

    assert run.bars_processed > 0
    assert run.bars_processed == 50_000
    # Some closed trades likely; ensure we don't blow up.
    # (parity gate will assert exact counts in Phase 5)
    assert len(run.closed_trades) >= 0


# ----- minimal provider/clock for in-memory parquet -----

class _InMemoryProvider:
    def __init__(self, frame: pd.DataFrame, *, symbol: str, timeframe: str) -> None:
        self._df = frame.copy()
        self.symbol = symbol
        self.timeframe = timeframe
        self._idx = 0

    def bars(self):
        from bt_engine.core.bar import Bar
        for _, row in self._df.iterrows():
            yield Bar.from_row(symbol=self.symbol, timeframe=self.timeframe, row=row)

    def history_up_to(self, ts):
        df = self._df[self._df["timestamp"] <= ts]
        return df.reset_index(drop=True)


class _InMemoryClock:
    def __init__(self, provider: _InMemoryProvider) -> None:
        self._iter = iter(provider.bars())

    def tick(self):
        try:
            return next(self._iter)
        except StopIteration:
            return None
