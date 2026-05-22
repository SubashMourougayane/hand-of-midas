"""Oil backtest engine — Alpha-Sweep only on BCO_USD."""
import numpy as np
import pandas as pd
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.cache import load_candles
from strategies.alpha_sweep import generate_signals, Signal
from execution.fill_model import execute_trade, TradeResult
from config import YEARLY_CAPITAL, RISK_PCT, MAX_UNITS, STRATEGY_RISK
from dataclasses import dataclass, field

_DATA_CACHE = {}


def _get_cached_data():
    if not _DATA_CACHE:
        t0 = time.time()
        _DATA_CACHE["oil_d"] = load_candles("BCO_USD_D.csv")
        _DATA_CACHE["oil_h1"] = load_candles("BCO_USD_H1.csv")
        _DATA_CACHE["oil_m3"] = load_candles("BCO_USD_M3.csv")
        print(f"  Oil data loaded in {time.time()-t0:.1f}s ({len(_DATA_CACHE['oil_m3'])} M3 bars)")
    return _DATA_CACHE


@dataclass
class BacktestTrade:
    date: str
    year: int
    month: int
    strategy: str
    direction: str
    entry: float
    sl: float
    tp: float
    exit_price: float
    pnl_unit: float
    pnl_sized: float
    units: float
    status: str
    bars_held: int
    hold_human: str
    risk: float
    r_mult: float
    equity_after: float


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    total_pnl: float = 0
    win_rate: float = 0
    profit_factor: float = 0
    max_drawdown_pct: float = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0


def run_backtest(
    start_date: str = "2006-01-01",
    end_date: str = "2026-12-31",
    capital: float = YEARLY_CAPITAL,
    risk_pct: float = RISK_PCT,
    seed: int = 42,
) -> BacktestResult:
    np.random.seed(seed)

    data = _get_cached_data()
    oil_d = data["oil_d"]
    oil_h1 = data["oil_h1"]
    oil_m3 = data["oil_m3"]

    # Daily bias
    daily_bias = {}
    for i in range(1, len(oil_d)):
        d = oil_d.index[i].date()
        daily_bias[d] = "bullish" if oil_d["mid_close"].iat[i - 1] > oil_d["mid_open"].iat[i - 1] else "bearish"

    # Generate signals
    np.random.seed(seed)
    all_signals = generate_signals(oil_h1, oil_m3, daily_bias)
    all_signals.sort(key=lambda x: x.date)

    # Filter by date range
    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC")
    all_signals = [s for s in all_signals if start_ts <= s.date <= end_ts]

    # Execute with fresh capital each year
    np.random.seed(seed)
    equity = capital
    peak_equity = capital
    consecutive_losses = 0
    equity_history = []
    trades: list[BacktestTrade] = []
    current_year = None

    for signal in all_signals:
        trade_date = signal.date.date()
        trade_year = trade_date.year

        if trade_year != current_year:
            equity = capital
            peak_equity = capital
            consecutive_losses = 0
            equity_history = []
            current_year = trade_year

        if equity < 100:
            continue

        # DD protection
        risk_mult = 1.0
        if consecutive_losses >= 3:
            risk_mult = 0.5
        if len(equity_history) >= 20:
            eq_ma = np.mean(equity_history[-20:])
            if equity < eq_ma:
                risk_mult *= 0.5

        strat_risk = STRATEGY_RISK.get("alpha_sweep", risk_pct)
        risk_dollar = equity * (strat_risk / 100) * risk_mult
        if signal.risk <= 0:
            continue
        units = min(risk_dollar / signal.risk, MAX_UNITS)

        # Execute
        try:
            bar_idx = oil_m3.index.get_loc(signal.date)
        except KeyError:
            continue

        result = execute_trade(
            df=oil_m3,
            bar_start=bar_idx,
            entry=signal.entry,
            sl=signal.sl,
            tp=signal.tp,
            direction=signal.direction,
            max_bars=signal.max_bars,
            strategy="alpha_sweep_oil",
            use_break_even=True,
        )

        if result is None:
            continue

        pnl_dollar = result.pnl_per_unit * units
        equity += pnl_dollar
        equity = max(equity, 0)

        if pnl_dollar > 0:
            consecutive_losses = 0
        else:
            consecutive_losses += 1

        equity_history.append(equity)
        if equity > peak_equity:
            peak_equity = equity

        hold_str = f"{result.bars_held * 3}min" if result.bars_held < 20 else f"{result.bars_held * 3 / 60:.1f}hrs"

        trades.append(BacktestTrade(
            date=signal.date.isoformat(), year=trade_year, month=trade_date.month,
            strategy="alpha_sweep_oil", direction=signal.direction.upper(),
            entry=round(signal.entry, 4), sl=round(signal.sl, 4), tp=round(signal.tp, 4),
            exit_price=round(result.exit_price, 4),
            pnl_unit=round(result.pnl_per_unit, 4), pnl_sized=round(pnl_dollar, 2),
            units=round(units, 2), status=result.exit_reason, bars_held=result.bars_held,
            hold_human=hold_str, risk=round(signal.risk, 4),
            r_mult=round(result.pnl_per_unit / signal.risk, 2) if signal.risk > 0 else 0,
            equity_after=round(equity, 2),
        ))

    # Stats
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
