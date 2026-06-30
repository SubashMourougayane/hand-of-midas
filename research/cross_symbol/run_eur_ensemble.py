"""Cross-symbol test on EUR/USD OANDA data — Fib V2 ensemble + Martin Luke.
SAME rules + params as XAU. Cost = $0.00005 (0.5 pip = typical EUR/USD spread).
"""
from __future__ import annotations

import sys
import math
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import headline, print_headline
from research.fib_retrace.run_fib import build_h1_features
from research.fib_retrace.run_fib_v2 import build_pivot_events, simulate_fixed_tp
from research.fib_retrace.run_fib_v2_21yr import add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5
)


EUR_COST = 0.00003  # 0.3 pip (EUR/USD tightest spread)


def load_eur():
    h1 = pd.read_parquet("/tmp/oanda_eur_h1.parquet")
    m5 = pd.read_parquet("/tmp/oanda_eur_m5.parquet")
    if h1["timestamp"].dt.tz is None:
        h1["timestamp"] = h1["timestamp"].dt.tz_localize("UTC")
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    return (h1.sort_values("timestamp").reset_index(drop=True),
            m5.sort_values("timestamp").reset_index(drop=True))


def run_fib_ensemble_eur():
    print("[EUR] loading H1 + M5...")
    h1, m5 = load_eur()
    print(f"  H1: {len(h1):,}   M5: {len(m5):,}")
    h1 = build_h1_features(h1)
    m5_f = add_m5_features(m5)
    d1 = resample_d1(m5_f); d1 = add_d1_features(d1)
    m5_f = attach_d1_to_m5(m5_f, d1)
    pivot_events = build_pivot_events(h1, 5)
    print(f"  H1 pivots: {len(pivot_events):,}")

    print("\n=== FIB V2 ENSEMBLE on EUR ===\n")
    long_kw = dict(direction="long", session="all", max_hold_bars=72*12,
                   ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bull_strong")
    short_kw = dict(direction="short", session="all", max_hold_bars=72*12,
                    ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bear_strong")

    long_sigs = gen_signals_with_regime(m5_f, pivot_events, **long_kw)
    short_sigs = gen_signals_with_regime(m5_f, pivot_events, **short_kw)
    print(f"  long sigs: {len(long_sigs):,}   short sigs: {len(short_sigs):,}")

    lt = simulate_fixed_tp(m5_f, long_sigs, horizon_bars=72*12*2, cost_usd=EUR_COST)
    st = simulate_fixed_tp(m5_f, short_sigs, horizon_bars=72*12*2, cost_usd=EUR_COST)
    ens = pd.concat([lt, st], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)

    print_headline("LONG_BULL_STRONG", headline(lt))
    print_headline("SHORT_BEAR_STRONG", headline(st))
    print_headline("ENSEMBLE", headline(ens))

    print("\n[Per-year ensemble]")
    by_yr = ens.groupby("year")["net_r"].agg(["sum","count"]).round(2)
    by_yr.columns = ["net_R","n"]
    print(by_yr.to_string())

    print("\n[Audit]")
    for d in [1, 5, 10]:
        sl = long_sigs.copy(); sl["entry_index"] = sl["entry_index"].astype(int) + d
        ss = short_sigs.copy(); ss["entry_index"] = ss["entry_index"].astype(int) + d
        ens_d = pd.concat([
            simulate_fixed_tp(m5_f, sl, horizon_bars=72*12*2, cost_usd=EUR_COST),
            simulate_fixed_tp(m5_f, ss, horizon_bars=72*12*2, cost_usd=EUR_COST),
        ], ignore_index=True)
        print_headline(f"+{d} delay", headline(ens_d))
    for extra in [0.00010, 0.00020]:
        ens_c = pd.concat([
            simulate_fixed_tp(m5_f, long_sigs, horizon_bars=72*12*2, cost_usd=EUR_COST + extra),
            simulate_fixed_tp(m5_f, short_sigs, horizon_bars=72*12*2, cost_usd=EUR_COST + extra),
        ], ignore_index=True)
        print_headline(f"cost+${extra:.5f}", headline(ens_c))

    out_dir = Path("/Users/subash/SUBASH/GoldDigger/research/cross_symbol")
    ens.to_parquet(out_dir / "eur_fib_ensemble_trades.parquet")

    # $5k 3% PnL (1 lot = 100k notional, $1/pip standard)
    PIP_VALUE_PER_LOT = 10  # $10 per 0.0001 pip per 1 standard lot (100k)
    print("\n=== $5k 3% monthly reset PnL — EUR ENSEMBLE ===")
    df = ens.sort_values("entry_ts").reset_index(drop=True)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")
    nav = 5000.0; curr_m = None; monthly = {}; lots_seen = []
    for r in df.itertuples(index=False):
        if curr_m is None: curr_m = r.year_month; nav = 5000.0
        if r.year_month != curr_m:
            monthly[curr_m] = nav - 5000.0
            curr_m = r.year_month; nav = 5000.0
        risk_units = float(r.risk_units)  # in price (e.g. 0.0050 = 50 pips)
        if risk_units <= 0: continue
        risk_d = nav * 0.03
        # $/lot for given risk_units = risk_units / 0.0001 * $10/pip = risk_units * 100000
        dollar_per_lot = risk_units * 100000
        if dollar_per_lot <= 0: continue
        raw_lots = risk_d / dollar_per_lot
        # margin cap (50:1 standard FX leverage; using 1000 to be permissive)
        max_m_lots = (0.9 * nav * 1000) / (float(r.entry_price) * 100000)
        lots = math.floor(min(raw_lots, max_m_lots) / 0.01) * 0.01
        if lots < 0.01: continue
        lots_seen.append(lots)
        pnl = float(r.net_r) * lots * dollar_per_lot
        nav += pnl
    if curr_m: monthly[curr_m] = nav - 5000.0
    s = pd.Series(monthly).sort_index()
    pos = int((s > 0).sum())
    print(f"trades={len(df)} months={len(s)} pos={pos}/{len(s)}={pos/len(s)*100:.0f}%")
    print(f"total=${s.sum():+,.2f}  avg/mo=${s.mean():+,.2f}")
    print(f"best  {s.idxmax()}: ${s.max():+,.2f}")
    print(f"worst {s.idxmin()}: ${s.min():+,.2f}")
    if lots_seen:
        print(f"avg_lots={np.mean(lots_seen):.3f}  max_lots={max(lots_seen):.2f}")
    by_yr_d = s.groupby(s.index.str[:4]).sum().round(0).to_dict()
    print(f"per-yr ${by_yr_d}")
    return ens


def run_martin_luke_eur():
    print("\n\n" + "=" * 80)
    print(">>> MARTIN LUKE on EUR/USD <<<")
    _, m5 = load_eur()
    m5_f = add_m5_features(m5)
    daily = m5_f.set_index("timestamp").resample("1D", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
    ).dropna().reset_index()
    daily["ema9"] = daily["close"].ewm(span=9, adjust=False).mean()
    daily["ema21"] = daily["close"].ewm(span=21, adjust=False).mean()
    daily["ema50"] = daily["close"].ewm(span=50, adjust=False).mean()
    for c in ["close","high","low","ema9","ema21","ema50"]:
        daily[f"{c}_lag"] = daily[c].shift(1)
    daily["uptrend_lag"] = (daily["ema9_lag"] > daily["ema21_lag"]) & (daily["ema21_lag"] > daily["ema50_lag"])
    daily["pdh"] = daily["high_lag"]
    daily["pdl"] = daily["low_lag"]
    daily["ny_date"] = daily["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    daily = daily.sort_values("ny_date").reset_index(drop=True)

    m5_f["ny_date"] = m5_f["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    m5_f["ny_hr"] = m5_f["timestamp"].dt.tz_convert("America/New_York").dt.hour
    m5_with_d = m5_f.merge(daily[["ny_date","pdh","pdl","uptrend_lag"]], on="ny_date", how="left")

    op = m5_with_d["open"].values
    hi = m5_with_d["high"].values
    lo = m5_with_d["low"].values
    cl = m5_with_d["close"].values
    ts = m5_with_d["timestamp"].values
    pdh = m5_with_d["pdh"].values
    uptrend = m5_with_d["uptrend_lag"].values.astype(bool)
    ny_hr = m5_with_d["ny_hr"].values
    days = m5_with_d["ny_date"].values
    yrs = m5_with_d["timestamp"].dt.year.values
    in_ny = (ny_hr >= 9) & (ny_hr < 16)
    base = (cl > pdh) & uptrend & in_ny & np.isfinite(pdh)
    sig_idx = np.flatnonzero(base)
    last_day = ""
    trades = []
    n = len(m5_with_d)
    for i in sig_idx:
        if i >= n - 2: break
        if days[i] == last_day: continue
        entry_idx = i + 1
        entry = op[entry_idx]
        same_day_mask = (days[:i+1] == days[i])
        lod = float(lo[same_day_mask].min())
        stop = lod
        if entry - stop > 0.05 * entry:
            stop = entry - 0.05 * entry
        risk = entry - stop
        if risk <= 0 or not np.isfinite(risk): continue
        tp = entry + 3.0 * risk
        end = min(n - 1, entry_idx + 288)
        outcome_r = 0.0; exit_i = end; broke = False
        for j in range(entry_idx, end + 1):
            c = cl[j]
            if c <= stop: outcome_r = -1.0; exit_i = j; broke = True; break
            if c >= tp: outcome_r = 3.0; exit_i = j; broke = True; break
        if not broke:
            outcome_r = max(-1.0, min(3.0, (cl[exit_i] - entry) / risk))
        trades.append({
            "entry_ts": ts[entry_idx], "side": 1,
            "entry_price": float(entry), "stop_price": float(stop),
            "tp_price": float(tp), "risk_units": float(risk),
            "exit_index": int(exit_i), "bracket_r": float(outcome_r),
            "cost_r": EUR_COST / risk,
            "net_r": float(outcome_r) - EUR_COST / risk,
            "year": int(yrs[entry_idx]),
        })
        last_day = days[i]
    tdf = pd.DataFrame(trades)
    if len(tdf) == 0:
        print("[NO TRADES]"); return None
    print_headline("MARTIN LUKE EUR", headline(tdf))
    print("\n[Per-year]")
    by_yr = tdf.groupby("year")["net_r"].agg(["sum","count"]).round(2)
    by_yr.columns = ["R","n"]
    print(by_yr.to_string())

    out_dir = Path("/Users/subash/SUBASH/GoldDigger/research/cross_symbol")
    tdf.to_parquet(out_dir / "eur_martin_luke_trades.parquet")
    return tdf


def main():
    fib = run_fib_ensemble_eur()
    ml = run_martin_luke_eur()
    print("\n\n=== EUR CROSS-SYMBOL SUMMARY ===")
    print(f"  Fib V2 Ensemble EUR: {len(fib) if fib is not None else 0} trades")
    if ml is not None:
        print(f"  Martin Luke EUR:     {len(ml)} trades")


if __name__ == "__main__":
    main()
