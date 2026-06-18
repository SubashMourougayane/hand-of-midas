"""Trace Gold Micro BT for 2026-06-17 02:15 SHORT trade."""
from __future__ import annotations
import os
import sys
import importlib

ROOT = "/Users/subash/SUBASH/GoldDigger"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

for k in list(sys.modules.keys()):
    if k.startswith(("scanner", "config", "backtest", "strategies",
                     "backend.execution", "backend.strategies", "backend.backtest",
                     "backend.data")):
        del sys.modules[k]

pkg_path = os.path.join(ROOT, "backend-micro")
if pkg_path in sys.path:
    sys.path.remove(pkg_path)
sys.path.insert(0, pkg_path)
importlib.invalidate_caches()

import pandas as pd

fill_model = importlib.import_module("backend.execution.fill_model")
original_execute = fill_model.execute_trade

def patched_execute(df, bar_start, entry, sl, tp, direction, max_bars, strategy, **kwargs):
    bar_ts = df.index[bar_start]
    target_ts = pd.Timestamp("2026-06-17 02:15:00", tz="UTC")
    if bar_ts == target_ts and direction == "short":
        print(f"\n>>> CAUGHT TARGET TRADE <<<")
        print(f"   bar_start: {bar_start} ({bar_ts})")
        print(f"   entry={entry} sl={sl} tp={tp} direction={direction} strategy={strategy}")
        print(f"   kwargs: {kwargs}")
        for i in range(22):
            b = bar_start + i
            if b >= len(df):
                break
            ts = df.index[b]
            ah = df["ask_high"].iat[b]
            al = df["ask_low"].iat[b]
            ao = df["ask_open"].iat[b]
            ac = df["ask_close"].iat[b]
            bl = df["bid_low"].iat[b]
            bh = df["bid_high"].iat[b]
            print(f"   [{i}] {ts}: ask o={ao:.2f} h={ah:.2f} l={al:.2f} c={ac:.2f}  bid h={bh:.2f} l={bl:.2f}")
        result = original_execute(df, bar_start, entry, sl, tp, direction, max_bars, strategy, **kwargs)
        print(f"   RESULT: bars_held={result.bars_held} exit={result.exit_price:.4f} reason={result.exit_reason} pnl={result.pnl_per_unit:.4f}")
        if result.bars_held > 0:
            exit_b = bar_start + result.bars_held
            print(f"   exit bar logical (bar_start+bars_held): [{result.bars_held}] {df.index[exit_b]}")
        print(f"<<< END TRADE >>>\n")
        return result
    return original_execute(df, bar_start, entry, sl, tp, direction, max_bars, strategy, **kwargs)

fill_model.execute_trade = patched_execute

engine = importlib.import_module("backtest.engine")
engine.execute_trade = patched_execute

print("Running Gold Micro BT with patched execute_trade (single-strategy)...")
result = engine.run_backtest(strategies=["micro_alpha_sweep"], bias_mode="neutral")
print(f"Done. {len(result.trades)} total trades.")
