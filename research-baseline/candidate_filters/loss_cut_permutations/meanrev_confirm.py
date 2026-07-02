"""MEAN-REVERSION CONFIRMATION oscillators as AT-ENTRY loss-cut filters.

POST-HOC RESEARCH ONLY. Zero strategy/BT/live edits. Reads existing bt_trades
(run b6604240) + raw OANDA M5 parquet. Writes nothing to prod.

Motivation (9,120-BT study): mean-reversion is the ONLY category with positive
OOS Sharpe. Top survivors: RSI+200EMA, Ultimate Oscillator, Money Flow Index.
Fib V2 IS mean-reversion (long = buy the dip off a fib extension). So a mean-rev
confirmation oscillator should KEEP trades where the oscillator agrees the move
is stretched (long only if oversold, short only if overbought) and DROP the rest.

CAUSALITY (bible-enforced via _causal_lib):
  - RSI/MFI/UO computed on M15 (and H1) bars.
  - For each trade at entry_ts T, we attach the oscillator value from the LAST
    bar whose close_ts (= bar_open + tf) <= T. searchsorted(..., 'right')-1 on
    close_ts. NEVER the still-forming bar. This is the exact same causal attach
    used elsewhere in the harness.
  - 200-EMA regime: EMA of closes up to the last CLOSED bar before T.
  - All rolling stats min_periods = full window.

Filters (each: True = KEEP):
  RSI(14) extreme alignment:
     long  -> RSI <= long_thr  (oversold, dip confirmed)
     short -> RSI >= short_thr (overbought)
  200-EMA regime (classic RSI+200EMA survivor uses trend regime):
     Two flavours tested:
       (a) TREND-ALIGN : long only if price>EMA200, short only if price<EMA200
       (b) MEANREV-STRETCH: long only if price<EMA200 (deep below), short if above
  Money Flow Index(14): same extreme alignment as RSI.
  Ultimate Oscillator(7,14,28): same extreme alignment.

We report filtered PF/WR/net-R/pos-years vs baseline and, crucially,
delta_r = (losers-R saved) - (winners-R lost) so we see if the filter actually
saves net profit rather than just trimming count.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _causal_lib as L  # noqa: E402


# ───────────────────────── oscillator builders (causal) ─────────────────────
# All operate on a resampled HTF frame that already has bar_open_ts + close_ts.
# Each returns the frame with the new column; value at bar i uses only bars <= i.

def add_rsi(df: pd.DataFrame, period: int = 14, col: str = "close",
            out: str = "rsi") -> pd.DataFrame:
    d = df.copy()
    delta = d[col].diff()
    up = delta.clip(lower=0.0)
    dn = -delta.clip(upper=0.0)
    # Wilder smoothing (causal, backward-looking EMA-style)
    roll_up = up.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    roll_dn = dn.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = roll_up / roll_dn.replace(0.0, np.nan)
    d[out] = 100.0 - (100.0 / (1.0 + rs))
    d.loc[roll_dn == 0, out] = 100.0
    return d


def add_ema(df: pd.DataFrame, period: int = 200, col: str = "close",
            out: str = "ema200") -> pd.DataFrame:
    d = df.copy()
    d[out] = d[col].ewm(span=period, adjust=False, min_periods=period).mean()
    return d


def add_mfi(df: pd.DataFrame, period: int = 14, out: str = "mfi") -> pd.DataFrame:
    d = df.copy()
    tp = (d["high"] + d["low"] + d["close"]) / 3.0
    rmf = tp * d["volume"].clip(lower=1)
    dtp = tp.diff()
    pos = rmf.where(dtp > 0, 0.0)
    neg = rmf.where(dtp < 0, 0.0)
    pos_sum = pos.rolling(period, min_periods=period).sum()
    neg_sum = neg.rolling(period, min_periods=period).sum()
    mfr = pos_sum / neg_sum.replace(0.0, np.nan)
    d[out] = 100.0 - (100.0 / (1.0 + mfr))
    d.loc[neg_sum == 0, out] = 100.0
    return d


def add_uo(df: pd.DataFrame, s: int = 7, m: int = 14, l: int = 28,
           out: str = "uo") -> pd.DataFrame:
    d = df.copy()
    prev_close = d["close"].shift(1)
    true_low = pd.concat([d["low"], prev_close], axis=1).min(axis=1)
    true_high = pd.concat([d["high"], prev_close], axis=1).max(axis=1)
    bp = d["close"] - true_low
    tr = true_high - true_low
    def avg(n):
        return (bp.rolling(n, min_periods=n).sum()
                / tr.rolling(n, min_periods=n).sum().replace(0.0, np.nan))
    a7, a14, a28 = avg(s), avg(m), avg(l)
    d[out] = 100.0 * (4 * a7 + 2 * a14 + a28) / 7.0
    return d


# ───────────────────────── delta-R accounting ─────────────────────
def delta_r_report(all_trades: pd.DataFrame, keep: pd.Series) -> dict:
    """Net-R impact of dropping the ~keep trades.

    delta_r = (R saved by dropping losers) - (R lost by dropping winners)
            = -sum(net_r of dropped trades)   [dropping removes their net_r]
    Positive delta_r => filter improved net R.
    """
    dropped = all_trades[~keep]
    kept = all_trades[keep]
    dropped_losers_r = -dropped.loc[dropped.net_r <= 0, "net_r"].sum()   # >0 saved
    dropped_winners_r = dropped.loc[dropped.net_r > 0, "net_r"].sum()    # >0 lost
    delta_r = float(dropped_losers_r - dropped_winners_r)  # == -dropped.net_r.sum()
    posY, totY = L.yearly_positive(kept)
    h = L.headline(kept)
    return {
        "n": h.get("n", 0), "pf": h.get("pf", float("nan")),
        "wr": h.get("wr", float("nan")), "sum_r": h.get("sum_r", float("nan")),
        "dropped": int((~keep).sum()),
        "dropped_losers_r_saved": round(float(dropped_losers_r), 1),
        "dropped_winners_r_lost": round(float(dropped_winners_r), 1),
        "delta_r": round(delta_r, 1),
        "pos_years": f"{posY}/{totY}",
    }


def dir_extreme_mask(trades: pd.DataFrame, osc_col: str,
                     long_thr: float, short_thr: float) -> pd.Series:
    """KEEP long if osc<=long_thr (oversold); KEEP short if osc>=short_thr."""
    keep = pd.Series(True, index=trades.index)
    have = trades[osc_col].notna()
    is_long = trades["direction"] == "long"
    # NaN oscillator -> pass (no data, don't fabricate a reject)
    long_keep = (~is_long) | (trades[osc_col] <= long_thr)
    short_keep = (is_long) | (trades[osc_col] >= short_thr)
    m = long_keep & short_keep
    keep = m | (~have)
    return keep


def main() -> None:
    print("[LOAD] trades + M5 ...")
    trades = L.load_trades()
    m5 = L.load_m5()
    print(f"  trades={len(trades):,}  m5={len(m5):,}")

    m15 = L.resample_causal(m5, "15min")
    h1 = L.resample_causal(m5, "1h")

    # Build oscillators on M15 and H1
    m15 = add_rsi(m15, 14, out="rsi14")
    m15 = add_ema(m15, 200, out="ema200")
    m15 = add_mfi(m15, 14, out="mfi14")
    m15 = add_uo(m15, out="uo")
    h1 = add_rsi(h1, 14, out="rsi14")
    h1 = add_ema(h1, 200, out="ema200")

    # Attach causally (last bar with close_ts <= entry_ts)
    trades = L.attach_htf_feature_causal(trades, m15, "rsi14", "m15_rsi")
    trades = L.attach_htf_feature_causal(trades, m15, "ema200", "m15_ema200")
    trades = L.attach_htf_feature_causal(trades, m15, "close", "m15_close")
    trades = L.attach_htf_feature_causal(trades, m15, "mfi14", "m15_mfi")
    trades = L.attach_htf_feature_causal(trades, m15, "uo", "m15_uo")
    trades = L.attach_htf_feature_causal(trades, h1, "rsi14", "h1_rsi")
    trades = L.attach_htf_feature_causal(trades, h1, "ema200", "h1_ema200")
    trades = L.attach_htf_feature_causal(trades, h1, "close", "h1_close")

    # Restrict to parquet coverage (fair baseline)
    cov = trades["m15_close"].notna()
    trades = trades[cov].reset_index(drop=True)

    base = L.headline(trades)
    bposY, btotY = L.yearly_positive(trades)
    print(f"\n=== BASELINE (parquet-covered) ===")
    print(f"  n={base['n']:,}  PF={base['pf']}  WR={base['wr']}%  "
          f"sumR={base['sum_r']}  posYears={bposY}/{btotY}")
    base_pf = base["pf"]

    # Diagnostic: quintile of M15 RSI vs outcome, split by direction
    print("\n=== Diagnostic: M15 RSI quintiles by direction ===")
    for d in ["long", "short"]:
        sub = trades[trades.direction == d]
        print(f"  --- {d} (n={len(sub)}) ---")
        for row in L.quintile_table(sub, "m15_rsi"):
            print(f"    {row['label']} range={row.get('range')} "
                  f"n={row['n']} PF={row['pf']} WR={row['wr']} sumR={row['sum_r']}")

    results = []

    def run(name, keep, rule):
        r = delta_r_report(trades, keep)
        r["name"] = name
        r["rule"] = rule
        results.append(r)
        print(f"\n=== {name} ===")
        print(f"  rule: {rule}")
        print(f"  n={r['n']:,} (dropped {r['dropped']:,})  PF={r['pf']} "
              f"(base {base_pf})  WR={r['wr']}%  sumR={r['sum_r']}  "
              f"posYears={r['pos_years']}")
        print(f"  loser-R saved={r['dropped_losers_r_saved']}  "
              f"winner-R lost={r['dropped_winners_r_lost']}  "
              f"delta_R={r['delta_r']}")

    # ── RSI extreme alignment (M15) — several thresholds ──
    for lt, st in [(50, 50), (45, 55), (40, 60), (35, 65), (30, 70)]:
        run(f"M15_RSI_align L<={lt}/S>={st}",
            dir_extreme_mask(trades, "m15_rsi", lt, st),
            f"long: m15_rsi<={lt}; short: m15_rsi>={st} (last closed M15)")

    # ── RSI extreme alignment (H1) ──
    for lt, st in [(45, 55), (40, 60), (35, 65)]:
        run(f"H1_RSI_align L<={lt}/S>={st}",
            dir_extreme_mask(trades, "h1_rsi", lt, st),
            f"long: h1_rsi<={lt}; short: h1_rsi>={st} (last closed H1)")

    # ── 200-EMA regime, TREND-ALIGN (long above, short below) ──
    is_long = trades["direction"] == "long"
    above15 = trades["m15_close"] > trades["m15_ema200"]
    have15 = trades["m15_ema200"].notna()
    trend_align = ((is_long & above15) | (~is_long & ~above15)) | (~have15)
    run("M15_EMA200_trend_align", trend_align,
        "long: close>ema200; short: close<ema200 (M15, last closed)")

    stretch = ((is_long & ~above15) | (~is_long & above15)) | (~have15)
    run("M15_EMA200_meanrev_stretch", stretch,
        "long: close<ema200; short: close>ema200 (M15, last closed)")

    above_h1 = trades["h1_close"] > trades["h1_ema200"]
    have_h1 = trades["h1_ema200"].notna()
    trend_align_h1 = ((is_long & above_h1) | (~is_long & ~above_h1)) | (~have_h1)
    run("H1_EMA200_trend_align", trend_align_h1,
        "long: close>ema200; short: close<ema200 (H1, last closed)")

    # ── MFI extreme alignment (M15) ──
    for lt, st in [(50, 50), (40, 60), (30, 70), (20, 80)]:
        run(f"M15_MFI_align L<={lt}/S>={st}",
            dir_extreme_mask(trades, "m15_mfi", lt, st),
            f"long: m15_mfi<={lt}; short: m15_mfi>={st} (last closed M15)")

    # ── Ultimate Oscillator extreme alignment (M15) ──
    for lt, st in [(50, 50), (40, 60), (30, 70)]:
        run(f"M15_UO_align L<={lt}/S>={st}",
            dir_extreme_mask(trades, "m15_uo", lt, st),
            f"long: m15_uo<={lt}; short: m15_uo>={st} (last closed M15)")

    # ── Best combo probe: RSI + trend regime (the classic survivor) ──
    rsi_align_40_60 = dir_extreme_mask(trades, "m15_rsi", 40, 60)
    run("M15_RSI40/60 + EMA200_trend_align",
        rsi_align_40_60 & trend_align,
        "RSI extreme AND price on trend side of EMA200 (M15)")
    run("M15_RSI40/60 + EMA200_meanrev_stretch",
        rsi_align_40_60 & stretch,
        "RSI extreme AND price stretched vs EMA200 (M15)")

    # ── Summary sorted by delta_R ──
    print("\n\n================ SUMMARY (by delta_R) ================")
    results.sort(key=lambda r: r["delta_r"], reverse=True)
    print(f"{'name':<42} {'n':>6} {'PF':>6} {'dR':>8} {'posY':>6}")
    for r in results:
        flag = ""
        if r["pf"] and r["pf"] > base_pf and r["delta_r"] > 0:
            flag = "  <== PF up & dR+"
        print(f"{r['name']:<42} {r['n']:>6,} {r['pf']:>6} "
              f"{r['delta_r']:>8} {r['pos_years']:>6}{flag}")
    print(f"\nBASELINE PF={base_pf}  posYears={bposY}/{btotY}  n={base['n']:,}")


if __name__ == "__main__":
    main()
