"""Headline summary from a trades DataFrame (entry_timestamp, net_r columns)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class HeadlineSummary:
    trades: int
    net_r: float
    win_rate: float
    profit_factor: float
    max_drawdown_r: float
    positive_years_ratio: str


def headline(trades: pd.DataFrame, *, r_col: str = "net_r", ts_col: str = "entry_timestamp") -> HeadlineSummary:
    if trades.empty:
        return HeadlineSummary(0, 0.0, 0.0, 0.0, 0.0, "0/0")
    r = trades[r_col].astype(float)
    n = len(r)
    wins = r > 0
    win_rate = float(wins.mean())
    gross_win = float(r[r > 0].sum())
    gross_loss = float(-r[r < 0].sum())
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    # max drawdown on cumulative R
    eq = r.cumsum().values
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    max_dd = float(dd.min())

    # positive years
    years = pd.to_datetime(trades[ts_col], utc=True).dt.year
    by_year = trades.assign(_year=years).groupby("_year")[r_col].sum()
    pos = int((by_year > 0).sum())
    total = int(len(by_year))
    return HeadlineSummary(
        trades=n,
        net_r=float(r.sum()),
        win_rate=win_rate,
        profit_factor=pf,
        max_drawdown_r=max_dd,
        positive_years_ratio=f"{pos}/{total}",
    )
