"""
Full portfolio backtest — Variant C bias filter.

Uses PRODUCTION data pipeline (backend/data/cache.py load_candles) to ensure
numbers are replicable by the dashboard and live system.

Fixes vs previous version:
  - Uses load_candles() which deduplicates H1 timestamps (22 dupes in Oil CSV)
  - Uses precomputed mid prices (identical to production strategies)
  - Resets seed before each strategy for reproducibility
  - MR + CM from the production engine (shared DD + compounding)

Variant C bias logic:
  - If yesterday's body > 40% of high-low range → apply directional bias
  - If yesterday's body <= 40% of range (indecision) → allow BOTH directions
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import numpy as np
import pandas as pd
from collections import defaultdict

from backend.data.cache import load_candles, load_inter_market
from backend.execution.fill_model import execute_trade
from backend.config import ALPHA_SWEEP as GOLD_CFG, slippage as gold_slippage, MAX_UNITS, YEARLY_CAPITAL

# Oil thresholds (from backend-oil/config.py)
OIL_CFG = {
    "asia_min_range": 0.50,
    "sweep_threshold": 0.20,
    "sl_buffer": 0.03,
    "min_sl": 0.10,
    "tp_multiplier": 2.0,
    "max_bars": 80,
    "skip_first_bar": True,
    "engulfing_window_hours": 2,
    "scan_start": 8,
    "scan_end": 20,
    "max_trades_per_day": 3,
}
OIL_MAX_UNITS = 5000


def oil_slippage(bar_range: float) -> float:
    return 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)


def compute_bias_c(daily_df):
    """Variant C: strong body = directional, weak body = neutral (allow both)."""
    if "mid_open" in daily_df.columns:
        opens = daily_df["mid_open"]
        closes = daily_df["mid_close"]
        highs = daily_df["mid_high"]
        lows = daily_df["mid_low"]
    else:
        opens = daily_df["open"]
        closes = daily_df["close"]
        highs = daily_df["high"]
        lows = daily_df["low"]

    bias = {}
    for i in range(1, len(daily_df)):
        d = daily_df.index[i].date()
        rng = highs.iat[i - 1] - lows.iat[i - 1]
        if rng == 0:
            bias[d] = "neutral"
            continue
        body_pct = abs(closes.iat[i - 1] - opens.iat[i - 1]) / rng
        if body_pct < 0.4:
            bias[d] = "neutral"
        else:
            bias[d] = "bullish" if closes.iat[i - 1] > opens.iat[i - 1] else "bearish"
    return bias


def compute_bias_a(daily_df):
    """Variant A (current production): yesterday direction, always applied."""
    if "mid_open" in daily_df.columns:
        opens = daily_df["mid_open"]
        closes = daily_df["mid_close"]
    else:
        opens = daily_df["open"]
        closes = daily_df["close"]

    bias = {}
    for i in range(1, len(daily_df)):
        d = daily_df.index[i].date()
        bias[d] = "bullish" if closes.iat[i - 1] > opens.iat[i - 1] else "bearish"
    return bias


def find_alpha_signals(h1, m3, daily_bias, cfg, slippage_fn, instrument="gold"):
    """
    Generate Alpha-Sweep signals. Same logic as backend/strategies/alpha_sweep.py
    but accepts configurable bias dict for variant testing.
    """
    risk_floor = 0.30 if instrument == "gold" else 0.01
    max_units = MAX_UNITS if instrument == "gold" else OIL_MAX_UNITS
    signals = []
    dates = sorted(set(h1.index.date))

    for date in dates:
        day_h1 = h1[h1.index.date == date]
        asia = day_h1[(day_h1.index.hour >= 0) & (day_h1.index.hour < 8)]
        scan = day_h1[
            (day_h1.index.hour >= cfg["scan_start"]) & (day_h1.index.hour < cfg["scan_end"])
        ]

        if len(asia) < 3 or len(scan) < 2:
            continue

        ah = asia["mid_high"].max()
        al = asia["mid_low"].min()
        ar = ah - al

        if ar < cfg["asia_min_range"]:
            continue

        bias = daily_bias.get(date, "none")

        sweeps = []
        for i in range(len(scan)):
            bh = scan["mid_high"].iloc[i]
            bl = scan["mid_low"].iloc[i]
            bc = scan["mid_close"].iloc[i]

            if bh > ah + cfg["sweep_threshold"] and bc < ah:
                sweeps.append(("bearish", bh, scan.index[i]))
            elif bl < al - cfg["sweep_threshold"] and bc > al:
                sweeps.append(("bullish", bl, scan.index[i]))

        if not sweeps:
            continue

        day_trades = 0
        for sweep_dir, sweep_wick, sweep_time in sweeps:
            if day_trades >= cfg["max_trades_per_day"]:
                break

            if bias != "neutral":
                if sweep_dir == "bullish" and bias != "bullish":
                    continue
                if sweep_dir == "bearish" and bias != "bearish":
                    continue

            end_time = sweep_time + pd.Timedelta(hours=cfg["engulfing_window_hours"])
            mw = m3[(m3.index > sweep_time) & (m3.index <= end_time)]

            if len(mw) < 3:
                continue

            start_idx = 2 if cfg["skip_first_bar"] else 1

            for j in range(start_idx, len(mw)):
                idx = m3.index.get_loc(mw.index[j])
                co = m3["mid_open"].iat[idx]
                cc = m3["mid_close"].iat[idx]
                po = m3["mid_open"].iat[idx - 1]
                pc = m3["mid_close"].iat[idx - 1]
                br = m3["mid_high"].iat[idx] - m3["mid_low"].iat[idx]

                ct, cb = max(co, cc), min(co, cc)
                pt, pb = max(po, pc), min(po, pc)

                if sweep_dir == "bullish" and not (cc > co and cb <= pb and ct >= pt):
                    continue
                if sweep_dir == "bearish" and not (cc < co and cb <= pb and ct >= pt):
                    continue

                if sweep_dir == "bullish":
                    entry = m3["ask_close"].iat[idx] + slippage_fn(br)
                    sl = sweep_wick - cfg["sl_buffer"]
                    risk = entry - sl
                    if risk < cfg["min_sl"]:
                        sl = entry - cfg["min_sl"]
                        risk = cfg["min_sl"]
                    if risk < risk_floor or risk > ar * 0.8:
                        continue
                    tp = entry + ar * cfg["tp_multiplier"]
                    if tp - entry < risk * 0.8:
                        continue
                    signals.append((mw.index[j], "long", entry, sl, tp, risk, max_units))
                else:
                    entry = m3["bid_close"].iat[idx] - slippage_fn(br)
                    sl = sweep_wick + cfg["sl_buffer"]
                    risk = sl - entry
                    if risk < cfg["min_sl"]:
                        sl = entry + cfg["min_sl"]
                        risk = cfg["min_sl"]
                    if risk < risk_floor or risk > ar * 0.8:
                        continue
                    tp = entry - ar * cfg["tp_multiplier"]
                    if entry - tp < risk * 0.8:
                        continue
                    signals.append((mw.index[j], "short", entry, sl, tp, risk, max_units))

                day_trades += 1
                break

    return signals


def run_backtest(sigs, m3_df, risk_pct=4.0):
    """Execute signals with fixed $5K capital, no DD protection."""
    np.random.seed(42)
    yearly = defaultdict(float)
    trades = 0
    wins = 0
    gross_win = 0.0
    gross_loss = 0.0
    peak = 5000
    eq = 5000
    max_dd = 0

    for (dt, d, e, s, tp, r, mu) in sigs:
        try:
            loc = m3_df.index.get_loc(dt)
            idx = loc if isinstance(loc, int) else loc.start if hasattr(loc, "start") else int(np.where(m3_df.index == dt)[0][0])
        except:
            continue

        u = min((5000 * risk_pct / 100) / r, mu)
        res = execute_trade(
            df=m3_df, bar_start=idx, entry=e, sl=s, tp=tp,
            direction=d, max_bars=80, strategy="alpha_sweep", use_break_even=True,
        )
        if res is None:
            continue

        p = res.pnl_per_unit * u
        trades += 1
        if p > 0:
            wins += 1
            gross_win += p
        else:
            gross_loss += abs(p)

        eq += p
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

        yearly[dt.year] += p

    total_pnl = gross_win - gross_loss
    lose = sum(1 for v in yearly.values() if v < 0)
    yrs = len(yearly)
    wr = wins / trades if trades else 0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    return trades, wr, pf, total_pnl, total_pnl / yrs if yrs else 0, max_dd, lose, yrs, dict(yearly)


def main():
    # --- Load data using PRODUCTION pipeline ---
    print("Loading data (production pipeline: load_candles with dedup)...")
    gold_d = load_candles("XAU_USD_D.csv")
    gold_h1 = load_candles("XAU_USD_H1.csv")
    gold_m3 = load_candles("XAU_USD_M3.csv")
    oil_d = load_candles("BCO_USD_D.csv")
    oil_h1 = load_candles("BCO_USD_H1.csv")
    oil_m3 = load_candles("BCO_USD_M3.csv")

    print(f"  Gold: H1={len(gold_h1)}, M3={len(gold_m3)}, Daily={len(gold_d)}")
    print(f"  Oil:  H1={len(oil_h1)}, M3={len(oil_m3)}, Daily={len(oil_d)}")

    # --- Compute bias ---
    gold_bias_c = compute_bias_c(gold_d)
    oil_bias_c = compute_bias_c(oil_d)
    gold_bias_a = compute_bias_a(gold_d)
    oil_bias_a = compute_bias_a(oil_d)

    # --- Generate & execute Alpha-Sweep signals ---
    print("\nRunning Gold Alpha-Sweep (Variant C)...")
    np.random.seed(42)
    gold_sigs_c = find_alpha_signals(gold_h1, gold_m3, gold_bias_c, GOLD_CFG, gold_slippage, "gold")
    gc = run_backtest(gold_sigs_c, gold_m3, 4.0)

    print("Running Oil Alpha-Sweep (Variant C)...")
    np.random.seed(42)
    oil_sigs_c = find_alpha_signals(oil_h1, oil_m3, oil_bias_c, OIL_CFG, oil_slippage, "oil")
    oc = run_backtest(oil_sigs_c, oil_m3, 4.0)

    print("Running Gold Alpha-Sweep (Variant A)...")
    np.random.seed(42)
    gold_sigs_a = find_alpha_signals(gold_h1, gold_m3, gold_bias_a, GOLD_CFG, gold_slippage, "gold")
    ga = run_backtest(gold_sigs_a, gold_m3, 4.0)

    print("Running Oil Alpha-Sweep (Variant A)...")
    np.random.seed(42)
    oil_sigs_a = find_alpha_signals(oil_h1, oil_m3, oil_bias_a, OIL_CFG, oil_slippage, "oil")
    oa = run_backtest(oil_sigs_a, oil_m3, 4.0)

    # --- MR + CM from production engine (shared DD + compounding) ---
    print("Running Gold MR + CM (production engine)...")
    np.random.seed(42)
    from backend.backtest.engine import run_backtest as full_backtest
    full_result = full_backtest()

    mr_pnl = sum(t.pnl_sized for t in full_result.trades if t.strategy == "mean_rev")
    cm_pnl = sum(t.pnl_sized for t in full_result.trades if t.strategy == "cross_market")
    mr_trades = sum(1 for t in full_result.trades if t.strategy == "mean_rev")
    cm_trades = sum(1 for t in full_result.trades if t.strategy == "cross_market")
    mr_wins = sum(1 for t in full_result.trades if t.strategy == "mean_rev" and t.pnl_sized > 0)
    cm_wins = sum(1 for t in full_result.trades if t.strategy == "cross_market" and t.pnl_sized > 0)
    mr_yearly = defaultdict(float)
    cm_yearly = defaultdict(float)
    for t in full_result.trades:
        if t.strategy == "mean_rev":
            mr_yearly[t.year] += t.pnl_sized
        elif t.strategy == "cross_market":
            cm_yearly[t.year] += t.pnl_sized

    # --- Unpack results ---
    # gc/oc/ga/oa = (trades, wr, pf, total_pnl, $/yr, max_dd, lose_yrs, n_yrs, yearly_dict)
    g_t, g_wr, g_pf, g_pnl, g_py, g_dd, g_ly, g_yrs, g_yearly = gc
    o_t, o_wr, o_pf, o_pnl, o_py, o_dd, o_ly, o_yrs, o_yearly = oc
    ga_t, ga_wr, ga_pf, ga_pnl, ga_py, ga_dd, ga_ly, ga_yrs, ga_yearly = ga
    oa_t, oa_wr, oa_pf, oa_pnl, oa_py, oa_dd, oa_ly, oa_yrs, oa_yearly = oa

    total_pnl_c = g_pnl + o_pnl + mr_pnl + cm_pnl
    total_trades_c = g_t + o_t + mr_trades + cm_trades
    total_pnl_a = ga_pnl + oa_pnl + mr_pnl + cm_pnl
    total_trades_a = ga_t + oa_t + mr_trades + cm_trades
    n_yrs = g_yrs

    # === OUTPUT ===
    print(f'\n{"=" * 90}')
    print(f'{"FULL PORTFOLIO — VARIANT C BIAS FILTER":^90}')
    print(f'{"(production pipeline, deduplicated, zero phantom fills)":^90}')
    print(f'{"=" * 90}')
    print(f'{"Strategy":<28} {"Trades":>7} {"WR":>7} {"PF":>7} {"$/yr":>9} {"Total":>11} {"DD":>7} {"Lose":>6}')
    print(f'{"-" * 90}')
    print(f'{"Gold Alpha-Sweep (C)":<28} {g_t:>7} {g_wr:>6.1%} {g_pf:>7.2f} {g_py:>+9,.0f} {g_pnl:>+11,.0f} {g_dd * 100:>6.1f}% {g_ly:>2}/{g_yrs}')
    print(f'{"Oil Alpha-Sweep (C)":<28} {o_t:>7} {o_wr:>6.1%} {o_pf:>7.2f} {o_py:>+9,.0f} {o_pnl:>+11,.0f} {o_dd * 100:>6.1f}% {o_ly:>2}/{o_yrs}')
    print(f'{"Gold Mean-Rev":<28} {mr_trades:>7} {mr_wins / mr_trades if mr_trades else 0:>6.1%} {"":>7} {mr_pnl / n_yrs:>+9,.0f} {mr_pnl:>+11,.0f}')
    print(f'{"Gold Cross-Market":<28} {cm_trades:>7} {cm_wins / cm_trades if cm_trades else 0:>6.1%} {"":>7} {cm_pnl / n_yrs:>+9,.0f} {cm_pnl:>+11,.0f}')
    print(f'{"-" * 90}')
    print(f'{"TOTAL PORTFOLIO (C)":<28} {total_trades_c:>7} {"":>7} {"":>7} {total_pnl_c / n_yrs:>+9,.0f} {total_pnl_c:>+11,.0f}')
    print(f'{"=" * 90}')

    # Year by year (Variant C)
    print(f'\n{"Year":<6} {"Gold-A":>10} {"Oil-A":>10} {"MR":>10} {"CM":>10} {"Combined":>12}')
    print(f'{"-" * 65}')
    all_years = sorted(set(
        list(g_yearly.keys()) + list(o_yearly.keys()) +
        list(mr_yearly.keys()) + list(cm_yearly.keys())
    ))
    lose_count = 0
    for yr in all_years:
        g = g_yearly.get(yr, 0)
        o = o_yearly.get(yr, 0)
        m = mr_yearly.get(yr, 0)
        c = cm_yearly.get(yr, 0)
        combined = g + o + m + c
        if combined < 0:
            lose_count += 1
        print(f'{yr:<6} {g:>+10,.0f} {o:>+10,.0f} {m:>+10,.0f} {c:>+10,.0f} {combined:>+12,.0f}')
    print(f'{"-" * 65}')
    print(f'{"TOTAL":<6} {g_pnl:>+10,.0f} {o_pnl:>+10,.0f} {mr_pnl:>+10,.0f} {cm_pnl:>+10,.0f} {total_pnl_c:>+12,.0f}')

    print(f"\nLosing years: {lose_count}/{len(all_years)}")
    print(f"Avg P&L/year: ${total_pnl_c / len(all_years):,.0f}")
    print(f"Starting capital: $10,000/year ($5K per instrument)")

    # === VARIANT A (current production) ===
    print(f'\n{"=" * 90}')
    print(f'{"FULL PORTFOLIO — VARIANT A (CURRENT PRODUCTION)":^90}')
    print(f'{"=" * 90}')
    print(f'{"Strategy":<28} {"Trades":>7} {"WR":>7} {"PF":>7} {"$/yr":>9} {"Total":>11} {"DD":>7} {"Lose":>6}')
    print(f'{"-" * 90}')
    print(f'{"Gold Alpha-Sweep (A)":<28} {ga_t:>7} {ga_wr:>6.1%} {ga_pf:>7.2f} {ga_py:>+9,.0f} {ga_pnl:>+11,.0f} {ga_dd * 100:>6.1f}% {ga_ly:>2}/{ga_yrs}')
    print(f'{"Oil Alpha-Sweep (A)":<28} {oa_t:>7} {oa_wr:>6.1%} {oa_pf:>7.2f} {oa_py:>+9,.0f} {oa_pnl:>+11,.0f} {oa_dd * 100:>6.1f}% {oa_ly:>2}/{oa_yrs}')
    print(f'{"Gold Mean-Rev":<28} {mr_trades:>7} {mr_wins / mr_trades if mr_trades else 0:>6.1%} {"":>7} {mr_pnl / n_yrs:>+9,.0f} {mr_pnl:>+11,.0f}')
    print(f'{"Gold Cross-Market":<28} {cm_trades:>7} {cm_wins / cm_trades if cm_trades else 0:>6.1%} {"":>7} {cm_pnl / n_yrs:>+9,.0f} {cm_pnl:>+11,.0f}')
    print(f'{"-" * 90}')
    print(f'{"TOTAL PORTFOLIO (A)":<28} {total_trades_a:>7} {"":>7} {"":>7} {total_pnl_a / n_yrs:>+9,.0f} {total_pnl_a:>+11,.0f}')
    print(f'{"=" * 90}')

    # Year by year (Variant A)
    print(f'\n{"Year":<6} {"Gold-A":>10} {"Oil-A":>10} {"MR":>10} {"CM":>10} {"Combined":>12}')
    print(f'{"-" * 65}')
    all_years_a = sorted(set(
        list(ga_yearly.keys()) + list(oa_yearly.keys()) +
        list(mr_yearly.keys()) + list(cm_yearly.keys())
    ))
    lose_a = 0
    for yr in all_years_a:
        g = ga_yearly.get(yr, 0)
        o = oa_yearly.get(yr, 0)
        m = mr_yearly.get(yr, 0)
        c = cm_yearly.get(yr, 0)
        combined = g + o + m + c
        if combined < 0:
            lose_a += 1
        print(f'{yr:<6} {g:>+10,.0f} {o:>+10,.0f} {m:>+10,.0f} {c:>+10,.0f} {combined:>+12,.0f}')
    print(f'{"-" * 65}')
    print(f'{"TOTAL":<6} {ga_pnl:>+10,.0f} {oa_pnl:>+10,.0f} {mr_pnl:>+10,.0f} {cm_pnl:>+10,.0f} {total_pnl_a:>+12,.0f}')
    print(f"\nLosing years: {lose_a}/{len(all_years_a)}")

    # === COMPARISON ===
    print(f'\n{"=" * 90}')
    print(f'{"COMPARISON":^90}')
    print(f'{"=" * 90}')
    delta = total_pnl_c - total_pnl_a
    print(f"  Variant A (current):  ${total_pnl_a:+,.0f}  ({total_trades_a} trades)")
    print(f"  Variant C (proposed): ${total_pnl_c:+,.0f}  ({total_trades_c} trades)")
    print(f"  Delta:                ${delta:+,.0f} ({delta / total_pnl_a * 100:+.1f}%)")
    print(f"  Extra trades:         +{total_trades_c - total_trades_a}")
    print(f'\n{"=" * 90}')


if __name__ == "__main__":
    main()
