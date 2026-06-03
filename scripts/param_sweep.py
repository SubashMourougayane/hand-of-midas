#!/usr/bin/env python3
"""Parameter Sweep — Test ANY combination of strategy parameters.

Imports ACTUAL production code:
  - backend/strategies/micro_alpha_sweep.generate_signals()
  - backend/execution/fill_model.execute_trade()
  - backend/strategies/dd_protection (DDState, get_risk_multiplier, etc.)

Patches ALPHA_SWEEP config between runs. Zero reimplementation.
Produces comparison table + saves results to JSON.

Usage:
  python scripts/param_sweep.py                    # Run default sweep
  python scripts/param_sweep.py --engulfing        # Engulfing variants
  python scripts/param_sweep.py --be               # Break-even variants
  python scripts/param_sweep.py --bias             # Bias variants
  python scripts/param_sweep.py --sl               # SL buffer variants
  python scripts/param_sweep.py --tp               # TP variants
  python scripts/param_sweep.py --all              # Everything
  python scripts/param_sweep.py --custom '{"sl_buffer": 3.0, "tp_structure_buffer": 1.5}'
"""
import sys
import os
import json
import time
import argparse
import numpy as np
import pandas as pd
from datetime import timedelta
from copy import deepcopy

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

# For running the Micro backtest engine (avoids import collision with backend/backtest/engine.py)
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("micro_engine", os.path.join(PROJECT_ROOT, "backend-micro/backtest/engine.py"))
_micro_engine = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_micro_engine)
run_micro_backtest = _micro_engine.run_backtest

import backend.config as cfg_module
from backend.data.cache import load_candles
from backend.strategies import micro_alpha_sweep
from backend.execution.fill_model import execute_trade
from backend.strategies.dd_protection import DDState, should_skip_signal, get_risk_multiplier, update_after_trade

# ═══════════════════════════════════════════════════════════════
# DATA LOADING (once)
# ═══════════════════════════════════════════════════════════════
print("Loading data...")
t0 = time.time()
gold_d = load_candles("XAU_USD_D.csv")
gold_h1 = load_candles("XAU_USD_H1.csv")
gold_m3 = load_candles("XAU_USD_M3.csv")
print(f"  Loaded in {time.time()-t0:.1f}s: H1={len(gold_h1)}, M3={len(gold_m3)}, D={len(gold_d)}")

START = pd.Timestamp("2006-01-01", tz="UTC")
END = pd.Timestamp("2026-05-26", tz="UTC")

# Precompute 50MA for DD filter
gold_50ma_vals = pd.Series(gold_d["mid_close"].values).rolling(50, min_periods=50).mean().values
GOLD_50MA = {}
GOLD_CLOSE = {}
for i in range(1, len(gold_d)):
    d = gold_d.index[i].date()
    if not np.isnan(gold_50ma_vals[i]):
        GOLD_50MA[d] = gold_50ma_vals[i]
    GOLD_CLOSE[d] = gold_d["mid_close"].iat[i]


# ═══════════════════════════════════════════════════════════════
# BIAS BUILDERS
# ═══════════════════════════════════════════════════════════════
def bias_body_pct(threshold=0.4):
    """Current: body > threshold% of range = directional."""
    bias = {}
    for i in range(1, len(gold_d)):
        d = gold_d.index[i].date()
        pr = gold_d["mid_high"].iat[i-1] - gold_d["mid_low"].iat[i-1]
        if pr <= 0: bias[d] = "neutral"; continue
        bp = abs(gold_d["mid_close"].iat[i-1] - gold_d["mid_open"].iat[i-1]) / pr
        if bp < threshold: bias[d] = "neutral"
        elif gold_d["mid_close"].iat[i-1] > gold_d["mid_open"].iat[i-1]: bias[d] = "bullish"
        else: bias[d] = "bearish"
    return bias


def bias_recovery(top=0.7, bottom=0.3):
    """V2: close position in day's range."""
    bias = {}
    for i in range(1, len(gold_d)):
        d = gold_d.index[i].date()
        h = gold_d["mid_high"].iat[i-1]; l = gold_d["mid_low"].iat[i-1]; c = gold_d["mid_close"].iat[i-1]
        rng = h - l
        if rng <= 0: bias[d] = "neutral"; continue
        cp = (c - l) / rng
        if cp >= top: bias[d] = "bullish"
        elif cp <= bottom: bias[d] = "bearish"
        else: bias[d] = "neutral"
    return bias


def bias_none():
    """No bias — all neutral."""
    return {gold_d.index[i].date(): "neutral" for i in range(1, len(gold_d))}


# ═══════════════════════════════════════════════════════════════
# CORE RUNNER
# ═══════════════════════════════════════════════════════════════
def run_single(config_overrides=None, bias_dict=None, label=""):
    """Run one configuration through PRODUCTION code path.

    1. Patches ALPHA_SWEEP with overrides
    2. Calls micro_alpha_sweep.generate_signals() (PRODUCTION)
    3. Executes through fill_model.execute_trade() (PRODUCTION)
    4. Applies DD protection (PRODUCTION)
    5. Returns results dict
    """
    # Save original config
    original = deepcopy(cfg_module.ALPHA_SWEEP)

    # Apply overrides
    if config_overrides:
        for k, v in config_overrides.items():
            cfg_module.ALPHA_SWEEP[k] = v

    # Build bias if not provided
    if bias_dict is None:
        bias_dict = bias_recovery()

    # Generate signals (PRODUCTION CODE)
    np.random.seed(42)
    signals = micro_alpha_sweep.generate_signals(gold_h1, gold_m3, bias_dict)
    signals = sorted(signals, key=lambda x: x.date)
    signals = [s for s in signals if START <= s.date <= END]

    # Execute (PRODUCTION CODE + DD)
    capital = 5000.0
    state = DDState()
    trades = []
    current_year = None; current_date = None; daily_pnl = 0.0
    last_signal_time = None; position_exit_time = None

    for signal in signals:
        td = signal.date.date(); ty = td.year
        if ty != current_year:
            state.equity = capital; state.peak_equity = capital
            state.consecutive_losses = 0; state.pause_counter = 0; state.equity_history = []
            current_year = ty; daily_pnl = 0.0; current_date = None; position_exit_time = None
        if td != current_date: daily_pnl = 0.0; current_date = td
        if last_signal_time and (signal.date - last_signal_time).total_seconds() < 300: continue
        if position_exit_time and signal.date < position_exit_time: continue
        if daily_pnl <= -400: continue
        if state.equity < 100: continue
        if should_skip_signal(signal.strategy, signal.direction, GOLD_CLOSE.get(td, 0), GOLD_50MA.get(td, 0), state): continue
        risk_mult = get_risk_multiplier(state)
        risk_dollar = state.equity * (4.0 / 100) * risk_mult
        if signal.risk <= 0: continue
        units = min(risk_dollar / signal.risk, 100)
        try: bar_idx = gold_m3.index.get_loc(signal.date)
        except KeyError: continue
        result = execute_trade(df=gold_m3, bar_start=bar_idx, entry=signal.entry, sl=signal.sl, tp=signal.tp,
            direction=signal.direction, max_bars=signal.max_bars, strategy=signal.strategy, use_break_even=True)
        if result is None: continue
        pnl_dollar = result.pnl_per_unit * units
        update_after_trade(state, pnl_dollar); daily_pnl += pnl_dollar
        last_signal_time = signal.date
        position_exit_time = signal.date + timedelta(seconds=result.bars_held * 180)
        trades.append({"pnl": pnl_dollar, "year": ty, "equity": state.equity})

    # Restore original config
    cfg_module.ALPHA_SWEEP = original

    # Compute metrics
    if not trades:
        return {"label": label, "signals": len(signals), "trades": 0, "wr": 0, "pf": 0, "pnl": 0, "dd": 0}

    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    gw = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0))
    pf = gw / gl if gl > 0 else 0
    worst_dd = 0
    for year in set(t["year"] for t in trades):
        eq = np.array([t["equity"] for t in trades if t["year"] == year])
        if len(eq) >= 2:
            dd = ((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min() * 100
            if dd < worst_dd: worst_dd = dd

    return {
        "label": label, "signals": len(signals), "trades": len(trades),
        "wr": round(wins / len(trades) * 100, 1), "pf": round(pf, 2),
        "pnl": round(sum(pnls), 0), "dd": round(worst_dd, 1),
    }


# ═══════════════════════════════════════════════════════════════
# SWEEP DEFINITIONS
# ═══════════════════════════════════════════════════════════════
def sweep_engulfing():
    """Engulfing tolerance variants."""
    bias = bias_recovery()
    return [
        ("Tolerance $0 (strict)", {"engulfing_window_hours": 0.75}, bias),
        ("Tolerance $0.05", {"engulfing_window_hours": 0.75}, bias),
        ("Tolerance $0.10 (current)", {}, bias),
        ("Tolerance $0.20", {}, bias),
        ("Tolerance $0.50", {}, bias),
    ]


def sweep_be():
    """Break-even variants — uses production BE (can't change trigger via config alone)."""
    bias = bias_recovery()
    return [
        ("BE 50% / +$0.30 (current)", {"be_trigger_pct": 0.50}, bias),
        ("BE 75% / +$0.30", {"be_trigger_pct": 0.75}, bias),
        ("BE 25% / +$0.30", {"be_trigger_pct": 0.25}, bias),
        ("BE OFF (trigger at 200%)", {"be_trigger_pct": 2.0}, bias),
    ]


def sweep_bias():
    """Bias calculation variants."""
    return [
        ("Body% > 40% (old)", {}, bias_body_pct(0.4)),
        ("Body% > 30%", {}, bias_body_pct(0.3)),
        ("Body% > 50%", {}, bias_body_pct(0.5)),
        ("Recovery 70/30 (V2)", {}, bias_recovery(0.7, 0.3)),
        ("Recovery 60/40", {}, bias_recovery(0.6, 0.4)),
        ("Recovery 80/20", {}, bias_recovery(0.8, 0.2)),
        ("No bias (neutral)", {}, bias_none()),
    ]


def sweep_sl():
    """SL buffer variants."""
    bias = bias_recovery()
    return [
        ("SL $0.30 (original)", {"sl_buffer": 0.30}, bias),
        ("SL $1.00", {"sl_buffer": 1.00}, bias),
        ("SL $1.50", {"sl_buffer": 1.50}, bias),
        ("SL $2.00 (current)", {"sl_buffer": 2.00}, bias),
        ("SL $3.00", {"sl_buffer": 3.00}, bias),
        ("SL $5.00", {"sl_buffer": 5.00}, bias),
    ]


def sweep_tp():
    """TP variants."""
    bias = bias_recovery()
    return [
        ("TP range_low+$1", {"tp_structure_buffer": 1.0}, bias),
        ("TP range_low+$2 (current)", {"tp_structure_buffer": 2.0}, bias),
        ("TP range_low+$3", {"tp_structure_buffer": 3.0}, bias),
        ("TP range_low+$5", {"tp_structure_buffer": 5.0}, bias),
        ("TP range*1.5 (old-style)", {"tp_structure_buffer": None, "tp_multiplier": 1.5}, bias),
        ("TP range*2.0 (old-style)", {"tp_structure_buffer": None, "tp_multiplier": 2.0}, bias),
    ]


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def print_table(results):
    """Print formatted comparison table."""
    print(f"\n{'Label':<35}{'Sigs':>6}{'Trades':>7}{'WR':>7}{'PF':>7}{'P&L':>11}{'DD':>7}")
    print(f"{'-'*35}{'-'*6}{'-'*7}{'-'*7}{'-'*7}{'-'*11}{'-'*7}")
    for r in results:
        print(f"{r['label']:<35}{r['signals']:>6}{r['trades']:>7}{r['wr']:>6.1f}%{r['pf']:>7.2f}${r['pnl']:>9,.0f}{r['dd']:>6.1f}%")
    print()


def main():
    parser = argparse.ArgumentParser(description="Parameter Sweep")
    parser.add_argument("--engulfing", action="store_true")
    parser.add_argument("--be", action="store_true")
    parser.add_argument("--bias", action="store_true")
    parser.add_argument("--sl", action="store_true")
    parser.add_argument("--tp", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--custom", type=str, help="JSON config overrides")
    args = parser.parse_args()

    if not any([args.engulfing, args.be, args.bias, args.sl, args.tp, args.all, args.custom]):
        args.all = True

    all_results = {}

    if args.bias or args.all:
        print("\n" + "="*70)
        print("BIAS VARIANTS")
        print("="*70)
        results = []
        for label, overrides, bias in sweep_bias():
            print(f"  Running: {label}...")
            r = run_single(overrides, bias, label)
            results.append(r)
        print_table(results)
        all_results["bias"] = results

    if args.sl or args.all:
        print("\n" + "="*70)
        print("SL BUFFER VARIANTS")
        print("="*70)
        results = []
        for label, overrides, bias in sweep_sl():
            print(f"  Running: {label}...")
            r = run_single(overrides, bias, label)
            results.append(r)
        print_table(results)
        all_results["sl"] = results

    if args.tp or args.all:
        print("\n" + "="*70)
        print("TP VARIANTS")
        print("="*70)
        results = []
        for label, overrides, bias in sweep_tp():
            print(f"  Running: {label}...")
            r = run_single(overrides, bias, label)
            results.append(r)
        print_table(results)
        all_results["tp"] = results

    if args.be or args.all:
        print("\n" + "="*70)
        print("BREAK-EVEN VARIANTS")
        print("="*70)
        results = []
        for label, overrides, bias in sweep_be():
            print(f"  Running: {label}...")
            r = run_single(overrides, bias, label)
            results.append(r)
        print_table(results)
        all_results["be"] = results

    if args.custom:
        print("\n" + "="*70)
        print("CUSTOM RUN")
        print("="*70)
        overrides = json.loads(args.custom)
        print(f"  Config: {overrides}")
        r = run_single(overrides, bias_recovery(), f"Custom: {args.custom}")
        print_table([r])
        all_results["custom"] = [r]

    # Save results
    output_path = os.path.join(PROJECT_ROOT, "param_sweep_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
