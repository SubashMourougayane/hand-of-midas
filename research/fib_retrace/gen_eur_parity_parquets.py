"""Regenerate EUR Fib V2 ensemble + per-leg parquets for parity testing.

Output:
  research/fib_retrace/fib_v2_oanda_eur_long_bull_strong_trades.parquet
  research/fib_retrace/fib_v2_oanda_eur_short_bear_strong_trades.parquet
  research/fib_retrace/fib_v2_oanda_eur_ensemble_trades.parquet

Uses /tmp/oanda_eur_h1.parquet + /tmp/oanda_eur_m5.parquet (21.5yr).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import headline, print_headline
from research.fib_retrace.run_fib import build_h1_features
from research.fib_retrace.run_fib_v2 import build_pivot_events, simulate_fixed_tp
from research.fib_retrace.run_fib_v2_21yr import add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5,
)


EUR_COST = 0.00003
OUT_DIR = Path("/Users/subash/SUBASH/GoldDigger/research/fib_retrace")


def main() -> None:
    print("[load] EUR H1 + M5...")
    h1 = pd.read_parquet("/tmp/oanda_eur_h1.parquet")
    m5 = pd.read_parquet("/tmp/oanda_eur_m5.parquet")
    if h1["timestamp"].dt.tz is None:
        h1["timestamp"] = h1["timestamp"].dt.tz_localize("UTC")
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    h1 = h1.sort_values("timestamp").reset_index(drop=True)
    m5 = m5.sort_values("timestamp").reset_index(drop=True)
    print(f"  H1: {len(h1):,}   M5: {len(m5):,}")

    h1 = build_h1_features(h1)
    m5_f = add_m5_features(m5)
    d1 = resample_d1(m5_f); d1 = add_d1_features(d1)
    m5_f = attach_d1_to_m5(m5_f, d1)
    pivot_events = build_pivot_events(h1, 5)
    print(f"  pivots: {len(pivot_events):,}")

    long_sigs = gen_signals_with_regime(
        m5_f, pivot_events, direction="long", session="all",
        max_hold_bars=72*12, ext_target_pct=1.618, sl_buffer_pct=0.02,
        regime="bull_strong",
    )
    short_sigs = gen_signals_with_regime(
        m5_f, pivot_events, direction="short", session="all",
        max_hold_bars=72*12, ext_target_pct=1.618, sl_buffer_pct=0.02,
        regime="bear_strong",
    )
    print(f"  long sigs: {len(long_sigs):,}   short sigs: {len(short_sigs):,}")

    lt = simulate_fixed_tp(m5_f, long_sigs, horizon_bars=72*12*2, cost_usd=EUR_COST)
    st = simulate_fixed_tp(m5_f, short_sigs, horizon_bars=72*12*2, cost_usd=EUR_COST)
    ens = pd.concat([lt, st], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)

    lt.to_parquet(OUT_DIR / "fib_v2_oanda_eur_long_bull_strong_trades.parquet")
    st.to_parquet(OUT_DIR / "fib_v2_oanda_eur_short_bear_strong_trades.parquet")
    ens.to_parquet(OUT_DIR / "fib_v2_oanda_eur_ensemble_trades.parquet")

    print_headline("EUR LONG_BULL_STRONG", headline(lt))
    print_headline("EUR SHORT_BEAR_STRONG", headline(st))
    print_headline("EUR ENSEMBLE", headline(ens))


if __name__ == "__main__":
    main()
