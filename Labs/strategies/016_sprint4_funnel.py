"""016 — Funnel diagnostic. How many bars survive each stage?

Picks EUR_USD top config and counts:
  - Total H1 bars in dev window
  - H1 bars where D1 bias is non-neutral
  - H1 bars where H4 sweep also fires
  - H1 bars where H1 confirmation also fires
  - H1 bars where M15 engulf entry also fires (= signals)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from Labs.shared.data_forex import get_forex

_p = Path(__file__).resolve().parent / "013_bearishharry_forex.py"
_spec = importlib.util.spec_from_file_location("bh", _p)
_m = importlib.util.module_from_spec(_spec)
sys.modules["bh"] = _m
_spec.loader.exec_module(_m)


def funnel(symbol: str) -> None:
    bundle = get_forex(symbol)
    cfg = _m.BearishHarryConfig(
        sweep_lookback_hours=12,
        h1_confirmation="rejection_wick",
        m15_entry="engulf_close",
        rr=3.0,
    )

    n_total = 0
    n_bias_bull = 0
    n_bias_bear = 0
    n_bias = 0
    n_sweep = 0
    n_h1_conf = 0
    n_m15_entry = 0

    bias_days_set = set()  # unique days with non-neutral bias

    for h1_open_ts in bundle.h1.index:
        n_total += 1
        h1_close_ts = h1_open_ts + pd.Timedelta(hours=1)
        bias = _m._daily_bias(bundle.d1, h1_close_ts)
        if bias == "none":
            continue
        n_bias += 1
        if bias == "bull":
            n_bias_bull += 1
        else:
            n_bias_bear += 1
        bias_days_set.add(h1_close_ts.date())

        if not _m._h4_sweep_found(bundle.h4, h1_close_ts, bias, cfg.sweep_lookback_hours):
            continue
        n_sweep += 1

        if not _m._h1_confirmation(bundle.h1, h1_close_ts, bias, cfg.h1_confirmation, cfg.min_rejection_wick_ratio):
            continue
        n_h1_conf += 1

        m15_result = _m._m15_entry(bundle.m15, h1_close_ts, bias, cfg.m15_entry)
        if m15_result is None:
            continue
        n_m15_entry += 1

    n_d1_total = len(bundle.d1)
    print()
    print(f"  {symbol} funnel (rejection_wick, 12h sweep, rr=3.0)")
    print("  " + "─" * 70)
    print(f"  Total D1 bars (trading days):      {n_d1_total:>8,}")
    print(f"  Days with non-neutral D1 bias:     {len(bias_days_set):>8,}  "
          f"({len(bias_days_set)/n_d1_total*100:.1f}% of days)")
    print()
    print(f"  Total H1 bars in dev window:       {n_total:>8,}")
    print(f"  H1 bars when D1 bias is bull:      {n_bias_bull:>8,}")
    print(f"  H1 bars when D1 bias is bear:      {n_bias_bear:>8,}")
    print(f"  H1 bars with ANY non-neutral bias: {n_bias:>8,}  "
          f"({n_bias/n_total*100:.1f}% pass-through)")
    print(f"  + H4 sweep within 12h:             {n_sweep:>8,}  "
          f"({n_sweep/max(n_bias,1)*100:.1f}% of biased)")
    print(f"  + H1 rejection wick (1.5x body):   {n_h1_conf:>8,}  "
          f"({n_h1_conf/max(n_sweep,1)*100:.1f}% of swept)")
    print(f"  + M15 engulf in next hour:         {n_m15_entry:>8,}  "
          f"({n_m15_entry/max(n_h1_conf,1)*100:.1f}% of confirmed)")
    print()
    print(f"  Final signals = {n_m15_entry} over ~{n_d1_total/250:.1f} years")
    print(f"  → ~{n_m15_entry/(n_d1_total/250):.1f} signals/year")
    print()


def main() -> None:
    print("=" * 78)
    print("  Sprint 4 — Funnel diagnostic: where do candidates die?")
    print("=" * 78)
    for sym in ["EUR_USD", "USD_JPY", "XAU_USD"]:
        funnel(sym)


if __name__ == "__main__":
    main()
