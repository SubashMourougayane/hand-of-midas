from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .execution import ExecutionModel, simulate_next_bar_execution
from .features import build_causal_features
from .hypotheses import Hypothesis
from .validation import PerformanceSummary, profit_factor, summarize_performance, volatility_regime_breakdown


@dataclass(frozen=True)
class AcceptanceThresholds:
    min_trades: int = 100
    min_win_rate: float = 0.60
    min_profit_factor: float = 2.0
    min_expectancy: float = 0.0
    min_bootstrap_ci_low: float = 0.0
    max_monte_carlo_loss_probability: float = 0.05
    min_cost_stress_profit_factor: float = 1.25
    min_cost_stress_expectancy: float = 0.0
    max_parameter_expectancy_cv: float = 1.0


@dataclass(frozen=True)
class ValidationGate:
    name: str
    passed: bool
    metric: float | int | str
    threshold: float | int | str
    details: str

    def to_dict(self) -> dict[str, float | int | str | bool]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceReport:
    accepted: bool
    gates: tuple[ValidationGate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "gates": [gate.to_dict() for gate in self.gates],
        }


def _period_expectancy(trades: pd.DataFrame, period: str) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float)
    timestamp = pd.to_datetime(trades["decision_timestamp"], utc=True).dt.tz_convert(None)
    return trades.assign(_period=timestamp.dt.to_period(period)).groupby("_period")["net_return"].mean()


def _walk_forward_fold_expectancies(trades: pd.DataFrame, folds: int = 4) -> list[float]:
    if trades.empty:
        return []
    ordered = trades.sort_values("decision_timestamp").reset_index(drop=True)
    fold_ids = np.array_split(np.arange(len(ordered)), folds)
    return [float(ordered.iloc[idx]["net_return"].mean()) for idx in fold_ids if len(idx)]


def _rolling_window_expectancies(trades: pd.DataFrame, window: int) -> list[float]:
    if trades.empty or len(trades) < window:
        return []
    values = trades.sort_values("decision_timestamp")["net_return"].rolling(window).mean().dropna()
    return [float(value) for value in values]


def _monte_carlo_loss_probability(trades: pd.DataFrame, n: int = 2000, seed: int = 13) -> float:
    if trades.empty:
        return 1.0
    rng = np.random.default_rng(seed)
    returns = trades["net_return"].to_numpy()
    samples = rng.choice(returns, size=(n, len(returns)), replace=True).mean(axis=1)
    return float((samples <= 0).mean())


def _cost_stress_summary(
    frame: pd.DataFrame,
    signals: pd.Series,
    base_model: ExecutionModel,
    multiplier: float,
) -> PerformanceSummary:
    stressed = ExecutionModel(
        commission_bps=base_model.commission_bps * multiplier,
        slippage_bps=base_model.slippage_bps * multiplier,
        horizon_bars=base_model.horizon_bars,
    )
    trades = simulate_next_bar_execution(frame, signals, stressed)
    return summarize_performance(trades)


def _parameter_perturbation_expectancies(
    frame: pd.DataFrame,
    hypothesis_factory: Callable[..., Hypothesis],
    execution_model: ExecutionModel,
    variations: tuple[dict[str, float | int | bool], ...],
) -> list[float]:
    features = build_causal_features(frame)
    expectancies = []
    for kwargs in variations:
        hypothesis = hypothesis_factory(**kwargs)
        signals = hypothesis.generate_signals(frame, features)
        trades = simulate_next_bar_execution(frame, signals, execution_model)
        if not trades.empty:
            expectancies.append(float(trades["net_return"].mean()))
    return expectancies


def evaluate_acceptance(
    frame: pd.DataFrame,
    hypothesis: Hypothesis,
    execution_model: ExecutionModel,
    summary: PerformanceSummary,
    expectancy_ci_95: tuple[float, float],
    trades: pd.DataFrame,
    parameter_variations: tuple[dict[str, float | int | bool], ...] | None = None,
    thresholds: AcceptanceThresholds = AcceptanceThresholds(),
) -> AcceptanceReport:
    features = build_causal_features(frame)
    signals = hypothesis.generate_signals(frame, features)
    regimes = volatility_regime_breakdown(frame, trades)
    monthly = _period_expectancy(trades, "M")
    yearly = _period_expectancy(trades, "Y")
    walk_forward = _walk_forward_fold_expectancies(trades)
    rolling_window = _rolling_window_expectancies(trades, window=max(20, min(100, len(trades) // 4 or 20)))
    mc_loss_probability = _monte_carlo_loss_probability(trades)
    cost_stress = _cost_stress_summary(frame, signals, execution_model, multiplier=2.0)

    gates: list[ValidationGate] = [
        ValidationGate(
            "minimum_sample_size",
            summary.trades >= thresholds.min_trades,
            summary.trades,
            thresholds.min_trades,
            "Rejects tiny samples before any performance claim is accepted.",
        ),
        ValidationGate(
            "win_rate",
            summary.win_rate >= thresholds.min_win_rate,
            summary.win_rate,
            thresholds.min_win_rate,
            "Required by mandate after realistic execution costs.",
        ),
        ValidationGate(
            "profit_factor",
            summary.profit_factor >= thresholds.min_profit_factor,
            summary.profit_factor,
            thresholds.min_profit_factor,
            "Gross gains divided by absolute gross losses on net returns.",
        ),
        ValidationGate(
            "expectancy",
            summary.expectancy > thresholds.min_expectancy,
            summary.expectancy,
            thresholds.min_expectancy,
            "Mean net return per trade after spread, commission, and slippage.",
        ),
        ValidationGate(
            "positive_every_month",
            bool(len(monthly)) and bool((monthly > 0).all()),
            f"{int((monthly > 0).sum())}/{len(monthly)}",
            "all",
            "Every calendar month with trades must be positive.",
        ),
        ValidationGate(
            "positive_every_year",
            bool(len(yearly)) and bool((yearly > 0).all()),
            f"{int((yearly > 0).sum())}/{len(yearly)}",
            "all",
            "Every calendar year with trades must be positive.",
        ),
        ValidationGate(
            "volatility_regime_stability",
            bool(len(regimes)) and bool((regimes["expectancy"] > 0).all()),
            f"{int((regimes['expectancy'] > 0).sum())}/{len(regimes)}",
            "all",
            "Low, medium, and high realized-volatility buckets must remain positive.",
        ),
        ValidationGate(
            "bootstrap_expectancy",
            expectancy_ci_95[0] > thresholds.min_bootstrap_ci_low,
            expectancy_ci_95[0],
            thresholds.min_bootstrap_ci_low,
            "Lower 95 percent bootstrap confidence bound must remain positive.",
        ),
        ValidationGate(
            "monte_carlo_loss_probability",
            mc_loss_probability <= thresholds.max_monte_carlo_loss_probability,
            mc_loss_probability,
            thresholds.max_monte_carlo_loss_probability,
            "Probability that resampled expectancy is non-positive.",
        ),
        ValidationGate(
            "walk_forward",
            bool(walk_forward) and all(value > 0 for value in walk_forward),
            f"{sum(value > 0 for value in walk_forward)}/{len(walk_forward)}",
            "all",
            "Chronological folds must all retain positive expectancy.",
        ),
        ValidationGate(
            "rolling_window",
            bool(rolling_window) and all(value > 0 for value in rolling_window),
            f"{sum(value > 0 for value in rolling_window)}/{len(rolling_window)}",
            "all",
            "Rolling trade windows must all retain positive expectancy.",
        ),
        ValidationGate(
            "cost_stress",
            (
                cost_stress.profit_factor >= thresholds.min_cost_stress_profit_factor
                and cost_stress.expectancy > thresholds.min_cost_stress_expectancy
            ),
            f"pf={cost_stress.profit_factor:.6g}, expectancy={cost_stress.expectancy:.6g}",
            f"pf>={thresholds.min_cost_stress_profit_factor}, expectancy>0",
            "Commission and slippage are doubled.",
        ),
    ]

    if parameter_variations:
        expectancies = _parameter_perturbation_expectancies(
            frame,
            type(hypothesis),
            execution_model,
            parameter_variations,
        )
        mean_abs = float(np.mean(np.abs(expectancies))) if expectancies else 0.0
        cv = float(np.std(expectancies) / mean_abs) if mean_abs else float("inf")
        gates.append(
            ValidationGate(
                "parameter_perturbation",
                bool(expectancies)
                and all(value > 0 for value in expectancies)
                and cv <= thresholds.max_parameter_expectancy_cv,
                cv,
                thresholds.max_parameter_expectancy_cv,
                "Nearby parameter variants must stay positive without excessive dispersion.",
            )
        )
    else:
        gates.append(
            ValidationGate(
                "parameter_perturbation",
                False,
                "not_run",
                "required",
                "No perturbation grid was supplied.",
            )
        )

    accepted = all(gate.passed for gate in gates)
    return AcceptanceReport(accepted=accepted, gates=tuple(gates))
