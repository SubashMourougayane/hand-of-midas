"""Walk-forward harness for Labs sprints.

Splits the development window into a Train period and a Validate period:
- Train: 2019-09-26 → 2022-12-31
- Validate: 2023-01-01 → 2023-12-31

Caller tunes on Train. Picks final config(s). Runs unchanged on Validate.
The Validate number is the only one that counts for promotion decisions.

This is a SUB-split of the dev window. R&D validation (2024) and holdout
(2025-2026) remain sealed. Labs walk-forward operates entirely within the
already-unlocked DEVELOPMENT slice.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

TRAIN_START = "2019-09-26"
TRAIN_END = "2022-12-31"
VALIDATE_START = "2023-01-01"
VALIDATE_END = "2023-12-31"


@dataclass(frozen=True)
class WindowedData:
    train: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
    validate: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]


def split_dev(data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]) -> WindowedData:
    """Split (D1, H1, M3) into (Train, Validate). Each is a 3-tuple."""
    d1, h1, m3 = data
    train_start_ts = pd.Timestamp(TRAIN_START, tz="UTC")
    train_end_ts = pd.Timestamp(TRAIN_END, tz="UTC") + pd.Timedelta(days=1)
    val_start_ts = pd.Timestamp(VALIDATE_START, tz="UTC")
    val_end_ts = pd.Timestamp(VALIDATE_END, tz="UTC") + pd.Timedelta(days=1)

    def _slice(df: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DataFrame:
        return df[(df.index >= lo) & (df.index < hi)]

    train = (
        _slice(d1, train_start_ts, train_end_ts),
        _slice(h1, train_start_ts, train_end_ts),
        _slice(m3, train_start_ts, train_end_ts),
    )
    validate = (
        _slice(d1, val_start_ts, val_end_ts),
        _slice(h1, val_start_ts, val_end_ts),
        _slice(m3, val_start_ts, val_end_ts),
    )
    return WindowedData(train=train, validate=validate)


def describe_split(data: WindowedData) -> str:
    t_d1, t_h1, t_m3 = data.train
    v_d1, v_h1, v_m3 = data.validate
    return (
        f"  Train    : {TRAIN_START} → {TRAIN_END}    "
        f"M3={len(t_m3):,}  H1={len(t_h1):,}\n"
        f"  Validate : {VALIDATE_START} → {VALIDATE_END}  "
        f"M3={len(v_m3):,}  H1={len(v_h1):,}"
    )
