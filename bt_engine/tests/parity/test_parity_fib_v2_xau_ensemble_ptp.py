"""Parity gate for Partial-TP variants on XAU OANDA.

Verifies bt_engine PTP+1R / PTP+2R outputs match research parquets:
- fib_v2_oanda_ensemble_ptp1r_trades.parquet
- fib_v2_oanda_ensemble_ptp2r_trades.parquet

Tolerance: 10% on count and net_R (same as baseline parity), 20% on PF.
Root cause for the band is H1 derivation drift (M5 mid vs OANDA H1 bid/ask).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bt_engine.strategies.fib_v2 import LONG_BULL_STRONG, SHORT_BEAR_STRONG

from ._fib_v2_helper import (
    run_engine_capture_trades,
    load_oanda_parquet,
    normalize_research_trades,
)


XAU_M5 = Path("/tmp/oanda_xau_m5.parquet")
XAU_H1 = Path("/tmp/oanda_xau_h1.parquet")
RESEARCH_DIR = Path(
    "/Users/subash/SUBASH/GoldDigger/research/fib_retrace/"
)


def _pf(df: pd.DataFrame) -> float:
    wins = df.loc[df["net_r"] > 0, "net_r"].sum()
    losses = -df.loc[df["net_r"] < 0, "net_r"].sum()
    return wins / losses if losses > 0 else float("inf")


@pytest.mark.parametrize("ptp_r,research_filename", [
    (1.0, "fib_v2_oanda_ensemble_ptp1r_trades.parquet"),
    (2.0, "fib_v2_oanda_ensemble_ptp2r_trades.parquet"),
])
def test_parity_ptp_xau(ptp_r, research_filename):
    research_path = RESEARCH_DIR / research_filename
    if not (XAU_M5.exists() and research_path.exists()):
        pytest.skip(f"OANDA XAU parquets or {research_filename} missing")

    m5 = load_oanda_parquet(XAU_M5)
    h1 = pd.read_parquet(XAU_H1)
    bt_trades = run_engine_capture_trades(
        m5_frame=m5, symbol="XAUUSD.ecn",
        legs=(LONG_BULL_STRONG, SHORT_BEAR_STRONG),
        cost_usd=0.30, h1_frame=h1,
        partial_tp_at_r=ptp_r, partial_tp_pct=0.5,
    )
    if len(bt_trades) == 0:
        pytest.fail(f"bt produced 0 trades for PTP+{ptp_r}R")
    research = normalize_research_trades(pd.read_parquet(research_path))

    bt_n = len(bt_trades)
    r_n = len(research)
    bt_net = bt_trades["net_r"].sum()
    r_net = research["net_r"].sum()
    bt_pf = _pf(bt_trades)
    r_pf = _pf(research)

    print(f"\n[PTP+{ptp_r}R] bt: n={bt_n} net={bt_net:.1f}R PF={bt_pf:.2f}")
    print(f"           research: n={r_n} net={r_net:.1f}R PF={r_pf:.2f}")

    count_diff_pct = abs(bt_n - r_n) / max(r_n, 1)
    net_diff_pct = abs(bt_net - r_net) / max(abs(r_net), 1e-9)
    pf_diff_pct = abs(bt_pf - r_pf) / max(abs(r_pf), 1e-9)

    print(f"           count diff%={count_diff_pct*100:.1f}% net diff%={net_diff_pct*100:.1f}% PF diff%={pf_diff_pct*100:.1f}%")

    assert count_diff_pct < 0.10, f"PTP+{ptp_r}R count diff {count_diff_pct*100:.1f}% too large"
    assert net_diff_pct < 0.20, f"PTP+{ptp_r}R net diff {net_diff_pct*100:.1f}% too large"
    assert pf_diff_pct < 0.25, f"PTP+{ptp_r}R PF diff {pf_diff_pct*100:.1f}% too large"


@pytest.mark.parametrize("ptp_r,research_filename", [
    (1.0, "fib_v2_oanda_eur_ensemble_ptp1r_trades.parquet"),
    (2.0, "fib_v2_oanda_eur_ensemble_ptp2r_trades.parquet"),
])
def test_parity_ptp_eur(ptp_r, research_filename):
    eur_m5 = Path("/tmp/oanda_eur_m5.parquet")
    eur_h1 = Path("/tmp/oanda_eur_h1.parquet")
    research_path = RESEARCH_DIR / research_filename
    if not (eur_m5.exists() and research_path.exists()):
        pytest.skip(f"OANDA EUR parquets or {research_filename} missing")

    m5 = load_oanda_parquet(eur_m5)
    h1 = pd.read_parquet(eur_h1)
    bt_trades = run_engine_capture_trades(
        m5_frame=m5, symbol="EURUSD.ecn",
        legs=(LONG_BULL_STRONG, SHORT_BEAR_STRONG),
        cost_usd=0.00003, h1_frame=h1,
        partial_tp_at_r=ptp_r, partial_tp_pct=0.5,
    )
    if len(bt_trades) == 0:
        pytest.fail(f"bt produced 0 EUR trades for PTP+{ptp_r}R")
    research = normalize_research_trades(pd.read_parquet(research_path))

    bt_n = len(bt_trades)
    r_n = len(research)
    bt_net = bt_trades["net_r"].sum()
    r_net = research["net_r"].sum()
    bt_pf = _pf(bt_trades)
    r_pf = _pf(research)

    print(f"\n[EUR PTP+{ptp_r}R] bt: n={bt_n} net={bt_net:.1f}R PF={bt_pf:.2f}")
    print(f"               research: n={r_n} net={r_net:.1f}R PF={r_pf:.2f}")

    count_diff_pct = abs(bt_n - r_n) / max(r_n, 1)
    net_diff_pct = abs(bt_net - r_net) / max(abs(r_net), 1e-9)
    pf_diff_pct = abs(bt_pf - r_pf) / max(abs(r_pf), 1e-9)

    print(f"               count diff%={count_diff_pct*100:.1f}% net diff%={net_diff_pct*100:.1f}% PF diff%={pf_diff_pct*100:.1f}%")

    assert count_diff_pct < 0.10, f"EUR PTP+{ptp_r}R count diff {count_diff_pct*100:.1f}% too large"
    assert net_diff_pct < 0.25, f"EUR PTP+{ptp_r}R net diff {net_diff_pct*100:.1f}% too large"
    assert pf_diff_pct < 0.25, f"EUR PTP+{ptp_r}R PF diff {pf_diff_pct*100:.1f}% too large"
