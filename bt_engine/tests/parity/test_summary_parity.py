"""Parity gate: headline numbers must match the frozen baseline EXACTLY.

Target:
    trades=1032, net_r=+256.11R, WR=63.86%, PF=1.68, max DD=-12.69R, 8/8 years.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bt_engine.strategies.sdr001.parity_replay import load_ledger
from bt_engine.strategies.sdr001.summary import headline


REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER = REPO_ROOT / "research-baseline" / "results" / "base" / "base_sleeve1_trades.csv"


pytestmark = pytest.mark.skipif(not LEDGER.is_file(), reason="baseline ledger missing")


def test_headline_matches_baseline_full_sample() -> None:
    df = load_ledger(LEDGER)
    # baseline ledger uses 'net_1r_after_cost' as the canonical net_r
    r_col = "net_1r_after_cost" if "net_1r_after_cost" in df.columns else "net_r"
    s = headline(df, r_col=r_col)
    assert s.trades == 1032
    assert s.net_r == pytest.approx(256.106675, abs=1e-3)
    assert s.win_rate == pytest.approx(0.638566, abs=1e-4)
    assert s.profit_factor == pytest.approx(1.683757, abs=1e-3)
    assert s.max_drawdown_r == pytest.approx(-12.694926, abs=1e-2)
    assert s.positive_years_ratio == "8/8"
