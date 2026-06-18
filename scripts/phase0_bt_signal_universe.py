"""Pull BT's full signal universe (output of generate_signals before execution loop)
for both Micros. This is the apples-to-apples comparand to live dry_run signals.
"""
from __future__ import annotations
import os, sys, importlib

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)


def get_bt_signal_universe(label, pkg_dir, instrument, strategy_module_path,
                            generate_signals_args_builder):
    print(f"\n{'='*60}")
    print(f"=== {label} BT signal universe ===")
    print(f"{'='*60}")
    for k in list(sys.modules.keys()):
        if k.startswith(("scanner", "config", "backtest", "strategies",
                         "backend.execution", "backend.strategies", "backend.backtest",
                         "backend.data")):
            del sys.modules[k]
    pkg_path = os.path.join(ROOT, pkg_dir)
    if pkg_path in sys.path:
        sys.path.remove(pkg_path)
    sys.path.insert(0, pkg_path)
    importlib.invalidate_caches()

    engine = importlib.import_module("backtest.engine")
    data = engine._get_cached_data() if hasattr(engine, "_get_cached_data") else None

    # Need to call generate_signals directly. Path differs per system.
    strat_mod = importlib.import_module(strategy_module_path)

    # Build neutral daily_bias dict
    from backend.backtest.neutral_bias import NeutralBiasDict
    daily_bias = NeutralBiasDict()

    args = generate_signals_args_builder(data, daily_bias)
    signals = strat_mod.generate_signals(*args)
    print(f"  total signals (generate_signals output): {len(signals)}")

    # Filter to Jun 11-18
    import pandas as pd
    start = pd.Timestamp("2026-06-11", tz="UTC")
    end = pd.Timestamp("2026-06-18 23:59:59", tz="UTC")
    window = [s for s in signals if start <= s.date <= end]
    print(f"  Jun 11-18 signals: {len(window)}")
    for s in window:
        print(f"    {s.date} {s.direction} entry={s.entry:.4f} sl={s.sl:.4f}")
    return window


# Gold Micro
def gm_args(data, daily_bias):
    return (data["gold_h1"], data["gold_m3"], daily_bias)

gm_signals = get_bt_signal_universe(
    "Gold Micro",
    "backend-micro",
    "XAU_USD",
    "backend.strategies.micro_alpha_sweep",
    gm_args,
)

# Oil Micro - generate_signals is inline in engine.py
def om_args(data, daily_bias):
    return (data["oil_h1"], data["oil_m3"], daily_bias)

print(f"\n{'='*60}")
print(f"=== Oil Micro BT signal universe ===")
print(f"{'='*60}")
for k in list(sys.modules.keys()):
    if k.startswith(("scanner", "config", "backtest", "strategies",
                     "backend.execution", "backend.strategies", "backend.backtest",
                     "backend.data")):
        del sys.modules[k]
pkg_path = os.path.join(ROOT, "backend-oil-micro")
if pkg_path in sys.path:
    sys.path.remove(pkg_path)
sys.path.insert(0, pkg_path)
importlib.invalidate_caches()

engine = importlib.import_module("backtest.engine")
data = engine._get_cached_data()
from backend.backtest.neutral_bias import NeutralBiasDict
daily_bias = NeutralBiasDict()
oil_signals = engine.generate_signals(data["oil_h1"], data["oil_m3"], daily_bias)
print(f"  total signals: {len(oil_signals)}")

import pandas as pd
start = pd.Timestamp("2026-06-11", tz="UTC")
end = pd.Timestamp("2026-06-18 23:59:59", tz="UTC")
om_window = [s for s in oil_signals if start <= s.date <= end]
print(f"  Jun 11-18 signals: {len(om_window)}")
for s in om_window:
    print(f"    {s.date} {s.direction} entry={s.entry:.4f} sl={s.sl:.4f}")

print(f"\n{'='*60}")
print(f"SUMMARY")
print(f"{'='*60}")
print(f"  Gold Micro BT signal universe: {len(gm_signals)}")
print(f"  Oil Micro BT signal universe : {len(om_window)}")
