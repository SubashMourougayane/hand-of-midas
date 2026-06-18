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
from backend.execution.limit_price import compute_limit_price
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
    # Filter #27 — limit-order entry stats. would_have_won_count is INFORMATIONAL
    # LOOKAHEAD; do not use it to rank variants in ship decisions.
    # All counters scoped to alpha_sweep strategy (mean_rev + cross_market are
    # daily-bar strategies, limit-order logic doesn't apply to them).
    missed_signals: int = 0
    would_have_won_count: int = 0
    total_signals: int = 0   # alpha_sweep signals reaching execute_trade (filled + missed)
    filled_signals: int = 0  # alpha_sweep signals that produced a trade (= total_signals - missed_signals)


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
    entry_mode: str | None = None,
    limit_offset_pct: float | None = None,
    limit_ttl_bars: int | None = None,
    limit_fill_strict: bool | None = None,
    bias_mode: str | None = None,
) -> BacktestResult:
    """Run full portfolio backtest.

    be_trigger_pct: BE trigger fraction. Default 0.5 (production), Filter #5 tests 0.35.
    trail_after_be_pct: post-BE trail fraction. 0.0 = legacy. Filter #6 tests 0.5.
    partial_tp_at_pct / partial_tp_size: Filter #7 overrides (None = config default).
    partial_arms_be: Filter #7 Variant B (None = config default).
    bias_mode: Filter #28 — None/'production' (default, compute daily_bias from
      previous-day candle) or 'neutral' (force NeutralBiasDict — every day
      treated as 'neutral', bias filter goes silent). See backend/backtest/
      neutral_bias.py for rationale + Path A research.
    entry_mode: Filter #27. None/"market" (default) = legacy market-entry baseline.
      "limit" = simulate limit orders at limit_price for limit_ttl_bars M3 bars.
    limit_offset_pct: Filter #27. Used only when entry_mode="limit".
      0.0 = level A (signal.entry verbatim, includes baseline slippage offset).
      "engulf_close" sentinel = level B (engulfing bar's bid/ask close, no slip).
      -0.10 / -0.20 / -0.30 = level C (pullback into structure; sign flipped for SHORT).
    limit_ttl_bars: Filter #27. 1 / 2 / 5 = 3min / 6min / 15min.
    limit_fill_strict: Filter #27. True = require touch+close beyond limit
      (sustained, pessimistic). False = wick touch only (optimistic).
    """
    from backend.config import ALPHA_SWEEP
    if partial_tp_at_pct is None:
        partial_tp_at_pct = ALPHA_SWEEP.get("partial_tp_at_pct", 0.0)
    if partial_tp_size is None:
        partial_tp_size = ALPHA_SWEEP.get("partial_tp_size", 0.0)
    if partial_arms_be is None:
        partial_arms_be = ALPHA_SWEEP.get("partial_arms_be", False)
    if entry_mode is None:
        entry_mode = ALPHA_SWEEP.get("entry_mode", "market")
    if limit_offset_pct is None:
        limit_offset_pct = ALPHA_SWEEP.get("limit_offset_pct", 0.0)
    if limit_ttl_bars is None:
        limit_ttl_bars = ALPHA_SWEEP.get("limit_ttl_bars", 0)
    if limit_fill_strict is None:
        limit_fill_strict = ALPHA_SWEEP.get("limit_fill_strict", False)
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
    # Filter #28: bias_mode='neutral' replaces daily_bias with a NeutralBiasDict so
    # every date returns "neutral" — bias filter goes silent. Path A research
    # (2026-06-18, single-seed 21yr): +$233k delta on Gold Macro alone.
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
        # OANDA daily bars use dailyAlignment=21 convention: a bar with timestamp T 21:00
        # represents the trading session T 21:00 → (T+1) 21:00, so .date() of the timestamp
        # is one day BEFORE the session it represents. The strategy looks up daily_bias[trade_date]
        # expecting "yesterday's session bias." Therefore: trade_date = bar_index[i].date() + 1day,
        # using oil_d[i-1] (which represents (trade_date - 1) session = TRUE yesterday).
        d = (gold_d.index[i] + pd.Timedelta(days=1)).date()
        prev_range = gold_d["mid_high"].iat[i - 1] - gold_d["mid_low"].iat[i - 1]
        if prev_range > 0:
            # Combined V1+V2 bias: EITHER body% OR close-position triggers directional
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
    current_date = None
    last_signal_time = None
    # Cap rework Jun 18: count FILLED alpha_sweep trades per day. Mirrors
    # live behavior where LIMIT_TTL_EXPIRED doesn't count toward the cap.
    day_filled_trades = 0
    from backend.config import ALPHA_SWEEP as _alpha_cfg_for_cap
    max_per_day = _alpha_cfg_for_cap.get("max_trades_per_day", 3)
    # Filter #27 accumulators (alpha_sweep scope only)
    _filter27_missed_local = 0
    _filter27_wwl_local = 0
    _filter27_total_local = 0
    _filter27_filled_local = 0

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
            current_date = None
            day_filled_trades = 0

        if trade_date != current_date:
            day_filled_trades = 0
            current_date = trade_date

        # Cap rework: scope to alpha_sweep only — other strategies (mean_rev,
        # cross_market) aren't sweep-based and have their own cadence.
        if signal.strategy == "alpha_sweep" and day_filled_trades >= max_per_day:
            continue

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

        # Filter #27 — compute limit_price per variant (only for alpha_sweep
        # since mean_rev/cross_market are daily-bar strategies, not M3-engulfing).
        # Uses the shared compute_limit_price helper so live scheduler computes
        # IDENTICAL prices for the same inputs. See backend/execution/limit_price.py.
        use_limit = (entry_mode == "limit" and signal.strategy == "alpha_sweep" and limit_ttl_bars > 0)
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

        # Filter #27: count this as a signal that reached execute_trade
        # (post-gates). Used as denominator for fill_rate.
        if signal.strategy == "alpha_sweep":
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
            use_break_even=(signal.strategy == "alpha_sweep"),
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

        # Filter #27: missed limit order — count it, do NOT advance cooldown
        # or position_exit_time, do NOT append to trades list.
        if not result.filled:
            result_missed_count = 1
            result_would_have_won = 1 if result.would_have_won else 0
            # Stash on the local accumulator dicts below at end of loop.
            _filter27_missed_local += result_missed_count
            _filter27_wwl_local += result_would_have_won
            continue

        pnl_dollar = result.pnl_per_unit * units
        update_after_trade(state, pnl_dollar)
        last_signal_time = signal.date

        # Filter #27: count filled alpha_sweep trades (denominator-pair to total_signals)
        if signal.strategy == "alpha_sweep":
            _filter27_filled_local += 1
            day_filled_trades += 1  # Cap rework Jun 18

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

    # Filter #27 stats — populated regardless of trades count.
    # All counters are alpha_sweep-scoped; mean_rev / cross_market trades
    # are NOT included so fill_rate = filled_signals / total_signals is correct.
    result_obj.missed_signals = _filter27_missed_local
    result_obj.would_have_won_count = _filter27_wwl_local
    result_obj.total_signals = _filter27_total_local
    result_obj.filled_signals = _filter27_filled_local

    return result_obj
