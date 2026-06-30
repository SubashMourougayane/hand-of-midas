"""Fast parity smoke: first 6 months of XAU OANDA (~50k M5 bars). Useful for
catching gross issues before the full 20yr test runs.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bt_engine.strategies.fib_v2 import LONG_BULL_STRONG, SHORT_BEAR_STRONG

from ._fib_v2_helper import run_engine_capture_trades, load_oanda_parquet


XAU_M5 = Path("/tmp/oanda_xau_m5.parquet")


@pytest.mark.skipif(not XAU_M5.exists(), reason="XAU parquet missing")
def test_parity_smoke_6mo_long_runs():
    m5 = load_oanda_parquet(XAU_M5).iloc[:50_000].reset_index(drop=True)
    bt = run_engine_capture_trades(
        m5_frame=m5, symbol="XAUUSD.ecn",
        legs=(LONG_BULL_STRONG,), cost_usd=0.30,
    )
    assert isinstance(bt, pd.DataFrame)
    # Should run without exceptions; trades can be 0+.
    print(f"\n[6mo long smoke] bt trades: {len(bt)}")
    if len(bt):
        print(bt.head().to_dict("records"))


@pytest.mark.skipif(not XAU_M5.exists(), reason="XAU parquet missing")
def test_parity_smoke_6mo_short_runs():
    m5 = load_oanda_parquet(XAU_M5).iloc[:50_000].reset_index(drop=True)
    bt = run_engine_capture_trades(
        m5_frame=m5, symbol="XAUUSD.ecn",
        legs=(SHORT_BEAR_STRONG,), cost_usd=0.30,
    )
    assert isinstance(bt, pd.DataFrame)
    print(f"\n[6mo short smoke] bt trades: {len(bt)}")
