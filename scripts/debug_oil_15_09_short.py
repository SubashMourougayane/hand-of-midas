"""Debug: trace BT execution for the Jun 17 15:09 SHORT trade.

Reproduces the BT path manually so we can see exactly what bar_idx,
what bars get walked, and what numbers go into the exit decision.
"""
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

pkg_path = os.path.join(ROOT, "backend-oil")
if pkg_path in sys.path:
    sys.path.remove(pkg_path)
sys.path.insert(0, pkg_path)
importlib.invalidate_caches()

import pandas as pd
import numpy as np

# Load the SAME oil_m3 the BT loaded
engine = importlib.import_module("backtest.engine")
data = engine._get_cached_data()
oil_m3 = data["oil_m3"]

print(f"oil_m3 columns: {list(oil_m3.columns)}")
print(f"oil_m3 index dtype: {oil_m3.index.dtype}")
print(f"oil_m3 length: {len(oil_m3)}")
print()

# Find the 15:09 signal bar
target_ts = pd.Timestamp("2026-06-17 15:09:00", tz="UTC")
print(f"target_ts: {target_ts}")
print(f"target_ts in index: {target_ts in oil_m3.index}")
print()

bar_idx = oil_m3.index.get_loc(target_ts)
print(f"bar_idx: {bar_idx}")
print(f"oil_m3.index[{bar_idx}]: {oil_m3.index[bar_idx]}")
print()

# Print bar at index, plus next 5 bars
print("=== Bars from bar_idx (engulfing) through bar_idx+5 ===")
for i in range(bar_idx, bar_idx + 6):
    ts = oil_m3.index[i]
    bo = oil_m3["bid_open"].iat[i]
    bh = oil_m3["bid_high"].iat[i]
    bl = oil_m3["bid_low"].iat[i]
    bc = oil_m3["bid_close"].iat[i]
    ao = oil_m3["ask_open"].iat[i]
    ah = oil_m3["ask_high"].iat[i]
    al = oil_m3["ask_low"].iat[i]
    ac = oil_m3["ask_close"].iat[i]
    print(f"  [{i}] {ts}  bid: o={bo:.4f} h={bh:.4f} l={bl:.4f} c={bc:.4f}  ask: o={ao:.4f} h={ah:.4f} l={al:.4f} c={ac:.4f}")

print()
print("=== Trade params: SHORT entry=79.1798 sl=79.6350 tp=76.8298 ===")
print()

# Manually walk SHORT exit logic
entry = 79.1798
sl = 79.6350
tp = 76.8298
bars_held = 0

# Set the same RNG seed as run_backtest does
np.random.seed(42)

print("Walking SHORT logic from bar_idx+1...")
for b in range(bar_idx + 1, bar_idx + 6):
    bars_held += 1
    ts = oil_m3.index[b]
    ao = oil_m3["ask_open"].iat[b]
    ah = oil_m3["ask_high"].iat[b]
    al = oil_m3["ask_low"].iat[b]
    bar_range = ah - al

    print(f"  bar {bars_held} [{b}] {ts}: ask_open={ao:.4f} ask_high={ah:.4f} ask_low={al:.4f} range={bar_range:.4f}")

    if ao >= sl:
        slip = 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)
        exit_price = ao + slip * 0.2
        print(f"    ✓ GAP-THROUGH SL: ao={ao} >= sl={sl}, slip={slip:.4f}, exit={exit_price:.4f}")
        print(f"    bars_held={bars_held}")
        break

    if al <= tp:
        print(f"    ✓ TP hit at {tp}")
        break

    if ah >= sl:
        slip = 0.03 + bar_range * 0.003 + np.random.uniform(0, 0.02)
        exit_price = sl + slip * 0.2
        print(f"    ✓ SL TOUCH: ah={ah} >= sl={sl}, slip={slip:.4f}, exit={exit_price:.4f}")
        print(f"    bars_held={bars_held}")
        break

    print(f"    no exit, continue")
