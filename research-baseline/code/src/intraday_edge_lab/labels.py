from __future__ import annotations

import pandas as pd


def forward_mid_return(frame: pd.DataFrame, horizon_bars: int) -> pd.Series:
    """Forward mid return from next-bar entry to horizon exit, for diagnostics only."""
    mid = (frame["bid"] + frame["ask"]) / 2.0
    entry = mid.shift(-1)
    exit_ = mid.shift(-(horizon_bars + 1))
    return (exit_ - entry) / entry
