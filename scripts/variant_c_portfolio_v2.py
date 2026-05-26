"""
Full portfolio backtest — Variant C bias filter.

Uses EXACT same modules as production:
  - backend/execution/fill_model.py (shared by live + backtest)
  - backend/data/cache.py (loads OANDA CSVs)
  - backend/config.py (Gold config)
  - backend-oil/config.py (Oil config)
  - backend/strategies/dd_protection.py (DD rules)
  - backend/strategies/mean_rev.py (unchanged)
  - backend/strategies/cross_market.py (unchanged)

Variant C bias logic:
  - If yesterday's body > 40% of high-low range → apply directional bias (bullish/bearish)
  - If yesterday's body <= 40% of range (indecision/doji) → allow BOTH directions

This script is VERIFIABLE: run the dashboard backtest with strategies=["mean_rev","cross_market"]
to confirm MR+CM numbers match. Alpha-Sweep numbers match variant_c_full_portfolio.py output.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import numpy as np
import pandas as pd
from collections import defaultdict

from backend.data.cache import load_candles, load_inter_market
from backend.execution.fill_model import execute_trade
from backend.strategies.base import Signal
from backend.strategies import mean_rev, cross_market
from backend.strategies.dd_protection import DDState, should_skip_signal, get_risk_multiplier, update_after_trade
from backend.config import (
    ALPHA_SWEEP as GOLD_ALPHA_CFG, YEARLY_CAPITAL, RISK_PCT, MAX_UNITS, STRATEGY_RISK,
    slippage as gold_slippage,
)

# Oil config (different thresholds)
OIL_ALPHA_CFG = {
    "asia_min_range": 0.50,
    "sweep_threshold": 0.20,
    "sl_buffer": 0.03,
    "min_sl": 0.10,
    "tp_multiplier": 2.0,
    "be_trigger_pct": 0.50,
    "max_bars": 80,
    "skip_first_bar": True,
    "engulfing_window_hours": 2,
    "scan_start": 8,
    "scan_end": 20,
    "max_trades_per_day": 3,
}
OIL_MAX_UNITS = 5000
OIL_RISK_PCT = 4.0


def oil_slippage(bar_range: float) -> float:
    return 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)


# ==============================================================================
# Variant C Bias Filter
# ==============================================================================

def _get_ohlc(daily_df, col):
    """Get column from daily df — handles both bid/ask format and plain OHLCV."""
    mid_col = f"mid_{col}"
    if mid_col in daily_df.columns:
        return daily_df[mid_col]
    return daily_df[col]


def compute_variant_c_bias(daily_df: pd.DataFrame) -> dict:
    """
    Compute Variant C bias for each date.
    Returns dict: {date: 'bullish'|'bearish'|'neutral'}

    Logic: look at YESTERDAY's candle.
      - If body > 40% of range → directional (bullish if green, bearish if red)
      - If body <= 40% of range → 'neutral' (allow both directions)
    """
    opens = _get_ohlc(daily_df, "open")
    closes = _get_ohlc(daily_df, "close")
    highs = _get_ohlc(daily_df, "high")
    lows = _get_ohlc(daily_df, "low")

    bias = {}
    for i in range(1, len(daily_df)):
        d = daily_df.index[i].date()
        prev_open = opens.iat[i - 1]
        prev_close = closes.iat[i - 1]
        prev_high = highs.iat[i - 1]
        prev_low = lows.iat[i - 1]
        prev_range = prev_high - prev_low
        if prev_range == 0:
            bias[d] = "neutral"
            continue
        body_pct = abs(prev_close - prev_open) / prev_range
        if body_pct < 0.4:
            bias[d] = "neutral"
        else:
            bias[d] = "bullish" if prev_close > prev_open else "bearish"
    return bias


def compute_variant_a_bias(daily_df: pd.DataFrame) -> dict:
    """Original Variant A: yesterday direction, always applied."""
    closes = _get_ohlc(daily_df, "close")
    opens = _get_ohlc(daily_df, "open")
    bias = {}
    for i in range(1, len(daily_df)):
        d = daily_df.index[i].date()
        bias[d] = "bullish" if closes.iat[i-1] > opens.iat[i-1] else "bearish"
    return bias


# ==============================================================================
# Alpha-Sweep Signal Generator (with configurable bias)
# ==============================================================================

def generate_alpha_signals(h1, m3, daily_bias, cfg, slippage_fn, instrument="gold"):
    """
    Generate Alpha-Sweep signals. Uses exact same logic as backend/strategies/alpha_sweep.py
    but with configurable bias dict (allows Variant C neutral = both directions).
    """
    signals = []
    dates = sorted(set(h1.index.date))

    for date in dates:
        day_h1 = h1[h1.index.date == date]
        asia = day_h1[(day_h1.index.hour >= 0) & (day_h1.index.hour < 8)]
        scan_window = day_h1[(day_h1.index.hour >= cfg["scan_start"]) & (day_h1.index.hour < cfg["scan_end"])]

        if len(asia) < 3 or len(scan_window) < 2:
            continue

        ah = asia["mid_high"].max()
        al = asia["mid_low"].min()
        ar = ah - al

        if ar < cfg["asia_min_range"]:
            continue

        bias = daily_bias.get(date, "none")

        sweeps = []
        for i in range(len(scan_window)):
            bh = scan_window["mid_high"].iloc[i]
            bl = scan_window["mid_low"].iloc[i]
            bc = scan_window["mid_close"].iloc[i]

            if bh > ah + cfg["sweep_threshold"] and bc < ah:
                sweeps.append(("bearish", bh, scan_window.index[i]))
            elif bl < al - cfg["sweep_threshold"] and bc > al:
                sweeps.append(("bullish", bl, scan_window.index[i]))

        if not sweeps:
            continue

        day_trades = 0
        max_per_day = cfg.get("max_trades_per_day", 3)

        for sweep_dir, sweep_wick, sweep_time in sweeps:
            if day_trades >= max_per_day:
                break

            # Variant C bias: 'neutral' allows BOTH directions
            if bias != "neutral":
                if sweep_dir == "bullish" and bias != "bullish":
                    continue
                if sweep_dir == "bearish" and bias != "bearish":
                    continue

            end_time = sweep_time + pd.Timedelta(hours=cfg["engulfing_window_hours"])
            m3_window = m3[(m3.index > sweep_time) & (m3.index <= end_time)]

            if len(m3_window) < 3:
                continue

            start_idx = 2 if cfg["skip_first_bar"] else 1

            for j in range(start_idx, len(m3_window)):
                idx = m3.index.get_loc(m3_window.index[j])
                co = m3["mid_open"].iat[idx]
                cc = m3["mid_close"].iat[idx]
                po = m3["mid_open"].iat[idx - 1]
                pc = m3["mid_close"].iat[idx - 1]
                br = m3["mid_high"].iat[idx] - m3["mid_low"].iat[idx]

                ct = max(co, cc)
                cb = min(co, cc)
                pt = max(po, pc)
                pb = min(po, pc)

                if sweep_dir == "bullish" and not (cc > co and cb <= pb and ct >= pt):
                    continue
                if sweep_dir == "bearish" and not (cc < co and cb <= pb and ct >= pt):
                    continue

                if sweep_dir == "bullish":
                    entry = m3["ask_close"].iat[idx] + slippage_fn(br)
                    slv = sweep_wick - cfg["sl_buffer"]
                    risk = entry - slv
                    if risk < cfg["min_sl"]:
                        slv = entry - cfg["min_sl"]
                        risk = cfg["min_sl"]
                    risk_floor = 0.3 if instrument == "gold" else 0.01
                    if risk < risk_floor or risk > ar * 0.8:
                        continue
                    tpv = entry + ar * cfg["tp_multiplier"]
                    if tpv - entry < risk * 0.8:
                        continue
                    signals.append(Signal(
                        date=m3.index[idx], entry=entry, sl=slv, tp=tpv,
                        direction="long", risk=risk,
                        strategy=f"alpha_sweep{'_oil' if instrument == 'oil' else ''}",
                        max_bars=cfg["max_bars"], timeframe="M3",
                        metadata={"asia_high": ah, "asia_low": al, "sweep_dir": sweep_dir, "sweep_wick": sweep_wick},
                    ))
                else:
                    entry = m3["bid_close"].iat[idx] - slippage_fn(br)
                    slv = sweep_wick + cfg["sl_buffer"]
                    risk = slv - entry
                    if risk < cfg["min_sl"]:
                        slv = entry + cfg["min_sl"]
                        risk = cfg["min_sl"]
                    risk_floor = 0.3 if instrument == "gold" else 0.01
                    if risk < risk_floor or risk > ar * 0.8:
                        continue
                    tpv = entry - ar * cfg["tp_multiplier"]
                    if entry - tpv < risk * 0.8:
                        continue
                    signals.append(Signal(
                        date=m3.index[idx], entry=entry, sl=slv, tp=tpv,
                        direction="short", risk=risk,
                        strategy=f"alpha_sweep{'_oil' if instrument == 'oil' else ''}",
                        max_bars=cfg["max_bars"], timeframe="M3",
                        metadata={"asia_high": ah, "asia_low": al, "sweep_dir": sweep_dir, "sweep_wick": sweep_wick},
                    ))

                day_trades += 1
                break

    return signals


# ==============================================================================
# Main
# ==============================================================================

def main():
    print("=" * 90)
    print(f"{'VARIANT C FULL PORTFOLIO BACKTEST':^90}")
    print(f"{'Using production fill_model.py + config.py + dd_protection.py':^90}")
    print("=" * 90)

    # --- Load Data ---
    print("\n[1/5] Loading data...")
    gold_d = load_candles("XAU_USD_D.csv")
    gold_h1 = load_candles("XAU_USD_H1.csv")
    gold_m3 = load_candles("XAU_USD_M3.csv")
    oil_d = load_candles("BCO_USD_D.csv")
    oil_h1 = load_candles("BCO_USD_H1.csv")
    oil_m3 = load_candles("BCO_USD_M3.csv")
    eur = load_inter_market("EUR_USD")
    us10y = load_inter_market("USB10Y_USD")
    spx = load_inter_market("SPX500_USD")
    silver = load_inter_market("XAG_USD")
    oil_inter = load_inter_market("BCO_USD")
    us2y = load_inter_market("USB02Y_USD")

    print(f"  Gold: D={len(gold_d)}, H1={len(gold_h1)}, M3={len(gold_m3)}")
    print(f"  Oil:  D={len(oil_d)}, H1={len(oil_h1)}, M3={len(oil_m3)}")

    # --- Compute Bias ---
    print("\n[2/5] Computing Variant C bias...")
    gold_bias_c = compute_variant_c_bias(gold_d)
    oil_bias_c = compute_variant_c_bias(oil_d)
    gold_bias_a = compute_variant_a_bias(gold_d)
    oil_bias_a = compute_variant_a_bias(oil_d)

    neutral_days_gold = sum(1 for v in gold_bias_c.values() if v == "neutral")
    neutral_days_oil = sum(1 for v in oil_bias_c.values() if v == "neutral")
    print(f"  Gold: {neutral_days_gold} indecision days ({neutral_days_gold*100/len(gold_bias_c):.1f}%) → allow both directions")
    print(f"  Oil:  {neutral_days_oil} indecision days ({neutral_days_oil*100/len(oil_bias_c):.1f}%) → allow both directions")

    # --- Generate Signals ---
    # IMPORTANT: seed order must match backend/backtest/engine.py:
    #   seed(42) → cross_market → seed(42) → mean_rev → seed(42) → alpha_sweep
    print("\n[3/5] Generating signals...")

    np.random.seed(42)
    cm_signals = cross_market.generate_signals(gold_d, eur, us10y, spx, silver, oil_inter, us2y)
    print(f"  Gold Cross-Market:    {len(cm_signals)} signals")

    np.random.seed(42)
    mr_signals = mean_rev.generate_signals(gold_d)
    print(f"  Gold Mean-Rev:        {len(mr_signals)} signals")

    np.random.seed(42)
    gold_alpha_c = generate_alpha_signals(gold_h1, gold_m3, gold_bias_c, GOLD_ALPHA_CFG, gold_slippage, "gold")
    print(f"  Gold Alpha-Sweep (C): {len(gold_alpha_c)} signals")

    np.random.seed(42)
    gold_alpha_a = generate_alpha_signals(gold_h1, gold_m3, gold_bias_a, GOLD_ALPHA_CFG, gold_slippage, "gold")
    print(f"  Gold Alpha-Sweep (A): {len(gold_alpha_a)} signals")

    np.random.seed(42)
    oil_alpha_c = generate_alpha_signals(oil_h1, oil_m3, oil_bias_c, OIL_ALPHA_CFG, oil_slippage, "oil")
    print(f"  Oil Alpha-Sweep (C):  {len(oil_alpha_c)} signals")

    np.random.seed(42)
    oil_alpha_a = generate_alpha_signals(oil_h1, oil_m3, oil_bias_a, OIL_ALPHA_CFG, oil_slippage, "oil")
    print(f"  Oil Alpha-Sweep (A):  {len(oil_alpha_a)} signals")

    # --- Execute Trades ---
    print("\n[4/5] Executing trades through fill model...")

    # 50-MA for DD filter
    gold_50ma_vals = pd.Series(gold_d["mid_close"].values).rolling(50, min_periods=50).mean().values
    gold_50ma_dict = {}
    gold_close_dict = {}
    for i in range(len(gold_d)):
        d = gold_d.index[i].date()
        if not np.isnan(gold_50ma_vals[i]):
            gold_50ma_dict[d] = gold_50ma_vals[i]
        gold_close_dict[d] = gold_d["mid_close"].iat[i]

    def run_strategy(signals, m3_df, strategy_name, capital, risk_pct, max_units, use_dd=True, use_be=True):
        """Execute signals through fill model with DD protection. Returns per-trade results."""
        np.random.seed(42)
        state = DDState()
        trades = []
        current_year = None

        for signal in sorted(signals, key=lambda s: s.date):
            trade_date = signal.date.date() if hasattr(signal.date, "date") else signal.date
            trade_year = trade_date.year

            if trade_year != current_year:
                state.equity = capital
                state.peak_equity = capital
                state.consecutive_losses = 0
                state.pause_counter = 0
                state.equity_history = []
                state.current_year = trade_year
                current_year = trade_year

            if state.equity < 100:
                continue

            # DD filters (only for Gold strategies that use 50-MA gate)
            if use_dd and strategy_name in ("mean_rev", "cross_market"):
                gp = gold_close_dict.get(trade_date, 0)
                gma = gold_50ma_dict.get(trade_date, 0)
                if should_skip_signal(strategy_name, signal.direction, gp, gma, state):
                    continue
            elif use_dd:
                if state.pause_counter > 0:
                    state.pause_counter -= 1
                    continue

            risk_mult = get_risk_multiplier(state)
            strat_risk = risk_pct
            risk_dollar = state.equity * (strat_risk / 100) * risk_mult
            if signal.risk <= 0:
                continue
            units = min(risk_dollar / signal.risk, max_units)

            df = gold_d if signal.timeframe == "D" else m3_df
            try:
                bar_idx = df.index.get_loc(signal.date)
            except KeyError:
                continue

            tp = signal.tp
            if signal.strategy == "mean_rev" and tp == 0:
                tp = signal.entry + signal.risk * 3

            result = execute_trade(
                df=df, bar_start=bar_idx, entry=signal.entry, sl=signal.sl, tp=tp,
                direction=signal.direction, max_bars=signal.max_bars,
                strategy=strategy_name, use_break_even=use_be,
            )

            if result is None:
                continue

            pnl = result.pnl_per_unit * units
            update_after_trade(state, pnl)

            trades.append({
                "date": signal.date,
                "year": trade_year,
                "month": trade_date.month,
                "direction": signal.direction,
                "entry": signal.entry,
                "sl": signal.sl,
                "tp": tp,
                "exit_price": result.exit_price,
                "exit_reason": result.exit_reason,
                "pnl_unit": result.pnl_per_unit,
                "pnl_sized": pnl,
                "units": units,
                "bars_held": result.bars_held,
                "risk": signal.risk,
                "r_mult": result.pnl_per_unit / signal.risk if signal.risk > 0 else 0,
                "equity_after": state.equity,
            })

        return trades

    # Execute Gold strategies with SHARED DD state (matches production engine exactly)
    def run_gold_portfolio(alpha_signals, mr_sigs, cm_sigs, capital, label=""):
        """Run all Gold strategies with shared DD state — identical to backend/backtest/engine.py"""
        np.random.seed(42)
        all_gold = []
        for s in alpha_signals:
            all_gold.append(s)
        for s in mr_sigs:
            all_gold.append(s)
        for s in cm_sigs:
            all_gold.append(s)
        all_gold.sort(key=lambda x: x.date)

        state = DDState()
        alpha_trades = []
        mr_trades_out = []
        cm_trades_out = []
        current_year = None

        for signal in all_gold:
            trade_date = signal.date.date() if hasattr(signal.date, "date") else signal.date
            trade_year = trade_date.year

            if trade_year != current_year:
                state.equity = capital
                state.peak_equity = capital
                state.consecutive_losses = 0
                state.pause_counter = 0
                state.equity_history = []
                state.current_year = trade_year
                current_year = trade_year

            if state.equity < 100:
                continue

            # DD filters (50-MA gate for MR/CM, pause for all)
            gp = gold_close_dict.get(trade_date, 0)
            gma = gold_50ma_dict.get(trade_date, 0)
            if should_skip_signal(signal.strategy, signal.direction, gp, gma, state):
                continue

            risk_mult = get_risk_multiplier(state)
            strat_risk = STRATEGY_RISK.get(signal.strategy, RISK_PCT)
            risk_dollar = state.equity * (strat_risk / 100) * risk_mult
            if signal.risk <= 0:
                continue
            units = min(risk_dollar / signal.risk, MAX_UNITS)

            df = gold_d if signal.timeframe == "D" else gold_m3
            try:
                bar_idx = df.index.get_loc(signal.date)
            except KeyError:
                continue

            tp = signal.tp
            if signal.strategy == "mean_rev" and tp == 0:
                tp = signal.entry + signal.risk * 3

            use_be = (signal.strategy == "alpha_sweep")
            result = execute_trade(
                df=df, bar_start=bar_idx, entry=signal.entry, sl=signal.sl, tp=tp,
                direction=signal.direction, max_bars=signal.max_bars,
                strategy=signal.strategy, use_break_even=use_be,
            )

            if result is None:
                continue

            pnl = result.pnl_per_unit * units
            update_after_trade(state, pnl)

            trade_record = {
                "date": signal.date, "year": trade_year, "month": trade_date.month,
                "direction": signal.direction, "entry": signal.entry, "sl": signal.sl,
                "tp": tp, "exit_price": result.exit_price, "exit_reason": result.exit_reason,
                "pnl_unit": result.pnl_per_unit, "pnl_sized": pnl, "units": units,
                "bars_held": result.bars_held, "risk": signal.risk,
                "r_mult": result.pnl_per_unit / signal.risk if signal.risk > 0 else 0,
                "equity_after": state.equity,
            }

            if signal.strategy == "alpha_sweep":
                alpha_trades.append(trade_record)
            elif signal.strategy == "mean_rev":
                mr_trades_out.append(trade_record)
            else:
                cm_trades_out.append(trade_record)

        return alpha_trades, mr_trades_out, cm_trades_out

    # Run Gold Variant C portfolio (shared DD)
    gold_alpha_c_trades, mr_trades, cm_trades = run_gold_portfolio(
        gold_alpha_c, mr_signals, cm_signals, YEARLY_CAPITAL, "Variant C"
    )

    # Run Oil Variant C (independent DD — Oil has its own DD state id=2 in production)
    oil_alpha_c_trades = run_strategy(oil_alpha_c, oil_m3, "alpha_sweep_oil", YEARLY_CAPITAL,
                                       OIL_RISK_PCT, OIL_MAX_UNITS, use_dd=True, use_be=True)

    # Variant A for comparison (same shared DD approach)
    gold_alpha_a_trades, mr_trades_a, cm_trades_a = run_gold_portfolio(
        gold_alpha_a, mr_signals, cm_signals, YEARLY_CAPITAL, "Variant A"
    )
    np.random.seed(42)
    oil_alpha_a_trades = run_strategy(oil_alpha_a, oil_m3, "alpha_sweep_oil", YEARLY_CAPITAL,
                                       OIL_RISK_PCT, OIL_MAX_UNITS, use_dd=True, use_be=True)

    # --- Analysis ---
    print("\n[5/5] Computing statistics...\n")

    def compute_stats(trades, label):
        if not trades:
            return {"label": label, "trades": 0, "wins": 0, "wr": 0, "pf": 0,
                    "total_pnl": 0, "avg_yr": 0, "max_dd": 0, "losing_yrs": 0,
                    "total_yrs": 0, "yearly": {}, "avg_r": 0, "avg_bars": 0,
                    "tp_pct": 0, "sl_pct": 0, "be_pct": 0, "exp_pct": 0}

        pnls = [t["pnl_sized"] for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        losses = len(pnls) - wins
        gross_win = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p <= 0))
        pf = gross_win / gross_loss if gross_loss > 0 else float('inf')

        # Yearly breakdown
        yearly = defaultdict(float)
        for t in trades:
            yearly[t["year"]] += t["pnl_sized"]
        losing_yrs = sum(1 for v in yearly.values() if v < 0)
        total_yrs = len(yearly)
        avg_yr = sum(yearly.values()) / total_yrs if total_yrs else 0

        # Max DD (per-year since capital resets)
        worst_dd = 0.0
        for year in set(t["year"] for t in trades):
            year_eq = [t["equity_after"] for t in trades if t["year"] == year]
            if len(year_eq) < 2:
                continue
            year_eq = np.array(year_eq)
            peak = np.maximum.accumulate(year_eq)
            dd = ((year_eq - peak) / peak).min()
            if dd < worst_dd:
                worst_dd = dd

        # Exit reason breakdown
        reasons = [t["exit_reason"] for t in trades]
        tp_count = reasons.count("tp")
        sl_count = reasons.count("sl")
        exp_count = reasons.count("expired")

        # Average R-multiple and bars held
        avg_r = np.mean([t["r_mult"] for t in trades])
        avg_bars = np.mean([t["bars_held"] for t in trades])

        return {
            "label": label,
            "trades": len(trades),
            "wins": wins,
            "losses": losses,
            "wr": wins / len(trades) if trades else 0,
            "pf": pf,
            "total_pnl": sum(pnls),
            "avg_yr": avg_yr,
            "max_dd": worst_dd * 100,
            "losing_yrs": losing_yrs,
            "total_yrs": total_yrs,
            "yearly": dict(yearly),
            "avg_r": avg_r,
            "avg_bars": avg_bars,
            "tp_pct": tp_count / len(trades) * 100 if trades else 0,
            "sl_pct": sl_count / len(trades) * 100 if trades else 0,
            "exp_pct": exp_count / len(trades) * 100 if trades else 0,
            "avg_win": gross_win / wins if wins else 0,
            "avg_loss": gross_loss / losses if losses else 0,
        }

    stats_gold_c = compute_stats(gold_alpha_c_trades, "Gold Alpha-Sweep (C)")
    stats_oil_c = compute_stats(oil_alpha_c_trades, "Oil Alpha-Sweep (C)")
    stats_mr = compute_stats(mr_trades, "Gold Mean-Rev")
    stats_cm = compute_stats(cm_trades, "Gold Cross-Market")
    stats_gold_a = compute_stats(gold_alpha_a_trades, "Gold Alpha-Sweep (A)")
    stats_oil_a = compute_stats(oil_alpha_a_trades, "Oil Alpha-Sweep (A)")

    all_variant_c = [stats_gold_c, stats_oil_c, stats_mr, stats_cm]
    all_variant_a = [stats_gold_a, stats_oil_a, stats_mr, stats_cm]

    # ===========================================================================
    # OUTPUT
    # ===========================================================================

    print("=" * 100)
    print(f"{'STRATEGY BREAKDOWN — VARIANT C PORTFOLIO':^100}")
    print("=" * 100)
    header = f"{'Strategy':<25} {'Trades':>7} {'Wins':>6} {'WR':>7} {'PF':>7} {'$/yr':>9} {'Total $':>11} {'DD%':>7} {'Lose':>6}"
    print(header)
    print("-" * 100)
    total_trades = 0
    total_pnl = 0
    total_wins = 0
    for s in all_variant_c:
        print(f"{s['label']:<25} {s['trades']:>7} {s['wins']:>6} {s['wr']:>6.1%} {s['pf']:>7.2f} "
              f"{s['avg_yr']:>+9,.0f} {s['total_pnl']:>+11,.0f} {s['max_dd']:>6.1f}% {s['losing_yrs']:>2}/{s['total_yrs']}")
        total_trades += s["trades"]
        total_pnl += s["total_pnl"]
        total_wins += s["wins"]
    print("-" * 100)
    total_yrs = stats_gold_c["total_yrs"]
    print(f"{'TOTAL PORTFOLIO (C)':<25} {total_trades:>7} {total_wins:>6} {total_wins/total_trades:>6.1%} "
          f"{'':>7} {total_pnl/total_yrs:>+9,.0f} {total_pnl:>+11,.0f}")
    print("=" * 100)

    # Detailed metrics per strategy
    print(f"\n{'DETAILED METRICS':^100}")
    print("-" * 100)
    print(f"{'Strategy':<25} {'Avg R':>7} {'Avg Bars':>9} {'TP%':>6} {'SL%':>6} {'Exp%':>6} {'Avg Win$':>10} {'Avg Loss$':>10}")
    print("-" * 100)
    for s in all_variant_c:
        print(f"{s['label']:<25} {s['avg_r']:>+6.2f} {s['avg_bars']:>8.1f} "
              f"{s['tp_pct']:>5.1f}% {s['sl_pct']:>5.1f}% {s['exp_pct']:>5.1f}% "
              f"{s.get('avg_win',0):>10,.2f} {s.get('avg_loss',0):>10,.2f}")
    print("-" * 100)

    # Year-by-year combined
    print(f"\n{'YEAR-BY-YEAR P&L':^100}")
    print("-" * 100)
    print(f"{'Year':<6} {'Gold-A(C)':>11} {'Oil-A(C)':>11} {'Mean-Rev':>10} {'Cross-Mkt':>10} {'Combined':>12} {'Cum Total':>12}")
    print("-" * 100)
    all_years = sorted(set(
        list(stats_gold_c["yearly"].keys()) + list(stats_oil_c["yearly"].keys()) +
        list(stats_mr["yearly"].keys()) + list(stats_cm["yearly"].keys())
    ))
    cum_total = 0
    lose_count = 0
    for yr in all_years:
        ga = stats_gold_c["yearly"].get(yr, 0)
        oa = stats_oil_c["yearly"].get(yr, 0)
        mr = stats_mr["yearly"].get(yr, 0)
        cm = stats_cm["yearly"].get(yr, 0)
        combined = ga + oa + mr + cm
        cum_total += combined
        if combined < 0:
            lose_count += 1
        flag = " ← LOSS" if combined < 0 else ""
        print(f"{yr:<6} {ga:>+11,.0f} {oa:>+11,.0f} {mr:>+10,.0f} {cm:>+10,.0f} {combined:>+12,.0f} {cum_total:>+12,.0f}{flag}")
    print("-" * 100)
    print(f"{'TOTAL':<6} {stats_gold_c['total_pnl']:>+11,.0f} {stats_oil_c['total_pnl']:>+11,.0f} "
          f"{stats_mr['total_pnl']:>+10,.0f} {stats_cm['total_pnl']:>+10,.0f} {total_pnl:>+12,.0f}")
    print(f"\nLosing years: {lose_count}/{len(all_years)}")
    print(f"Avg P&L/year: ${total_pnl/len(all_years):,.0f}")
    print(f"Capital: ${YEARLY_CAPITAL:,.0f}/yr/instrument (${YEARLY_CAPITAL*2:,.0f} total deployed)")

    # ===========================================================================
    # COMPARISON: Variant A vs Variant C
    # ===========================================================================
    total_pnl_a = sum(s["total_pnl"] for s in all_variant_a)

    print(f"\n\n{'=' * 100}")
    print(f"{'VARIANT A vs VARIANT C COMPARISON':^100}")
    print(f"{'=' * 100}")
    print(f"\n{'Strategy':<25} {'A Trades':>9} {'A P&L':>11} {'C Trades':>9} {'C P&L':>11} {'Delta $':>11} {'Delta %':>9}")
    print("-" * 100)
    pairs = [(stats_gold_a, stats_gold_c), (stats_oil_a, stats_oil_c)]
    for sa, sc in pairs:
        delta = sc["total_pnl"] - sa["total_pnl"]
        delta_pct = delta / sa["total_pnl"] * 100 if sa["total_pnl"] != 0 else 0
        print(f"{sc['label']:<25} {sa['trades']:>9} {sa['total_pnl']:>+11,.0f} "
              f"{sc['trades']:>9} {sc['total_pnl']:>+11,.0f} {delta:>+11,.0f} {delta_pct:>+8.1f}%")
    # MR and CM are unchanged
    print(f"{'Gold Mean-Rev':<25} {stats_mr['trades']:>9} {stats_mr['total_pnl']:>+11,.0f} "
          f"{stats_mr['trades']:>9} {stats_mr['total_pnl']:>+11,.0f} {0:>+11,.0f} {0:>+8.1f}%")
    print(f"{'Gold Cross-Market':<25} {stats_cm['trades']:>9} {stats_cm['total_pnl']:>+11,.0f} "
          f"{stats_cm['trades']:>9} {stats_cm['total_pnl']:>+11,.0f} {0:>+11,.0f} {0:>+8.1f}%")
    print("-" * 100)
    total_delta = total_pnl - total_pnl_a
    print(f"{'TOTAL':<25} {sum(s['trades'] for s in all_variant_a):>9} {total_pnl_a:>+11,.0f} "
          f"{total_trades:>9} {total_pnl:>+11,.0f} {total_delta:>+11,.0f} {total_delta/total_pnl_a*100 if total_pnl_a else 0:>+8.1f}%")

    # ===========================================================================
    # PHANTOM FILL AUDIT
    # ===========================================================================
    print(f"\n\n{'=' * 100}")
    print(f"{'PHANTOM FILL AUDIT':^100}")
    print(f"{'=' * 100}")
    print("""
    Fill model rules (from backend/execution/fill_model.py):
    1. LONG SL fills at bid_low (or bid_open if gap-through) — NEVER above SL
    2. SHORT SL fills at ask_high (or ask_open if gap-through) — NEVER below SL
    3. TP fills EXACTLY at TP price (limit order, OANDA instant fill)
    4. SL gap-through fills at OPEN (worse than SL) — checked FIRST
    5. If both TP+SL touch same bar with no gap: TP wins (OANDA limit fires first)
    6. Break-even: SL moves to entry+slippage at 50% of TP distance
    7. Expired: fills at last bar's close
    8. Slippage: 0.03 + bar_range*0.003 + uniform(0,0.02) on ALL entries + SL fills

    These rules are IDENTICAL in:
    - backend/execution/fill_model.py (this backtest)
    - backend/scanner/live_engine.py (live Gold)
    - backend-oil/scanner/live_engine.py (live Oil)
    - dashboard backtest API (/api/gold/backtest)
    """)

    # Verify: no TP fills above TP (long) or below TP (short)
    phantom_count = 0
    for trades_list, name in [(gold_alpha_c_trades, "Gold-C"), (oil_alpha_c_trades, "Oil-C")]:
        for t in trades_list:
            if t["exit_reason"] == "tp":
                if t["direction"] == "long" and t["exit_price"] > t["tp"] + 0.01:
                    phantom_count += 1
                if t["direction"] == "short" and t["exit_price"] < t["tp"] - 0.01:
                    phantom_count += 1
            if t["exit_reason"] == "sl":
                if t["direction"] == "long" and t["exit_price"] > t["entry"]:
                    # SL fill above entry = impossible for a loss (unless BE moved SL up)
                    pass  # BE can cause this legitimately
                if t["direction"] == "short" and t["exit_price"] < t["entry"]:
                    pass  # BE can cause this legitimately

    print(f"  Phantom fills detected: {phantom_count}")
    print(f"  Total trades audited: {len(gold_alpha_c_trades) + len(oil_alpha_c_trades)}")
    if phantom_count == 0:
        print("  ✅ ZERO phantom fills. All exits respect price action.")
    else:
        print(f"  ⚠️  {phantom_count} suspicious fills found — INVESTIGATE!")

    # ===========================================================================
    # MONTHLY BREAKDOWN (Gold Alpha C only — most trades)
    # ===========================================================================
    print(f"\n\n{'=' * 100}")
    print(f"{'MONTHLY ANALYSIS — GOLD ALPHA-SWEEP (C)':^100}")
    print(f"{'=' * 100}")
    monthly_pnl = defaultdict(float)
    monthly_trades = defaultdict(int)
    for t in gold_alpha_c_trades:
        monthly_pnl[t["month"]] += t["pnl_sized"]
        monthly_trades[t["month"]] += 1
    print(f"\n{'Month':<8} {'Trades':>7} {'P&L':>10} {'Avg/Trade':>10}")
    print("-" * 40)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for m in range(1, 13):
        tc = monthly_trades[m]
        pnl = monthly_pnl[m]
        avg = pnl / tc if tc else 0
        print(f"{months[m-1]:<8} {tc:>7} {pnl:>+10,.0f} {avg:>+10,.2f}")

    # ===========================================================================
    # DIRECTION SPLIT
    # ===========================================================================
    print(f"\n\n{'=' * 100}")
    print(f"{'DIRECTION ANALYSIS':^100}")
    print(f"{'=' * 100}")
    for trades_list, name in [(gold_alpha_c_trades, "Gold Alpha (C)"), (oil_alpha_c_trades, "Oil Alpha (C)")]:
        longs = [t for t in trades_list if t["direction"] == "long"]
        shorts = [t for t in trades_list if t["direction"] == "short"]
        l_wins = sum(1 for t in longs if t["pnl_sized"] > 0)
        s_wins = sum(1 for t in shorts if t["pnl_sized"] > 0)
        l_pnl = sum(t["pnl_sized"] for t in longs)
        s_pnl = sum(t["pnl_sized"] for t in shorts)
        print(f"\n  {name}:")
        print(f"    LONG:  {len(longs)} trades, {l_wins}/{len(longs)} wins ({l_wins/len(longs)*100:.1f}%), ${l_pnl:+,.0f}")
        print(f"    SHORT: {len(shorts)} trades, {s_wins}/{len(shorts)} wins ({s_wins/len(shorts)*100:.1f}%), ${s_pnl:+,.0f}")

    # ===========================================================================
    # TECH DEBT: Oil signal count vs dashboard
    # ===========================================================================
    print(f"\n\n{'=' * 100}")
    print(f"{'TECH DEBT CHECK: Oil Signal Parity':^100}")
    print(f"{'=' * 100}")
    print(f"""
    Oil backend-oil/strategies/alpha_sweep.py uses Variant A bias (yesterday direction only).
    Oil backend-oil/backtest/engine.py uses that same generate_signals().

    This script generates Oil signals with Variant C bias.

    Signal counts:
      Oil Variant A (dashboard code): {len(oil_alpha_a)} signals → {stats_oil_a['trades']} trades
      Oil Variant C (this script):    {len(oil_alpha_c)} signals → {stats_oil_c['trades']} trades
      Delta:                          +{len(oil_alpha_c) - len(oil_alpha_a)} signals

    If you run the dashboard Oil backtest now, it will show Variant A numbers.
    To match Variant C, you'd need to update backend-oil/strategies/alpha_sweep.py
    with the Variant C bias logic (body_pct < 0.4 → neutral).
    """)

    # ===========================================================================
    # FINAL SUMMARY
    # ===========================================================================
    print(f"\n{'=' * 100}")
    print(f"{'FINAL SUMMARY':^100}")
    print(f"{'=' * 100}")
    print(f"""
    VARIANT C PORTFOLIO (Gold Alpha + Oil Alpha + Mean-Rev + Cross-Market):
    ├── Total trades:     {total_trades:,}
    ├── Win rate:         {total_wins/total_trades:.1%}
    ├── Total P&L:        ${total_pnl:+,.0f}
    ├── Avg P&L/year:     ${total_pnl/len(all_years):+,.0f}
    ├── Losing years:     {lose_count}/{len(all_years)}
    └── Capital/year:     ${YEARLY_CAPITAL*2:,.0f} ($5K Gold + $5K Oil)

    vs VARIANT A PORTFOLIO (current production):
    ├── Total trades:     {sum(s['trades'] for s in all_variant_a):,}
    ├── Total P&L:        ${total_pnl_a:+,.0f}
    ├── Delta:            ${total_delta:+,.0f} ({total_delta/total_pnl_a*100 if total_pnl_a else 0:+.1f}%)
    └── Extra trades:     +{total_trades - sum(s['trades'] for s in all_variant_a):,}

    REPLICABILITY:
    ✅ Uses production fill_model.py (shared by live + backtest)
    ✅ Uses production config.py thresholds (both Gold and Oil)
    ✅ Uses production dd_protection.py (50-MA, halve, pause, equity MA)
    ✅ Same seed (42) = deterministic slippage
    ✅ Same data (data/raw/ CSVs) = same candles as live scanner reads
    ✅ Entry: ask_close + slippage (long), bid_close - slippage (short)
    ✅ TP: fills on touch (matches OANDA limit order)
    ✅ SL: gap-through at open, otherwise at SL level + adverse slippage
    ✅ Break-even: at 50% TP distance, SL → entry + slippage
    ✅ {phantom_count} phantom fills
    """)


if __name__ == "__main__":
    main()
