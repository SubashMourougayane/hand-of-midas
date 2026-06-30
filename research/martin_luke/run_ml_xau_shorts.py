"""Martin Luke SHORT side mirror on XAUUSD.

Long-side rule was: PDH break + uptrend (9>21>50 EMA) + TP=3R
Short mirror:       PDL break + downtrend (9<21<50 EMA) + TP=3R

PDL = Prior Day Low.
Downtrend filter = EMAs declining and converging (per Luke's short setup).
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd

from research.harness.causal_sim import load_data
from research.martin_luke.run_ml_xau import build_daily, simulate_ml, headline


def generate_pdl_short_signals(m5: pd.DataFrame, daily: pd.DataFrame,
                                require_downtrend: bool = True,
                                require_converging: bool = False,
                                ny_window: tuple[int, int] = (9, 16)) -> list[dict]:
    """SHORT mirror: M5 close < prior daily low → SHORT next M5 open.
    Downtrend: ema9 < ema21 < ema50 on prior closed daily.
    Optional 'converging' check: prior daily EMAs are within X% of each other.
    """
    daily_idx = {str(d): i for i, d in enumerate(daily["ny_date"].astype(str).values)}

    prior_daily_low = []
    prior_daily_high = []
    downtrend_lag = []
    converging_lag = []
    for d_str in m5["ny_date"].values:
        didx = daily_idx.get(str(d_str))
        if didx is None or didx < 1:
            prior_daily_low.append(np.nan); prior_daily_high.append(np.nan)
            downtrend_lag.append(False); converging_lag.append(False)
            continue
        prior_daily_low.append(daily["low"].iloc[didx-1])
        prior_daily_high.append(daily["high"].iloc[didx-1])
        e9 = daily["ema9"].iloc[didx-1]
        e21 = daily["ema21"].iloc[didx-1]
        e50 = daily["ema50"].iloc[didx-1]
        dn = (e9 < e21) and (e21 < e50)
        downtrend_lag.append(bool(dn))
        # Convergence: max diff between EMAs < 2% of price
        if dn:
            spread = (e50 - e9) / daily["close"].iloc[didx-1]
            converging_lag.append(bool(spread < 0.02))
        else:
            converging_lag.append(False)
    m5 = m5.copy()
    m5["pdl"] = prior_daily_low
    m5["pdh"] = prior_daily_high
    m5["downtrend"] = downtrend_lag
    m5["converging"] = converging_lag

    m5["in_window"] = (m5["ny_hr"] >= ny_window[0]) & (m5["ny_hr"] < ny_window[1])
    m5["sig_short"] = m5["in_window"] & (m5["close"] < m5["pdl"])
    if require_downtrend:
        m5["sig_short"] = m5["sig_short"] & m5["downtrend"]
    if require_converging:
        m5["sig_short"] = m5["sig_short"] & m5["converging"]

    m5["first_short"] = m5["sig_short"] & ~m5.groupby("ny_date")["sig_short"].cumsum().shift(1).fillna(0).astype(bool)

    # Today's high so far (HOD) — analogous to LOD for longs
    m5["hod_so_far"] = m5.groupby("ny_date")["high"].cummax()

    signals = []
    for i in m5.index[m5["first_short"]]:
        row = m5.iloc[i]
        if i + 1 >= len(m5): continue
        entry_open = float(m5["open"].iloc[i + 1])
        hod = float(row["hod_so_far"])
        # Standard stop = HOD of today (above entry for shorts)
        risk_std = hod - entry_open
        risk_pct = risk_std / entry_open
        if risk_pct > 0.05:
            # Aggressive stop = 5min entry candle high
            risk_alt = float(row["high"]) - entry_open
            if risk_alt < risk_std:
                risk_units = risk_alt
            else:
                risk_units = entry_open * 0.05
        else:
            risk_units = risk_std
        # Cap at 5%
        max_risk = entry_open * 0.05
        if risk_units > max_risk:
            risk_units = max_risk
        if risk_units <= 0: continue
        signals.append({"entry_index": i + 1, "side": -1, "risk_units": float(risk_units)})
    return signals


def print_h(label, h):
    if h.get("n",0)==0: print(f"  {label:<55s} ZERO"); return
    print(f"  {label:<55s} n={h['n']:>4d} /yr={h['trades_per_year']:>4.0f} "
          f"net={h['net']:>+7.1f}R /yr={h['yr_r']:>+6.1f}R WR={h['wr']*100:>5.1f}% "
          f"PF={h['pf']:>5.2f} DD={h['dd']:>+6.1f} MAR={h['mar']:>+5.2f} pos={h['pos_years']}")


def run():
    print("="*120)
    print("MARTIN LUKE SHORT SIDE — XAU")
    print("="*120)
    m1, m5, m15 = load_data()
    daily = build_daily(m1)

    configs = [
        ("PDL only (no filter)",       {"require_downtrend": False, "require_converging": False}),
        ("PDL + downtrend",            {"require_downtrend": True,  "require_converging": False}),
        ("PDL + downtrend + converge", {"require_downtrend": True,  "require_converging": True}),
    ]

    for label, params in configs:
        sigs = generate_pdl_short_signals(m5, daily, **params)
        print(f"\n{label}: signals = {len(sigs)}")
        for tp_mult in [None, 1.0, 2.0, 3.0]:
            t = simulate_ml(sigs, m5, daily, tp_mult=tp_mult)
            tp_lbl = "trail" if tp_mult is None else f"TP={tp_mult}R"
            print_h(f"  {tp_lbl}", headline(t))


if __name__ == "__main__":
    run()
