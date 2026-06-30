"""Audit top-3 TraderzDen variants — 9-test adversarial battery + IS/OOS + bootstrap."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import load_data, simulate, headline, print_headline
from research.traderzden_retest.run_sweep import (
    prep_full_frame, gen_signals
)


TOP = [
    dict(direction="long", trend_tf="H4", pullback="ema20", pullback_tol=0.3,
         confirm="close", session="london", swing_lookback=20, tp=4.0),
    dict(direction="long", trend_tf="H4", pullback="ema20", pullback_tol=1.0,
         confirm="strong_body", session="london", swing_lookback=20, tp=4.0),
    dict(direction="long", trend_tf="H1", pullback="ema50", pullback_tol=1.0,
         confirm="engulf", session="london", swing_lookback=20, tp=4.0),
]


def audit_variant(df: pd.DataFrame, cfg: dict, label: str):
    print(f"\n=== AUDIT {label} ===")
    g_kwargs = {k: v for k, v in cfg.items() if k != "tp"}
    tp = cfg["tp"]
    sigs = gen_signals(df, **g_kwargs)
    print(f"baseline signals: {len(sigs)}")

    h0 = headline(simulate(sigs, df, tp_mult=tp))
    print_headline("baseline", h0)

    for d in [1, 3, 5, 10]:
        s = sigs.copy(); s["entry_index"] = s["entry_index"].astype(int) + d
        h = headline(simulate(s, df, tp_mult=tp))
        print_headline(f"+{d} bar delay", h)

    flip = sigs.copy(); flip["side"] = -flip["side"].astype(int)
    h = headline(simulate(flip, df, tp_mult=tp))
    print_headline("FLIP", h)

    for extra in [0.10, 0.20, 0.50]:
        h = headline(simulate(sigs, df, tp_mult=tp, cost_usd=0.30 + extra))
        print_headline(f"cost+${extra:.2f}", h)

    is_mask = sigs["entry_index"] < int(0.6 * len(df))
    h_is = headline(simulate(sigs[is_mask], df, tp_mult=tp))
    h_oos = headline(simulate(sigs[~is_mask], df, tp_mult=tp))
    print_headline("IS first 60%", h_is)
    print_headline("OOS last 40%", h_oos)

    # bootstrap
    trades = simulate(sigs, df, tp_mult=tp)
    rng = np.random.default_rng(42)
    nets = []
    for _ in range(5000):
        sample = trades["net_r"].sample(n=len(trades), replace=True, random_state=rng.integers(0, 10**9))
        nets.append(sample.sum())
    nets = np.array(nets)
    p_neg = (nets < 0).mean()
    p05 = np.percentile(nets, 5)
    print(f"BOOTSTRAP n=5000: P(net<0)={p_neg*100:.2f}%  p05={p05:+.1f}R")

    # year-by-year
    y = trades.groupby("year")["net_r"].sum().round(2)
    print(f"by year: {y.to_dict()}")


def main():
    print("[load] frames...")
    m1, m5, _ = load_data()
    df = prep_full_frame(m1, m5, trend_tfs=["H1", "H4", "D1"], swing_lookbacks=[10, 20])

    for i, cfg in enumerate(TOP):
        audit_variant(df, cfg, label=f"TOP{i+1}_{cfg['trend_tf']}_{cfg['pullback']}_{cfg['confirm']}")


if __name__ == "__main__":
    main()
