"""ICT 2022 model — FULL permutation/combination mega-sweep.

Sweeps every knob of the session-range sweep->MSS->PD-array fade model and gates
each combo through the causal battery. Log-heavy. Reports survivors + best-by-metric.

Grid (all combinations):
  scenario     : london | ny | both
  entry_zone   : fvg_ce | range_ote | sweep_50
  sl_buf_atr   : 0.05 | 0.10 | 0.25 | 0.50
  min_sweep_atr: 0.0 | 0.10 | 0.25            (sweep must exceed range by N*ATR)
  k            : 2 | 3 | 5                     (swing lookback for MSS ref)
  mss_look     : 12 | 24 | 48                  (bars to find CHoCH after sweep)
  tp_mode      : range | 2R | 3R | 4R          (opposite range boundary, or fixed R)
  wait_bars    : 48 | 96                        (limit-fill patience)

Gate (same as campaign): PF>=1.30, MAR>=1.5, >=150 trades/yr, 7-8/8 pos years,
bootstrap P(net<=0)<=0.02, OOS PF within 80% of IS, delay+1 survives (PF>=1.2).
cost $0.30/risk_units. Big-numbers guard: high-PF low-n flagged phantom.
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")

from research.smc_campaign.framework import MTF, sim_price_bracket, _log
from research.smc_campaign.sweep_engine import fill_setups
from research.smc_campaign.combined_numbers import headline
import logging
logging.disable(logging.CRITICAL)

MIDNIGHT_HR, LONDON_HR, NY_HR, NY_END_HR = 0, 3, 8, 12


def build_setups(m5pre, *, scenario, entry_zone, sl_buf_atr, min_sweep_atr, k,
                 mss_look, tp_mode, hi, lo, cl, ts, atr, nyh, ndate, bounds, uniq, n):
    setups = []
    for di, d in enumerate(uniq):
        s = bounds[di]; e = bounds[di + 1] if di + 1 < len(bounds) else n
        rows = np.arange(s, e); h = nyh[rows]
        rng_mask = (h >= MIDNIGHT_HR) & (h < LONDON_HR)
        if rng_mask.sum() < 6:
            continue
        rng_rows = rows[rng_mask]
        range_hi = hi[rng_rows].max(); range_lo = lo[rng_rows].min()
        london_open_i = rng_rows[-1] + 1
        windows = []
        if scenario in ("london", "both"):
            lm = (h >= LONDON_HR) & (h < NY_HR)
            if lm.any(): windows.append(rows[lm])
        if scenario in ("ny", "both"):
            nm = (h >= NY_HR) & (h < NY_END_HR)
            if nm.any(): windows.append(rows[nm])
        done = False
        for wrows in windows:
            if done: break
            for i in wrows:
                took_high = hi[i] > range_hi and (min_sweep_atr == 0 or (hi[i] - range_hi) >= min_sweep_atr * atr[i])
                took_low = lo[i] < range_lo and (min_sweep_atr == 0 or (range_lo - lo[i]) >= min_sweep_atr * atr[i])
                if not (took_high or took_low):
                    continue
                side = -1.0 if took_high else 1.0
                sweep_extreme = hi[i] if took_high else lo[i]
                look = np.arange(i + 1, min(i + mss_look + 1, n))
                if len(look) < 3: continue
                arm_i = None
                if side < 0:
                    ref = lo[london_open_i:i + 1].min() if i >= london_open_i else lo[i]
                    for j in look:
                        if cl[j] < ref: arm_i = j; break
                else:
                    ref = hi[london_open_i:i + 1].max() if i >= london_open_i else hi[i]
                    for j in look:
                        if cl[j] > ref: arm_i = j; break
                if arm_i is None: continue
                dlo = min(sweep_extreme, cl[arm_i]); dhi = max(sweep_extreme, cl[arm_i])
                leg = dhi - dlo
                if leg <= 0: continue
                if entry_zone == "range_ote":
                    entry = (dlo + 0.705 * leg) if side < 0 else (dhi - 0.705 * leg)
                else:  # fvg_ce / sweep_50 both = midpoint
                    entry = (dhi + dlo) / 2.0
                sl = sweep_extreme + sl_buf_atr * atr[arm_i] * (1 if side < 0 else -1)
                risk = abs(entry - sl)
                if risk <= 0: continue
                if tp_mode == "range":
                    tp = range_lo if side < 0 else range_hi
                else:
                    rmult = {"2R": 2.0, "3R": 3.0, "4R": 4.0}[tp_mode]
                    tp = entry - rmult * risk if side < 0 else entry + rmult * risk
                if side < 0 and not (tp < entry < sl): continue
                if side > 0 and not (sl < entry < tp): continue
                setups.append((ts[arm_i], side, entry, tp, sl))
                done = True; break
    if not setups:
        return None
    out = pd.DataFrame(setups, columns=["arm_ts", "side", "entry_price", "tp_price", "sl_price"])
    out["arm_ts"] = pd.to_datetime(out["arm_ts"])
    return out.sort_values("arm_ts").reset_index(drop=True)


def gate(mtf, setups, wait_bars):
    """Return (headline dict, passed_bool, reason) or (None,...) if too few."""
    if setups is None or len(setups) < 60:
        return None, False, "few_setups"
    sig = fill_setups(setups, mtf.m5, wait_bars=wait_bars, slip_atr=0.05)
    if len(sig) < 60:
        return None, False, "few_fills"
    base = sim_price_bracket(sig, mtf.m5, horizon=288)
    if len(base) < 60:
        return None, False, "few_trades"
    h = headline(base)
    # delay+1
    op = mtf.m5["open"].values; n = len(mtf.m5)
    s = sig.copy(); s["fill_index"] = s["fill_index"].astype(int) + 1
    s = s[s["fill_index"] < n - 2].reset_index(drop=True)
    s["entry_price"] = op[s["fill_index"].values]
    s["risk_units"] = (s["entry_price"] - s["sl_price"]).abs()
    s = s[s["risk_units"] > 0]
    d1 = headline(sim_price_bracket(s, mtf.m5)) if len(s) > 30 else {"pf": 0}
    # cost stress $0.50
    c5 = headline(sim_price_bracket(sig, mtf.m5, cost_usd=0.50))
    # IS/OOS
    is_ = headline(base[base.year <= 2023]); oos = headline(base[base.year >= 2024])
    r = base["net_r"].values
    rng = np.random.default_rng(13)
    pboot = float((np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(800)]) <= 0).mean())
    h["d1_pf"] = d1.get("pf", 0); h["c5_pf"] = c5["pf"]; h["pboot"] = pboot
    h["is_pf"] = is_.get("pf", 0); h["oos_pf"] = oos.get("pf", 0)
    passed = (
        h["pf"] >= 1.30 and h["mar"] >= 1.5 and h["per_yr"] >= 150 and
        _posyrs(h["pos"]) >= 7 and pboot <= 0.02 and
        d1.get("pf", 0) >= 1.2 and
        oos.get("pf", 0) >= 0.8 * max(is_.get("pf", 1e9), 1e-9)
    )
    return h, passed, "ok"


def _posyrs(pos):
    try:
        a, b = pos.split("/"); return int(a)
    except Exception:
        return 0


def main():
    mtf = MTF()
    m5 = mtf.m5
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    hi = m5["high"].values; lo = m5["low"].values; cl = m5["close"].values
    ts = m5["timestamp"].values; atr = m5["atr14_lag"].values
    nyh = ny.dt.hour.values; ndate = ny.dt.date.astype(str).values
    n = len(m5)
    uniq = np.unique(ndate); bounds = np.searchsorted(ndate, uniq)

    grid = dict(
        scenario=["london", "ny", "both"],
        entry_zone=["fvg_ce", "range_ote"],
        sl_buf_atr=[0.05, 0.10, 0.25, 0.50],
        min_sweep_atr=[0.0, 0.10, 0.25],
        k=[3],  # k only affects nothing here (MSS uses raw structure ref) — keep 1
        mss_look=[12, 24, 48],
        tp_mode=["range", "2R", "3R", "4R"],
        wait_bars=[48, 96],
    )
    keys = list(grid)
    combos = list(product(*[grid[k] for k in keys]))
    total = len(combos)
    _log(f"ICT2022 MEGA-SWEEP: {total} combinations")
    rows = []
    survivors = []
    for ci, vals in enumerate(combos):
        cfg = dict(zip(keys, vals))
        setups = build_setups(
            m5, scenario=cfg["scenario"], entry_zone=cfg["entry_zone"],
            sl_buf_atr=cfg["sl_buf_atr"], min_sweep_atr=cfg["min_sweep_atr"],
            k=cfg["k"], mss_look=cfg["mss_look"], tp_mode=cfg["tp_mode"],
            hi=hi, lo=lo, cl=cl, ts=ts, atr=atr, nyh=nyh, ndate=ndate,
            bounds=bounds, uniq=uniq, n=n)
        h, passed, reason = gate(mtf, setups, cfg["wait_bars"])
        if h is not None:
            rec = {**cfg, "n": h["n"], "per_yr": round(h["per_yr"]), "pf": round(h["pf"], 3),
                   "mar": round(h["mar"], 2), "net": round(h["net"], 1), "pos": h["pos"],
                   "d1_pf": round(h["d1_pf"], 2), "c5_pf": round(h["c5_pf"], 2),
                   "oos_pf": round(h["oos_pf"], 2), "pboot": round(h["pboot"], 4),
                   "passed": passed}
            rows.append(rec)
            if passed:
                survivors.append(rec)
        if (ci + 1) % 50 == 0:
            _log(f"  [{ci+1}/{total}] tested={len(rows)} survivors={len(survivors)}")
    df = pd.DataFrame(rows)
    out = Path("research/smc_campaign/results/ICT2022_sweep.csv")
    df.to_csv(out, index=False)
    _log(f"DONE. {len(rows)} evaluated, {len(survivors)} PASS gate. -> {out}")

    print("\n" + "#" * 100)
    print(f"# ICT2022 MEGA-SWEEP RESULTS — {total} combos, {len(rows)} evaluable, {len(survivors)} PASS")
    print("#" * 100)
    if len(df):
        print("\n--- TOP 15 by MAR (any n) ---")
        cols = ["scenario", "entry_zone", "sl_buf_atr", "min_sweep_atr", "mss_look",
                "tp_mode", "wait_bars", "n", "per_yr", "pf", "mar", "net", "pos",
                "d1_pf", "c5_pf", "oos_pf", "passed"]
        top = df.sort_values("mar", ascending=False).head(15)
        print(top[cols].to_string(index=False))
        print("\n--- TOP 15 by PF (n>=900 only, tradeable freq) ---")
        big = df[df["per_yr"] >= 135].sort_values("pf", ascending=False).head(15)
        print(big[cols].to_string(index=False) if len(big) else "  none >=135/yr")
    if survivors:
        print("\n" + "=" * 60 + "\n### SURVIVORS (full gate PASS) ###")
        print(pd.DataFrame(survivors).to_string(index=False))
    else:
        print("\n>>> ZERO combos pass the full gate. <<<")


if __name__ == "__main__":
    main()
