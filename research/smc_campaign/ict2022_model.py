"""ICT 2022 Trading Model — built to the dot from "Complete ICT Trading Strategy 2022"
(innercircletrader.net) + HowToTrade "Liquidity Sweep Strategy" + "14 ICT Concepts".

THE MODEL (PDF line-by-line):
  1. Mark the RANGE = high & low from NY-midnight open (00:00 NY) to London open
     (03:00 NY).  [pg1-2]
  2. Scenario A — London (03:00-08:00 NY): price SWEEPS the range high or low
     (takes it out by one candle wick/body).  [pg2]
     Scenario B — if London stays range-bound (no sweep), extend the range to
     NY-midnight..NY-open and let NEW YORK (08:00-12:00 NY) do the sweep.  [pg4]
  3. After the sweep, on the LTF (M5) look for a Market-Structure-Shift with
     displacement on the OPPOSITE side (fade the sweep = mean-revert into range).
     [pg2, pg4]
  4. Mark the PD-array (FVG or OB) left by the displacement; wait for price to
     trade back to it in premium/discount.  [pg2,5]
  5. ENTER at the PD-array (FVG midpoint = CE, or OB edge). SL just past the swept
     extreme (+ buffer). TP at the OPPOSITE range boundary (the book's ~1:3).  [pg2,6]

Causal to the dot: range uses ONLY bars closed before London open; sweep detected
on closed M5 bars; MSS confirmed k-bars right; entry is a limit into the zone that
must be TOUCHED after arm_ts. No look-ahead. cost $0.30/risk_units.

Also builds the HowToTrade "Liquidity Sweep" variant: same sweep+CHoCH but entry
at OB/FVG midpoint with NO fixed range TP — TP = next opposite swing (3R proxy).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")

from research.smc_campaign.framework import MTF, sim_price_bracket, _log
from research.smc_campaign.sweep_engine import fill_setups
from research.smc_campaign.combined_numbers import headline, print_headline, model_b
import research.smc_campaign.primitives as P
import logging
logging.disable(logging.CRITICAL)


# NY-hour session boundaries (m5 carries ny_hr, ny_min, ny_date).
MIDNIGHT_HR = 0        # NY-midnight open 00:00
LONDON_HR = 3          # London open 03:00 NY
NY_HR = 8              # NY open 08:00 NY
NY_END_HR = 12         # after NY lunch start, stop looking


def _ny_dt(m5: pd.DataFrame) -> pd.Series:
    """NY-local timestamp (m5 ny_hr/ny_min are NY-local already)."""
    return m5["timestamp"].dt.tz_convert("America/New_York")


def build_ict2022_setups(mtf: MTF, *, k: int = 3, sl_buf_atr: float = 0.10,
                         entry_zone: str = "fvg_ce", scenario: str = "both",
                         min_sweep_atr: float = 0.0) -> pd.DataFrame:
    """Generate ICT-2022 setups (fade the session-range sweep, TP = opposite range).

    entry_zone: 'fvg_ce' (FVG midpoint) | 'sweep_50' (50% of sweep-leg) | 'range_ote'
                (0.705 fib of the sweep leg — OTE).
    scenario:   'london' | 'ny' | 'both'.
    """
    m5 = mtf.m5
    ny = _ny_dt(m5)
    m5 = m5.assign(_ny_hr=ny.dt.hour, _ny_min=ny.dt.minute, _ny_date=ny.dt.date.astype(str))
    hi = m5["high"].values; lo = m5["low"].values; cl = m5["close"].values
    ts = m5["timestamp"].values
    atr = m5["atr14_lag"].values
    nyh = m5["_ny_hr"].values
    ndate = m5["_ny_date"].values
    n = len(m5)

    # index bars by NY-date
    setups = []
    # group boundaries
    order = np.argsort(ndate, kind="stable")
    # iterate unique dates
    uniq, first_idx = np.unique(ndate, return_index=True)
    date_to_rows: dict[str, np.ndarray] = {}
    # build contiguous slices (m5 is time-sorted so each date is contiguous)
    bounds = np.searchsorted(ndate, uniq)  # start index of each date
    for di, d in enumerate(uniq):
        s = bounds[di]
        e = bounds[di + 1] if di + 1 < len(bounds) else n
        rows = np.arange(s, e)
        h = nyh[rows]
        # range = midnight(00:00) .. London open(03:00), bars with 0<=hr<3
        rng_mask = (h >= MIDNIGHT_HR) & (h < LONDON_HR)
        if rng_mask.sum() < 6:
            continue
        rng_rows = rows[rng_mask]
        range_hi = hi[rng_rows].max()
        range_lo = lo[rng_rows].min()
        london_open_i = rng_rows[-1] + 1  # first bar at/after London open

        # scenario windows
        windows = []
        if scenario in ("london", "both"):
            lon_mask = (h >= LONDON_HR) & (h < NY_HR)
            if lon_mask.any():
                windows.append(("london", rows[lon_mask]))
        if scenario in ("ny", "both"):
            ny_mask = (h >= NY_HR) & (h < NY_END_HR)
            if ny_mask.any():
                windows.append(("ny", rows[ny_mask]))

        swept = False
        for wname, wrows in windows:
            if swept and scenario == "both":
                break  # first sweep of the day wins (London priority)
            for i in wrows:
                # sweep HIGH -> fade short ; sweep LOW -> fade long
                took_high = hi[i] > range_hi and (min_sweep_atr == 0 or (hi[i] - range_hi) >= min_sweep_atr * atr[i])
                took_low = lo[i] < range_lo and (min_sweep_atr == 0 or (range_lo - lo[i]) >= min_sweep_atr * atr[i])
                if not (took_high or took_low):
                    continue
                side = -1.0 if took_high else 1.0
                sweep_extreme = hi[i] if took_high else lo[i]
                sweep_i = i
                # ---- require M5 MSS (CHoCH) in fade direction AFTER the sweep ----
                # look ahead up to 24 bars (2h) for a structure break opposite the sweep
                look = np.arange(sweep_i + 1, min(sweep_i + 25, n))
                if len(look) < 3:
                    continue
                arm_i = None
                if side < 0:  # fade short: need a lower-low break (close < prior swing low)
                    # prior swing low = min low between london_open_i..sweep_i
                    ref_lo = lo[london_open_i:sweep_i + 1].min() if sweep_i >= london_open_i else lo[sweep_i]
                    for j in look:
                        if cl[j] < ref_lo:
                            arm_i = j; break
                else:  # fade long: need higher-high break
                    ref_hi = hi[london_open_i:sweep_i + 1].max() if sweep_i >= london_open_i else hi[sweep_i]
                    for j in look:
                        if cl[j] > ref_hi:
                            arm_i = j; break
                if arm_i is None:
                    continue
                # ---- entry zone from the displacement leg (sweep_extreme -> arm close) ----
                disp_lo = min(sweep_extreme, cl[arm_i])
                disp_hi = max(sweep_extreme, cl[arm_i])
                leg = disp_hi - disp_lo
                if leg <= 0:
                    continue
                if entry_zone == "fvg_ce":
                    entry = (disp_hi + disp_lo) / 2.0        # CE / equilibrium of displacement
                elif entry_zone == "sweep_50":
                    entry = (disp_hi + disp_lo) / 2.0
                elif entry_zone == "range_ote":
                    # 0.705 retrace of the displacement leg toward the sweep
                    entry = (disp_lo + 0.705 * leg) if side < 0 else (disp_hi - 0.705 * leg)
                else:
                    entry = (disp_hi + disp_lo) / 2.0
                # SL just past swept extreme; TP opposite range boundary
                sl = sweep_extreme + sl_buf_atr * atr[arm_i] * (1 if side < 0 else -1)
                tp = range_lo if side < 0 else range_hi
                # sanity: TP must be beyond entry in trade direction, SL opposite
                if side < 0 and not (tp < entry < sl):
                    continue
                if side > 0 and not (sl < entry < tp):
                    continue
                setups.append((ts[arm_i], side, entry, tp, sl))
                swept = True
                break  # one setup per window
    if not setups:
        return pd.DataFrame(columns=["arm_ts", "side", "entry_price", "tp_price", "sl_price"])
    out = pd.DataFrame(setups, columns=["arm_ts", "side", "entry_price", "tp_price", "sl_price"])
    out["arm_ts"] = pd.to_datetime(out["arm_ts"])
    return out.sort_values("arm_ts").reset_index(drop=True)


def audit(mtf, setups, label):
    print("\n" + "=" * 100)
    print(f"### {label} ###")
    if len(setups) < 30:
        print(f"  only {len(setups)} setups — SKIP"); return None
    sig = fill_setups(setups, mtf.m5, wait_bars=96, slip_atr=0.05)
    base = sim_price_bracket(sig, mtf.m5, horizon=288)
    if len(base) < 30:
        print(f"  only {len(base)} fills — SKIP"); return None
    base = base.rename(columns={"entry_ts": "entry_ts"})
    print_headline(f"{label} base", headline(base))
    # delay reprice
    op = mtf.m5["open"].values; n = len(mtf.m5)
    for d in (1, 2, 3):
        s = sig.copy(); s["fill_index"] = s["fill_index"].astype(int) + d
        s = s[s["fill_index"] < n - 2].reset_index(drop=True)
        s["entry_price"] = op[s["fill_index"].values]
        s["risk_units"] = (s["entry_price"] - s["sl_price"]).abs()
        s = s[s["risk_units"] > 0]
        print_headline(f"{label} delay+{d}", headline(sim_price_bracket(s, mtf.m5)))
    for c in (0.30, 0.50, 0.80):
        print_headline(f"{label} cost${c}", headline(sim_price_bracket(sig, mtf.m5, cost_usd=c)))
    r = base["net_r"].values
    rng = np.random.default_rng(13)
    boots = np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(1500)])
    _log(f"  bootstrap net={r.sum():+.1f}R P(net<=0)={(boots <= 0).mean():.4f}")
    print_headline(f"{label} IS19-23", headline(base[base.year <= 2023]))
    print_headline(f"{label} OOS24-26", headline(base[base.year >= 2024]))
    yt = base.groupby("year")["net_r"].agg(["sum", "count"]).round(1)
    print("  year (netR|n):")
    for y, row in yt.iterrows():
        print(f"    {int(y)}: {row['sum']:>+8.1f}R ({int(row['count'])})")
    mb = model_b(base, 0.015)
    print(f"  Model B $5k@1.5%: total ${mb['total']:,.0f} (banked ${mb['banked']:,.0f}"
          f"+carry ${mb['carry']:,.0f}) {mb['total']/5000:.1f}x maxDD ${mb['maxdd']:,.0f}")
    return base


def main():
    mtf = MTF()
    print("\n" + "#" * 100)
    print("# ICT 2022 MODEL — session-range sweep -> MSS -> PD-array fade. XAUUSD, to the dot.")
    print("#" * 100)
    combos = [
        ("both",  "fvg_ce",   "ICT2022 both / FVG-CE"),
        ("both",  "range_ote","ICT2022 both / OTE-0.705"),
        ("london","fvg_ce",   "ICT2022 London-only / FVG-CE"),
        ("ny",    "fvg_ce",   "ICT2022 NY-only / FVG-CE"),
    ]
    results = []
    for scen, ez, lab in combos:
        s = build_ict2022_setups(mtf, scenario=scen, entry_zone=ez)
        _log(f"{lab}: {len(s)} raw setups")
        b = audit(mtf, s, lab)
        if b is not None:
            results.append((lab, headline(b)))
    print("\n" + "#" * 100 + "\n# VERDICT (gate PF>=1.3 MAR>=1.5 7-8/8yr delay+1-survives)")
    print(f"{'variant':<32}{'n':>5}{'/yr':>5}{'PF':>6}{'MAR':>6}{'netR':>9}{'pos':>6}")
    for lab, h in results:
        print(f"{lab:<32}{h['n']:>5}{h['per_yr']:>5.0f}{h['pf']:>6.2f}{h['mar']:>6.2f}{h['net']:>+9.1f}{h['pos']:>6}")


if __name__ == "__main__":
    main()
