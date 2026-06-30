"""Regenerate top 2 VWAP-MSS survivor trades and save parquets."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import load_data, persist, headline, print_headline
from research.vwap_mss.run_vwap_mss import (
    resample, build_features, gen_signals, simulate_rr
)


def main():
    m1, m5, _ = load_data()
    m15 = resample(m1, "15min")
    for df in (m5, m15):
        if "ny_hr" not in df.columns:
            df["ny_hr"] = df["timestamp"].dt.tz_convert("America/New_York").dt.hour
            df["year"] = df["timestamp"].dt.year

    # Short M15 sw3 ny atr1.5 prox0.5 wait5 RR4
    feat = build_features(m15, swing_lookback=3)
    sigs = gen_signals(feat, direction="short", session="ny",
                       retest_prox=0.5, atr_mult=1.5, wait_window=5)
    trades = simulate_rr(feat, sigs, rr=4.0, horizon_bars=96)
    h = headline(trades)
    print_headline("VWAP short M15 sw3 ny", h)
    persist("vwap_mss", "short_M15_sw3_sessny_atr1.5_prox0.5_wait5_RR4.0",
            trades, notes="VWAP-MSS short survivor")

    # Long M5 sw7 ny atr2.0 prox1.0 wait3 RR4
    feat = build_features(m5, swing_lookback=7)
    sigs = gen_signals(feat, direction="long", session="ny",
                       retest_prox=1.0, atr_mult=2.0, wait_window=3)
    trades = simulate_rr(feat, sigs, rr=4.0, horizon_bars=288)
    h = headline(trades)
    print_headline("VWAP long M5 sw7 ny", h)
    persist("vwap_mss", "long_M5_sw7_sessny_atr2.0_prox1.0_wait3_RR4.0",
            trades, notes="VWAP-MSS long survivor")


if __name__ == "__main__":
    main()
