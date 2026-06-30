"""Intraday pilot — Fib V2 with hard 12h max-hold cap + M5/M15 base timeframes.

Tests if Fib V2's edge survives when forced into intraday (≤12h hold).

NO ENGINE CODE CHANGE. Reuses research's vectorized signal generator + a forked
walker that overrides max_hold_bars.

Matrix:
  base_tf   ∈ {M5, M15}
  symbols   ∈ {XAU, EUR}
  ptp_modes ∈ {None, 1.0, 2.0}

= 2 × 2 × 3 = 12 runs.

Output:
  research/fib_retrace/intraday_pilot/
    matrix.csv          # one row per (base_tf, symbol, ptp_mode)
    REPORT.md           # plain-english summary

NO LOOK-AHEAD. Same gen_signals_with_regime + same close-based bracket walker;
only the horizon shrinks from 144h to 12h.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import headline
from research.fib_retrace.run_fib import build_h1_features
from research.fib_retrace.run_fib_v2 import build_pivot_events
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5,
)
from research.fib_retrace.safety_net_sweep import simulate_with_safety

OUT_DIR = Path(__file__).parent / "intraday_pilot"
PILOT_CAP_HOURS = 12          # the intraday cap to test
COST_XAU = 0.30
COST_EUR = 0.00003

ACCOUNT_START = 5000.0
RISK_DOLLAR_PER_TRADE = ACCOUNT_START * 0.015  # $75


def resample_m5_to_m15(m5: pd.DataFrame) -> pd.DataFrame:
    """OHLCV resample to M15 with label='left', closed='left' (matches OANDA H1 convention)."""
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in m5.columns:
        agg["volume"] = "sum"
    out = idx.resample("15min", label="left", closed="left").agg(agg).dropna()
    out = out.reset_index()
    return out


def pilot_run(*, label: str, h1: pd.DataFrame, base_tf_frame: pd.DataFrame,
              cost_usd: float, cap_hours: int,
              partial_tp_at_r: float | None) -> dict:
    """Run signals on (h1 pivots, regime) + base_tf entries with N-hour cap.

    base_tf_frame: M5 OR M15 frame with timestamp/open/high/low/close + features.
    cap_hours: hard cap on hold time (overrides default 72h).
    """
    # bars-per-hour for this base TF
    if len(base_tf_frame) >= 2:
        dt_sec = (base_tf_frame["timestamp"].iloc[1] - base_tf_frame["timestamp"].iloc[0]).total_seconds()
    else:
        dt_sec = 300.0
    bars_per_hour = int(round(3600 / dt_sec))
    max_hold_bars = cap_hours * bars_per_hour          # hard cap
    horizon_bars = max_hold_bars                       # NO doubling — strict intraday

    pivots = build_pivot_events(h1, 5)
    long_sigs = gen_signals_with_regime(
        base_tf_frame, pivots, direction="long", session="all",
        max_hold_bars=max_hold_bars,
        ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bull_strong",
    )
    short_sigs = gen_signals_with_regime(
        base_tf_frame, pivots, direction="short", session="all",
        max_hold_bars=max_hold_bars,
        ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bear_strong",
    )
    long_trades = simulate_with_safety(
        base_tf_frame, long_sigs, cost_usd=cost_usd, horizon_bars=horizon_bars,
        partial_tp_at_r=partial_tp_at_r,
    ) if len(long_sigs) else pd.DataFrame()
    short_trades = simulate_with_safety(
        base_tf_frame, short_sigs, cost_usd=cost_usd, horizon_bars=horizon_bars,
        partial_tp_at_r=partial_tp_at_r,
    ) if len(short_sigs) else pd.DataFrame()
    merged = pd.concat([long_trades, short_trades], ignore_index=True)
    if "year" not in merged.columns and len(merged):
        merged["year"] = pd.to_datetime(merged["entry_ts"]).dt.year

    h = headline(merged) if len(merged) else {}
    n = len(merged)
    net_r = float(merged["net_r"].sum()) if n else 0.0
    wins = int((merged["net_r"] > 0).sum()) if n else 0
    pos_years = int(h.get("pos_years", "0").split("/")[0]) if h.get("pos_years") else 0
    total_years = int(h.get("pos_years", "0/0").split("/")[-1]) if h.get("pos_years") else 0
    dollar_pnl = net_r * RISK_DOLLAR_PER_TRADE

    print(f"\n[{label}] n={n} net_R={net_r:+.1f} PF={h.get('pf', 0):.2f} "
          f"WR={(wins/n*100 if n else 0):.1f}% MAR={h.get('mar', 0):+.2f} "
          f"pos_yrs={pos_years}/{total_years} $PnL={dollar_pnl:+,.0f}")

    return {
        "label": label,
        "n": n,
        "net_R": round(net_r, 1),
        "wins": wins,
        "WR_pct": round(wins / n * 100, 2) if n else 0,
        "PF": round(h.get("pf", 0), 3),
        "MAR": round(h.get("mar", 0), 3),
        "pos_years": h.get("pos_years", ""),
        "dollar_pnl": round(dollar_pnl, 0),
        "return_pct_total": round(dollar_pnl / ACCOUNT_START * 100, 1),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"=== Intraday pilot: {PILOT_CAP_HOURS}h hard cap ===")

    rows = []
    for sym, h1_path, m5_path, cost in [
        ("XAU", "/tmp/oanda_xau_h1.parquet", "/tmp/oanda_xau_m5.parquet", COST_XAU),
        ("EUR", "/tmp/oanda_eur_h1.parquet", "/tmp/oanda_eur_m5.parquet", COST_EUR),
    ]:
        print(f"\n=== {sym} ===")
        h1, m5 = load_oanda(Path(h1_path), Path(m5_path))
        h1 = build_h1_features(h1)

        # M5 base
        m5_f = add_m5_features(m5)
        d1 = add_d1_features(resample_d1(m5_f))
        m5_f = attach_d1_to_m5(m5_f, d1)

        # M15 base — resample M5 then re-attach D1 (D1 comes from M5 daily aggregate, unchanged)
        m15 = resample_m5_to_m15(m5)
        m15_f = add_m5_features(m15)  # function name is generic; works on M15 OK
        m15_f = attach_d1_to_m5(m15_f, d1)

        for base_tf_name, base_frame in [("M5", m5_f), ("M15", m15_f)]:
            for ptp_label, ptp_r in [("baseline", None), ("PTP+1R", 1.0), ("PTP+2R", 2.0)]:
                label = f"{sym}/{base_tf_name}/{ptp_label}/{PILOT_CAP_HOURS}h"
                r = pilot_run(
                    label=label, h1=h1, base_tf_frame=base_frame,
                    cost_usd=cost, cap_hours=PILOT_CAP_HOURS,
                    partial_tp_at_r=ptp_r,
                )
                r.update({
                    "symbol": sym, "base_tf": base_tf_name, "ptp_mode": ptp_label,
                    "cap_hours": PILOT_CAP_HOURS, "cost_usd": cost,
                })
                rows.append(r)

    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "matrix.csv", index=False)
    print(f"\nSaved {OUT_DIR}/matrix.csv ({len(rows)} rows)")

    # ---- baseline reference: same signals at 72h cap, M5, no PTP — for context ----
    print("\n=== Reference: M5 / baseline / 72h (production config) ===")
    ref_rows = []
    for sym, h1_path, m5_path, cost in [
        ("XAU", "/tmp/oanda_xau_h1.parquet", "/tmp/oanda_xau_m5.parquet", COST_XAU),
        ("EUR", "/tmp/oanda_eur_h1.parquet", "/tmp/oanda_eur_m5.parquet", COST_EUR),
    ]:
        h1, m5 = load_oanda(Path(h1_path), Path(m5_path))
        h1 = build_h1_features(h1)
        m5_f = add_m5_features(m5)
        d1 = add_d1_features(resample_d1(m5_f))
        m5_f = attach_d1_to_m5(m5_f, d1)
        for ptp_label, ptp_r in [("baseline", None), ("PTP+1R", 1.0), ("PTP+2R", 2.0)]:
            label = f"{sym}/M5/{ptp_label}/72h"
            r = pilot_run(label=label, h1=h1, base_tf_frame=m5_f, cost_usd=cost,
                          cap_hours=72, partial_tp_at_r=ptp_r)
            r.update({"symbol": sym, "base_tf": "M5_72h_REF", "ptp_mode": ptp_label,
                      "cap_hours": 72, "cost_usd": cost})
            ref_rows.append(r)
    ref_df = pd.DataFrame(ref_rows)
    ref_df.to_csv(OUT_DIR / "reference_72h.csv", index=False)
    print(f"Saved {OUT_DIR}/reference_72h.csv")

    # ---- REPORT ----
    lines = ["# Intraday Pilot Report — 12h Hard Cap", ""]
    lines.append(f"Test: re-walk Fib V2 ENSEMBLE signals with `max_hold_h={PILOT_CAP_HOURS}h` hard cap.")
    lines.append("Same SL/TP/regime/fib_382-786 entry zone. Only the time-stop tightens.")
    lines.append("")
    lines.append("**Sizing**: $5,000 account, 1.5% risk per trade ($75).")
    lines.append("")
    lines.append(f"## 12h cap results")
    lines.append("")
    lines.append("```")
    lines.append(df.to_string(index=False))
    lines.append("```")
    lines.append("")
    lines.append(f"## 72h reference (production)")
    lines.append("")
    lines.append("```")
    lines.append(ref_df.to_string(index=False))
    lines.append("```")
    lines.append("")
    lines.append("## Edge-survival check")
    lines.append("")
    survives = []
    dies = []
    for r in rows:
        sym = r["symbol"]; base = r["base_tf"]; ptp = r["ptp_mode"]
        ref_row = [x for x in ref_rows if x["symbol"] == sym and x["ptp_mode"] == ptp][0]
        net_pct = (r["net_R"] / ref_row["net_R"] * 100) if ref_row["net_R"] != 0 else 0
        pf_pct = (r["PF"] / ref_row["PF"] * 100) if ref_row["PF"] > 0 else 0
        line = f"- {sym}/{base}/{ptp}: 12h n={r['n']} net_R={r['net_R']:+.1f} PF={r['PF']:.2f}  vs  72h-M5 n={ref_row['n']} net_R={ref_row['net_R']:+.1f} PF={ref_row['PF']:.2f}  ({net_pct:.0f}% of net, {pf_pct:.0f}% of PF)"
        lines.append(line)
        if pf_pct >= 80:
            survives.append(f"{sym}/{base}/{ptp}")
        else:
            dies.append(f"{sym}/{base}/{ptp}")
    lines.append("")
    lines.append(f"**Survived (≥80% PF kept):** {', '.join(survives) if survives else 'none'}")
    lines.append(f"**Died (<80% PF):** {', '.join(dies) if dies else 'none'}")
    lines.append("")
    lines.append("## Files")
    lines.append("- `matrix.csv` — 12h cap, 2 symbols × 2 base TFs × 3 PTP modes")
    lines.append("- `reference_72h.csv` — production 72h M5 for context")
    (OUT_DIR / "REPORT.md").write_text("\n".join(lines))
    print(f"\nWrote {OUT_DIR}/REPORT.md")


if __name__ == "__main__":
    main()
