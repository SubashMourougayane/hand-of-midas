"""Adversarial battery for top intraday survivors (XAU only).

5 configs × 6 stress tests = 30 sub-runs.

Stress tests:
  1. Delay test: shift entry_index by +1, +5, +10 M15 bars. Edge from real
     microstructure survives small delays; phantom edge dies.
  2. Cost stress: cost_usd ∈ {0.30, 0.40, 0.50, 0.80, 1.50}. Robust edge tolerates +$0.20 spread.
  3. Walk-forward 60/40 IS/OOS chronological. PF ratio OOS/IS ≥ 0.7 to pass.
  4. Block bootstrap: 1000 resamples, 30-day blocks. P(net<0) ≤ 1%.
  5. Year-by-year breakdown — must show 18+/21 positive years.
  6. Shuffle stress — random year-permutation 1000 trials; show DD distribution.

NO ENGINE CODE CHANGE. NO LOOK-AHEAD. Same primitives as Phase 1 sweep.

Output:
  research/fib_retrace/intraday_battery/
    battery.log       (line per sub-run)
    summary.csv       (one row per config × test)
    REPORT.md         (verdict table)
"""
from __future__ import annotations

import sys
import time
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


OUT = Path(__file__).parent / "intraday_battery"
OUT.mkdir(parents=True, exist_ok=True)
LOG_PATH = OUT / "battery.log"
CSV_PATH = OUT / "summary.csv"

ACCOUNT_START = 5000.0
RISK_DOLLAR = ACCOUNT_START * 0.015  # $75


# Top 5 survivors from Phase 1 (by MAR with diversity profile coverage)
SURVIVORS = [
    {
        "name": "A_best_MAR",
        "lb": 3, "hold_h": 12, "ext": 2.618, "sl_buf": 0.02,
        "session": "london_ny", "regime": "any", "direction": "long", "ptp": 1.0,
    },
    {
        "name": "B_tight_regime",
        "lb": 5, "hold_h": 24, "ext": 2.618, "sl_buf": 0.02,
        "session": "all", "regime": "bull", "direction": "long", "ptp": 1.0,
    },
    {
        "name": "C_high_volume",
        "lb": 3, "hold_h": 8, "ext": 2.618, "sl_buf": 0.02,
        "session": "all", "regime": "any", "direction": "long", "ptp": 1.0,
    },
    {
        "name": "D_short_leg",
        "lb": 3, "hold_h": 24, "ext": 2.618, "sl_buf": 0.02,
        "session": "all", "regime": "any", "direction": "short", "ptp": 1.0,
    },
    {
        "name": "E_dollar_leader",
        "lb": 3, "hold_h": 24, "ext": 2.618, "sl_buf": 0.02,
        "session": "all", "regime": "any", "direction": "long", "ptp": 2.0,
    },
]

BARS_PER_HOUR_M15 = 4


def log(msg: str) -> None:
    ts = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")
        f.flush()
    print(line, flush=True)


def resample_m5_to_m15(m5: pd.DataFrame) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in m5.columns:
        agg["volume"] = "sum"
    out = idx.resample("15min", label="left", closed="left").agg(agg).dropna().reset_index()
    return out


def run_one(
    m15_f: pd.DataFrame, pivots: pd.DataFrame, cfg: dict, *,
    cost_usd: float = 0.30,
    delay_bars: int = 0,
    is_mask=None,
    sig_override: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Run a single survivor with optional delay/IS-mask. Returns (trades, headline)."""
    max_hold_bars = cfg["hold_h"] * BARS_PER_HOUR_M15
    horizon_bars = max_hold_bars  # strict cap

    if sig_override is not None:
        sigs = sig_override.copy()
    else:
        sigs = gen_signals_with_regime(
            m15_f, pivots,
            direction=cfg["direction"], session=cfg["session"],
            max_hold_bars=max_hold_bars,
            ext_target_pct=cfg["ext"], sl_buffer_pct=cfg["sl_buf"],
            regime=cfg["regime"],
        )

    if delay_bars > 0:
        sigs = sigs.copy()
        sigs["entry_index"] = sigs["entry_index"].astype(int) + delay_bars
        sigs = sigs[sigs["entry_index"] < len(m15_f) - 2]

    if is_mask is not None:
        sigs = sigs[is_mask(sigs["entry_index"].values)]

    if len(sigs) == 0:
        return pd.DataFrame(), {}

    trades = simulate_with_safety(
        m15_f, sigs,
        cost_usd=cost_usd, horizon_bars=horizon_bars,
        partial_tp_at_r=cfg["ptp"],
    )
    if len(trades) and "year" not in trades.columns:
        trades["year"] = pd.to_datetime(trades["entry_ts"]).dt.year
    return trades, headline(trades) if len(trades) else {}


def metrics_from_trades(trades: pd.DataFrame, h: dict) -> dict:
    if len(trades) == 0:
        return {"n": 0, "net_R": 0, "PF": 0, "MAR": 0, "WR_pct": 0, "pos_years": "", "$PnL": 0}
    n = len(trades)
    wins = int((trades["net_r"] > 0).sum())
    return {
        "n": n,
        "net_R": round(float(trades["net_r"].sum()), 1),
        "PF": round(h.get("pf", 0), 3),
        "MAR": round(h.get("mar", 0), 3),
        "WR_pct": round(wins / n * 100, 2),
        "pos_years": h.get("pos_years", ""),
        "$PnL": round(float(trades["net_r"].sum()) * RISK_DOLLAR, 0),
    }


def block_bootstrap_p_loss(trades: pd.DataFrame, n_iters: int = 1000,
                             block_days: int = 30, seed: int = 42) -> tuple[float, float, float]:
    """Block bootstrap P(net<0) on daily returns. Returns (p_loss, p05, p95)."""
    if len(trades) == 0:
        return 1.0, 0.0, 0.0
    df = trades.copy()
    df["date"] = pd.to_datetime(df["entry_ts"]).dt.normalize()
    daily = df.groupby("date")["net_r"].sum().sort_index()
    days = daily.index.values
    rets = daily.values
    n_days = len(rets)
    if n_days < block_days * 2:
        return 1.0, 0.0, 0.0

    rng = np.random.default_rng(seed)
    n_blocks = max(1, n_days // block_days)
    sums = []
    for _ in range(n_iters):
        starts = rng.integers(0, n_days - block_days + 1, size=n_blocks)
        sample = np.concatenate([rets[s:s + block_days] for s in starts])
        sums.append(sample.sum())
    sums = np.array(sums)
    return float((sums < 0).mean()), float(np.percentile(sums, 5)), float(np.percentile(sums, 95))


def year_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    if len(trades) == 0:
        return pd.DataFrame()
    g = trades.groupby("year").agg(
        n=("net_r", "count"),
        net_R=("net_r", "sum"),
    ).reset_index()
    g["positive"] = g["net_R"] > 0
    return g


def main():
    LOG_PATH.write_text("")
    if CSV_PATH.exists():
        CSV_PATH.unlink()

    log("=== Adversarial Battery: XAU Top 5 Survivors ===")
    log(f"Sizing: $5,000 account, 1.5% risk per trade (=${RISK_DOLLAR:.0f})")
    log("")

    log("[load] OANDA M5 + H1 + resample to M15...")
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"),
                         Path("/tmp/oanda_xau_m5.parquet"))
    m15 = resample_m5_to_m15(m5)
    m15_f = add_m5_features(m15)
    d1 = add_d1_features(resample_d1(m15_f))
    m15_f = attach_d1_to_m5(m15_f, d1)
    log(f"  M15 bars: {len(m15_f):,}")

    # Pre-compute pivots per unique lb
    pivots_by_lb = {}
    for lb in {cfg["lb"] for cfg in SURVIVORS}:
        pivots_by_lb[lb] = build_pivot_events(m15_f, lb)
        log(f"  lb={lb}: {len(pivots_by_lb[lb]):,} M15 pivots")
    log("")

    summary_rows = []

    for cfg in SURVIVORS:
        log(f"\n{'='*88}")
        log(f"### {cfg['name']}: lb={cfg['lb']} h={cfg['hold_h']} ext={cfg['ext']} "
            f"sl={cfg['sl_buf']} {cfg['session']} {cfg['regime']} {cfg['direction']} ptp={cfg['ptp']}")
        log(f"{'='*88}\n")

        pivots = pivots_by_lb[cfg["lb"]]

        # ----- 0. BASELINE -----
        log(f"[{cfg['name']}] 0. BASELINE cost=$0.30")
        trades_base, h_base = run_one(m15_f, pivots, cfg, cost_usd=0.30)
        m = metrics_from_trades(trades_base, h_base)
        log(f"  n={m['n']:>5}  PF={m['PF']:.2f}  MAR={m['MAR']:+.2f}  WR={m['WR_pct']:.1f}%  net_R={m['net_R']:+.1f}  $PnL={m['$PnL']:+,.0f}  pos={m['pos_years']}")
        baseline_pf = m["PF"]
        baseline_net = m["net_R"]
        summary_rows.append({**cfg, "test": "baseline", **m})

        # ----- 1. DELAY TEST -----
        for delay in [1, 5, 10]:
            t, h = run_one(m15_f, pivots, cfg, cost_usd=0.30, delay_bars=delay)
            m = metrics_from_trades(t, h)
            pf_pct = (m["PF"] / baseline_pf * 100) if baseline_pf > 0 else 0
            verdict = "PASS" if pf_pct >= 50 else "DECAY"
            log(f"[{cfg['name']}] 1. DELAY+{delay} bars ({delay*15}min)  n={m['n']}  PF={m['PF']:.2f} ({pf_pct:.0f}% of baseline)  net_R={m['net_R']:+.1f}  $PnL={m['$PnL']:+,.0f}  {verdict}")
            summary_rows.append({**cfg, "test": f"delay+{delay}", **m, "pf_pct_of_baseline": round(pf_pct, 1), "verdict": verdict})

        # ----- 2. COST STRESS -----
        for cost in [0.40, 0.50, 0.80, 1.50]:
            t, h = run_one(m15_f, pivots, cfg, cost_usd=cost)
            m = metrics_from_trades(t, h)
            verdict = "PASS" if m["net_R"] > 0 and m["PF"] >= 1.2 else "DECAY"
            log(f"[{cfg['name']}] 2. COST=${cost:.2f}  n={m['n']}  PF={m['PF']:.2f}  net_R={m['net_R']:+.1f}  $PnL={m['$PnL']:+,.0f}  {verdict}")
            summary_rows.append({**cfg, "test": f"cost_${cost}", **m, "verdict": verdict})

        # ----- 3. WALK-FORWARD IS/OOS -----
        n_bars = len(m15_f)
        cutoff = int(0.6 * n_bars)
        is_fn = lambda idx_arr, c=cutoff: idx_arr < c
        oos_fn = lambda idx_arr, c=cutoff: idx_arr >= c

        t_is, h_is = run_one(m15_f, pivots, cfg, cost_usd=0.30, is_mask=is_fn)
        t_oos, h_oos = run_one(m15_f, pivots, cfg, cost_usd=0.30, is_mask=oos_fn)
        m_is = metrics_from_trades(t_is, h_is)
        m_oos = metrics_from_trades(t_oos, h_oos)
        pf_ratio = (m_oos["PF"] / m_is["PF"]) if m_is["PF"] > 0 else 0
        wf_verdict = "PASS" if pf_ratio >= 0.7 else "FAIL"
        log(f"[{cfg['name']}] 3. WALK-FWD IS(60%): n={m_is['n']} PF={m_is['PF']:.2f} net_R={m_is['net_R']:+.1f}")
        log(f"[{cfg['name']}] 3. WALK-FWD OOS(40%): n={m_oos['n']} PF={m_oos['PF']:.2f} net_R={m_oos['net_R']:+.1f}  ratio={pf_ratio:.2f}  {wf_verdict}")
        summary_rows.append({**cfg, "test": "walkfwd_IS", **m_is})
        summary_rows.append({**cfg, "test": "walkfwd_OOS", **m_oos, "pf_ratio_oos_is": round(pf_ratio, 2), "verdict": wf_verdict})

        # ----- 4. BLOCK BOOTSTRAP -----
        p_loss, p05, p95 = block_bootstrap_p_loss(trades_base, n_iters=1000, block_days=30)
        bb_verdict = "PASS" if p_loss <= 0.05 else "FAIL"
        log(f"[{cfg['name']}] 4. BLOCK-BOOTSTRAP (1k iters, 30d blocks): P(net<0)={p_loss*100:.2f}%  p05={p05:+.1f}R  p95={p95:+.1f}R  {bb_verdict}")
        summary_rows.append({**cfg, "test": "block_bootstrap",
                              "p_net_negative_pct": round(p_loss * 100, 2),
                              "bootstrap_p05_R": round(p05, 1),
                              "bootstrap_p95_R": round(p95, 1),
                              "verdict": bb_verdict})

        # ----- 5. YEAR-BY-YEAR -----
        yb = year_breakdown(trades_base)
        if len(yb):
            total_y = len(yb)
            pos_y = int(yb["positive"].sum())
            worst_y = yb.loc[yb["net_R"].idxmin()]
            best_y = yb.loc[yb["net_R"].idxmax()]
            yb_verdict = "PASS" if pos_y / total_y >= 0.85 else "FAIL"
            log(f"[{cfg['name']}] 5. YEAR-BY-YEAR: pos={pos_y}/{total_y}  worst {int(worst_y['year'])}={worst_y['net_R']:+.1f}R  best {int(best_y['year'])}={best_y['net_R']:+.1f}R  {yb_verdict}")
            summary_rows.append({**cfg, "test": "year_breakdown",
                                  "pos_year_count": pos_y, "total_years": total_y,
                                  "worst_year_R": round(float(worst_y["net_R"]), 1),
                                  "best_year_R": round(float(best_y["net_R"]), 1),
                                  "verdict": yb_verdict})

        # ----- 6. SHUFFLE STRESS (year-permutation) -----
        if len(yb) >= 5:
            rng = np.random.default_rng(42)
            years_arr = yb["year"].values
            rets_arr = yb["net_R"].values
            shuffled_dds = []
            for _ in range(1000):
                perm = rng.permutation(len(rets_arr))
                cum = np.cumsum(rets_arr[perm])
                run_max = np.maximum.accumulate(cum)
                dd = (cum - run_max).min()
                shuffled_dds.append(dd)
            dds = np.array(shuffled_dds)
            true_cum = np.cumsum(rets_arr)
            true_run_max = np.maximum.accumulate(true_cum)
            true_dd = (true_cum - true_run_max).min()
            dd_pct = float((dds < true_dd).mean())
            sh_verdict = "PASS" if dd_pct >= 0.10 else "WARN"
            log(f"[{cfg['name']}] 6. SHUFFLE-STRESS (1k yr-perms): true_DD={true_dd:.1f}R  median_perm_DD={np.median(dds):.1f}R  p_perm_worse={dd_pct*100:.1f}%  {sh_verdict}")
            summary_rows.append({**cfg, "test": "shuffle_stress",
                                  "true_dd_R": round(true_dd, 1),
                                  "median_shuffled_dd_R": round(float(np.median(dds)), 1),
                                  "p_shuffles_worse_than_true_pct": round(dd_pct * 100, 1),
                                  "verdict": sh_verdict})

    # Save CSV
    df_summary = pd.DataFrame(summary_rows)
    df_summary.to_csv(CSV_PATH, index=False)
    log(f"\nSaved {CSV_PATH}")

    # ----- REPORT verdict table -----
    lines = ["# Adversarial Battery — Verdict Table", "",
              f"Tested: {len(SURVIVORS)} configs × 6 stress dimensions = {len(SURVIVORS)*6} test families.",
              "",
              "## Verdict per config (PASS / DECAY / FAIL)",
              ""]

    verdict_table = []
    for cfg in SURVIVORS:
        sub = df_summary[df_summary["name"] == cfg["name"]]
        baseline = sub[sub["test"] == "baseline"].iloc[0]
        delays = sub[sub["test"].str.startswith("delay")]
        costs = sub[sub["test"].str.startswith("cost_")]
        wf = sub[sub["test"] == "walkfwd_OOS"].iloc[0] if (sub["test"] == "walkfwd_OOS").any() else None
        bb = sub[sub["test"] == "block_bootstrap"].iloc[0] if (sub["test"] == "block_bootstrap").any() else None
        yb = sub[sub["test"] == "year_breakdown"].iloc[0] if (sub["test"] == "year_breakdown").any() else None

        verdict_table.append({
            "config": cfg["name"],
            "baseline_PF": baseline["PF"],
            "baseline_MAR": baseline["MAR"],
            "baseline_$PnL": baseline["$PnL"],
            "delay+1_PF_pct": delays[delays["test"] == "delay+1"]["pf_pct_of_baseline"].iloc[0] if (delays["test"] == "delay+1").any() else 0,
            "delay+5_PF_pct": delays[delays["test"] == "delay+5"]["pf_pct_of_baseline"].iloc[0] if (delays["test"] == "delay+5").any() else 0,
            "delay+10_PF_pct": delays[delays["test"] == "delay+10"]["pf_pct_of_baseline"].iloc[0] if (delays["test"] == "delay+10").any() else 0,
            "cost_$0.50_PF": costs[costs["test"] == "cost_$0.50"]["PF"].iloc[0] if (costs["test"] == "cost_$0.50").any() else 0,
            "cost_$1.50_PF": costs[costs["test"] == "cost_$1.50"]["PF"].iloc[0] if (costs["test"] == "cost_$1.50").any() else 0,
            "OOS/IS_PF_ratio": wf.get("pf_ratio_oos_is", 0) if wf is not None else 0,
            "OOS_verdict": wf.get("verdict", "?") if wf is not None else "?",
            "P(net<0)_pct": bb.get("p_net_negative_pct", 0) if bb is not None else 0,
            "pos_years": f"{yb.get('pos_year_count', 0)}/{yb.get('total_years', 0)}" if yb is not None else "?",
        })

    lines.append("```")
    lines.append(pd.DataFrame(verdict_table).to_string(index=False))
    lines.append("```")
    (OUT / "REPORT.md").write_text("\n".join(lines))
    log("Report written.")
    log("DONE.")


if __name__ == "__main__":
    main()
