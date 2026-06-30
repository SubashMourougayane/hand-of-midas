"""Fib V2 on OANDA 20-year data. Same rules as run_fib_v2.py but
loads from /tmp/oanda_xau_h1.parquet + /tmp/oanda_xau_m5.parquet.

Re-test on 2006-2026 to validate the edge across 2008 crash + 2011-2015 bear +
2016-2020 base + 2020+ bull regimes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import headline, persist, print_headline, gate, COST_USD
from research.fib_retrace.run_fib import build_h1_features, detect_pivots, in_session
from research.fib_retrace.run_fib_v2 import (
    build_pivot_events, gen_signals_v2, simulate_fixed_tp
)


H1_PARQUET = Path("/tmp/oanda_xau_h1.parquet")
M5_PARQUET = Path("/tmp/oanda_xau_m5.parquet")


def load_oanda(h1_path: Path, m5_path: Path):
    h1 = pd.read_parquet(h1_path)
    m5 = pd.read_parquet(m5_path)
    # Normalise tz to UTC
    if h1["timestamp"].dt.tz is None:
        h1["timestamp"] = h1["timestamp"].dt.tz_localize("UTC")
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    h1 = h1.sort_values("timestamp").reset_index(drop=True)
    m5 = m5.sort_values("timestamp").reset_index(drop=True)
    return h1, m5


def add_m5_features(m5: pd.DataFrame, swing_lb: int = 20, atr_period: int = 14) -> pd.DataFrame:
    df = m5.copy()
    df[f"swing_high_{swing_lb}_lag"] = df["high"].shift(1).rolling(swing_lb).max()
    df[f"swing_low_{swing_lb}_lag"] = df["low"].shift(1).rolling(swing_lb).min()
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14_m5"] = tr.rolling(atr_period).mean()
    df["atr14_m5_lag"] = df["atr14_m5"].shift(1)
    df["ny_hr"] = df["timestamp"].dt.tz_convert("America/New_York").dt.hour
    df["year"] = df["timestamp"].dt.year
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["winner", "sweep"], default="winner")
    args = ap.parse_args()

    print("[load] OANDA H1 + M5...")
    h1, m5 = load_oanda(H1_PARQUET, M5_PARQUET)
    print(f"  H1: {len(h1):,} bars ({h1.timestamp.min()} → {h1.timestamp.max()})")
    print(f"  M5: {len(m5):,} bars ({m5.timestamp.min()} → {m5.timestamp.max()})")

    h1 = build_h1_features(h1)
    m5_f = add_m5_features(m5)

    if args.mode == "winner":
        # Re-run TOP1 config from 6.75yr backtest on 20yr data
        cfg = dict(direction="long", pivot_lb=5, max_hold_h=72, session="all",
                   ext=1.618, sl_buf=0.02)
        print(f"\n[winner] config: {cfg}")
        pivot_events = build_pivot_events(h1, cfg["pivot_lb"])
        print(f"  pivot events (lb={cfg['pivot_lb']}): {len(pivot_events):,}")
        max_hold_bars = cfg["max_hold_h"] * 12
        sigs = gen_signals_v2(m5_f, pivot_events,
                              direction=cfg["direction"], session=cfg["session"],
                              min_diff_atr=0.0, max_hold_bars=max_hold_bars,
                              ext_target_pct=cfg["ext"], sl_buffer_pct=cfg["sl_buf"])
        print(f"  signals: {len(sigs):,}")
        if len(sigs) == 0:
            print("[empty]"); return
        trades = simulate_fixed_tp(m5_f, sigs, horizon_bars=max_hold_bars*2)
        if len(trades) == 0:
            print("[no trades]"); return

        h = headline(trades)
        g = gate(h)
        print_headline("BASELINE 20yr", h)

        # Save
        out = Path("/Users/subash/SUBASH/GoldDigger/research/fib_retrace/"
                   "fib_v2_oanda_20yr_winner_trades.parquet")
        trades.to_parquet(out)
        print(f"[save] → {out}")

        # 9-test audit
        print("\n=== AUDIT (20yr) ===")
        for d in [1, 3, 5, 10]:
            s = sigs.copy(); s["entry_index"] = s["entry_index"].astype(int) + d
            print_headline(f"+{d} delay", headline(simulate_fixed_tp(m5_f, s, horizon_bars=max_hold_bars*2)))
        for extra in [0.10, 0.20, 0.50]:
            print_headline(f"cost+${extra:.2f}",
                headline(simulate_fixed_tp(m5_f, sigs, horizon_bars=max_hold_bars*2,
                                            cost_usd=0.30 + extra)))
        n = len(m5_f)
        is_mask = sigs["entry_index"].astype(int) < int(0.6 * n)
        print_headline("IS 60%", headline(simulate_fixed_tp(m5_f, sigs[is_mask], horizon_bars=max_hold_bars*2)))
        print_headline("OOS 40%", headline(simulate_fixed_tp(m5_f, sigs[~is_mask], horizon_bars=max_hold_bars*2)))
        # Bootstrap
        rng = np.random.default_rng(42)
        nets = np.array([trades["net_r"].sample(n=len(trades), replace=True,
                          random_state=rng.integers(10**9)).sum() for _ in range(3000)])
        print(f"BOOTSTRAP n=3000: P(net<0)={(nets<0).mean()*100:.2f}% p05={np.percentile(nets,5):+.1f}R")
        y = trades.groupby("year")["net_r"].sum().round(2)
        print(f"\n[Per-year R]")
        for yr, r in y.items():
            print(f"  {yr}: {r:+.2f}R")
        # Per-regime grouping
        print("\n[Per-regime R]")
        regimes = [
            ("2007-2008 (pre-crash/crash)", 2007, 2008),
            ("2009-2010 (recovery)", 2009, 2010),
            ("2011 (peak $1900)", 2011, 2011),
            ("2012-2015 (bear)", 2012, 2015),
            ("2016-2018 (base)", 2016, 2018),
            ("2019-2020 (breakout/COVID)", 2019, 2020),
            ("2021-2023 (range)", 2021, 2023),
            ("2024-2026 (parabolic up)", 2024, 2026),
        ]
        for name, y0, y1 in regimes:
            slc = trades[(trades.year >= y0) & (trades.year <= y1)]
            if len(slc):
                h_slc = headline(slc)
                print(f"  {name:35s} n={len(slc):>5d} net={h_slc['net']:+7.1f}R "
                      f"PF={h_slc['pf']:>4.2f} pos_yrs={h_slc['pos_years']}")
        return

    if args.mode == "sweep":
        # Re-sweep small grid on 20yr to find optimal params
        print("\n=== Phase 2 (20yr) deep sweep ===\n")
        rows = []
        for pivot_lb in [3, 5, 8]:
            pivot_events = build_pivot_events(h1, pivot_lb)
            for direction in ["long", "short"]:
                for max_hold_h in [24, 48, 72]:
                    max_hold_bars = max_hold_h * 12
                    for sess in ["all", "london", "ny", "overlap"]:
                        for ext in [1.0, 1.618, 2.0]:
                            for sl_buf in [0.02, 0.05]:
                                sigs = gen_signals_v2(m5_f, pivot_events,
                                    direction=direction, session=sess,
                                    min_diff_atr=0.0, max_hold_bars=max_hold_bars,
                                    ext_target_pct=ext, sl_buffer_pct=sl_buf)
                                if len(sigs) == 0: continue
                                trades = simulate_fixed_tp(m5_f, sigs, horizon_bars=max_hold_bars*2)
                                if len(trades) == 0: continue
                                h = headline(trades); g = gate(h)
                                label = f"{direction}_lb{pivot_lb}_hold{max_hold_h}h_sess{sess}_ext{ext}_sl{sl_buf}_OANDA20yr"
                                rows.append({
                                    "direction": direction, "pivot_lb": pivot_lb,
                                    "max_hold_h": max_hold_h, "session": sess,
                                    "ext": ext, "sl_buf": sl_buf, **h,
                                    **{f"gate_{k}": v for k, v in g.items()},
                                    "label": label,
                                })
                                if h["pf"] >= 1.3 and "/" in h["pos_years"]:
                                    pos = int(h["pos_years"].split("/")[0])
                                    if pos >= 12:
                                        print_headline(label, h)
        lb = pd.DataFrame(rows)
        out = Path("/Users/subash/SUBASH/GoldDigger/research/fib_retrace/sweep_v2_oanda_20yr.csv")
        lb.to_csv(out, index=False)
        print(f"\n[save] → {out}")
        print("\n[TOP 30 by MAR]")
        top = lb.sort_values("mar", ascending=False).head(30)
        cols = ["direction", "pivot_lb", "max_hold_h", "session", "ext", "sl_buf",
                "n", "trades_per_year", "pf", "mar", "pos_years"]
        print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
