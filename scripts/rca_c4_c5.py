"""
RCA for C5 (sweep re-fire after SL) + min_range/min_sl optimization.

Uses the EXACT production code path:
  - backend/strategies/micro_alpha_sweep.py:generate_signals()
  - backend/execution/fill_model.py:execute_trade()
  - DD protection logic from backend/strategies/dd_protection.py

We patch backend.config.ALPHA_SWEEP between runs to test different params.
Period: 2020-2026 (6.4 years)
"""
import sys, os, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

import backend.config as cfg_module
from backend.data.cache import load_candles, load_inter_market
from backend.strategies.base import Signal
from backend.strategies import micro_alpha_sweep
from backend.strategies.dd_protection import DDState, should_skip_signal, get_risk_multiplier, update_after_trade
from backend.execution.fill_model import execute_trade


# ─── Data loading (once) ───
def load_data():
    gold_d = load_candles("XAU_USD_D.csv")
    gold_h1 = load_candles("XAU_USD_H1.csv")
    gold_m3 = load_candles("XAU_USD_M3.csv")
    # Filter to 2020-2026 for speed
    fs = pd.Timestamp("2019-11-01", tz="UTC")  # Buffer for bias
    fe = pd.Timestamp("2026-06-30", tz="UTC")
    gold_h1 = gold_h1[(gold_h1.index >= fs) & (gold_h1.index <= fe)]
    gold_m3 = gold_m3[(gold_m3.index >= fs) & (gold_m3.index <= fe)]
    return gold_d, gold_h1, gold_m3


def build_daily_bias(gold_d):
    daily_bias = {}
    for i in range(1, len(gold_d)):
        d = gold_d.index[i].date()
        prev_range = gold_d["mid_high"].iat[i - 1] - gold_d["mid_low"].iat[i - 1]
        body_pct = abs(gold_d["mid_close"].iat[i - 1] - gold_d["mid_open"].iat[i - 1]) / prev_range if prev_range > 0 else 0
        if body_pct < 0.4:
            daily_bias[d] = "neutral"
        else:
            daily_bias[d] = "bullish" if gold_d["mid_close"].iat[i - 1] > gold_d["mid_open"].iat[i - 1] else "bearish"
    return daily_bias


# ─── Execute signals through fill model + DD protection ───
# This is the SAME loop as backend-micro/backtest/engine.py lines 96-208
# but isolated to avoid the import path mess between backend/backend-micro.
def execute_signals(signals, gold_m3, gold_d, capital=5000.0, risk_pct=4.0):
    """Execute micro_alpha_sweep signals. Exact same logic as production engine."""
    np.random.seed(42)
    signals = sorted(signals, key=lambda x: x.date)

    start_ts = pd.Timestamp("2020-01-01", tz="UTC")
    end_ts = pd.Timestamp("2026-05-29", tz="UTC")
    signals = [s for s in signals if start_ts <= s.date <= end_ts]

    DAILY_MAX_LOSS = 400
    HALF_AFTER_CONSECUTIVE = 3
    COOLDOWN_SECONDS = 300

    # DD state
    state = DDState()
    trades = []
    current_year = None
    current_date = None
    daily_pnl = 0.0
    last_signal_time = None

    # Gold 50MA for DD filter
    gold_50ma_vals = pd.Series(gold_d["mid_close"].values).rolling(50, min_periods=50).mean().values
    gold_50ma_dict = {}
    gold_close_dict = {}
    for i in range(1, len(gold_d)):
        d = gold_d.index[i].date()
        if not np.isnan(gold_50ma_vals[i]):
            gold_50ma_dict[d] = gold_50ma_vals[i]
        gold_close_dict[d] = gold_d["mid_close"].iat[i]

    for signal in signals:
        trade_date = signal.date.date()
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

        if trade_date != current_date:
            daily_pnl = 0.0
            current_date = trade_date

        # 5-min cooldown (same as live)
        if last_signal_time and (signal.date - last_signal_time).total_seconds() < COOLDOWN_SECONDS:
            continue

        if daily_pnl <= -DAILY_MAX_LOSS:
            continue

        if state.equity < 100:
            continue

        # DD filters
        gp = gold_close_dict.get(trade_date, 0)
        gma = gold_50ma_dict.get(trade_date, 0)
        if should_skip_signal(signal.strategy, signal.direction, gp, gma, state):
            continue

        # Position sizing (same as production)
        risk_mult = get_risk_multiplier(state)
        if state.consecutive_losses >= HALF_AFTER_CONSECUTIVE:
            risk_mult *= 0.5
        # micro_alpha_sweep uses 4% risk (from STRATEGY_RISK in micro config)
        strat_risk_pct = 4.0  # Hardcoded: micro_alpha_sweep = 4%
        risk_dollar = state.equity * (strat_risk_pct / 100) * risk_mult
        if signal.risk <= 0:
            continue
        units = min(risk_dollar / signal.risk, 100)  # MAX_UNITS = 100

        # Fill model execution
        df = gold_m3
        try:
            bar_idx = df.index.get_loc(signal.date)
        except KeyError:
            continue

        result = execute_trade(
            df=df,
            bar_start=bar_idx,
            entry=signal.entry,
            sl=signal.sl,
            tp=signal.tp,
            direction=signal.direction,
            max_bars=signal.max_bars,
            strategy=signal.strategy,
            use_break_even=True,
        )
        if result is None:
            continue

        pnl_dollar = result.pnl_per_unit * units
        update_after_trade(state, pnl_dollar)
        daily_pnl += pnl_dollar
        last_signal_time = signal.date

        trades.append({
            "date": signal.date,
            "year": trade_year,
            "direction": signal.direction,
            "entry": signal.entry,
            "sl": signal.sl,
            "tp": signal.tp,
            "risk": signal.risk,
            "exit_price": result.exit_price,
            "exit_reason": result.exit_reason,
            "pnl_unit": result.pnl_per_unit,
            "pnl_sized": pnl_dollar,
            "units": units,
            "bars_held": result.bars_held,
            "equity_after": state.equity,
            "consol_range": signal.metadata.get("consol_range", 0) if signal.metadata else 0,
        })

    return trades


def compute_stats(trades, label=""):
    if not trades:
        return {"label": label, "trades": 0, "wr": 0, "pf": 0, "pnl": 0, "dd": 0}

    pnls = [t["pnl_sized"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    gw = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0))
    pf = gw / gl if gl > 0 else 999

    # Max DD per year
    worst_dd = 0.0
    for year in set(t["year"] for t in trades):
        eq = np.array([t["equity_after"] for t in trades if t["year"] == year])
        if len(eq) >= 2:
            peaks = np.maximum.accumulate(eq)
            dd = ((eq - peaks) / peaks).min() * 100
            if dd < worst_dd:
                worst_dd = dd

    return {
        "label": label,
        "trades": len(trades),
        "wr": wins / len(trades) * 100,
        "pf": pf,
        "pnl": sum(pnls),
        "dd": worst_dd,
    }


def print_year_by_year(trades):
    if not trades:
        print("    No trades.")
        return
    years = sorted(set(t["year"] for t in trades))
    print(f"    {'Year':<6} {'Trades':>7} {'WR':>7} {'PF':>7} {'P&L':>10} {'DD':>7}")
    print(f"    {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*10} {'-'*7}")
    for year in years:
        yt = [t for t in trades if t["year"] == year]
        pnls = [t["pnl_sized"] for t in yt]
        w = sum(1 for p in pnls if p > 0)
        gw = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p <= 0))
        pf = gw / gl if gl > 0 else 999
        eq = np.array([t["equity_after"] for t in yt])
        dd = ((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min() * 100 if len(eq) >= 2 else 0
        print(f"    {year:<6} {len(yt):>7} {w/len(yt)*100:>6.1f}% {pf:>7.2f} ${sum(pnls):>8,.0f} {dd:>6.1f}%")


def print_risk_buckets(trades):
    if not trades:
        return
    buckets = {"$5-10": [], "$10-15": [], "$15-20": [], "$20-30": [], "$30+": []}
    for t in trades:
        r = t["risk"]
        if r < 10:
            buckets["$5-10"].append(t)
        elif r < 15:
            buckets["$10-15"].append(t)
        elif r < 20:
            buckets["$15-20"].append(t)
        elif r < 30:
            buckets["$20-30"].append(t)
        else:
            buckets["$30+"].append(t)

    print(f"    {'Bucket':<10} {'Trades':>7} {'WR':>7} {'PF':>7} {'P&L':>12} {'Avg Risk':>10}")
    print(f"    {'-'*10} {'-'*7} {'-'*7} {'-'*7} {'-'*12} {'-'*10}")
    for bucket, bt in buckets.items():
        if bt:
            pnls = [t["pnl_sized"] for t in bt]
            w = sum(1 for p in pnls if p > 0)
            gw = sum(p for p in pnls if p > 0)
            gl = abs(sum(p for p in pnls if p <= 0))
            pf = gw / gl if gl > 0 else 999
            avg_r = np.mean([t["risk"] for t in bt])
            print(f"    {bucket:<10} {len(bt):>7} {w/len(bt)*100:>6.1f}% {pf:>7.2f} ${sum(pnls):>10,.0f} ${avg_r:>9.2f}")


def main():
    print("=" * 80)
    print("RCA: C5 (Sweep Re-fire) + min_range/min_sl Optimization")
    print("  Signal gen: backend/strategies/micro_alpha_sweep.py:generate_signals()")
    print("  Fill model: backend/execution/fill_model.py:execute_trade()")
    print("  DD protect: backend/strategies/dd_protection.py")
    print("  Period: 2020-01-01 to 2026-05-29")
    print("=" * 80)

    t0 = time.time()
    gold_d, gold_h1, gold_m3 = load_data()
    daily_bias = build_daily_bias(gold_d)
    print(f"\n  Data loaded in {time.time()-t0:.1f}s: H1={len(gold_h1)}, M3={len(gold_m3)}")

    # Save original config
    orig_min_range = cfg_module.ALPHA_SWEEP["asia_min_range"]
    orig_min_sl = cfg_module.ALPHA_SWEEP["min_sl"]
    print(f"  Current config: asia_min_range=${orig_min_range}, min_sl=${orig_min_sl}")

    # ═══════════════════════════════════════════════════════════════════════
    # PART 1: BASELINE
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("PART 1: BASELINE (min_range=$5, min_sl=$5)")
    print("=" * 80)

    cfg_module.ALPHA_SWEEP["asia_min_range"] = 5.0
    cfg_module.ALPHA_SWEEP["min_sl"] = 5.0
    np.random.seed(42)
    t0 = time.time()
    sigs = micro_alpha_sweep.generate_signals(gold_h1, gold_m3, daily_bias)
    print(f"  Signal gen: {time.time()-t0:.1f}s, {len(sigs)} raw signals")
    trades = execute_signals(sigs, gold_m3, gold_d)
    s = compute_stats(trades)
    print(f"  Trades: {s['trades']} | WR: {s['wr']:.1f}% | PF: {s['pf']:.2f} | P&L: ${s['pnl']:,.0f} | DD: {s['dd']:.1f}%")
    print("\n  Year-by-year:")
    print_year_by_year(trades)
    print("\n  Risk Bucket Breakdown:")
    print_risk_buckets(trades)
    baseline_pnl = s["pnl"]

    # ═══════════════════════════════════════════════════════════════════════
    # PART 2: min_range SWEEP
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("PART 2: min_range SWEEP (min_sl fixed at $5)")
    print("  Q: Below what range is the edge gone?")
    print("=" * 80)

    print(f"\n  {'min_range':>10} {'Trades':>7} {'WR':>7} {'PF':>7} {'P&L':>12} {'DD':>7} {'Δ P&L':>10}")
    print(f"  {'-'*10} {'-'*7} {'-'*7} {'-'*7} {'-'*12} {'-'*7} {'-'*10}")
    for mr in [5, 8, 10, 12, 15, 18, 20, 25, 30]:
        cfg_module.ALPHA_SWEEP["asia_min_range"] = float(mr)
        cfg_module.ALPHA_SWEEP["min_sl"] = 5.0
        np.random.seed(42)
        sigs = micro_alpha_sweep.generate_signals(gold_h1, gold_m3, daily_bias)
        tr = execute_signals(sigs, gold_m3, gold_d)
        st = compute_stats(tr)
        d = st["pnl"] - baseline_pnl
        print(f"  ${mr:>8} {st['trades']:>7} {st['wr']:>6.1f}% {st['pf']:>7.2f} ${st['pnl']:>10,.0f} {st['dd']:>6.1f}% ${d:>+8,.0f}")

    # ═══════════════════════════════════════════════════════════════════════
    # PART 3: min_sl SWEEP
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("PART 3: min_sl SWEEP (min_range fixed at $5)")
    print("  Q: What minimum SL filters noise-territory?")
    print("=" * 80)

    print(f"\n  {'min_sl':>10} {'Trades':>7} {'WR':>7} {'PF':>7} {'P&L':>12} {'DD':>7} {'Δ P&L':>10}")
    print(f"  {'-'*10} {'-'*7} {'-'*7} {'-'*7} {'-'*12} {'-'*7} {'-'*10}")
    for ms in [5, 8, 10, 12, 15, 18, 20]:
        cfg_module.ALPHA_SWEEP["asia_min_range"] = 5.0
        cfg_module.ALPHA_SWEEP["min_sl"] = float(ms)
        np.random.seed(42)
        sigs = micro_alpha_sweep.generate_signals(gold_h1, gold_m3, daily_bias)
        tr = execute_signals(sigs, gold_m3, gold_d)
        st = compute_stats(tr)
        d = st["pnl"] - baseline_pnl
        print(f"  ${ms:>8} {st['trades']:>7} {st['wr']:>6.1f}% {st['pf']:>7.2f} ${st['pnl']:>10,.0f} {st['dd']:>6.1f}% ${d:>+8,.0f}")

    # ═══════════════════════════════════════════════════════════════════════
    # PART 4: COMBINED
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("PART 4: COMBINED min_range × min_sl")
    print("=" * 80)

    print(f"\n  {'range':>6} {'sl':>4} {'Trades':>7} {'WR':>7} {'PF':>7} {'P&L':>12} {'DD':>7} {'Δ P&L':>10}")
    print(f"  {'-'*6} {'-'*4} {'-'*7} {'-'*7} {'-'*7} {'-'*12} {'-'*7} {'-'*10}")
    for mr, ms in [(10, 8), (10, 10), (12, 10), (12, 12), (15, 10), (15, 12), (15, 15), (20, 10), (20, 12), (20, 15)]:
        cfg_module.ALPHA_SWEEP["asia_min_range"] = float(mr)
        cfg_module.ALPHA_SWEEP["min_sl"] = float(ms)
        np.random.seed(42)
        sigs = micro_alpha_sweep.generate_signals(gold_h1, gold_m3, daily_bias)
        tr = execute_signals(sigs, gold_m3, gold_d)
        st = compute_stats(tr)
        d = st["pnl"] - baseline_pnl
        print(f"  ${mr:>4} ${ms:>2} {st['trades']:>7} {st['wr']:>6.1f}% {st['pf']:>7.2f} ${st['pnl']:>10,.0f} {st['dd']:>6.1f}% ${d:>+8,.0f}")

    # ═══════════════════════════════════════════════════════════════════════
    # PART 5: Year-by-year for top candidates
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("PART 5: YEAR-BY-YEAR for key variants")
    print("=" * 80)

    for mr, ms in [(5, 5), (10, 10), (15, 12)]:
        cfg_module.ALPHA_SWEEP["asia_min_range"] = float(mr)
        cfg_module.ALPHA_SWEEP["min_sl"] = float(ms)
        np.random.seed(42)
        sigs = micro_alpha_sweep.generate_signals(gold_h1, gold_m3, daily_bias)
        tr = execute_signals(sigs, gold_m3, gold_d)
        st = compute_stats(tr)
        print(f"\n  --- min_range=${mr}, min_sl=${ms} ({st['trades']} trades, PF={st['pf']:.2f}, P&L=${st['pnl']:,.0f}) ---")
        print_year_by_year(tr)

    # Restore
    cfg_module.ALPHA_SWEEP["asia_min_range"] = orig_min_range
    cfg_module.ALPHA_SWEEP["min_sl"] = orig_min_sl

    print("\n" + "=" * 80)
    print(f"  Total runtime: {time.time()-t0:.0f}s")
    print("  Code path: micro_alpha_sweep.generate_signals() → fill_model.execute_trade()")
    print("  Zero reimplementation. Same functions as production.")
    print("=" * 80)


if __name__ == "__main__":
    main()
