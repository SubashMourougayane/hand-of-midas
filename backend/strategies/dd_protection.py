"""
Drawdown Protection — applied to all strategies.
Ported from generate_portfolio_dashboard.py lines 193-226.

Rules:
1. Gold below 50-MA → skip Mean-Rev/Cross-Market longs
2. 3 consecutive losses → halve position size
3. 5 consecutive losses → pause next 2 signals
4. Equity below 20-trade MA → halve position size (stacks with #2)
"""
import numpy as np
from dataclasses import dataclass, field
from backend.config import DD_PROTECTION, YEARLY_CAPITAL


@dataclass
class DDState:
    consecutive_losses: int = 0
    pause_counter: int = 0
    equity_history: list = field(default_factory=list)
    equity: float = YEARLY_CAPITAL
    peak_equity: float = YEARLY_CAPITAL
    current_year: int = 0

    def reset_year(self, year: int):
        self.equity = YEARLY_CAPITAL
        self.peak_equity = YEARLY_CAPITAL
        self.consecutive_losses = 0
        self.pause_counter = 0
        self.equity_history = []
        self.current_year = year


def should_skip_signal(
    strategy: str,
    direction: str,
    gold_close: float,
    gold_50ma: float,
    state: DDState,
) -> bool:
    """Return True if signal should be skipped."""
    cfg = DD_PROTECTION

    # Filter 1: 50-MA gate for Mean-Rev and Cross-Market
    if strategy in ("mean_rev", "cross_market") and direction == "long":
        if gold_close > 0 and gold_50ma > 0 and gold_close < gold_50ma:
            return True

    # Filter 2: Pause counter
    if state.pause_counter > 0:
        state.pause_counter -= 1
        return True

    return False


def get_risk_multiplier(state: DDState) -> float:
    """Get position size multiplier based on DD state."""
    cfg = DD_PROTECTION
    mult = 1.0

    if state.consecutive_losses >= cfg["consecutive_loss_halve"]:
        mult = 0.5

    if len(state.equity_history) >= cfg["equity_ma_period"]:
        eq_ma = np.mean(state.equity_history[-cfg["equity_ma_period"]:])
        if state.equity < eq_ma:
            mult *= 0.5

    return mult


def update_after_trade(state: DDState, pnl: float):
    """Update DD state after a trade completes."""
    cfg = DD_PROTECTION
    state.equity += pnl
    state.equity = max(state.equity, 0)

    if pnl > 0:
        state.consecutive_losses = 0
    else:
        state.consecutive_losses += 1
        if state.consecutive_losses >= cfg["consecutive_loss_pause"]:
            state.pause_counter = cfg["pause_signals"]

    state.equity_history.append(state.equity)
    if state.equity > state.peak_equity:
        state.peak_equity = state.equity
