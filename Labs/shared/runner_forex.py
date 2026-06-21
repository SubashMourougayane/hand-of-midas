"""Forex strategy runner.

Same shape as Labs.shared.runner but the fill timeframe is M15 instead
of M3, and there's a 4th frame (H4). Strategies are pure functions of
the bundle + config.

The yearly-reset, risk-sizing, and per-trade-PnL logic mirror
Labs.shared.runner exactly so cross-sprint comparisons stay apples-to-
apples.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

import pandas as pd

from Labs.shared.data_forex import ForexBundle
from Labs.shared.fill_model import TradeResult, execute_trade


Direction = Literal["long", "short"]


@dataclass(frozen=True)
class Signal:
    entry_bar_ts: pd.Timestamp
    direction: Direction
    entry: float
    sl: float
    tp: float
    max_bars: int
    metadata: dict = field(default_factory=dict)


@dataclass
class Trade:
    signal: Signal
    result: TradeResult


@dataclass
class RunResult:
    symbol: str
    config_label: str
    trades: list[Trade]
    total_signals: int
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    max_dd_pct_yearly_worst: float
    by_year: dict[int, dict]


def _yearly_stats(
    trades: list[Trade],
    starting_capital: float,
    risk_pct: float,
    max_units: float,
) -> dict[int, dict]:
    by_year: dict[int, dict] = {}
    if not trades:
        return by_year

    sorted_trades = sorted(trades, key=lambda t: t.signal.entry_bar_ts)
    current_year: int | None = None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    wins = 0
    pnl = 0.0
    n = 0

    for t in sorted_trades:
        y = t.signal.entry_bar_ts.year
        if y != current_year:
            if current_year is not None:
                by_year[current_year] = {
                    "trades": n, "wins": wins, "pnl": round(pnl, 2),
                    "dd_pct": round(max_dd, 2),
                    "ending_equity": round(starting_capital + pnl, 2),
                }
            current_year = y
            equity = starting_capital
            peak = starting_capital
            max_dd = 0.0
            wins = 0
            pnl = 0.0
            n = 0

        risk_dollar = equity * (risk_pct / 100.0)
        signal_risk = abs(t.signal.entry - t.signal.sl)
        if signal_risk <= 0:
            continue
        units = min(risk_dollar / signal_risk, max_units)
        trade_pnl = t.result.pnl_per_unit * units

        equity += trade_pnl
        equity = max(equity, 0)
        pnl += trade_pnl
        n += 1
        if trade_pnl > 0:
            wins += 1
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak * 100.0
            if dd > max_dd:
                max_dd = dd

    if current_year is not None:
        by_year[current_year] = {
            "trades": n, "wins": wins, "pnl": round(pnl, 2),
            "dd_pct": round(max_dd, 2),
            "ending_equity": round(starting_capital + pnl, 2),
        }
    return by_year


_FOREX_SLIP_BASE = 0.00005       # 0.5 pip baseline for non-JPY pairs
_FOREX_SLIP_BASE_JPY = 0.005     # 0.5 pip baseline for JPY (price ~150)
_GOLD_SLIP_BASE = 0.05           # 5 cents baseline for XAU


def _slip_params_for(symbol: str) -> tuple[float, float]:
    """Pick (base, range_coef) for the instrument's price scale."""
    if symbol == "USD_JPY":
        return _FOREX_SLIP_BASE_JPY, 0.05
    if symbol == "XAU_USD":
        return _GOLD_SLIP_BASE, 0.01
    if symbol == "BCO_USD":
        # Oil price ~$70-90; same family as gold/oil production calibration
        return 0.0325, 0.01
    return _FOREX_SLIP_BASE, 0.05


def run_forex_strategy(
    strategy_fn: Callable,
    bundle: ForexBundle,
    config_label: str = "",
    *,
    starting_capital: float = 5_000.0,
    risk_pct: float = 4.0,
    max_units: float = 5_000.0,
) -> RunResult:
    """Run one forex strategy through canonical fill model.

    strategy_fn signature:
        strategy_fn(d1, h4, h1, m15) -> list[Signal]
    """
    signals = strategy_fn(bundle.d1, bundle.h4, bundle.h1, bundle.m15)
    slip_base, slip_range_coef = _slip_params_for(bundle.symbol)

    trades: list[Trade] = []
    m15 = bundle.m15
    for sig in signals:
        try:
            bar_idx = m15.index.get_loc(sig.entry_bar_ts)
        except KeyError:
            continue
        result = execute_trade(
            df=m15,
            bar_start=bar_idx,
            entry=sig.entry,
            sl=sig.sl,
            tp=sig.tp,
            direction=sig.direction,
            max_bars=sig.max_bars,
            slip_base=slip_base,
            slip_range_coef=slip_range_coef,
        )
        if result is None:
            continue
        trades.append(Trade(signal=sig, result=result))

    pnls = [t.result.pnl_per_unit * (
        min(starting_capital * (risk_pct / 100.0) / max(abs(t.signal.entry - t.signal.sl), 1e-9), max_units)
    ) for t in trades]

    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    total_pnl = float(sum(pnls))
    gross_wins = float(sum(p for p in pnls if p > 0))
    gross_losses = float(abs(sum(p for p in pnls if p <= 0)))
    pf = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    by_year = _yearly_stats(trades, starting_capital, risk_pct, max_units)
    max_dd_yearly = max((y["dd_pct"] for y in by_year.values()), default=0.0)

    return RunResult(
        symbol=bundle.symbol,
        config_label=config_label,
        trades=trades,
        total_signals=len(signals),
        total_trades=len(trades),
        wins=wins,
        losses=losses,
        win_rate=wins / len(trades) if trades else 0.0,
        total_pnl=round(total_pnl, 2),
        profit_factor=round(pf, 3),
        max_dd_pct_yearly_worst=round(max_dd_yearly, 2),
        by_year=by_year,
    )


def print_report(name: str, result: RunResult) -> None:
    print()
    print("=" * 72)
    print(f"  {name}")
    print("=" * 72)
    print(f"  Symbol             : {result.symbol}")
    if result.config_label:
        print(f"  Config             : {result.config_label}")
    print(f"  Signals emitted    : {result.total_signals:>10,}")
    print(f"  Trades filled      : {result.total_trades:>10,}")
    print(f"  Wins / Losses      : {result.wins:>10,} / {result.losses:,}")
    print(f"  Win rate           : {result.win_rate * 100:>10.2f} %")
    print(f"  Profit factor      : {result.profit_factor:>10.3f}")
    print(f"  Total P&L          : ${result.total_pnl:>10,.2f}")
    print(f"  Max DD (yearly)    : {result.max_dd_pct_yearly_worst:>10.2f} %")
    print()
    print(f"  {'Year':<6} {'Trades':<8} {'Wins':<6} {'WR%':<8} {'P&L':>12} {'DD%':>8}")
    for y in sorted(result.by_year.keys()):
        s = result.by_year[y]
        wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0.0
        print(f"  {y:<6} {s['trades']:<8} {s['wins']:<6} {wr:<8.1f} ${s['pnl']:>10,.2f} {s['dd_pct']:>8.2f}")
    print()
