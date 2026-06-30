from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .acceptance import AcceptanceReport, evaluate_acceptance
from .causality import CausalityReport, prepare_intraday_frame, validate_market_data
from .execution import ExecutionModel, simulate_next_bar_execution
from .features import add_synthetic_quotes, build_causal_features
from .hypotheses import Hypothesis
from .validation import (
    PerformanceSummary,
    bootstrap_expectancy_ci,
    summarize_performance,
    volatility_regime_breakdown,
)


@dataclass(frozen=True)
class ResearchResult:
    causality: CausalityReport
    summary: PerformanceSummary
    expectancy_ci_95: tuple[float, float]
    regime_breakdown: pd.DataFrame
    acceptance: AcceptanceReport
    trades: pd.DataFrame


def run_research(
    raw: pd.DataFrame,
    hypothesis: Hypothesis,
    execution_model: ExecutionModel,
    synthetic_spread_bps: float = 2.0,
) -> ResearchResult:
    frame = prepare_intraday_frame(raw)
    frame = add_synthetic_quotes(frame, spread_bps=synthetic_spread_bps)
    causality = validate_market_data(frame)
    features = build_causal_features(frame)
    signals = hypothesis.generate_signals(frame, features)
    trades = simulate_next_bar_execution(frame, signals, execution_model)
    summary = summarize_performance(trades)
    ci = bootstrap_expectancy_ci(trades)
    regimes = volatility_regime_breakdown(frame, trades)
    acceptance = evaluate_acceptance(
        frame,
        hypothesis,
        execution_model,
        summary,
        ci,
        trades,
        parameter_variations=hypothesis.parameter_variations(),
    )
    return ResearchResult(causality, summary, ci, regimes, acceptance, trades)
