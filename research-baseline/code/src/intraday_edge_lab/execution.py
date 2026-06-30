from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ExecutionModel:
    commission_bps: float = 0.25
    slippage_bps: float = 0.50
    horizon_bars: int = 5


def simulate_next_bar_execution(
    frame: pd.DataFrame,
    signals: pd.Series,
    model: ExecutionModel,
) -> pd.DataFrame:
    """Execute decisions on the next bar at bid/ask with explicit costs."""
    side = signals.reindex(frame.index).fillna(0).astype(int)
    side = side.where(side.isin([-1, 0, 1]), 0)

    entry_ask = frame["ask"].shift(-1)
    entry_bid = frame["bid"].shift(-1)
    exit_ask = frame["ask"].shift(-(model.horizon_bars + 1))
    exit_bid = frame["bid"].shift(-(model.horizon_bars + 1))

    entry = np.where(side > 0, entry_ask, np.where(side < 0, entry_bid, np.nan))
    exit_ = np.where(side > 0, exit_bid, np.where(side < 0, exit_ask, np.nan))
    gross_return = np.where(side > 0, (exit_ - entry) / entry, np.where(side < 0, (entry - exit_) / entry, np.nan))

    round_trip_cost = (2 * model.commission_bps + 2 * model.slippage_bps) / 10000.0
    net_return = gross_return - round_trip_cost

    trades = pd.DataFrame(
        {
            "decision_timestamp": frame["timestamp"],
            "entry_timestamp": frame["timestamp"].shift(-1),
            "exit_timestamp": frame["timestamp"].shift(-(model.horizon_bars + 1)),
            "side": side,
            "entry_price": entry,
            "exit_price": exit_,
            "gross_return": gross_return,
            "net_return": net_return,
            "spread_bps_at_decision": ((frame["ask"] - frame["bid"]) / frame["close"]) * 10000.0,
        }
    )
    trades = trades[(trades["side"] != 0) & trades["net_return"].notna()].copy()
    trades["pnl_units"] = trades["net_return"]
    return trades.reset_index(drop=True)
