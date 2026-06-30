"""Adversarial audit on the two PDF strategies. Same 9-test battery
used for Martin Luke. Confirms whether even the marginal-PF variants
are real or microstructure leak.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.harness.causal_sim import load_data, simulate, headline, print_headline
from research.confluence_xau.run_confluence import build_features as build_confluence, generate_signals as gen_confluence
from research.rsi_divergence.run_rsi_div_m15 import (
    build_m15_features, build_h1_zones, generate_long_m15_h1
)


def shift_entry(sigs: pd.DataFrame, delta: int) -> pd.DataFrame:
    out = sigs.copy()
    out["entry_index"] = out["entry_index"].astype(int) + delta
    return out


def flip_direction(sigs: pd.DataFrame) -> pd.DataFrame:
    out = sigs.copy()
    out["side"] = -out["side"].astype(int)
    return out


def audit_strategy(name: str, sigs: pd.DataFrame, df: pd.DataFrame, base_tp: float):
    print(f"\n=== AUDIT {name} (TP={base_tp}R) ===")
    h0 = headline(simulate(sigs, df, tp_mult=base_tp))
    print_headline("baseline", h0)

    for d in [1, 3, 5, 10]:
        s = shift_entry(sigs, d)
        h = headline(simulate(s, df, tp_mult=base_tp))
        print_headline(f"delay +{d} bars", h)

    flip = flip_direction(sigs)
    h = headline(simulate(flip, df, tp_mult=base_tp))
    print_headline("RANDOM_DIR (flip)", h)

    for extra in [0.10, 0.20, 0.50]:
        cost_total = 0.30 + extra
        h = headline(simulate(sigs, df, tp_mult=base_tp, cost_usd=cost_total))
        print_headline(f"cost+{extra:.2f}USD", h)

    is_mask = sigs["entry_index"] < int(0.6 * len(df))
    h_is = headline(simulate(sigs[is_mask], df, tp_mult=base_tp))
    h_oos = headline(simulate(sigs[~is_mask], df, tp_mult=base_tp))
    print_headline("IS (first 60%)", h_is)
    print_headline("OOS (last 40%)", h_oos)


def main():
    print("[load] frames...")
    m1, m5, _ = load_data()

    print("\n--- A: Confluence (PDF1) long ---")
    df_cf = build_confluence(m5)
    sigs_long = gen_confluence(df_cf, direction="long")
    if len(sigs_long) > 0:
        audit_strategy("confluence_long", sigs_long, df_cf, base_tp=3.0)

    print("\n--- A: Confluence (PDF1) short ---")
    sigs_short = gen_confluence(df_cf, direction="short")
    if len(sigs_short) > 0:
        audit_strategy("confluence_short", sigs_short, df_cf, base_tp=3.0)

    print("\n--- B: RSI Div M15+H1 long ---")
    m15 = build_m15_features(m1)
    h1 = build_h1_zones(m1)
    sigs_rsi = generate_long_m15_h1(m15, h1)
    if len(sigs_rsi) > 0:
        audit_strategy("rsidiv_m15_h1zone_long", sigs_rsi, m15, base_tp=4.0)


if __name__ == "__main__":
    main()
