"""Fib V2 ENSEMBLE — XAU + EUR production strategy.

20.3yr OANDA backtest: PF 1.31 / MAR 0.41 / 18/21 pos years (XAU).
21.5yr OANDA backtest: PF 1.15 / MAR 0.17 / 16/22 pos years (EUR).

Stress test PASSED: causality 100%, shuffle-future PASS, walk-forward 84% windows,
cost-robust to +$0.50, k-fold ratio 1.00.

Source-of-truth: research/fib_retrace/run_fib_v2.py + run_fib_v2_regime.py.
Plan: /Users/subash/.claude/plans/ok-now-that-we-piped-fog.md
"""
from .config import FibV2Config, LegSpec, LONG_BULL_STRONG, SHORT_BEAR_STRONG
from .state import FibV2State, FibSetup
from .strategy import FibV2EnsembleStrategy, FibV2LongStrategy, FibV2ShortStrategy

__all__ = [
    "FibV2Config",
    "LegSpec",
    "LONG_BULL_STRONG",
    "SHORT_BEAR_STRONG",
    "FibV2State",
    "FibSetup",
    "FibV2EnsembleStrategy",
    "FibV2LongStrategy",
    "FibV2ShortStrategy",
]
