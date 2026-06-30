"""Generate research parity baseline parquets for intraday A+D port.

LOCKED production config:
  A leg: LONG  lb=3 hold=12h session=london_ny regime=any  ext=2.618 sl_buf=0.02 PTP+1R
  D leg: SHORT lb=3 hold=24h session=all       regime=any  ext=2.618 sl_buf=0.02 PTP+1R

Filters applied (matching production port):
  - Dedup: keep first signal per (entry_ts, side, leg)
  - Min risk floor: risk_units >= 0.50 ($0.50 stop on XAU)
  - Cost: $0.65 per trade (JustMarkets Raw Spread realistic)

Outputs:
  research/fib_retrace/intraday_dedup/intraday_a_trades.parquet
  research/fib_retrace/intraday_dedup/intraday_d_trades.parquet
  research/fib_retrace/intraday_dedup/headline.json

NO LOOK-AHEAD. NO PHANTOM FILLS. Same primitives as production (gen_signals_with_regime + simulate_with_safety).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import headline as causal_headline
from research.fib_retrace.run_fib_v2 import build_pivot_events
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5,
)
from research.fib_retrace.safety_net_sweep import simulate_with_safety

OUT = Path(__file__).parent / "intraday_dedup"
OUT.mkdir(parents=True, exist_ok=True)

# Production config (LOCKED)
COST = 0.65
MIN_RISK_UNITS = 0.50
PIVOT_LB = 3
EXT_TARGET = 2.618
SL_BUFFER = 0.02
PTP_AT_R = 1.0
ACCOUNT = 5000.0
RISK_PCT = 0.015
RISK_DOLLAR = ACCOUNT * RISK_PCT  # $75


def resample_m5_to_m15(m5: pd.DataFrame) -> pd.DataFrame:
    """Causally clean resample: label='left', closed='left'. Bar [T, T+15min)."""
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in m5.columns:
        agg["volume"] = "sum"
    out = idx.resample("15min", label="left", closed="left").agg(agg).dropna().reset_index()
    return out


def gen_leg_trades(m15_f: pd.DataFrame, pivots3, *, direction: str, session: str,
                    hold_h: int, leg_name: str) -> pd.DataFrame:
    """Run signals + simulator with dedup + min_risk filter applied."""
    max_hold_bars = hold_h * 4  # M15 = 4 bars/hour

    sigs = gen_signals_with_regime(
        m15_f, pivots3,
        direction=direction, session=session,
        max_hold_bars=max_hold_bars,
        ext_target_pct=EXT_TARGET, sl_buffer_pct=SL_BUFFER,
        regime="any",
    )

    # Attach entry_ts to signals from m15_f
    sigs = sigs.copy()
    sigs["entry_ts"] = m15_f["timestamp"].iloc[sigs["entry_index"].astype(int).values].values

    # Production filter 1: dedup by (entry_ts, side) — keep first
    sigs = sigs.sort_values("entry_index").drop_duplicates(
        subset=["entry_ts", "side"], keep="first"
    ).reset_index(drop=True)
    n_after_dedup = len(sigs)

    # Production filter 2: min_risk floor
    sigs = sigs[sigs["risk_units"] >= MIN_RISK_UNITS].reset_index(drop=True)
    n_after_min_risk = len(sigs)

    # Walk brackets with PTP+1R and strict 12h/24h horizon (NO doubling)
    trades = simulate_with_safety(
        m15_f, sigs,
        cost_usd=COST,
        horizon_bars=max_hold_bars,  # strict cap
        partial_tp_at_r=PTP_AT_R,
    )
    if len(trades) and "year" not in trades.columns:
        trades["year"] = pd.to_datetime(trades["entry_ts"]).dt.year
    trades["leg"] = leg_name
    trades["direction"] = direction
    trades["hold_h"] = hold_h
    trades["session"] = session

    print(f"  [{leg_name}] signals -> dedup {n_after_dedup} -> min_risk {n_after_min_risk} -> trades {len(trades)}")
    return trades


def summarize(trades: pd.DataFrame, label: str) -> dict:
    if len(trades) == 0:
        return {"label": label, "n": 0}
    n = len(trades)
    wins = int((trades["net_r"] > 0).sum())
    wr = wins / n * 100
    gw = float(trades.loc[trades["net_r"] > 0, "net_r"].sum())
    gl = -float(trades.loc[trades["net_r"] < 0, "net_r"].sum())
    pf = gw / gl if gl > 0 else float("inf")
    net_r = float(trades["net_r"].sum())
    dollar = net_r * RISK_DOLLAR

    yb = trades.groupby("year")["net_r"].sum()
    pos_yrs = int((yb > 0).sum())
    total_yrs = len(yb)
    h = causal_headline(trades)
    return {
        "label": label,
        "n": n,
        "WR_pct": round(wr, 2),
        "PF": round(pf, 3),
        "MAR": round(h.get("mar", 0), 3),
        "net_R": round(net_r, 1),
        "dollar_pnl_lifetime_at_1.5pct": round(dollar, 0),
        "dollar_pnl_per_year_avg": round(dollar / 21, 0),
        "pos_years": f"{pos_yrs}/{total_yrs}",
    }


def main():
    print("=" * 80)
    print("Phase 0: Generate intraday A+D dedup parity parquets")
    print("=" * 80)
    print()
    print("Loading XAU OANDA M5 + resample to M15...")
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"),
                         Path("/tmp/oanda_xau_m5.parquet"))
    m15 = resample_m5_to_m15(m5)
    m15_f = add_m5_features(m15)
    d1 = add_d1_features(resample_d1(m15_f))
    m15_f = attach_d1_to_m5(m15_f, d1)
    print(f"  M15 bars: {len(m15_f):,}")
    print(f"  Date range: {m15_f['timestamp'].min()} -> {m15_f['timestamp'].max()}")
    print()

    print(f"Building M15 pivots (lb={PIVOT_LB})...")
    pivots3 = build_pivot_events(m15_f, PIVOT_LB)
    print(f"  Pivots: {len(pivots3):,}")
    print()

    print("Generating A leg (long, london_ny, 12h)...")
    a_trades = gen_leg_trades(m15_f, pivots3,
                                direction="long", session="london_ny",
                                hold_h=12, leg_name="intraday_a_long")
    a_path = OUT / "intraday_a_trades.parquet"
    a_trades.to_parquet(a_path)
    print(f"  Saved: {a_path}")
    print()

    print("Generating D leg (short, all sessions, 24h)...")
    d_trades = gen_leg_trades(m15_f, pivots3,
                                direction="short", session="all",
                                hold_h=24, leg_name="intraday_d_short")
    d_path = OUT / "intraday_d_trades.parquet"
    d_trades.to_parquet(d_path)
    print(f"  Saved: {d_path}")
    print()

    a_h = summarize(a_trades, "intraday_a")
    d_h = summarize(d_trades, "intraday_d")
    combined = pd.concat([a_trades, d_trades], ignore_index=True)
    c_h = summarize(combined, "intraday_a_plus_d")

    print("=" * 80)
    print("PARITY BASELINE HEADLINE")
    print("=" * 80)
    for h in (a_h, d_h, c_h):
        print(f"\n[{h['label']}]")
        for k, v in h.items():
            if k == "label":
                continue
            print(f"  {k}: {v}")

    headline_json = {
        "config": {
            "pivot_lb": PIVOT_LB, "ext_target": EXT_TARGET, "sl_buffer": SL_BUFFER,
            "cost_usd": COST, "min_risk_units": MIN_RISK_UNITS,
            "ptp_at_r": PTP_AT_R, "risk_dollar_per_trade": RISK_DOLLAR,
            "account_start": ACCOUNT,
        },
        "A": a_h, "D": d_h, "combined": c_h,
    }
    with (OUT / "headline.json").open("w") as f:
        json.dump(headline_json, f, indent=2, default=str)
    print(f"\nSaved {OUT}/headline.json")

    target_yr = 38876
    actual = c_h["dollar_pnl_per_year_avg"]
    drift_pct = abs(actual - target_yr) / target_yr * 100
    print()
    print(f"TARGET CHECK: combined $/yr should be ~$38,876 (production-locked)")
    print(f"  Actual: ${actual:+,.0f}    drift: {drift_pct:.2f}%")
    if drift_pct < 5:
        print(f"  PASS - within 5% of target")
    else:
        print(f"  WARN - drift > 5%, investigate before proceeding")


if __name__ == "__main__":
    main()
