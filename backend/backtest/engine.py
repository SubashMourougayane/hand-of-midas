"""
Backtest engine — orchestrates signal generation, fill model execution, and DD protection.
Mirrors generate_portfolio_dashboard.py execution loop (lines 188-271).
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
import time

from backend.data.cache import load_candles, load_inter_market
from backend.strategies.base import Signal
from backend.strategies import alpha_sweep, mean_rev, cross_market
from backend.strategies.dd_protection import DDState, should_skip_signal, get_risk_multiplier, update_after_trade
from backend.execution.fill_model import execute_trade, TradeResult
from backend.config import YEARLY_CAPITAL, RISK_PCT, MAX_UNITS, STRATEGY_RISK

# Module-level data cache — loaded once, reused across requests
_DATA_CACHE = {}


def _get_cached_data():
    """Load data once and cache in memory."""
    if not _DATA_CACHE:
        t0 = time.time()
        _DATA_CACHE["gold_d"] = load_candles("XAU_USD_D.csv")
        _DATA_CACHE["gold_h1"] = load_candles("XAU_USD_H1.csv")
        _DATA_CACHE["gold_m3"] = load_candles("XAU_USD_M3.csv")
        _DATA_CACHE["eur"] = load_inter_market("EUR_USD")
        _DATA_CACHE["us10y"] = load_inter_market("USB10Y_USD")
        _DATA_CACHE["spx"] = load_inter_market("SPX500_USD")
        _DATA_CACHE["silver"] = load_inter_market("XAG_USD")
        _DATA_CACHE["oil"] = load_inter_market("BCO_USD")
        _DATA_CACHE["us2y"] = load_inter_market("USB02Y_USD")
        print(f"  Data loaded in {time.time()-t0:.1f}s ({len(_DATA_CACHE['gold_m3'])} M3 bars)")
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
    strategies: list[str] = None,
    start_date: str = "2006-01-01",
    end_date: str = "2026-12-31",
    capital: float = YEARLY_CAPITAL,
    risk_pct: float = RISK_PCT,
    seed: int = 42,
    be_trigger_pct: float = 0.5,
    trail_after_be_pct: float = 0.0,
    partial_tp_at_pct: float | None = None,
    partial_tp_size: float | None = None,
    partial_arms_be: bool | None = None,
    bias_source: str = "prior_day",  # Filter #25 sweep: prior_day | asia | pre_session | lookahead_today
) -> BacktestResult:
    """Run full portfolio backtest.

    be_trigger_pct: BE trigger fraction. Default 0.5 (production), Filter #5 tests 0.35.
    trail_after_be_pct: post-BE trail fraction. 0.0 = legacy. Filter #6 tests 0.5.
    partial_tp_at_pct / partial_tp_size: Filter #7 overrides (None = config default).
    partial_arms_be: Filter #7 Variant B (None = config default).
    """
    from backend.config import ALPHA_SWEEP
    if partial_tp_at_pct is None:
        partial_tp_at_pct = ALPHA_SWEEP.get("partial_tp_at_pct", 0.0)
    if partial_tp_size is None:
        partial_tp_size = ALPHA_SWEEP.get("partial_tp_size", 0.0)
    if partial_arms_be is None:
        partial_arms_be = ALPHA_SWEEP.get("partial_arms_be", False)
    if strategies is None:
        strategies = ["alpha_sweep", "mean_rev", "cross_market"]

    np.random.seed(seed)

    # Load data (cached after first call)
    data = _get_cached_data()
    gold_d = data["gold_d"]
    gold_h1 = data["gold_h1"]
    gold_m3 = data["gold_m3"]

    # Daily bias + 50MA
    # Variant C bias: strong body = directional, weak body (< 40% of range) = neutral (allow both)
    daily_bias = {}
    gold_50ma_vals = pd.Series(gold_d["mid_close"].values).rolling(50, min_periods=50).mean().values
    gold_50ma_dict = {}
    gold_close_dict = {}

    # Filter #25 sweep: pre-compute partial-day OHLC from H1 for asia/pre_session variants.
    # H1 timestamps in OANDA are at the *start* of the hour (xx:00). With dailyAlignment=21,
    # the trade-day session "T+1" runs from `T 21:00` to `(T+1) 21:00`. Asia covers
    # `(T+1) 00:00 → (T+1) 08:00`. Pre-session covers `T 21:00 → (T+1) 08:00` (full overnight).
    asia_ohlc: dict = {}        # keyed by trade_date
    pre_session_ohlc: dict = {} # keyed by trade_date
    if bias_source in ("asia", "pre_session"):
        h1 = gold_h1
        h1_idx = h1.index
        # Group H1 bars by trade_date_assigned. trade_date_assigned for an H1 bar at hour H of
        # calendar date C: if H >= 21, it belongs to trade_date C+1; else trade_date C.
        cal_dates = h1_idx.normalize()
        hours = h1_idx.hour
        # trade_date for each row
        td = cal_dates + pd.to_timedelta((hours >= 21).astype(int), unit="D")
        td_dates = td.date  # numpy array of date objects
        # Asia mask: hour in 0..7 of trade-date (so cal_date == trade-date AND hour < 8)
        asia_mask = (cal_dates.date == td_dates) & (hours < 8)
        # Pre-session mask: from prev-cal-date 21:00 to trade-date 08:00 → all rows where trade_date assignment != neutral
        # Simpler: pre_session = prev-cal-date hour>=21 OR trade-date hour<8
        pre_mask = ((hours >= 21) | (hours < 8))

        # Build dict: trade_date -> (open, high, low, close)
        from collections import defaultdict
        def _build(mask_arr):
            buckets = defaultdict(list)
            for j in range(len(h1_idx)):
                if not mask_arr[j]:
                    continue
                buckets[td_dates[j]].append(j)
            out = {}
            for d_, idxs in buckets.items():
                if not idxs:
                    continue
                ohlc_open = (h1["bid_open"].iat[idxs[0]] + h1["ask_open"].iat[idxs[0]]) / 2
                ohlc_close = (h1["bid_close"].iat[idxs[-1]] + h1["ask_close"].iat[idxs[-1]]) / 2
                # high/low from the slice
                highs = [(h1["bid_high"].iat[k] + h1["ask_high"].iat[k]) / 2 for k in idxs]
                lows = [(h1["bid_low"].iat[k] + h1["ask_low"].iat[k]) / 2 for k in idxs]
                out[d_] = (ohlc_open, max(highs), min(lows), ohlc_close)
            return out

        if bias_source == "asia":
            asia_ohlc = _build(asia_mask)
        else:
            pre_session_ohlc = _build(pre_mask)

    def _bias_from_ohlc(o, h, l, c):
        rng = h - l
        if rng <= 0:
            return "neutral"
        body_pct = abs(c - o) / rng
        v1 = "neutral"
        if body_pct >= 0.4:
            v1 = "bullish" if c > o else "bearish"
        cp = (c - l) / rng
        v2 = "neutral"
        if cp >= 0.8:
            v2 = "bullish"
        elif cp <= 0.2:
            v2 = "bearish"
        if v1 == "bearish" or v2 == "bearish":
            return "bearish"
        if v1 == "bullish" or v2 == "bullish":
            return "bullish"
        return "neutral"

    for i in range(1, len(gold_d)):
        # OANDA daily bars use dailyAlignment=21 convention: a bar with timestamp T 21:00
        # represents the trading session T 21:00 → (T+1) 21:00, so .date() of the timestamp
        # is one day BEFORE the session it represents. The strategy looks up daily_bias[trade_date]
        # expecting "yesterday's session bias." Therefore: trade_date = bar_index[i].date() + 1day,
        # using oil_d[i-1] (which represents (trade_date - 1) session = TRUE yesterday).
        d = (gold_d.index[i] + pd.Timedelta(days=1)).date()

        if bias_source == "prior_day":
            o = gold_d["mid_open"].iat[i - 1]
            h = gold_d["mid_high"].iat[i - 1]
            l = gold_d["mid_low"].iat[i - 1]
            c = gold_d["mid_close"].iat[i - 1]
            daily_bias[d] = _bias_from_ohlc(o, h, l, c)
        elif bias_source == "lookahead_today":
            o = gold_d["mid_open"].iat[i]
            h = gold_d["mid_high"].iat[i]
            l = gold_d["mid_low"].iat[i]
            c = gold_d["mid_close"].iat[i]
            daily_bias[d] = _bias_from_ohlc(o, h, l, c)
        elif bias_source == "asia":
            ohlc = asia_ohlc.get(d)
            daily_bias[d] = _bias_from_ohlc(*ohlc) if ohlc else "neutral"
        elif bias_source == "pre_session":
            ohlc = pre_session_ohlc.get(d)
            daily_bias[d] = _bias_from_ohlc(*ohlc) if ohlc else "neutral"
        else:
            raise ValueError(f"Unknown bias_source: {bias_source}")

        if not np.isnan(gold_50ma_vals[i]):
            gold_50ma_dict[d] = gold_50ma_vals[i]
        gold_close_dict[d] = gold_d["mid_close"].iat[i]

    # Generate all signals
    all_signals: list[Signal] = []

    if "cross_market" in strategies:
        np.random.seed(seed)
        all_signals.extend(cross_market.generate_signals(
            gold_d, data["eur"], data["us10y"], data["spx"], data["silver"], data["oil"], data["us2y"]
        ))

    if "mean_rev" in strategies:
        np.random.seed(seed)
        all_signals.extend(mean_rev.generate_signals(gold_d))

    if "alpha_sweep" in strategies:
        np.random.seed(seed)
        all_signals.extend(alpha_sweep.generate_signals(gold_h1, gold_m3, daily_bias))

    all_signals.sort(key=lambda x: x.date)

    # Filter by date range
    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC")
    all_signals = [s for s in all_signals if start_ts <= s.date <= end_ts]

    # Execute with DD protection + fresh capital each year
    COOLDOWN_SECONDS = 300  # 5-min cooldown between signals (matches live)

    np.random.seed(seed)
    state = DDState()
    trades: list[BacktestTrade] = []
    current_year = None
    last_signal_time = None

    for signal in all_signals:
        trade_date = signal.date.date() if hasattr(signal.date, "date") else signal.date
        trade_year = trade_date.year

        # Fresh capital each year (uses the capital param, not hardcoded)
        if trade_year != current_year:
            if current_year is not None:
                pass  # year ended
            state.equity = capital
            state.peak_equity = capital
            state.consecutive_losses = 0
            state.pause_counter = 0
            state.equity_history = []
            state.current_year = trade_year
            current_year = trade_year

        if state.equity < 100:
            continue

        # 5-min cooldown between signals (matches live)
        if last_signal_time and (signal.date - last_signal_time).total_seconds() < COOLDOWN_SECONDS:
            continue

        # DD filters
        gp = gold_close_dict.get(trade_date, 0)
        gma = gold_50ma_dict.get(trade_date, 0)
        if should_skip_signal(signal.strategy, signal.direction, gp, gma, state):
            continue

        # Position sizing — tiered by strategy
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

        # Handle V7 TP (condition-based, use 3x risk as proxy)
        tp = signal.tp
        if signal.strategy == "mean_rev" and tp == 0:
            tp = signal.entry + signal.risk * 3

        # Filter #7 — partial TP only on alpha-sweep
        if signal.strategy == "alpha_sweep":
            ptp_at, ptp_sz, p_arms = partial_tp_at_pct, partial_tp_size, partial_arms_be
        else:
            ptp_at, ptp_sz, p_arms = 0.0, 0.0, False

        result = execute_trade(
            df=df,
            bar_start=bar_idx,
            entry=signal.entry,
            sl=signal.sl,
            tp=tp,
            direction=signal.direction,
            max_bars=signal.max_bars,
            strategy=signal.strategy,
            use_break_even=(signal.strategy == "alpha_sweep"),
            be_trigger_pct=be_trigger_pct,
            trail_after_be_pct=trail_after_be_pct,
            partial_tp_at_pct=ptp_at,
            partial_tp_size=ptp_sz,
            partial_arms_be=p_arms,
        )

        if result is None:
            continue

        pnl_dollar = result.pnl_per_unit * units
        update_after_trade(state, pnl_dollar)
        last_signal_time = signal.date

        # Hold time string
        if signal.strategy == "alpha_sweep":
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

        # Max drawdown (per-year, since capital resets each year)
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
