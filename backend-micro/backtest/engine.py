"""Micro backtest engine — Micro Alpha-Sweep + Mean-Rev + Cross-Market on XAU_USD."""
import numpy as np
import pandas as pd
import time
from datetime import timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.backtest.engine import (
    _get_cached_data, BacktestTrade, BacktestResult, Signal,
)
from backend.strategies import micro_alpha_sweep, mean_rev, cross_market
from backend.strategies.dd_protection import DDState, should_skip_signal, get_risk_multiplier, update_after_trade
from backend.execution.fill_model import execute_trade
from backend.execution.limit_price import compute_limit_price
from config import YEARLY_CAPITAL, RISK_PCT, MAX_UNITS, STRATEGY_RISK, MICRO_ALPHA_SWEEP


def run_backtest(
    strategies: list[str] = None,
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
    disable_market_close: bool | None = None,
    entry_mode: str | None = None,
    limit_offset_pct=None,
    limit_ttl_bars: int | None = None,
    limit_fill_strict: bool | None = None,
    bias_mode: str | None = None,
) -> BacktestResult:
    """Run Micro portfolio backtest (Micro Alpha-Sweep + Mean-Rev + Cross-Market).

    bias_mode: Filter #28 — None/'production' (default, compute daily_bias) or
      'neutral' (force NeutralBiasDict — every day treated as 'neutral'). See
      backend/backtest/neutral_bias.py.

    be_trigger_pct: BE trigger fraction override. None (default) = read from
      MICRO_ALPHA_SWEEP config (post-Filter-#5: 0.35).
    trail_after_be_pct: post-BE trail fraction override. None = read from config.
    partial_tp_at_pct / partial_tp_size: Filter #7 overrides. None = read from
      config (.get with default 0.0 = legacy single-leg).
    partial_arms_be: Filter #7 Variant B override. None = read from config.
    entry_mode/limit_offset_pct/limit_ttl_bars/limit_fill_strict: Filter #27.
      See backend/backtest/engine.py for full semantics.
    """
    if be_trigger_pct is None:
        be_trigger_pct = MICRO_ALPHA_SWEEP["be_trigger_pct"]
    if trail_after_be_pct is None:
        trail_after_be_pct = MICRO_ALPHA_SWEEP.get("trail_after_be_pct", 0.0)
    if partial_tp_at_pct is None:
        partial_tp_at_pct = MICRO_ALPHA_SWEEP.get("partial_tp_at_pct", 0.0)
    if partial_tp_size is None:
        partial_tp_size = MICRO_ALPHA_SWEEP.get("partial_tp_size", 0.0)
    if partial_arms_be is None:
        partial_arms_be = MICRO_ALPHA_SWEEP.get("partial_arms_be", False)
    if disable_market_close is None:
        disable_market_close = MICRO_ALPHA_SWEEP.get("disable_market_close", False)
    if entry_mode is None:
        entry_mode = MICRO_ALPHA_SWEEP.get("entry_mode", "market")
    if limit_offset_pct is None:
        limit_offset_pct = MICRO_ALPHA_SWEEP.get("limit_offset_pct", 0.0)
    if limit_ttl_bars is None:
        limit_ttl_bars = MICRO_ALPHA_SWEEP.get("limit_ttl_bars", 0)
    if limit_fill_strict is None:
        limit_fill_strict = MICRO_ALPHA_SWEEP.get("limit_fill_strict", False)
    if strategies is None:
        strategies = ["micro_alpha_sweep", "mean_rev", "cross_market"]
    # Frontend sends "alpha_sweep" — map to micro variant
    if "alpha_sweep" in strategies:
        strategies = [s if s != "alpha_sweep" else "micro_alpha_sweep" for s in strategies]


    np.random.seed(seed)

    data = _get_cached_data()
    gold_d = data["gold_d"]
    gold_h1 = data["gold_h1"]
    gold_m3 = data["gold_m3"]

    # Pre-filter data to date range + 1 month buffer (saves memory + time)
    filter_start = pd.Timestamp(start_date, tz="UTC") - pd.Timedelta(days=60)
    filter_end = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=30)
    gold_h1 = gold_h1[(gold_h1.index >= filter_start) & (gold_h1.index <= filter_end)]
    gold_m3 = gold_m3[(gold_m3.index >= filter_start) & (gold_m3.index <= filter_end)]

    # Daily bias + 50MA (same as Gold Macro)
    # Filter #28: bias_mode='neutral' → NeutralBiasDict; default = compute as before.
    from backend.backtest.neutral_bias import NeutralBiasDict, resolve_bias_mode
    _resolved_bias_mode = resolve_bias_mode(bias_mode)
    if _resolved_bias_mode == "neutral":
        daily_bias = NeutralBiasDict()
    else:
        daily_bias = {}
    gold_50ma_vals = pd.Series(gold_d["mid_close"].values).rolling(50, min_periods=50).mean().values
    gold_50ma_dict = {}
    gold_close_dict = {}

    for i in range(1, len(gold_d)):
        # OANDA dailyAlignment=21: bar at T 21:00 represents (T → T+1) session,
        # so trade-date = bar.date() + 1day; oil_d[i-1] = true yesterday's bar. See parity audit
        # 2026-06-12 (drift bug #6).
        d = (gold_d.index[i] + pd.Timedelta(days=1)).date()
        prev_range = gold_d["mid_high"].iat[i - 1] - gold_d["mid_low"].iat[i - 1]
        if prev_range > 0:
            # Combined V1+V2: EITHER body% OR close-position triggers directional
            body_pct = abs(gold_d["mid_close"].iat[i - 1] - gold_d["mid_open"].iat[i - 1]) / prev_range
            v1_bias = "neutral"
            if body_pct >= 0.4:
                v1_bias = "bullish" if gold_d["mid_close"].iat[i - 1] > gold_d["mid_open"].iat[i - 1] else "bearish"
            close_position = (gold_d["mid_close"].iat[i - 1] - gold_d["mid_low"].iat[i - 1]) / prev_range
            v2_bias = "neutral"
            if close_position >= 0.8:
                v2_bias = "bullish"
            elif close_position <= 0.2:
                v2_bias = "bearish"
            if v1_bias == "bearish" or v2_bias == "bearish":
                daily_bias[d] = "bearish"
            elif v1_bias == "bullish" or v2_bias == "bullish":
                daily_bias[d] = "bullish"
            else:
                daily_bias[d] = "neutral"
        else:
            daily_bias[d] = "neutral"
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
        all_signals.extend(micro_alpha_sweep.generate_signals(
            gold_h1, gold_m3, daily_bias,
            disable_market_close=disable_market_close,
        ))

    all_signals.sort(key=lambda x: x.date)

    # Filter by date range
    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC")
    all_signals = [s for s in all_signals if start_ts <= s.date <= end_ts]

    # DD protection config (matches live)
    DAILY_MAX_LOSS = 400
    HALF_AFTER_CONSECUTIVE = 3
    COOLDOWN_SECONDS = 300  # 5-minute cooldown between signals (matches live)

    # Execute with DD protection + fresh capital each year
    np.random.seed(seed)
    state = DDState()
    trades: list[BacktestTrade] = []
    current_year = None
    current_date = None
    daily_pnl = 0.0
    last_signal_time = None  # For cooldown tracking
    position_exit_time = None  # One-at-a-time: when current position exits (C9 fix)
    # Cap rework Jun 18: count FILLED micro_alpha_sweep trades per day.
    day_filled_trades = 0
    from backend.strategies.micro_alpha_sweep import MICRO_CONFIG as _micro_cfg_for_cap
    max_per_day = _micro_cfg_for_cap.get("max_trades_per_day", 3)
    # Filter #27 accumulators (micro_alpha_sweep scope only)
    _filter27_missed_local = 0
    _filter27_wwl_local = 0
    _filter27_total_local = 0
    _filter27_filled_local = 0

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
            daily_pnl = 0.0
            current_date = None
            day_filled_trades = 0

        # Daily reset
        if trade_date != current_date:
            daily_pnl = 0.0
            day_filled_trades = 0
            current_date = trade_date

        if signal.strategy == "micro_alpha_sweep" and day_filled_trades >= max_per_day:
            continue

        # 5-minute cooldown between signals (same as live — prevents same-scan re-entry)
        if last_signal_time and (signal.date - last_signal_time).total_seconds() < COOLDOWN_SECONDS:
            continue

        # One-at-a-time: skip if previous trade hasn't exited yet (matches live)
        if position_exit_time and signal.date < position_exit_time:
            continue

        # Daily max loss circuit breaker (same as live)
        if daily_pnl <= -DAILY_MAX_LOSS:
            continue

        if state.equity < 100:
            continue

        # DD filters
        gp = gold_close_dict.get(trade_date, 0)
        gma = gold_50ma_dict.get(trade_date, 0)
        if should_skip_signal(signal.strategy, signal.direction, gp, gma, state):
            continue

        # Position sizing (matches live — get_risk_multiplier already halves at >= 3 losses)
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
        # Filter #7 (partial TP) — only on alpha-sweep variant
        if signal.strategy == "micro_alpha_sweep":
            ptp_at, ptp_sz, p_arms = partial_tp_at_pct, partial_tp_size, partial_arms_be
        else:
            ptp_at, ptp_sz, p_arms = 0.0, 0.0, False

        # Filter #27 — compute limit_price per variant (only on micro_alpha_sweep).
        # Uses the shared helper for live↔BT parity. See backend/execution/limit_price.py.
        use_limit = (entry_mode == "limit" and signal.strategy == "micro_alpha_sweep" and limit_ttl_bars > 0)
        limit_price = None
        if use_limit:
            limit_price = compute_limit_price(
                direction=signal.direction,
                signal_entry=signal.entry,
                signal_risk=signal.risk,
                engulf_close_ask=df["ask_close"].iat[bar_idx],
                engulf_close_bid=df["bid_close"].iat[bar_idx],
                limit_offset_pct=limit_offset_pct,
            )

        # Filter #27: count post-gates as a signal that reached execute_trade
        if signal.strategy == "micro_alpha_sweep":
            _filter27_total_local += 1

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
            be_trigger_pct=be_trigger_pct,
            trail_after_be_pct=trail_after_be_pct,
            partial_tp_at_pct=ptp_at,
            partial_tp_size=ptp_sz,
            partial_arms_be=p_arms,
            entry_mode="limit" if use_limit else "market",
            limit_price=limit_price,
            limit_ttl_bars=limit_ttl_bars if use_limit else 0,
            limit_fill_strict=limit_fill_strict if use_limit else False,
        )

        if result is None:
            continue

        # Filter #27: missed limit order — count, do NOT advance cooldown/position_exit_time
        if not result.filled:
            _filter27_missed_local += 1
            if result.would_have_won:
                _filter27_wwl_local += 1
            continue

        pnl_dollar = result.pnl_per_unit * units
        update_after_trade(state, pnl_dollar)
        daily_pnl += pnl_dollar
        last_signal_time = signal.date  # Update cooldown tracker

        # Filter #27: count filled micro_alpha_sweep trades (denominator-pair)
        if signal.strategy == "micro_alpha_sweep":
            _filter27_filled_local += 1
            day_filled_trades += 1  # Cap rework Jun 18

        # Track when this position exits (for one-at-a-time rule)
        bar_seconds = 180 if signal.timeframe == "M3" else 86400  # 3min or 1day
        position_exit_time = signal.date + timedelta(seconds=result.bars_held * bar_seconds)

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

    # Filter #27 stats — micro_alpha_sweep-scoped
    result_obj.missed_signals = _filter27_missed_local
    result_obj.would_have_won_count = _filter27_wwl_local
    result_obj.total_signals = _filter27_total_local
    result_obj.filled_signals = _filter27_filled_local

    return result_obj
