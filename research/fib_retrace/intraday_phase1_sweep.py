"""Phase 1 intraday sweep — M15 pivots + M15 base, full param grid, XAU 20yr.

NO ENGINE CODE CHANGE. NO LOOK-AHEAD.

Grid:
  pivot_lb       ∈ {3, 5, 8}
  max_hold_h     ∈ {2, 4, 8, 12, 24}
  ext_target_pct ∈ {1.0, 1.618, 2.618}
  sl_buffer_pct  ∈ {0.02, 0.10}
  session        ∈ {all, london, ny, london_ny}
  regime         ∈ {any, bull, bear, bull_strong, bear_strong}
  ptp_at_r       ∈ {None, 1.0, 2.0}
  direction      ∈ {long, short}

= 3 × 5 × 3 × 2 × 4 × 5 × 3 × 2 = 5,400 configs.

Pivots run on M15 instead of H1 — multi-hour intraday structure.
Base entry runs on M15 too.

Each config result appended to log + CSV. Heavy logging so tail -f works.

Outputs:
  research/fib_retrace/intraday_phase1/
    sweep.log         (line per config: tail -f to follow)
    matrix.csv        (one row per config, accumulating)
    REPORT.md         (written at end)
"""
from __future__ import annotations

import json
import sys
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import headline
from research.fib_retrace.run_fib import detect_pivots
from research.fib_retrace.run_fib_v2 import build_pivot_events
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5,
)
from research.fib_retrace.safety_net_sweep import simulate_with_safety


OUT = Path(__file__).parent / "intraday_phase1"
OUT.mkdir(parents=True, exist_ok=True)
LOG_PATH = OUT / "sweep.log"
CSV_PATH = OUT / "matrix.csv"
COST_XAU = 0.30

ACCOUNT_START = 5000.0
RISK_DOLLAR_PER_TRADE = ACCOUNT_START * 0.015  # $75


PIVOT_LBS       = [3, 5, 8]
HOLD_HOURS      = [2, 4, 8, 12, 24]
EXT_TARGETS     = [1.0, 1.618, 2.618]
SL_BUFFERS      = [0.02, 0.10]
SESSIONS        = ["all", "london", "ny", "london_ny"]
REGIMES         = ["any", "bull", "bear", "bull_strong", "bear_strong"]
PTP_VALUES      = [None, 1.0, 2.0]
DIRECTIONS      = ["long", "short"]


def log(msg: str, also_print: bool = True) -> None:
    ts = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")
        f.flush()
    if also_print:
        print(line, flush=True)


def resample_m5_to_m15(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in m5.columns:
        agg["volume"] = "sum"
    out = idx.resample("15min", label="left", closed="left").agg(agg).dropna().reset_index()
    return out


def build_m15_pivot_events(m15: pd.DataFrame, lb: int) -> pd.DataFrame:
    """Detect pivots on M15 instead of H1. Same primitive, different TF.

    Causality: detect_pivots emits at idx+lb (no center-rolling). Time-aware.
    """
    # detect_pivots returns (h_idx, l_idx) but build_pivot_events does the merge.
    # Reuse build_pivot_events directly — it takes an H1-like frame with timestamp/high/low.
    return build_pivot_events(m15, lb)


def append_csv_row(row: dict, first: bool) -> None:
    df = pd.DataFrame([row])
    mode = "w" if first else "a"
    header = first
    df.to_csv(CSV_PATH, mode=mode, header=header, index=False)


def main():
    # Reset log + csv
    LOG_PATH.write_text("")
    if CSV_PATH.exists():
        CSV_PATH.unlink()

    log("=== Phase 1 Intraday Sweep ===")
    log("Symbol: XAU | Base TF: M15 | Pivot TF: M15")
    log(f"Total configs: {3*5*3*2*4*5*3*2} = 5,400")
    log("")

    t0 = time.time()
    log("[load] OANDA M5 + H1...")
    h1_raw, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"),
                             Path("/tmp/oanda_xau_m5.parquet"))
    log(f"  M5 bars: {len(m5):,}")

    # M15 base frame
    log("[resample] M5 → M15...")
    m15 = resample_m5_to_m15(m5)
    log(f"  M15 bars: {len(m15):,}")

    # Build features on M15 (uses M5 feature builder; works on M15 fine since it's bar-by-bar features)
    log("[features] add M15 features + D1 regime...")
    m15_f = add_m5_features(m15)
    d1 = add_d1_features(resample_d1(m15_f))
    m15_f = attach_d1_to_m5(m15_f, d1)
    log(f"  M15 feature frame ready: {len(m15_f):,} rows")
    log(f"  Setup: {(time.time()-t0):.1f}s")

    # Pre-build pivot events per pivot_lb (independent of other params)
    log("[pivots] pre-computing M15 pivot events for each lb...")
    pivots_by_lb = {}
    for lb in PIVOT_LBS:
        ev = build_m15_pivot_events(m15_f, lb)
        pivots_by_lb[lb] = ev
        log(f"  lb={lb}: {len(ev):,} pivots")

    # 60min / 15min = 4 M15 bars per hour
    BARS_PER_HOUR = 4

    grid = list(product(PIVOT_LBS, HOLD_HOURS, EXT_TARGETS, SL_BUFFERS,
                         SESSIONS, REGIMES, DIRECTIONS, PTP_VALUES))
    total = len(grid)
    log(f"\n=== Starting sweep: {total} configs ===\n")

    first = True
    t_start = time.time()
    for i, (lb, hold_h, ext, sl_buf, session, regime, direction, ptp) in enumerate(grid, 1):
        max_hold_bars = hold_h * BARS_PER_HOUR
        horizon_bars = max_hold_bars  # strict cap, no doubling
        cfg_id = (f"lb{lb}_h{hold_h}_ext{ext}_sl{sl_buf}_{session}_{regime}_{direction}"
                  f"_ptp{ptp if ptp is not None else 'none'}")

        # Generate signals
        try:
            sigs = gen_signals_with_regime(
                m15_f, pivots_by_lb[lb],
                direction=direction, session=session,
                max_hold_bars=max_hold_bars,
                ext_target_pct=ext, sl_buffer_pct=sl_buf,
                regime=regime,
            )
            n_sigs = len(sigs)
            if n_sigs == 0:
                trades = pd.DataFrame()
            else:
                trades = simulate_with_safety(
                    m15_f, sigs, cost_usd=COST_XAU,
                    horizon_bars=horizon_bars, partial_tp_at_r=ptp,
                )
        except Exception as e:
            log(f"[{i}/{total}] {cfg_id}  ERROR: {e}")
            row = {"cfg_id": cfg_id, "lb": lb, "hold_h": hold_h, "ext": ext,
                   "sl_buf": sl_buf, "session": session, "regime": regime,
                   "direction": direction, "ptp": ptp,
                   "n": 0, "net_R": 0, "PF": 0, "MAR": 0, "WR_pct": 0,
                   "pos_years": "", "dollar_pnl": 0, "error": str(e)}
            append_csv_row(row, first); first = False
            continue

        if len(trades):
            if "year" not in trades.columns:
                trades["year"] = pd.to_datetime(trades["entry_ts"]).dt.year
            h = headline(trades)
            n = len(trades)
            net_r = float(trades["net_r"].sum())
            wins = int((trades["net_r"] > 0).sum())
            wr = wins / n * 100
            dollar_pnl = net_r * RISK_DOLLAR_PER_TRADE
            row = {
                "cfg_id": cfg_id, "lb": lb, "hold_h": hold_h, "ext": ext,
                "sl_buf": sl_buf, "session": session, "regime": regime,
                "direction": direction, "ptp": ptp,
                "n": n, "net_R": round(net_r, 1),
                "PF": round(h.get("pf", 0), 3),
                "MAR": round(h.get("mar", 0), 3),
                "WR_pct": round(wr, 2),
                "pos_years": h.get("pos_years", ""),
                "dollar_pnl": round(dollar_pnl, 0),
                "error": "",
            }
        else:
            row = {
                "cfg_id": cfg_id, "lb": lb, "hold_h": hold_h, "ext": ext,
                "sl_buf": sl_buf, "session": session, "regime": regime,
                "direction": direction, "ptp": ptp,
                "n": 0, "net_R": 0, "PF": 0, "MAR": 0, "WR_pct": 0,
                "pos_years": "", "dollar_pnl": 0, "error": "",
            }

        # ETA + heavy logging
        elapsed = time.time() - t_start
        rate = i / elapsed if elapsed > 0 else 0
        remaining = (total - i) / rate if rate > 0 else 0
        eta_min = remaining / 60

        log(f"[{i:4d}/{total}] {cfg_id:60s}  n={row['n']:>4d}  net_R={row['net_R']:>+7.1f}  "
            f"PF={row['PF']:>4.2f}  MAR={row['MAR']:>+5.2f}  WR={row['WR_pct']:>5.1f}%  "
            f"$PnL={row['dollar_pnl']:>+10,.0f}  pos={row['pos_years']:6s}  "
            f"[ETA {eta_min:.0f}min]")

        append_csv_row(row, first)
        first = False

    elapsed_total = (time.time() - t_start) / 60
    log(f"\n=== Sweep complete: {total} configs in {elapsed_total:.1f} min ===")
    log(f"Output: {CSV_PATH}")

    # Top picks report
    df = pd.read_csv(CSV_PATH)
    df = df[df["n"] >= 100]
    if len(df):
        df_sorted = df.sort_values(["MAR", "PF"], ascending=[False, False])
        top20 = df_sorted.head(20)
        lines = [
            "# Phase 1 Intraday Sweep — Top 20 by MAR",
            "",
            f"Configs run: {total}, with n≥100 trades: {len(df)}",
            f"Total wall time: {elapsed_total:.1f} min",
            "",
            "```",
            top20.to_string(index=False),
            "```",
            "",
            "## Next steps",
            "",
            "1. Cross-validate top 5-10 on EUR (Phase 2)",
            "2. Adversarial battery (delay/cost-stress/walk-forward) on survivors (Phase 3)",
            "3. M30/H1 pivot check (Phase 4)",
        ]
        (OUT / "REPORT.md").write_text("\n".join(lines))
        log(f"Report: {OUT / 'REPORT.md'}")
    log("DONE.")


if __name__ == "__main__":
    main()
