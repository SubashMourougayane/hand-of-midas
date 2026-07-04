"""Cross-symbol test on SPX500 (Dukascopy) — Fib V2 A+D ensemble.
SAME rules + params as XAU. JPY-specific: quote is 2-3 dp (pip=0.01), so a typical
1-pip spread = 0.01 in price. Cost passed in PRICE units to the harness.

Notional/PnL: 1 std lot = 100,000 USD (base). risk_units are in JPY price (e.g. 0.50
= 50 pips). $/lot for a given risk = risk_units(JPY) * 100000 / SPX500_rate.
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

# JPY typical spread ~1.0 pip = 0.010 in price. Conservative round-trip 1.5 pip = 0.015.
SPX_COST = 0.5


def load_spx():
    h1 = pd.read_parquet("/tmp/oanda_spx_h1.parquet")
    m5 = pd.read_parquet("/tmp/oanda_spx_m5.parquet")
    for df in (h1, m5):
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    return (h1.sort_values("timestamp").reset_index(drop=True),
            m5.sort_values("timestamp").reset_index(drop=True))


def run_fib_ensemble_spx():
    print("[SPX] loading H1 + M5...")
    h1, m5 = load_spx()
    print(f"  H1: {len(h1):,}   M5: {len(m5):,}")
    h1 = build_h1_features(h1)
    m5_f = add_m5_features(m5)
    d1 = resample_d1(m5_f); d1 = add_d1_features(d1)
    m5_f = attach_d1_to_m5(m5_f, d1)
    pivot_events = build_pivot_events(h1, 5)
    print(f"  H1 pivots: {len(pivot_events):,}")

    print("\n=== FIB V2 ENSEMBLE on SPX500 (A + D) ===\n")
    long_kw = dict(direction="long", session="all", max_hold_bars=72*12,
                   ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bull_strong")
    short_kw = dict(direction="short", session="all", max_hold_bars=72*12,
                    ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bear_strong")
    long_sigs = gen_signals_with_regime(m5_f, pivot_events, **long_kw)
    short_sigs = gen_signals_with_regime(m5_f, pivot_events, **short_kw)
    print(f"  long sigs: {len(long_sigs):,}   short sigs: {len(short_sigs):,}")

    lt = simulate_fixed_tp(m5_f, long_sigs, horizon_bars=72*12*2, cost_usd=SPX_COST)
    st = simulate_fixed_tp(m5_f, short_sigs, horizon_bars=72*12*2, cost_usd=SPX_COST)
    ens = pd.concat([lt, st], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)

    print_headline("A · LONG_BULL_STRONG", headline(lt))
    print_headline("D · SHORT_BEAR_STRONG", headline(st))
    print_headline("A+D ENSEMBLE", headline(ens))

    print("\n[Per-year ensemble]")
    by = ens.groupby("year")["net_r"].agg(["sum", "count"]).round(2)
    by.columns = ["net_R", "n"]; print(by.to_string())

    print("\n[Audit — delay + cost stress]")
    for d in (1, 5, 10):
        sl = long_sigs.copy(); sl["entry_index"] = sl["entry_index"].astype(int) + d
        ss = short_sigs.copy(); ss["entry_index"] = ss["entry_index"].astype(int) + d
        ens_d = pd.concat([
            simulate_fixed_tp(m5_f, sl, horizon_bars=72*12*2, cost_usd=SPX_COST),
            simulate_fixed_tp(m5_f, ss, horizon_bars=72*12*2, cost_usd=SPX_COST),
        ], ignore_index=True)
        print_headline(f"  +{d} bar delay", headline(ens_d))
    for extra in (0.010, 0.020):
        ens_c = pd.concat([
            simulate_fixed_tp(m5_f, long_sigs, horizon_bars=72*12*2, cost_usd=SPX_COST + extra),
            simulate_fixed_tp(m5_f, short_sigs, horizon_bars=72*12*2, cost_usd=SPX_COST + extra),
        ], ignore_index=True)
        print_headline(f"  cost+{extra:.3f}", headline(ens_c))

    Path("/Users/subash/SUBASH/GoldDigger/research/cross_symbol").mkdir(exist_ok=True)
    ens.to_parquet("/Users/subash/SUBASH/GoldDigger/research/cross_symbol/spx_fib_ensemble_trades.parquet")

    # ── $1,000 · 3% risk · monthly reset PnL ──
    print("\n=== $1,000 · 3% risk · MONTHLY RESET PnL — SPX500 A+D ===")
    df = ens.sort_values("entry_ts").reset_index(drop=True)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    df["ym"] = df["entry_ts"].dt.strftime("%Y-%m")
    nav = 1000.0; cm = None; monthly = {}; lots_seen = []
    for r in df.itertuples(index=False):
        if cm is None: cm = r.ym; nav = 1000.0
        if r.ym != cm:
            monthly[cm] = nav - 1000.0; cm = r.ym; nav = 1000.0
        ru = float(r.risk_units)                     # JPY price (e.g. 0.50 = 50 pip)
        if ru <= 0: continue
        rate = float(r.entry_price)                  # SPX500
        dollar_per_unit = ru * 100000 / rate          # $ risk per 1.0 std lot
        if dollar_per_unit <= 0: continue
        raw_lots = (nav * 0.03) / dollar_per_unit
        max_m_lots = (0.9 * nav * 1000) / (100000)   # 1000x permissive margin on 100k notional
        lots = math.floor(min(raw_lots, max_m_lots) / 0.01) * 0.01
        if lots < 0.01: continue
        lots_seen.append(lots)
        nav += float(r.net_r) * lots * dollar_per_unit
    if cm: monthly[cm] = nav - 1000.0
    s = pd.Series(monthly).sort_index()
    pos = int((s > 0).sum())
    print(f"trades={len(df)} months={len(s)} pos={pos}/{len(s)} ({pos/max(1,len(s))*100:.0f}%)")
    print(f"total skim=${s[s>0].sum():+,.0f}  net months=${s.sum():+,.0f}  avg/mo=${s.mean():+,.0f}")
    print(f"best {s.idxmax()} ${s.max():+,.0f}  worst {s.idxmin()} ${s.min():+,.0f}")
    if lots_seen:
        print(f"avg_lots={np.mean(lots_seen):.3f} max_lots={max(lots_seen):.2f}")
    print("per-yr:", {k: round(v) for k, v in s.groupby(s.index.str[:4]).sum().items()})
    return ens


if __name__ == "__main__":
    run_fib_ensemble_spx()
