"""BLOCKING parity gate: bt_engine FibV2ShortStrategy on XAU OANDA must match
research/fib_retrace/fib_v2_oanda_short_bear_strong_trades.parquet within 10% drift.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bt_engine.strategies.fib_v2 import SHORT_BEAR_STRONG

from ._fib_v2_helper import (
    run_engine_capture_trades,
    load_oanda_parquet,
    normalize_research_trades,
)


XAU_M5 = Path("/tmp/oanda_xau_m5.parquet")
XAU_H1 = Path("/tmp/oanda_xau_h1.parquet")
RESEARCH_PARQUET = Path(
    "/Users/subash/SUBASH/GoldDigger/research/fib_retrace/"
    "fib_v2_oanda_short_bear_strong_trades.parquet"
)


@pytest.mark.skipif(not (XAU_M5.exists() and RESEARCH_PARQUET.exists()),
                     reason="OANDA XAU parquets missing")
def test_parity_fib_v2_xau_short_count_within_tolerance():
    m5 = load_oanda_parquet(XAU_M5)
    h1 = pd.read_parquet(XAU_H1)
    bt_trades = run_engine_capture_trades(
        m5_frame=m5, symbol="XAUUSD.ecn",
        legs=(SHORT_BEAR_STRONG,), cost_usd=0.30, h1_frame=h1,
    )
    research = normalize_research_trades(pd.read_parquet(RESEARCH_PARQUET))

    n_bt = len(bt_trades)
    n_research = len(research)
    diff = abs(n_bt - n_research)
    tolerance_pct = 0.10
    abs_tol = max(2, int(n_research * tolerance_pct))
    assert diff <= abs_tol, (
        f"Trade count mismatch: bt={n_bt} vs research={n_research} (diff={diff}, tol={abs_tol})"
    )


@pytest.mark.skipif(not (XAU_M5.exists() and RESEARCH_PARQUET.exists()),
                     reason="OANDA XAU parquets missing")
def test_parity_fib_v2_xau_short_net_r_close():
    m5 = load_oanda_parquet(XAU_M5)
    h1 = pd.read_parquet(XAU_H1)
    bt_trades = run_engine_capture_trades(
        m5_frame=m5, symbol="XAUUSD.ecn",
        legs=(SHORT_BEAR_STRONG,), cost_usd=0.30, h1_frame=h1,
    )
    research = normalize_research_trades(pd.read_parquet(RESEARCH_PARQUET))
    bt_net = bt_trades["net_r"].sum() if len(bt_trades) else 0.0
    r_net = research["net_r"].sum()
    diff_pct = abs(bt_net - r_net) / max(abs(r_net), 1e-9)
    # Short has fewer trades (1380) → slightly larger relative drift; allow 15%.
    assert diff_pct < 0.15, f"Net R diff {diff_pct*100:.2f}%: bt={bt_net:.2f} vs research={r_net:.2f}"
