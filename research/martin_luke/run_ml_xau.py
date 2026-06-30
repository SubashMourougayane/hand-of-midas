"""Martin Luke strategy quantised on XAUUSD.

STRATEGY MAPPING (Luke's rules → causal quant):
1. Daily-chart entries with intraday triggers
2. Inside-day filter (prior daily bar inside prior-prior daily range) — TIGHTNESS
3. Entry tactics:
   - PDH break: M5 bar close > prior daily high → LONG next M5 open
   - ORH break: M5 bar close > first-M5-of-NY-session high → LONG next M5 open
   (No ADR scanner — XAU only, ADR ~1.5%, so we test universe-of-one)
4. Stop placement:
   - Standard: low of breakout day (LOD) — daily low so far at entry time
   - Aggressive: low of M5 entry candle (if LOD > 5% away)
   - Max stop = 5% of price
5. Position sizing: risk_units in $ (cost charged as $0.30/risk)
6. Trail exit: daily close < 9 EMA (computed on prior closed daily, lagged)
7. 1R / 3R / open-ended variants tested

Strict causal:
- Daily indicators (EMA, ADR) from PRIOR closed daily bar
- ORH = high of first M5 bar of NY session (06:30-06:35 NY=09:30-09:35 ET regular hrs?  XAU 24/5 → use NY 03:00 London = NY 03:00, or NY 09:30 stocks-style)
  Pick: NY 09:30 (US equity open) since Luke is stock-based
- All entries on M5 grid; entry = NEXT M5 bar open after signal
- Trail check: at each daily close, if close < prior-day-9-EMA, exit at next M5 open
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd

from research.harness.causal_sim import load_data
try:
    from research.harness.causal_sim import persist
except ImportError:
    def persist(*a, **kw): return None


def build_daily(m1: pd.DataFrame) -> pd.DataFrame:
    """Daily bars anchored to NY date (16:00 NY = market close), so daily bar represents one trading day."""
    df = m1.copy()
    df["ny_ts"] = df["timestamp"].dt.tz_convert("America/New_York")
    # Daily bar = NY trading day (16:00 prior NY close → 16:00 today NY close)
    # Simpler: just use UTC date for daily (or NY date)
    df["ny_date"] = df["ny_ts"].dt.date
    daily = df.groupby("ny_date").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        first_ts=("timestamp", "first"),
        last_ts=("timestamp", "last"),
    ).reset_index()
    daily["timestamp"] = pd.to_datetime(daily["ny_date"]).dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    # Daily indicators
    daily["ema9"] = daily["close"].ewm(span=9, adjust=False).mean()
    daily["ema21"] = daily["close"].ewm(span=21, adjust=False).mean()
    daily["ema50"] = daily["close"].ewm(span=50, adjust=False).mean()
    daily["range_pct"] = (daily["high"] - daily["low"]) / daily["close"]
    daily["adr20"] = daily["range_pct"].rolling(20).mean()  # 20-day ADR as %
    # Lag everything by 1 — at start of NY day N, values from N-1 are knowable
    for c in ["ema9", "ema21", "ema50", "adr20", "open", "high", "low", "close", "range_pct"]:
        daily[f"{c}_lag"] = daily[c].shift(1)
    # Inside-day: prior daily bar inside prior-prior daily bar
    daily["inside_lag"] = (daily["high"].shift(1) < daily["high"].shift(2)) & (daily["low"].shift(1) > daily["low"].shift(2))
    daily["uptrend_lag"] = (daily["ema9_lag"] > daily["ema21_lag"]) & (daily["ema21_lag"] > daily["ema50_lag"])
    daily = daily.dropna().reset_index(drop=True)
    return daily


def simulate_ml(signals: list[dict], m5: pd.DataFrame, daily: pd.DataFrame,
                cost_usd: float = 0.30, tp_mult: float | None = None,
                trail_ema: int = 9) -> pd.DataFrame:
    """Simulate ML-style swing trades.

    Each signal: {entry_index (M5), side, risk_units, daily_idx_at_entry}
    Exit rules:
        1. Stop hit (close ≤ stop) → exit at that bar's close, R = -1
        2. Optional TP (tp_mult provided) → exit at that bar's close, R = +tp_mult
        3. Trail: at each DAILY close, if daily close < prior daily 9 EMA → exit at next M5 open
        4. Hard timeout: 30 days (forced exit at close)
    """
    op = m5["open"].values; cl = m5["close"].values
    ts = m5["timestamp"].values
    ny_date_m5 = m5["ny_date"].values
    # Map ny_date → daily index
    date_to_didx = {str(d): i for i, d in enumerate(daily["ny_date"].astype(str).values)}
    daily_close = daily["close"].values
    daily_ema9 = daily["ema9"].values
    daily_ema21 = daily["ema21"].values
    daily_ema50 = daily["ema50"].values
    daily_last_ts = pd.to_datetime(daily["last_ts"]).values

    # Pre-compute m5 index of each daily close (last M5 bar of that NY date)
    last_m5_of_date = m5.groupby("ny_date").apply(lambda g: g.index[-1]).to_dict()

    outs = []
    for sig in signals:
        i = sig["entry_index"]; side = sig["side"]; risk = sig["risk_units"]
        if risk <= 0 or i >= len(m5) - 2: continue
        entry = op[i]
        stop = entry - risk * side
        tp = entry + tp_mult * risk * side if tp_mult is not None else None
        max_horizon = min(len(m5) - 1, i + 30 * 24 * 12)  # 30 days × 288 M5
        outcome_r = 0.0; exit_i = max_horizon; reason = "time"

        # Track which daily index we are in
        for j in range(i, max_horizon + 1):
            c = cl[j]
            # Stop / TP
            if side > 0:
                if c <= stop: outcome_r = -1.0; exit_i = j; reason="stop"; break
                if tp is not None and c >= tp: outcome_r = tp_mult; exit_i = j; reason="tp"; break
            else:
                if c >= stop: outcome_r = -1.0; exit_i = j; reason="stop"; break
                if tp is not None and c <= tp: outcome_r = tp_mult; exit_i = j; reason="tp"; break
            # Daily-close trail check: only when crossing a NY-date boundary
            if j > i and ny_date_m5[j] != ny_date_m5[j-1]:
                # we just entered a new day; check that PRIOR day's close (just closed) vs its ema9
                prev_date = ny_date_m5[j-1]
                prev_didx = date_to_didx.get(str(prev_date))
                if prev_didx is not None and prev_didx >= 1:
                    # daily close = last bar of that NY date
                    prev_close = daily_close[prev_didx]
                    # use 9 EMA THROUGH that date — but that's a look-ahead in real time;
                    # use ema9 computed up to that date (which is fine since daily bar just closed)
                    prev_ema9 = daily_ema9[prev_didx]
                    if side > 0 and prev_close < prev_ema9:
                        # exit at this bar's open (which is the new day's first M5)
                        outcome_r = side * (op[j] - entry) / risk
                        outcome_r = max(-1.0, min(10.0, outcome_r))
                        exit_i = j; reason = "trail"; break
                    if side < 0 and prev_close > prev_ema9:
                        outcome_r = side * (op[j] - entry) / risk
                        outcome_r = max(-1.0, min(10.0, outcome_r))
                        exit_i = j; reason = "trail"; break
        else:
            outcome_r = max(-1.0, min(10.0, side * (cl[max_horizon] - entry) / risk))

        outs.append({
            "entry_ts": ts[i], "side": side, "entry_price": entry, "stop": stop,
            "risk_units": risk, "exit_index": exit_i, "bracket_r": outcome_r,
            "cost_r": cost_usd / risk, "net_r": outcome_r - cost_usd / risk,
            "reason": reason, "year": pd.to_datetime(ts[i]).year,
        })
    return pd.DataFrame(outs)


def generate_pdh_signals(m5: pd.DataFrame, daily: pd.DataFrame,
                         require_inside_day: bool = True,
                         require_uptrend: bool = True,
                         ny_window: tuple[int, int] = (9, 16)) -> list[dict]:
    """At each M5 bar in NY hours, check: close > prior_day_high?
    First trigger per day = signal.
    """
    high_lag = m5["high_lag"].values  # prior closed M15 high — but we want prior DAILY high
    # Need prior daily high mapped to each M5 row
    daily_idx = {str(d): i for i, d in enumerate(daily["ny_date"].astype(str).values)}
    prior_daily_high = []
    prior_daily_low = []
    prior_ema9 = []
    uptrend_lag = []
    inside_lag = []
    for d_str in m5["ny_date"].values:
        didx = daily_idx.get(str(d_str))
        if didx is None or didx < 1:
            prior_daily_high.append(np.nan); prior_daily_low.append(np.nan)
            prior_ema9.append(np.nan); uptrend_lag.append(False); inside_lag.append(False)
            continue
        prior_daily_high.append(daily["high"].iloc[didx-1])
        prior_daily_low.append(daily["low"].iloc[didx-1])
        prior_ema9.append(daily["ema9"].iloc[didx-1])
        uptrend_lag.append(bool(daily["uptrend_lag"].iloc[didx]))
        inside_lag.append(bool(daily["inside_lag"].iloc[didx]))
    m5 = m5.copy()
    m5["pdh"] = prior_daily_high
    m5["pdl"] = prior_daily_low
    m5["prior_ema9"] = prior_ema9
    m5["uptrend"] = uptrend_lag
    m5["inside"] = inside_lag

    # Trigger: M5 close > pdh AND in NY window
    m5["in_window"] = (m5["ny_hr"] >= ny_window[0]) & (m5["ny_hr"] < ny_window[1])
    m5["sig_long"] = m5["in_window"] & (m5["close"] > m5["pdh"])
    if require_inside_day:
        m5["sig_long"] = m5["sig_long"] & m5["inside"]
    if require_uptrend:
        m5["sig_long"] = m5["sig_long"] & m5["uptrend"]

    # First trigger per day
    m5["first_long"] = m5["sig_long"] & ~m5.groupby("ny_date")["sig_long"].cumsum().shift(1).fillna(0).astype(bool)

    # For each trigger row, compute risk: LOD of today so far
    # Approximate LOD = m5["low"] cummin within ny_date up to bar i
    m5["lod_so_far"] = m5.groupby("ny_date")["low"].cummin()
    signals = []
    for i in m5.index[m5["first_long"]]:
        row = m5.iloc[i]
        entry_open = m5["open"].iloc[i + 1] if i + 1 < len(m5) else None
        if entry_open is None: continue
        # Standard stop = LOD of today
        lod = row["lod_so_far"]
        stop_std = lod
        # 5% rule: if LOD > 5% away from entry, use 5min candle low (this bar's low)
        risk_std = entry_open - stop_std
        risk_pct = risk_std / entry_open
        if risk_pct > 0.05:
            stop_alt = row["low"]
            risk_alt = entry_open - stop_alt
            if entry_open - stop_alt < entry_open - stop_std:
                risk_units = risk_alt
                stop_used = stop_alt
            else:
                risk_units = entry_open * 0.05
                stop_used = entry_open - risk_units
        else:
            risk_units = risk_std
        # Cap risk at 5%
        max_risk = entry_open * 0.05
        if risk_units > max_risk:
            risk_units = max_risk
        if risk_units <= 0: continue
        signals.append({"entry_index": i + 1, "side": 1, "risk_units": float(risk_units)})
    return signals


def headline(t: pd.DataFrame) -> dict:
    if len(t)==0: return {"n":0}
    r = t["net_r"].astype(float)
    n = len(r); net = r.sum()
    wr = (r > 0).mean()
    gw = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gw / gl if gl > 0 else float("inf")
    eq = r.cumsum().values; peak = np.maximum.accumulate(eq); dd = (eq-peak).min()
    yrs = max(0.01, (pd.to_datetime(t["entry_ts"]).max() - pd.to_datetime(t["entry_ts"]).min()).total_seconds() / (365.25*86400))
    yr_r = net / yrs
    mar = yr_r / abs(dd) if dd != 0 else 0
    y = t.groupby("year")["net_r"].sum(); pos = int((y>0).sum())
    return {"n":n, "net":net, "yr_r":yr_r, "wr":wr, "pf":pf, "dd":dd, "mar":mar,
            "pos_years":f"{pos}/{len(y)}", "trades_per_year":n/yrs,
            "years_dict":y.round(2).to_dict()}


def print_h(label, h):
    if h.get("n",0)==0: print(f"  {label:<55s} ZERO"); return
    print(f"  {label:<55s} n={h['n']:>4d} /yr={h['trades_per_year']:>4.0f} "
          f"net={h['net']:>+7.1f}R /yr={h['yr_r']:>+6.1f}R WR={h['wr']*100:>5.1f}% "
          f"PF={h['pf']:>5.2f} DD={h['dd']:>+6.1f} MAR={h['mar']:>+5.2f} pos={h['pos_years']}")


def run():
    print("="*120)
    print("MARTIN LUKE QUANTISED — XAU")
    print("="*120)
    m1, m5, m15 = load_data()
    print(f"M1 bars: {len(m1):,}  M5: {len(m5):,}")
    daily = build_daily(m1)
    print(f"Daily bars: {len(daily)} (from {daily['ny_date'].iloc[0]} to {daily['ny_date'].iloc[-1]})")
    print(f"XAU ADR (median): {daily['range_pct'].median()*100:.2f}% (Luke target: > 5%)")
    print(f"XAU ADR20 max: {daily['adr20'].max()*100:.2f}%")
    print()

    # Variant matrix
    configs = [
        ("PDH only",              {"require_inside_day": False, "require_uptrend": False}),
        ("PDH + uptrend",         {"require_inside_day": False, "require_uptrend": True}),
        ("PDH + inside-day",      {"require_inside_day": True,  "require_uptrend": False}),
        ("PDH + uptrend + inside",{"require_inside_day": True,  "require_uptrend": True}),
    ]

    for label, params in configs:
        sigs = generate_pdh_signals(m5, daily, **params)
        print(f"\n{label}: signals = {len(sigs)}")
        for tp_mult in [None, 1.0, 2.0, 3.0]:
            t = simulate_ml(sigs, m5, daily, tp_mult=tp_mult)
            tp_lbl = "trail" if tp_mult is None else f"TP={tp_mult}R"
            h = headline(t)
            print_h(f"  {tp_lbl}", h)
            persist("martin_luke", f"xau_{label.replace(' ','_').replace('+','plus')}_{tp_lbl}", t,
                    notes=f"{label}, {tp_lbl}")


if __name__ == "__main__":
    run()
