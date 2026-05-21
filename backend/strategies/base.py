"""Base signal dataclass used by all strategies."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import pandas as pd


@dataclass
class Signal:
    date: pd.Timestamp
    entry: float
    sl: float
    tp: float
    direction: str  # 'long' or 'short'
    risk: float  # entry - sl (absolute)
    strategy: str  # 'alpha_sweep', 'mean_rev', 'cross_market'
    max_bars: int
    timeframe: str  # 'M3' or 'D'
    metadata: Optional[dict] = None
