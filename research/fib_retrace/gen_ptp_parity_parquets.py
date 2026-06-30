"""Generate research parity parquets for Partial-TP safety-net variants.

Runs the proven `gen_signals_with_regime` + `simulate_with_safety(partial_tp_at_r=...)`
on the same OANDA M5/H1 data already used for baseline ENSEMBLE parquets.

Outputs (in research/fib_retrace/):
  - fib_v2_oanda_ensemble_ptp1r_trades.parquet
  - fib_v2_oanda_ensemble_ptp2r_trades.parquet
  - fib_v2_oanda_eur_ensemble_ptp1r_trades.parquet  (if EUR parquets exist)
  - fib_v2_oanda_eur_ensemble_ptp2r_trades.parquet

NO LOOK-AHEAD. NO PHANTOM FILLS. Uses identical signal generator + walker as
baseline; only adds the partial-TP layer in simulate_with_safety.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import headline, print_headline
from research.fib_retrace.run_fib import build_h1_features
from research.fib_retrace.run_fib_v2 import build_pivot_events
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5,
)
from research.fib_retrace.safety_net_sweep import simulate_with_safety, MAX_HOLD_BARS

OUT_DIR = Path(__file__).parent


def build_ensemble_ptp(
    *, h1_path: Path, m5_path: Path, cost_usd: float, partial_tp_at_r: float, label: str,
) -> pd.DataFrame:
    """Run ensemble (long_bull_strong + short_bear_strong) with partial-TP safety net."""
    print(f"\n=== {label}: partial_tp_at_r={partial_tp_at_r} cost=${cost_usd:g} ===")
    print(f"[load] H1={h1_path} M5={m5_path}")
    h1, m5 = load_oanda(h1_path, m5_path)
    h1 = build_h1_features(h1)
    m5_f = add_m5_features(m5)
    d1 = resample_d1(m5_f)
    d1 = add_d1_features(d1)
    m5_f = attach_d1_to_m5(m5_f, d1)
    pivot_events = build_pivot_events(h1, 5)
    print(f"  H1 pivots: {len(pivot_events):,}")

    long_sigs = gen_signals_with_regime(
        m5_f, pivot_events, direction="long", session="all",
        max_hold_bars=MAX_HOLD_BARS,
        ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bull_strong",
    )
    short_sigs = gen_signals_with_regime(
        m5_f, pivot_events, direction="short", session="all",
        max_hold_bars=MAX_HOLD_BARS,
        ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bear_strong",
    )
    print(f"  long_bull_strong sigs: {len(long_sigs):,}")
    print(f"  short_bear_strong sigs: {len(short_sigs):,}")

    long_trades = simulate_with_safety(
        m5_f, long_sigs, cost_usd=cost_usd, partial_tp_at_r=partial_tp_at_r,
    ) if len(long_sigs) else pd.DataFrame()
    short_trades = simulate_with_safety(
        m5_f, short_sigs, cost_usd=cost_usd, partial_tp_at_r=partial_tp_at_r,
    ) if len(short_sigs) else pd.DataFrame()

    if len(long_trades) > 0 and "year" not in long_trades.columns:
        long_trades["year"] = pd.to_datetime(long_trades["entry_ts"]).dt.year
    if len(short_trades) > 0 and "year" not in short_trades.columns:
        short_trades["year"] = pd.to_datetime(short_trades["entry_ts"]).dt.year
    long_trades["leg"] = "long_bull_strong"
    short_trades["leg"] = "short_bear_strong"

    merged = pd.concat([long_trades, short_trades], ignore_index=True).sort_values("entry_ts").reset_index(drop=True)
    print(f"\n[ensemble PTP{partial_tp_at_r:g}R] combined trades: {len(merged):,}")
    print_headline(label, headline(merged))
    return merged


def main() -> None:
    # --- XAU ---
    for ptp_r in (1.0, 2.0):
        out_path = OUT_DIR / f"fib_v2_oanda_ensemble_ptp{int(ptp_r)}r_trades.parquet"
        merged = build_ensemble_ptp(
            h1_path=Path("/tmp/oanda_xau_h1.parquet"),
            m5_path=Path("/tmp/oanda_xau_m5.parquet"),
            cost_usd=0.30,
            partial_tp_at_r=ptp_r,
            label=f"XAU ENSEMBLE PTP+{ptp_r:g}R",
        )
        merged.to_parquet(out_path)
        print(f"saved → {out_path}")

    # --- EUR (if data exists) ---
    eur_h1 = Path("/tmp/oanda_eur_h1.parquet")
    eur_m5 = Path("/tmp/oanda_eur_m5.parquet")
    if eur_h1.exists() and eur_m5.exists():
        for ptp_r in (1.0, 2.0):
            out_path = OUT_DIR / f"fib_v2_oanda_eur_ensemble_ptp{int(ptp_r)}r_trades.parquet"
            merged = build_ensemble_ptp(
                h1_path=eur_h1, m5_path=eur_m5,
                cost_usd=0.00003,
                partial_tp_at_r=ptp_r,
                label=f"EUR ENSEMBLE PTP+{ptp_r:g}R",
            )
            merged.to_parquet(out_path)
            print(f"saved → {out_path}")
    else:
        print("\n[skip EUR] /tmp/oanda_eur_h1.parquet not found — regenerate via research/data/oanda_fetch.py if needed.")


if __name__ == "__main__":
    main()
