"""Unit tests for headline summary."""
from __future__ import annotations

import pandas as pd
import pytest

from bt_engine.strategies.sdr001.summary import headline


def test_summary_empty() -> None:
    s = headline(pd.DataFrame(columns=["entry_timestamp", "net_r"]))
    assert s.trades == 0
    assert s.net_r == 0.0


def test_summary_basic_metrics() -> None:
    df = pd.DataFrame(
        {
            "entry_timestamp": pd.to_datetime(
                ["2020-01-01", "2020-06-01", "2021-03-01", "2021-12-15"], utc=True
            ),
            "net_r": [1.0, -0.5, 2.0, -1.0],
        }
    )
    s = headline(df)
    assert s.trades == 4
    assert s.net_r == pytest.approx(1.5)
    assert s.win_rate == pytest.approx(0.5)
    # gross win = 1+2=3, gross loss = 0.5+1=1.5, PF = 2.0
    assert s.profit_factor == pytest.approx(2.0)
    # cumulative: 1, 0.5, 2.5, 1.5. peak: 1, 1, 2.5, 2.5. dd: 0, -0.5, 0, -1.0
    assert s.max_drawdown_r == pytest.approx(-1.0)
    # positive years: 2020 sum = 0.5 (pos), 2021 sum = 1.0 (pos) => 2/2
    assert s.positive_years_ratio == "2/2"


def test_summary_baseline_oracle_subset() -> None:
    """Spot-check headline on a small subset matches manual calc."""
    df = pd.DataFrame(
        {
            "entry_timestamp": pd.to_datetime(
                ["2019-06-01", "2020-01-01", "2021-01-01"], utc=True
            ),
            "net_r": [1.5, -0.7, 0.8],
        }
    )
    s = headline(df)
    assert s.trades == 3
    assert s.net_r == pytest.approx(1.6)
    # 2020 has only one trade at -0.7 (negative year)
    assert s.positive_years_ratio == "2/3"
