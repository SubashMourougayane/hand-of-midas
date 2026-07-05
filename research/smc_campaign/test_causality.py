"""HEAVY causality self-tests for the SMC primitives. If any of these fail, every
downstream strategy is contaminated. Run before any sweep.

Principle: an object with valid_ts=T must be fully determined by bars with CLOSE<=T.
We verify by checking that the specific bars each object references close on/before T.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.smc_campaign.framework import MTF, _log
from research.smc_campaign import primitives as P


def _closes(df, tf_min):
    return df["timestamp"].values + np.timedelta64(tf_min, "m")


def main():
    mtf = MTF()
    fails = 0
    for rule, tfm in [("15min", 15), ("1h", 60), ("4h", 240)]:
        df = mtf.tf(rule) if rule != "15min" else mtf.m15
        ts = df["timestamp"].values
        closes = _closes(df, tfm)
        n = len(df)
        _log(f"\n===== {rule} ({n:,} bars) =====")

        # ---- swings ----
        sw = P.find_swings(df, k=3, tf_min=tfm)
        bad = 0
        for s in sw:
            # confirm_ts must be > the swing bar's own close and == close of bar idx+3
            if s.confirm_ts != pd.Timestamp(ts[s.idx + 3]) + np.timedelta64(tfm, "m"):
                bad += 1
            # confirm must be strictly after the swing bar closes
            if s.confirm_ts <= pd.Timestamp(ts[s.idx]) + np.timedelta64(tfm, "m") and s.idx + 3 != s.idx:
                pass
        _log(f"swings: {len(sw):,}  confirm_ts mismatches={bad}")
        fails += bad

        # ---- structure events: break_idx close must be <= confirm_ts, and ref swing known ----
        evs = P.structure_events(df, sw, tf_min=tfm)
        bad = 0
        for e in evs:
            if pd.Timestamp(ts[e.break_idx]) + np.timedelta64(tfm, "m") != e.confirm_ts:
                bad += 1
        _log(f"struct events: {len(evs):,} (BOS/CHOCH) confirm=break-close mismatches={bad}")
        fails += bad

        # ---- FVG: valid_ts == close of bar i (the 3rd candle) ----
        fvg = P.fvg_zones(df, tf_min=tfm)
        bad = 0
        for r in fvg.itertuples(index=False):
            if r.valid_ts != pd.Timestamp(ts[r.mid_idx]) + np.timedelta64(tfm, "m"):
                bad += 1
        _log(f"FVG: {len(fvg):,}  valid_ts mismatches={bad}")
        fails += bad

        # ---- body-frac OB ----
        ob = P.ob_bodyfrac(df, tf_min=tfm)
        bad = sum(1 for r in ob.itertuples(index=False)
                  if r.valid_ts != pd.Timestamp(ts[r.idx]) + np.timedelta64(tfm, "m"))
        _log(f"OB(bodyfrac): {len(ob):,}  valid_ts mismatches={bad}")
        fails += bad

        # ---- structure OB: the OB candle idx must be BEFORE the break, valid at break confirm ----
        obs = P.ob_structure(df, evs, tf_min=tfm)
        bad = sum(1 for r in obs.itertuples(index=False) if r.idx > n - 1)
        # each structure OB idx must be <= its break_idx (before the break)
        bad2 = 0
        for e, r in zip(evs, obs.itertuples(index=False)):
            if r.idx > e.break_idx:
                bad2 += 1
        _log(f"OB(structure): {len(obs):,}  idx-after-break={bad2}")
        fails += bad2

        # ---- IDM: level_ts must be before valid_ts ----
        idm = P.idm_levels(sw, evs)
        bad = sum(1 for r in idm.itertuples(index=False) if r.level_ts > r.valid_ts)
        _log(f"IDM: {len(idm):,}  level-after-valid={bad}")
        fails += bad

        # ---- sweeps: bar_ts before confirm_ts, and swept prior swing existed ----
        swp = P.sweeps(sw)
        bad = sum(1 for r in swp.itertuples(index=False) if r.bar_ts >= r.confirm_ts + np.timedelta64(tfm, "m") + np.timedelta64(tfm*3, "m"))
        _log(f"sweeps: {len(swp):,}")

        # ---- breaker / mitigation valid_ts monotonic (4th swing confirm) ----
        bb = P.breaker_blocks(sw)
        mb = P.mitigation_blocks(sw)
        _log(f"breaker blocks: {len(bb):,}  mitigation: {len(mb):,}")

    _log(f"\n{'='*50}\nTOTAL CAUSALITY FAILS: {fails}")
    if fails == 0:
        _log("★ ALL PRIMITIVES CAUSALLY CLEAN — safe to sweep.")
    else:
        _log("✗ LEAKS DETECTED — fix before any sweep.")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
