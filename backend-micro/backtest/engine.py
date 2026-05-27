"""Micro backtest engine — Micro Alpha-Sweep + Mean-Rev + Cross-Market on XAU_USD."""
import numpy as np
import pandas as pd
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.backtest.engine import (
    _get_cached_data, BacktestTrade, BacktestResult, Signal,
)
from backend.strategies import micro_alpha_sweep, mean_rev, cross_market
from backend.strategies.dd_protection import DDState, should_skip_signal, get_risk_multiplier, update_after_trade
from backend.execution.fill_model import execute_trade
from config import YEARLY_CAPITAL, RISK_PCT, MAX_UNITS, STRATEGY_RISK


def run_backtest(
    strategies: list[str] = None,
    start_date: str = "2006-01-01",
    end_date: str = "2026-12-31",
    capital: float = YEARLY_CAPITAL,
    risk_pct: float = RISK_PCT,
    seed: int = 42,
) -> BacktestResult:
    """Run Micro portfolio backtest (Micro Alpha-Sweep + Mean-Rev + Cross-Market)."""
    if strategies is None:
        strategies = ["micro_alpha_sweep", "mean_rev", "cross_market"]
    # Frontend sends "alpha_sweep" — map to micro variant
    if "alpha_sweep" in strategies:
        strategies = [s if s != "alpha_sweep" else "micro_alpha_sweep" for s in strategies]

    # Cap to max 7 years to prevent OOM on VPS (rolling windows = 8x more signals than original)
    from datetime import datetime
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    if (end_dt - start_dt).days > 7 * 365:
        start_date = f"{end_dt.year - 7}-01-01"

    np.random.seed(seed)

    data = _get_cached_data()
    gold_d = data["gold_d"]
    gold_h1 = data["gold_h1"]
    gold_m3 = data["gold_m3"]

    # Daily bias + 50MA (same as Gold Macro)
    daily_bias = {}
    gold_50ma_vals = pd.Series(gold_d["mid_close"].values).rolling(50, min_periods=50).mean().values
    gold_50ma_dict = {}
    gold_close_dict = {}

    for i in range(1, len(gold_d)):
        d = gold_d.index[i].date()
        prev_range = gold_d["mid_high"].iat[i - 1] - gold_d["mid_low"].iat[i - 1]
        if prev_range > 0:
            body_pct = abs(gold_d["mid_close"].iat[i - 1] - gold_d["mid_open"].iat[i - 1]) / prev_range
        else:
            body_pct = 0
        if body_pct < 0.4:
            daily_bias[d] = "neutral"
        else:
            daily_bias[d] = "bullish" if gold_d["mid_close"].iat[i - 1] > gold_d["mid_open"].iat[i - 1] else "bearish"
        if not np.isnan(gold_50ma_vals[i]):
            gold_50ma_dict[d] = gold_50ma_vals[i]
        gold_close_dict[d] = gold_d["mid_close"].iat[i]

    # Generate signals from selected strategies
    all_signals: list[Signal] = []

    if "cross_market" in strategies:
        np.random.seed(seed)
        all_signals.extend(cross_market.generate_signals(
            gold_d, data["eur"], data["us10y"], data["spx"], data["silver"], data["oil"], data["us2y"]
        ))

    if "mean_rev" in strategies:
        np.random.seed(seed)
        all_signals.extend(mean_rev.generate_signals(gold_d))

    if "micro_alpha_sweep" in strategies:
        np.random.seed(seed)
        all_signals.extend(micro_alpha_sweep.generate_signals(gold_h1, gold_m3, daily_bias))

    all_signals.sort(key=lambda x: x.date)

    # Filter by date range
    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC")
    all_signals = [s for s in all_signals if start_ts <= s.date <= end_ts]

    # Execute with DD protection + fresh capital each year
    np.random.seed(seed)
    state = DDState()
    trades: list[BacktestTrade] = []
    current_year = None

    for signal in all_signals:
        trade_date = signal.date.date() if hasattr(signal.date, "date") else signal.date
        trade_year = trade_date.year

        if trade_year != current_year:
            state.equity = capital
            state.peak_equity = capital
            state.consecutive_losses = 0
            state.pause_counter = 0
            state.equity_history = []
            current_year = trade_year

        if state.equity < 100:
            continue

        # DD filters
        gp = gold_close_dict.get(trade_date, 0)
        gma = gold_50ma_dict.get(trade_date, 0)
        if should_skip_signal(signal.strategy, signal.direction, gp, gma, state):
            continue

        # Position sizing
        risk_mult = get_risk_multiplier(state)
        strat_risk_pct = STRATEGY_RISK.get(signal.strategy, risk_pct)
        risk_dollar = state.equity * (strat_risk_pct / 100) * risk_mult
        if signal.risk <= 0:
            continue
        units = min(risk_dollar / signal.risk, MAX_UNITS)

        # Execute via fill model
        df = gold_d if signal.timeframe == "D" else gold_m3
        try:
            bar_idx = df.index.get_loc(signal.date)
        except KeyError:
            continue

        tp = signal.tp
        if signal.strategy == "mean_rev" and tp == 0:
            tp = signal.entry + signal.risk * 3

        use_be = signal.strategy == "micro_alpha_sweep"
        result = execute_trade(
            df=df,
            bar_start=bar_idx,
            entry=signal.entry,
            sl=signal.sl,
            tp=tp,
            direction=signal.direction,
            max_bars=signal.max_bars,
            strategy=signal.strategy,
            use_break_even=use_be,
        )

        if result is None:
            continue

        pnl_dollar = result.pnl_per_unit * units
        update_after_trade(state, pnl_dollar)

        if signal.strategy == "micro_alpha_sweep":
            hold_str = f"{result.bars_held * 3}min" if result.bars_held < 20 else f"{result.bars_held * 3 / 60:.1f}hrs"
        else:
            hold_str = f"{result.bars_held}d"

        trades.append(BacktestTrade(
            date=signal.date.isoformat(),
            year=trade_year,
            month=trade_date.month,
            strategy=signal.strategy,
            direction=signal.direction.upper(),
            entry=round(signal.entry, 2),
            sl=round(signal.sl, 2),
            tp=round(tp, 2),
            exit_price=round(result.exit_price, 2),
            pnl_unit=round(result.pnl_per_unit, 2),
            pnl_sized=round(pnl_dollar, 2),
            units=round(units, 2),
            status=result.exit_reason,
            bars_held=result.bars_held,
            hold_human=hold_str,
            risk=round(signal.risk, 2),
            r_mult=round(result.pnl_per_unit / signal.risk, 2) if signal.risk > 0 else 0,
            equity_after=round(state.equity, 2),
        ))

    # Compute stats
    result_obj = BacktestResult(trades=trades)
    if trades:
        pnls = [t.pnl_sized for t in trades]
        result_obj.total_trades = len(trades)
        result_obj.wins = sum(1 for p in pnls if p > 0)
        result_obj.losses = result_obj.total_trades - result_obj.wins
        result_obj.win_rate = result_obj.wins / result_obj.total_trades
        result_obj.total_pnl = sum(pnls)

        gross_wins = sum(p for p in pnls if p > 0)
        gross_losses = abs(sum(p for p in pnls if p <= 0))
        result_obj.profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0

        worst_dd = 0.0
        for year in set(t.year for t in trades):
            year_eq = np.array([t.equity_after for t in trades if t.year == year])
            if len(year_eq) < 2:
                continue
            year_peak = np.maximum.accumulate(year_eq)
            year_dd = ((year_eq - year_peak) / year_peak).min()
            if year_dd < worst_dd:
                worst_dd = year_dd
        result_obj.max_drawdown_pct = float(worst_dd * 100)

    return result_obj
