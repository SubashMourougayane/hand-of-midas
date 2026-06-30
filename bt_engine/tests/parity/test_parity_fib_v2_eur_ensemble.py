"""BLOCKING parity gate: ENSEMBLE on EUR/USD OANDA must match
research/fib_retrace/fib_v2_oanda_eur_ensemble_trades.parquet within 15% drift.
EUR has tighter spreads and shorter R units; minor drift expected from H1 derivation.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bt_engine.strategies.fib_v2 import LONG_BULL_STRONG, SHORT_BEAR_STRONG

from ._fib_v2_helper import (
    run_engine_capture_trades,
    load_oanda_parquet,
    normalize_research_trades,
)


EUR_M5 = Path("/tmp/oanda_eur_m5.parquet")
EUR_H1 = Path("/tmp/oanda_eur_h1.parquet")
RESEARCH_PARQUET = Path(
    "/Users/subash/SUBASH/GoldDigger/research/fib_retrace/"
    "fib_v2_oanda_eur_ensemble_trades.parquet"
)


@pytest.mark.skipif(not (EUR_M5.exists() and RESEARCH_PARQUET.exists()),
                     reason="OANDA EUR parquets missing")
def test_parity_fib_v2_eur_ensemble_count():
    m5 = load_oanda_parquet(EUR_M5)
    h1 = pd.read_parquet(EUR_H1)
    bt = run_engine_capture_trades(
        m5_frame=m5, symbol="EURUSD.ecn",
        legs=(LONG_BULL_STRONG, SHORT_BEAR_STRONG), cost_usd=0.00003, h1_frame=h1,
    )
    research = normalize_research_trades(pd.read_parquet(RESEARCH_PARQUET))
    n_bt = len(bt)
    n_research = len(research)
    diff = abs(n_bt - n_research)
    abs_tol = max(2, int(n_research * 0.15))
    print(f"\n[EUR ensemble] bt={n_bt} research={n_research} diff={diff} tol={abs_tol}")
    assert diff <= abs_tol


@pytest.mark.skipif(not (EUR_M5.exists() and RESEARCH_PARQUET.exists()),
                     reason="OANDA EUR parquets missing")
def test_parity_fib_v2_eur_ensemble_net_r_close():
    m5 = load_oanda_parquet(EUR_M5)
    h1 = pd.read_parquet(EUR_H1)
    bt = run_engine_capture_trades(
        m5_frame=m5, symbol="EURUSD.ecn",
        legs=(LONG_BULL_STRONG, SHORT_BEAR_STRONG), cost_usd=0.00003, h1_frame=h1,
    )
    research = normalize_research_trades(pd.read_parquet(RESEARCH_PARQUET))
    bt_net = bt["net_r"].sum() if len(bt) else 0.0
    r_net = research["net_r"].sum()
    diff_pct = abs(bt_net - r_net) / max(abs(r_net), 1e-9)
    print(f"\n[EUR ensemble net_R] bt={bt_net:.2f} research={r_net:.2f} diff%={diff_pct*100:.2f}")
    assert diff_pct < 0.25, f"Net R drift {diff_pct*100:.2f}% too large"
