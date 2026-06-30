from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PerformanceSummary:
    trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    long_expectancy: float
    short_expectancy: float
    positive_months: int
    total_months: int
    positive_years: int
    total_years: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def profit_factor(returns: pd.Series) -> float:
    gains = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def summarize_performance(trades: pd.DataFrame) -> PerformanceSummary:
    if trades.empty:
        return PerformanceSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0, 0)

    returns = trades["net_return"]
    timestamp = pd.to_datetime(trades["decision_timestamp"], utc=True).dt.tz_convert(None)
    monthly = trades.assign(_period=timestamp.dt.to_period("M")).groupby("_period")["net_return"].mean()
    yearly = trades.assign(_period=timestamp.dt.to_period("Y")).groupby("_period")["net_return"].mean()
    long_returns = trades.loc[trades["side"] > 0, "net_return"]
    short_returns = trades.loc[trades["side"] < 0, "net_return"]

    return PerformanceSummary(
        trades=int(len(trades)),
        win_rate=float((returns > 0).mean()),
        profit_factor=profit_factor(returns),
        expectancy=float(returns.mean()),
        long_expectancy=float(long_returns.mean()) if not long_returns.empty else 0.0,
        short_expectancy=float(short_returns.mean()) if not short_returns.empty else 0.0,
        positive_months=int((monthly > 0).sum()),
        total_months=int(len(monthly)),
        positive_years=int((yearly > 0).sum()),
        total_years=int(len(yearly)),
    )


def volatility_regime_breakdown(frame: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["volatility_regime", "trades", "win_rate", "profit_factor", "expectancy"])

    proxy = frame[["timestamp", "close"]].copy()
    proxy["rv_50"] = proxy["close"].pct_change().rolling(50, min_periods=20).std()
    proxy["volatility_regime"] = pd.qcut(
        proxy["rv_50"].rank(method="first"),
        q=3,
        labels=["low", "medium", "high"],
        duplicates="drop",
    )
    enriched = trades.merge(proxy[["timestamp", "volatility_regime"]], left_on="decision_timestamp", right_on="timestamp")
    rows = []
    for regime, group in enriched.groupby("volatility_regime", observed=True):
        summary = summarize_performance(group)
        rows.append(
            {
                "volatility_regime": str(regime),
                "trades": summary.trades,
                "win_rate": summary.win_rate,
                "profit_factor": summary.profit_factor,
                "expectancy": summary.expectancy,
            }
        )
    return pd.DataFrame(rows)


def bootstrap_expectancy_ci(trades: pd.DataFrame, n: int = 1000, seed: int = 7) -> tuple[float, float]:
    if trades.empty:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    returns = trades["net_return"].to_numpy()
    samples = rng.choice(returns, size=(n, len(returns)), replace=True).mean(axis=1)
    return (float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975)))
