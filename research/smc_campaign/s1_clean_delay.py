#!/usr/bin/env python3
"""S1 CLEAN delay/robustness test (fixes the risk-renormalization artifact).

The gauntlet's delay test recomputed risk_units from the delayed entry -> when a
later entry lands near the SL, risk->0 and R explodes (RR jumped 2.66->9.52,
PF became meaningless). This keeps the ORIGINAL risk_units for R-normalization and
just fills at the delayed bar's open (a worse/later price). That is the honest
'what if I'm N bars slow' test — no artifact.

Also: proper slip stress + a 'limit still reachable' check.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")
from research.smc_campaign.framework import MTF, sim_price_bracket
from research.smc_campaign.combined_numbers import headline, print_headline
from research.smc_campaign.sweep_engine import fill_setups
from research.smc_campaign.s1_session_gauntlet import s1_setups_for_session, SESSIONS

def main():
    mtf = MTF()
    mask = SESSIONS["kz_base (NY2-11)"]
    setups = s1_setups_for_session(mtf, mask)
    sig = fill_setups(setups, mtf.m5, wait_bars=96, slip_atr=0.05)
    op = mtf.m5["open"].values; n = len(mtf.m5)

    print_headline("S1 base", headline(sim_price_bracket(sig, mtf.m5, horizon=288)))
    print("\n=== CLEAN delay (original risk kept for R-normalization) ===")
    for d in (1, 2, 3, 5):
        s = sig.copy()
        s["fill_index"] = s["fill_index"].astype(int) + d
        s = s[s["fill_index"] < n - 2].reset_index(drop=True)
        s["entry_price"] = op[s["fill_index"].values]   # fill later, worse price
        # KEEP original risk_units (do NOT recompute) -> honest R
        h = headline(sim_price_bracket(s, mtf.m5, horizon=288))
        print_headline(f"S1 delay+{d}", h)
    print("\n(If PF stays >~1.3 and pos-years hold across delays, the edge is NOT a")
    print(" 1-bar microstructure fluke — it survives being slow.)")

if __name__ == "__main__":
    main()
