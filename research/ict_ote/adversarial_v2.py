"""Full adversarial + 15-point audit on the credible v2 config: H1 LONG OTE.

Big-numbers mandate: n=13 H4 configs are PHANTOMS (ignored). Only H1-long n~287
is worth vetting. Battery: causal self-test, +1/+2/+3 delay, cost stress,
bootstrap P(net<=0), year-by-year, IS/OOS split.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import load_data, headline, print_headline  # noqa: E402
from research.ict_ote.run_ote import simulate_price_bracket  # noqa: E402
from research.ict_ote.run_ote_v2 import build_htf, build_signals_v2  # noqa: E402

CFG = dict(swing_k=3, min_conf=4, require_fvg=True, sides=(+1,))


def delayed(sig, m5, d):
    s = sig.copy()
    s["fill_index"] = s["fill_index"] + d
    n = len(m5)
    s = s[s["fill_index"] < n - 2].reset_index(drop=True)
    op = m5["open"].values
    s["entry_price"] = op[s["fill_index"].values]
    s["risk_units"] = (s["entry_price"] - s["sl_price"]).abs()
    return s[s["risk_units"] > 0].reset_index(drop=True)


if __name__ == "__main__":
    m1, m5, m15 = load_data()
    htf = build_htf(m1, "1h")
    sig = build_signals_v2(m5, htf, htf_rule_min=60, **CFG)
    print(f"H1 LONG OTE — signals: {len(sig)}")

    # causal self-test
    arm = pd.to_datetime(sig["arm_ts"]).values
    fill_ts = m5["timestamp"].values[sig["fill_index"].values]
    assert (fill_ts >= arm).all(), "LEAK"
    print("Causal self-test PASS (fills at/after CHoCH-confirm arm_ts).\n")

    base = simulate_price_bracket(sig, m5)
    print("=== Delay robustness ===")
    print_headline("delay +0 (base)", headline(base))
    for d in (1, 2, 3):
        print_headline(f"delay +{d}", headline(simulate_price_bracket(delayed(sig, m5, d), m5)))

    print("\n=== Cost stress ($/risk_units) ===")
    for c in (0.30, 0.50, 0.80, 1.20):
        tr = simulate_price_bracket(sig, m5, cost_usd=c)
        print_headline(f"cost ${c:.2f}", headline(tr))

    print("\n=== Bootstrap P(net<=0), 2000 resamples ===")
    r = base["net_r"].values
    rng = np.random.default_rng(42)
    boots = np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(2000)])
    print(f"  net={r.sum():+.1f}R  mean_boot={boots.mean():+.1f}  P(net<=0)={(boots <= 0).mean():.3f}")

    print("\n=== IS/OOS split (2019-2023 IS | 2024-2026 OOS) ===")
    for lbl, sub in [("IS 2019-23", base[base.year <= 2023]),
                     ("OOS 2024-26", base[base.year >= 2024])]:
        print_headline(lbl, headline(sub))

    print("\n=== Year-by-year ===")
    print(base.groupby("year")["net_r"].agg(["sum", "count"]).round(1).to_string())
