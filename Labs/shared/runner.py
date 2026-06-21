"""Labs strategy runner.

Strategies are pure: they take (D1, H1, M3) DataFrames + a config dict
and return a list of Signal objects. The runner walks each signal through
the canonical fill model and aggregates stats.

Strategies MUST NOT have side effects, do I/O, or maintain state across
runs. The runner is the single point of state.

Live-reproducibility contract: a strategy's signal at time T may only
read data with index <= T. The runner enforces this by feeding the
strategy the full data slice but auditing afterwards (see safeguards.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

import pandas as pd

from Labs.shared.fill_model import TradeResult, execute_trade


Direction = Literal["long", "short"]


@dataclass(frozen=True)
class Signal:
    """A strategy's intent to trade. Pure data. No side effects.

    `entry_bar_ts` = the M3 bar AT WHICH the trade enters. The fill model
    walks bars from entry_bar_idx+1 onwards looking for SL/TP/max-hold.
    """
    entry_bar_ts: pd.Timestamp
    direction: Direction
    entry: float
    sl: float
    tp: float
    max_bars: int
    metadata: dict = field(default_factory=dict)


@dataclass
class Trade:
    """A filled trade with its outcome."""
    signal: Signal
    result: TradeResult


@dataclass
class RunResult:
    """Output of running one strategy on one dataset.

    Yearly capital reset is the SAME convention as production
    (yearly $5K starting capital, no compounding across years).
    """
    trades: list[Trade]
    total_signals: int   # signals strategy emitted (filled + dropped due to data end)
    total_trades: int    # signals that filled
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    max_dd_pct_yearly_worst: float
    by_year: dict[int, dict]  # {year: {trades, wins, pnl, dd_pct, ending_equity}}


def _yearly_stats(trades: list[Trade], starting_capital: float, risk_pct: float, max_units: float) -> dict[int, dict]:
    """Yearly P&L with the same per-year reset convention as production."""
    by_year: dict[int, dict] = {}
    if not trades:
        return by_year

    # Group trades by entry year
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

        # Risk-based sizing — same shape as production
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


def run_strategy(
    strategy_fn: Callable,
    data: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    *,
    starting_capital: float = 5_000.0,
    risk_pct: float = 4.0,
    max_units: float = 5_000.0,
) -> RunResult:
    """Run one strategy through the canonical BT.

    strategy_fn signature:
        strategy_fn(d1, h1, m3) -> list[Signal]

    The strategy is responsible for ensuring its signals reference only
    data <= entry_bar_ts. The runner does NOT enforce this at signal
    time; the lookahead audit (safeguards.py) verifies it after the fact.
    """
    d1, h1, m3 = data
    signals = strategy_fn(d1, h1, m3)

    trades: list[Trade] = []
    for sig in signals:
        # Locate entry bar index in m3
        try:
            bar_idx = m3.index.get_loc(sig.entry_bar_ts)
        except KeyError:
            continue
        result = execute_trade(
            df=m3,
            bar_start=bar_idx,
            entry=sig.entry,
            sl=sig.sl,
            tp=sig.tp,
            direction=sig.direction,
            max_bars=sig.max_bars,
        )
        if result is None:
            continue  # data ran out
        trades.append(Trade(signal=sig, result=result))

    pnls = [t.result.pnl_per_unit * (
        # apply per-trade sizing for the "total_pnl" reported here
        # (we redo this in _yearly_stats with equity-aware sizing)
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
    """Pretty-print a run's stats. Used by individual strategy runs."""
    print()
    print("=" * 72)
    print(f"  {name}")
    print("=" * 72)
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
