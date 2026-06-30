"""Final optimisation around TOP1: long H4 ema20 tol=0.3 close-confirm london sw=20.

Vary: TP, swing_lookback (5/10/15/20/30/50), pullback_tol (0.1, 0.2, 0.3, 0.5),
also test +EMA50 second condition, +RSI>50 momentum filter.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import load_data, simulate, headline, persist, print_headline, gate
from research.traderzden_retest.run_sweep import (
    prep_full_frame, gen_signals, add_swings
)


def main():
    m1, m5, _ = load_data()
    df = prep_full_frame(m1, m5, trend_tfs=["H4"], swing_lookbacks=[5, 10, 15, 20, 30, 50])

    base_cfg = dict(direction="long", trend_tf="H4", pullback="ema20",
                    confirm="close", session="london")

    print("\n=== Tune around TOP1 (long H4 ema20 close london) ===\n")
    out_rows = []
    for tol in [0.1, 0.2, 0.3, 0.4, 0.5, 0.7]:
        for sw in [5, 10, 15, 20, 30, 50]:
            for tp in [2.0, 3.0, 4.0, 5.0]:
                sigs = gen_signals(df, **base_cfg, pullback_tol=tol, swing_lookback=sw)
                if len(sigs) == 0:
                    continue
                trades = simulate(sigs, df, tp_mult=tp)
                if len(trades) == 0:
                    continue
                h = headline(trades)
                g = gate(h)
                label = f"H4_ema20_close_london_tol{tol}_sw{sw}_TP{tp}R"
                row = {"tol": tol, "sw": sw, "tp": tp, **h,
                       **{f"gate_{k}": v for k, v in g.items()}, "label": label}
                out_rows.append(row)
                if h["pf"] >= 1.4 and "/" in h["pos_years"]:
                    pos = int(h["pos_years"].split("/")[0])
                    if pos >= 7:
                        print_headline(label, h)
                        persist("traderzden_retest", label, trades, notes="TOP1 tuned")

    lb = pd.DataFrame(out_rows).sort_values("mar", ascending=False).head(20)
    print("\n[TUNED TOP 20 by MAR]\n")
    print(lb[["tol", "sw", "tp", "n", "trades_per_year", "pf", "mar", "pos_years"]].to_string(index=False))
    out_path = Path("/Users/subash/SUBASH/GoldDigger/research/traderzden_retest/tuned_leaderboard.csv")
    pd.DataFrame(out_rows).to_csv(out_path, index=False)
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
