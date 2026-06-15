"""Oil backtest engine — Alpha-Sweep only on BCO_USD."""
import numpy as np
import pandas as pd
import time
from datetime import timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.cache import load_candles
from strategies.alpha_sweep import generate_signals, Signal
from execution.fill_model import execute_trade, TradeResult
from config import YEARLY_CAPITAL, RISK_PCT, MAX_UNITS, STRATEGY_RISK, ALPHA_SWEEP
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
    be_trigger_pct: float | None = None,
    trail_after_be_pct: float | None = None,
    partial_tp_at_pct: float | None = None,
    partial_tp_size: float | None = None,
    partial_arms_be: bool | None = None,
    bias_source: str = "prior_day",  # Filter #25 sweep
) -> BacktestResult:
    """be_trigger_pct: BE trigger fraction. None = read from ALPHA_SWEEP config (post-#5: 0.35).
    trail_after_be_pct: post-BE trail. None = read from config. Filter #6 shipped Oil Macro only (0.50).
    partial_tp_at_pct / partial_tp_size: Filter #7 overrides (None = config default).
    partial_arms_be: Filter #7 Variant B (None = config default).
    """
    if partial_tp_at_pct is None:
        partial_tp_at_pct = ALPHA_SWEEP.get("partial_tp_at_pct", 0.0)
    if partial_tp_size is None:
        partial_tp_size = ALPHA_SWEEP.get("partial_tp_size", 0.0)
    if partial_arms_be is None:
        partial_arms_be = ALPHA_SWEEP.get("partial_arms_be", False)
    if be_trigger_pct is None:
        be_trigger_pct = ALPHA_SWEEP["be_trigger_pct"]
    if trail_after_be_pct is None:
        trail_after_be_pct = ALPHA_SWEEP.get("trail_after_be_pct", 0.0)
    np.random.seed(seed)

    data = _get_cached_data()
    oil_d = data["oil_d"]
    oil_h1 = data["oil_h1"]
    oil_m3 = data["oil_m3"]

    # Daily bias — Combined V1+V2 (matches live scheduler and other 3 systems)
    daily_bias = {}

    # Filter #25 sweep: pre-compute partial-day OHLC from H1 for asia/pre_session variants.
    asia_ohlc: dict = {}
    pre_session_ohlc: dict = {}
    if bias_source in ("asia", "pre_session"):
        h1_idx = oil_h1.index
        cal_dates = h1_idx.normalize()
        hours = h1_idx.hour
        td = cal_dates + pd.to_timedelta((hours >= 21).astype(int), unit="D")
        td_dates = td.date
        from collections import defaultdict
        def _build(mask_arr):
            buckets = defaultdict(list)
            for j in range(len(h1_idx)):
                if not mask_arr[j]: continue
                buckets[td_dates[j]].append(j)
            out = {}
            for d_, idxs in buckets.items():
                if not idxs: continue
                o = (oil_h1["bid_open"].iat[idxs[0]] + oil_h1["ask_open"].iat[idxs[0]]) / 2
                c = (oil_h1["bid_close"].iat[idxs[-1]] + oil_h1["ask_close"].iat[idxs[-1]]) / 2
                highs = [(oil_h1["bid_high"].iat[k] + oil_h1["ask_high"].iat[k]) / 2 for k in idxs]
                lows = [(oil_h1["bid_low"].iat[k] + oil_h1["ask_low"].iat[k]) / 2 for k in idxs]
                out[d_] = (o, max(highs), min(lows), c)
            return out
        if bias_source == "asia":
            asia_mask = (cal_dates.date == td_dates) & (hours < 8)
            asia_ohlc = _build(asia_mask)
        else:
            pre_mask = ((hours >= 21) | (hours < 8))
            pre_session_ohlc = _build(pre_mask)

    def _bias_from_ohlc(o, h, l, c):
        rng = h - l
        if rng <= 0: return "neutral"
        body_pct = abs(c - o) / rng
        v1 = "neutral"
        if body_pct >= 0.4:
            v1 = "bullish" if c > o else "bearish"
        cp = (c - l) / rng
        v2 = "neutral"
        if cp >= 0.8: v2 = "bullish"
        elif cp <= 0.2: v2 = "bearish"
        if v1 == "bearish" or v2 == "bearish": return "bearish"
        if v1 == "bullish" or v2 == "bullish": return "bullish"
        return "neutral"

    for i in range(1, len(oil_d)):
        d = (oil_d.index[i] + pd.Timedelta(days=1)).date()
        if bias_source == "prior_day":
            o = oil_d["mid_open"].iat[i - 1]; h = oil_d["mid_high"].iat[i - 1]
            l = oil_d["mid_low"].iat[i - 1]; c = oil_d["mid_close"].iat[i - 1]
            daily_bias[d] = _bias_from_ohlc(o, h, l, c)
        elif bias_source == "lookahead_today":
            o = oil_d["mid_open"].iat[i]; h = oil_d["mid_high"].iat[i]
            l = oil_d["mid_low"].iat[i]; c = oil_d["mid_close"].iat[i]
            daily_bias[d] = _bias_from_ohlc(o, h, l, c)
        elif bias_source == "asia":
            ohlc = asia_ohlc.get(d)
            daily_bias[d] = _bias_from_ohlc(*ohlc) if ohlc else "neutral"
        elif bias_source == "pre_session":
            ohlc = pre_session_ohlc.get(d)
            daily_bias[d] = _bias_from_ohlc(*ohlc) if ohlc else "neutral"
        else:
            raise ValueError(f"Unknown bias_source: {bias_source}")

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
    pause_counter = 0
    equity_history = []
    trades: list[BacktestTrade] = []
    current_year = None
    position_exit_time = None  # One-at-a-time: when current position exits

    for signal in all_signals:
        trade_date = signal.date.date()
        trade_year = trade_date.year

        if trade_year != current_year:
            equity = capital
            peak_equity = capital
            consecutive_losses = 0
            pause_counter = 0
            equity_history = []
            current_year = trade_year
            position_exit_time = None

        if equity < 100:
            continue

        # One-at-a-time: skip if previous trade hasn't exited yet (matches live)
        if position_exit_time and signal.date < position_exit_time:
            continue

        # DD protection: pause after 5 consecutive losses (skip next 2 signals)
        if pause_counter > 0:
            pause_counter -= 1
            continue

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
            be_trigger_pct=be_trigger_pct,
            trail_after_be_pct=trail_after_be_pct,
            partial_tp_at_pct=partial_tp_at_pct,
            partial_tp_size=partial_tp_size,
            partial_arms_be=partial_arms_be,
        )

        if result is None:
            continue

        pnl_dollar = result.pnl_per_unit * units
        equity += pnl_dollar
        equity = max(equity, 0)

        # Track when this position exits (for one-at-a-time rule)
        position_exit_time = signal.date + timedelta(seconds=result.bars_held * 180)

        if pnl_dollar > 0:
            consecutive_losses = 0
        else:
            consecutive_losses += 1
            if consecutive_losses >= 5:
                pause_counter = 2

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
