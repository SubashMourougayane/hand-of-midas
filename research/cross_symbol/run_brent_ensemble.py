"""Cross-symbol test on BRENT (BCO_USD) OANDA data.

Runs SAME Fib V2 Ensemble + Martin Luke rules + params as XAU.
No re-tuning. This is the strict generalization test.

Cost: $0.05/risk_units (BRENT — tighter spread than gold per memory).
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


BRENT_COST = 0.05  # BRENT $/risk_units


def load_brent():
    h1 = pd.read_parquet("/tmp/oanda_brent_h1.parquet")
    m5 = pd.read_parquet("/tmp/oanda_brent_m5.parquet")
    if h1["timestamp"].dt.tz is None:
        h1["timestamp"] = h1["timestamp"].dt.tz_localize("UTC")
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    h1 = h1.sort_values("timestamp").reset_index(drop=True)
    m5 = m5.sort_values("timestamp").reset_index(drop=True)
    return h1, m5


def run_fib_ensemble_brent():
    print("[BRENT] loading H1 + M5...")
    h1, m5 = load_brent()
    print(f"  H1: {len(h1):,} bars  range {h1.timestamp.min()} → {h1.timestamp.max()}")
    print(f"  M5: {len(m5):,} bars  range {m5.timestamp.min()} → {m5.timestamp.max()}")

    h1 = build_h1_features(h1)
    m5_f = add_m5_features(m5)
    d1 = resample_d1(m5_f)
    d1 = add_d1_features(d1)
    m5_f = attach_d1_to_m5(m5_f, d1)
    pivot_events = build_pivot_events(h1, 5)
    print(f"  H1 pivots: {len(pivot_events):,}")

    print("\n=== FIB V2 ENSEMBLE on BRENT ===\n")

    long_kwargs = dict(direction="long", session="all", max_hold_bars=72*12,
                       ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bull_strong")
    short_kwargs = dict(direction="short", session="all", max_hold_bars=72*12,
                        ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bear_strong")

    print("[gen LONG_BULL_STRONG]")
    long_sigs = gen_signals_with_regime(m5_f, pivot_events, **long_kwargs)
    print(f"  long sigs: {len(long_sigs):,}")
    print("[gen SHORT_BEAR_STRONG]")
    short_sigs = gen_signals_with_regime(m5_f, pivot_events, **short_kwargs)
    print(f"  short sigs: {len(short_sigs):,}")

    long_trades = simulate_fixed_tp(m5_f, long_sigs, horizon_bars=72*12*2, cost_usd=BRENT_COST)
    short_trades = simulate_fixed_tp(m5_f, short_sigs, horizon_bars=72*12*2, cost_usd=BRENT_COST)
    ensemble = pd.concat([long_trades, short_trades], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)

    print(f"\n--- LONG only ---")
    h_long = headline(long_trades)
    print_headline("LONG_BULL_STRONG BRENT", h_long)
    print(f"\n--- SHORT only ---")
    h_short = headline(short_trades)
    print_headline("SHORT_BEAR_STRONG BRENT", h_short)
    print(f"\n--- ENSEMBLE ---")
    h_ens = headline(ensemble)
    print_headline("ENSEMBLE BRENT", h_ens)

    # Per year
    print("\n[Per-year R — ENSEMBLE BRENT]")
    by_yr = ensemble.groupby("year")["net_r"].agg(["sum","count"]).round(2)
    by_yr.columns = ["net_R","n"]
    print(by_yr.to_string())

    # Audit subset
    print("\n=== AUDIT subset ===")
    for d in [1, 5, 10]:
        sl = long_sigs.copy(); sl["entry_index"] = sl["entry_index"].astype(int) + d
        ss = short_sigs.copy(); ss["entry_index"] = ss["entry_index"].astype(int) + d
        tl = simulate_fixed_tp(m5_f, sl, horizon_bars=72*12*2, cost_usd=BRENT_COST)
        ts = simulate_fixed_tp(m5_f, ss, horizon_bars=72*12*2, cost_usd=BRENT_COST)
        ens_d = pd.concat([tl, ts], ignore_index=True)
        print_headline(f"+{d} delay (ensemble)", headline(ens_d))
    for extra in [0.02, 0.05, 0.10]:
        tl = simulate_fixed_tp(m5_f, long_sigs, horizon_bars=72*12*2, cost_usd=BRENT_COST + extra)
        ts = simulate_fixed_tp(m5_f, short_sigs, horizon_bars=72*12*2, cost_usd=BRENT_COST + extra)
        ens_d = pd.concat([tl, ts], ignore_index=True)
        print_headline(f"cost+${extra:.2f} (ensemble)", headline(ens_d))

    # Save
    out_dir = Path("/Users/subash/SUBASH/GoldDigger/research/cross_symbol")
    out_dir.mkdir(parents=True, exist_ok=True)
    ensemble.to_parquet(out_dir / "brent_fib_ensemble_trades.parquet")
    long_trades.to_parquet(out_dir / "brent_fib_long_trades.parquet")
    short_trades.to_parquet(out_dir / "brent_fib_short_trades.parquet")
    print(f"\nsaved → {out_dir}")

    # $5k 3% monthly reset PnL
    print("\n=== $5k 3% monthly reset PnL — BRENT ENSEMBLE ===")
    df = ensemble.sort_values("entry_ts").reset_index(drop=True)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")
    nav = 5000.0; curr_m = None; monthly = {}
    lots_seen = []
    XAU_CONTRACT = 100  # actually BRENT contract is different; use 100 as proxy
    for r in df.itertuples(index=False):
        if curr_m is None: curr_m = r.year_month; nav = 5000.0
        if r.year_month != curr_m:
            monthly[curr_m] = nav - 5000.0
            curr_m = r.year_month; nav = 5000.0
        risk_units = float(r.risk_units)
        if risk_units <= 0: continue
        risk_d = nav * 0.03
        raw_lots = risk_d / (risk_units * XAU_CONTRACT)
        max_m_lots = (0.9 * nav * 1000) / (float(r.entry_price) * XAU_CONTRACT)
        lots = math.floor(min(raw_lots, max_m_lots) / 0.01) * 0.01
        if lots < 0.01: continue
        lots_seen.append(lots)
        pnl = float(r.net_r) * lots * XAU_CONTRACT * risk_units
        nav += pnl
    if curr_m: monthly[curr_m] = nav - 5000.0
    s = pd.Series(monthly).sort_index()
    pos = int((s > 0).sum())
    print(f"trades={len(df)} months={len(s)} pos={pos}/{len(s)}={pos/len(s)*100:.0f}%")
    print(f"total=${s.sum():+,.2f}  avg/mo=${s.mean():+,.2f}")
    print(f"best  {s.idxmax()}: ${s.max():+,.2f}")
    print(f"worst {s.idxmin()}: ${s.min():+,.2f}")
    print(f"avg_lots={np.mean(lots_seen):.3f}  max_lots={max(lots_seen) if lots_seen else 0:.2f}")
    by_yr_d = s.groupby(s.index.str[:4]).sum().round(0).to_dict()
    print(f"per-yr ${by_yr_d}")

    return ensemble


def run_martin_luke_brent():
    print("\n\n" + "=" * 80)
    print(">>> MARTIN LUKE PDH+uptrend+TP3R on BRENT <<<\n")
    h1, m5 = load_brent()
    m5_f = add_m5_features(m5)
    # Build daily from M5
    daily = m5_f.set_index("timestamp").resample("1D", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
    ).dropna().reset_index()
    # ML uses NY-date groupby; need to adapt build_daily for BRENT
    # Simpler: replicate logic inline
    daily["ema9"] = daily["close"].ewm(span=9, adjust=False).mean()
    daily["ema21"] = daily["close"].ewm(span=21, adjust=False).mean()
    daily["ema50"] = daily["close"].ewm(span=50, adjust=False).mean()
    # Lag
    for c in ["close","high","low","ema9","ema21","ema50"]:
        daily[f"{c}_lag"] = daily[c].shift(1)
    daily["uptrend_lag"] = (daily["ema9_lag"] > daily["ema21_lag"]) & (daily["ema21_lag"] > daily["ema50_lag"])
    daily["pdh"] = daily["high_lag"]
    daily["pdl"] = daily["low_lag"]
    daily["ny_date"] = daily["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    daily = daily.sort_values("ny_date").reset_index(drop=True)

    # Map to M5
    m5_f["ny_date"] = m5_f["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    m5_f["ny_hr"] = m5_f["timestamp"].dt.tz_convert("America/New_York").dt.hour
    m5_with_d = m5_f.merge(daily[["ny_date","pdh","pdl","uptrend_lag"]], on="ny_date", how="left")

    # ML signal: M5 close > prior daily high during NY 9-16, uptrend_lag True, one trade per day
    op = m5_with_d["open"].values
    hi = m5_with_d["high"].values
    lo = m5_with_d["low"].values
    cl = m5_with_d["close"].values
    ts = m5_with_d["timestamp"].values
    pdh = m5_with_d["pdh"].values
    pdl = m5_with_d["pdl"].values
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
        # SL = LOD so far this day
        same_day_mask = (days[:i+1] == days[i])
        lod = float(lo[same_day_mask].min())
        stop = lod
        # Hard 5% cap from entry
        max_loss = 0.05 * entry
        if entry - stop > max_loss:
            stop = entry - max_loss
        risk = entry - stop
        if risk <= 0 or not np.isfinite(risk): continue
        tp = entry + 3.0 * risk
        # Walk close-based bracket
        end = min(n - 1, entry_idx + 288)
        outcome_r = 0.0; exit_i = end; broke = False
        for j in range(entry_idx, end + 1):
            c = cl[j]
            if c <= stop:
                outcome_r = -1.0; exit_i = j; broke = True; break
            if c >= tp:
                outcome_r = 3.0; exit_i = j; broke = True; break
        if not broke:
            outcome_r = max(-1.0, min(3.0, (cl[exit_i] - entry) / risk))
        trades.append({
            "entry_ts": ts[entry_idx], "side": 1,
            "entry_price": float(entry), "stop_price": float(stop),
            "tp_price": float(tp), "risk_units": float(risk),
            "exit_index": int(exit_i), "bracket_r": float(outcome_r),
            "cost_r": BRENT_COST / risk,
            "net_r": float(outcome_r) - BRENT_COST / risk,
            "year": int(yrs[entry_idx]),
        })
        last_day = days[i]

    trades_df = pd.DataFrame(trades)
    if len(trades_df) == 0:
        print("[NO TRADES]"); return None
    h = headline(trades_df)
    print_headline("MARTIN LUKE BRENT", h)
    print("\n[Per-year]")
    by_yr = trades_df.groupby("year")["net_r"].agg(["sum","count"]).round(2)
    by_yr.columns = ["net_R","n"]
    print(by_yr.to_string())

    out_dir = Path("/Users/subash/SUBASH/GoldDigger/research/cross_symbol")
    out_dir.mkdir(parents=True, exist_ok=True)
    trades_df.to_parquet(out_dir / "brent_martin_luke_trades.parquet")
    print(f"saved → {out_dir / 'brent_martin_luke_trades.parquet'}")

    # $5k 3% monthly reset
    print("\n=== $5k 3% monthly reset PnL — BRENT MARTIN LUKE ===")
    df = trades_df.sort_values("entry_ts").reset_index(drop=True)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["year_month"] = df["entry_ts"].dt.strftime("%Y-%m")
    nav = 5000.0; curr_m = None; monthly = {}
    XAU_CONTRACT = 100
    for r in df.itertuples(index=False):
        if curr_m is None: curr_m = r.year_month; nav = 5000.0
        if r.year_month != curr_m:
            monthly[curr_m] = nav - 5000.0
            curr_m = r.year_month; nav = 5000.0
        risk_units = float(r.risk_units)
        if risk_units <= 0: continue
        risk_d = nav * 0.03
        raw_lots = risk_d / (risk_units * XAU_CONTRACT)
        max_m_lots = (0.9 * nav * 1000) / (float(r.entry_price) * XAU_CONTRACT)
        lots = math.floor(min(raw_lots, max_m_lots) / 0.01) * 0.01
        if lots < 0.01: continue
        pnl = float(r.net_r) * lots * XAU_CONTRACT * risk_units
        nav += pnl
    if curr_m: monthly[curr_m] = nav - 5000.0
    s = pd.Series(monthly).sort_index()
    pos = int((s > 0).sum())
    print(f"trades={len(df)} months={len(s)} pos={pos}/{len(s)}")
    print(f"total=${s.sum():+,.2f}  avg/mo=${s.mean():+,.2f}")
    print(f"best  {s.idxmax()}: ${s.max():+,.2f}")
    print(f"worst {s.idxmin()}: ${s.min():+,.2f}")
    by_yr_d = s.groupby(s.index.str[:4]).sum().round(0).to_dict()
    print(f"per-yr ${by_yr_d}")
    return trades_df


def main():
    # Run Fib ensemble
    fib_trades = run_fib_ensemble_brent()
    # Run Martin Luke
    ml_trades = run_martin_luke_brent()
    print("\n\n=== CROSS-SYMBOL SUMMARY ===")
    print(f"  Fib V2 Ensemble BRENT: {len(fib_trades)} trades")
    if ml_trades is not None:
        print(f"  Martin Luke BRENT:     {len(ml_trades)} trades")


if __name__ == "__main__":
    main()
