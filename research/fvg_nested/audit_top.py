"""Audit top FVG nested variants with 9-test adversarial battery."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import load_data, headline, print_headline
from research.fvg_nested.run_fvg_fast import (
    resample, detect_fvgs, gen_signals_fast, simulate_with_limit
)


TOP = [
    dict(direction="short", fvg_max_age_h=4, session="all",
         swing_lookback=20, require_m15_inside_h4=False, tp=4.0,
         label="short_age4h_all_sw20_inside0_TP4R"),
    dict(direction="short", fvg_max_age_h=4, session="all",
         swing_lookback=20, require_m15_inside_h4=False, tp=3.0,
         label="short_age4h_all_sw20_inside0_TP3R"),
    dict(direction="long", fvg_max_age_h=4, session="all",
         swing_lookback=30, require_m15_inside_h4=False, tp=4.0,
         label="long_age4h_all_sw30_inside0_TP4R"),
    dict(direction="short", fvg_max_age_h=12, session="all",
         swing_lookback=20, require_m15_inside_h4=True, tp=4.0,
         label="short_age12h_all_sw20_inside1_TP4R"),
    dict(direction="long", fvg_max_age_h=72, session="london",
         swing_lookback=20, require_m15_inside_h4=True, tp=4.0,
         label="long_age72h_london_sw20_inside1_TP4R"),
]


def audit(label, sigs, m5_arr, tp_base):
    print(f"\n=== AUDIT {label} ===\nsignals: {len(sigs)}")
    h = headline(simulate_with_limit(m5_arr, sigs, tp_mult=tp_base))
    print_headline("baseline", h)
    for d in [1, 3, 5, 10]:
        s = sigs.copy(); s["signal_index"] = s["signal_index"].astype(int) + d
        h = headline(simulate_with_limit(m5_arr, s, tp_mult=tp_base))
        print_headline(f"+{d} bar delay", h)
    flip = sigs.copy(); flip["side"] = -flip["side"].astype(int)
    # flip limit/stop too — but messy. simpler: just flip side, leave limit/stop. real test = re-generate opposite.
    h = headline(simulate_with_limit(m5_arr, flip, tp_mult=tp_base))
    print_headline("FLIP", h)
    for extra in [0.10, 0.20, 0.50]:
        h = headline(simulate_with_limit(m5_arr, sigs, tp_mult=tp_base, cost_usd=0.30 + extra))
        print_headline(f"cost+${extra:.2f}", h)
    is_mask = sigs["signal_index"].values < int(0.6 * 475810)
    h_is = headline(simulate_with_limit(m5_arr, sigs[is_mask], tp_mult=tp_base))
    h_oos = headline(simulate_with_limit(m5_arr, sigs[~is_mask], tp_mult=tp_base))
    print_headline("IS first 60%", h_is)
    print_headline("OOS last 40%", h_oos)
    trades = simulate_with_limit(m5_arr, sigs, tp_mult=tp_base)
    if len(trades) > 5:
        rng = np.random.default_rng(42)
        nets = np.array([trades["net_r"].sample(n=len(trades), replace=True,
                                                  random_state=rng.integers(10**9)).sum()
                          for _ in range(3000)])
        print(f"BOOTSTRAP n=3000: P(net<0)={(nets<0).mean()*100:.2f}%  p05={np.percentile(nets,5):+.1f}R")
    if len(trades):
        y = trades.groupby("year")["net_r"].sum().round(2)
        print(f"by year: {y.to_dict()}")


def main():
    print("[load] frames + FVGs...")
    m1, m5, _ = load_data()
    h4_fvgs = detect_fvgs(resample(m1, "4h"))
    m15_fvgs = detect_fvgs(resample(m1, "15min"))
    m5_arr = {
        "open": m5["open"].values, "high": m5["high"].values,
        "low": m5["low"].values, "close": m5["close"].values,
        "ts": m5["timestamp"].values, "year": m5["year"].values,
    }
    for cfg in TOP:
        sigs = gen_signals_fast(
            m5, h4_fvgs, m15_fvgs,
            direction=cfg["direction"], fvg_max_age_h=cfg["fvg_max_age_h"],
            session=cfg["session"], swing_lookback=cfg["swing_lookback"],
            require_m15_inside_h4=cfg["require_m15_inside_h4"],
        )
        if len(sigs) == 0:
            print(f"\n=== {cfg['label']}: NO SIGNALS"); continue
        audit(cfg["label"], sigs, m5_arr, cfg["tp"])


if __name__ == "__main__":
    main()
