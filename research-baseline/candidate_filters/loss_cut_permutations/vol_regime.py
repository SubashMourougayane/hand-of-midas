"""VOLATILITY / ATR REGIME loss-cut research — POST-HOC ONLY. Zero prod edits.

Fib V2 intraday mean-reversion on XAUUSD M15. Baseline run b6604240:
  27,950 trades, 8279R, PF 1.516, 48.9% WR, 21/21 pos years.
Mean-reversion traps live in specific vol regimes. Question: which AT-ENTRY vol
regime holds the losers? Filter, recompute, keep only causal (knowable at entry).

All features derived from bars whose CLOSE <= entry_ts (via _causal_lib):
  - D1 ATR14 (Wilder) percentile rank vs trailing history  -> vol regime
  - Intraday M15 ATR14 vs its own trailing median           -> expansion/contraction
  - ATR-normalized stop distance (|entry-stop| / D1 ATR14)  -> how tight the stop is
  - Current M15 bar range vs recent 20-bar avg range         -> range ratio at entry

Run:
  python3 research-baseline/candidate_filters/loss_cut_permutations/vol_regime.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _causal_lib as L  # noqa: E402


BASELINE_PF = 1.516


# ─────────────────────────── ATR (Wilder) ───────────────────────────

def wilder_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Backward-looking Wilder ATR on an OHLC frame. min_periods=n (no partial).
    Value at bar i uses bars [.. i], all closed by construction (close_ts=open+tf).
    """
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    # Wilder smoothing == EWM alpha=1/n, but require full window first
    atr = tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    return atr


def pctile_rank_trailing(s: pd.Series, window: int) -> pd.Series:
    """Trailing percentile rank of the CURRENT value within the last `window`
    values INCLUDING current (all values are from closed bars). Backward-looking.
    """
    def _rank(x):
        return (x[:-1] <= x[-1]).mean() if len(x) > 1 else np.nan
    return s.rolling(window, min_periods=window).apply(_rank, raw=True)


# ─────────────────────────── metrics ───────────────────────────

def stats(net_r: np.ndarray) -> dict:
    n = len(net_r)
    if n == 0:
        return {"n": 0, "wr": 0.0, "sum_r": 0.0, "pf": 0.0}
    prof = net_r[net_r > 0].sum()
    loss = -net_r[net_r <= 0].sum()
    pf = prof / loss if loss > 0 else float("inf")
    return {"n": n, "wr": round(100.0 * (net_r > 0).mean(), 2),
            "sum_r": round(float(net_r.sum()), 1), "pf": round(float(pf), 3)}


def pos_years(df: pd.DataFrame) -> str:
    g = df.groupby("year")["net_r"].sum()
    return f"{int((g > 0).sum())}/{int(len(g))}"


def evaluate(base: pd.DataFrame, mask: pd.Series, name: str) -> dict:
    """mask=True means KEEP the trade. Report kept vs baseline + net-R delta."""
    kept = base[mask]
    dropped = base[~mask]
    b = stats(base["net_r"].to_numpy())
    k = stats(kept["net_r"].to_numpy())
    # net R change vs baseline = -(sum of dropped net_r)
    # if we drop net losers, dropped.sum()<0 -> delta_r positive (saved)
    delta_r = -float(dropped["net_r"].sum())
    dropped_losers_saved = -float(dropped.loc[dropped.net_r <= 0, "net_r"].sum())
    dropped_winners_lost = float(dropped.loc[dropped.net_r > 0, "net_r"].sum())
    return {
        "name": name,
        "n_base": b["n"], "n_kept": k["n"], "n_dropped": len(dropped),
        "pf_base": b["pf"], "pf_kept": k["pf"],
        "wr_kept": k["wr"], "sumr_kept": k["sum_r"],
        "delta_r": round(delta_r, 1),
        "saved": round(dropped_losers_saved, 1),
        "gave_up": round(dropped_winners_lost, 1),
        "pos_years": pos_years(kept),
    }


def main() -> None:
    print("Loading trades + M5 ...", flush=True)
    tr = L.load_trades()
    m5 = L.load_m5()
    print(f"trades={len(tr)}  m5_bars={len(m5)}", flush=True)

    base = stats(tr["net_r"].to_numpy())
    print(f"\nBASELINE (recomputed): {base}  pos_years={pos_years(tr)}", flush=True)

    # ── D1 ATR14 + trailing percentile (252-bar ~ 1yr trading-day trailing) ──
    d1 = L.resample_causal(m5, "1D")
    d1["d1_atr14"] = wilder_atr(d1, 14)
    d1["d1_atr_pct252"] = pctile_rank_trailing(d1["d1_atr14"], 252)
    d1["d1_atr_pct63"] = pctile_rank_trailing(d1["d1_atr14"], 63)  # ~quarter
    # D1 close_ts = open+1D -> only usable for entries after the day fully closes.
    tr = L.attach_htf_feature_causal(tr, d1, "d1_atr14", "d1_atr14")
    tr = L.attach_htf_feature_causal(tr, d1, "d1_atr_pct252", "d1_atr_pct252")
    tr = L.attach_htf_feature_causal(tr, d1, "d1_atr_pct63", "d1_atr_pct63")

    # ── M15 ATR14 + expansion ratio vs trailing 20-bar median ──
    m15 = L.resample_causal(m5, "15min")
    m15["m15_atr14"] = wilder_atr(m15, 14)
    m15 = L.rolling_feature_causal(m15, "m15_atr14", 20, "median", "m15_atr_med20")
    m15["m15_atr_exp"] = m15["m15_atr14"] / m15["m15_atr_med20"]
    # current bar range vs recent avg range
    m15["m15_range"] = m15["high"] - m15["low"]
    m15 = L.rolling_feature_causal(m15, "m15_range", 20, "mean", "m15_range_avg20")
    m15["m15_range_ratio"] = m15["m15_range"] / m15["m15_range_avg20"]
    tr = L.attach_htf_feature_causal(tr, m15, "m15_atr14", "m15_atr14")
    tr = L.attach_htf_feature_causal(tr, m15, "m15_atr_exp", "m15_atr_exp")
    tr = L.attach_htf_feature_causal(tr, m15, "m15_range_ratio", "m15_range_ratio")

    # ── ATR-normalized stop distance (knowable at entry: entry+stop prices) ──
    tr["stop_dist"] = (tr["entry_price"] - tr["stop_price"]).abs()
    tr["stop_atr_ratio"] = tr["stop_dist"] / tr["d1_atr14"]

    # ─────────────── QUINTILE DIAGNOSTICS (where do losers live?) ───────────────
    print("\n" + "=" * 78)
    print("QUINTILE TABLES — locate the losers by vol regime")
    print("=" * 78)
    for feat in ["d1_atr14", "d1_atr_pct252", "d1_atr_pct63", "m15_atr14",
                 "m15_atr_exp", "m15_range_ratio", "stop_atr_ratio"]:
        qt = L.quintile_table(tr, feat)
        if not qt:
            print(f"\n[{feat}] insufficient data")
            continue
        print(f"\n[{feat}]  (Q1=low ... Q5=high)")
        for r in qt:
            print(f"  {r['label']}: n={r['n']:5d} wr={r.get('wr',0):5.1f}% "
                  f"sumR={r.get('sum_r',0):8.1f} pf={r.get('pf',0):.3f} "
                  f"range={r.get('range')}")

    # ─────────────── DECILE tails (top/bottom decile skip) ───────────────
    print("\n" + "=" * 78)
    print("DECILE TAILS — bottom/top 10% behaviour")
    print("=" * 78)
    for feat in ["d1_atr_pct252", "d1_atr14", "m15_atr_exp", "m15_range_ratio",
                 "stop_atr_ratio"]:
        d = tr.dropna(subset=[feat])
        if len(d) < 200:
            continue
        lo = d[feat].quantile(0.10)
        hi = d[feat].quantile(0.90)
        bot = stats(d.loc[d[feat] <= lo, "net_r"].to_numpy())
        top = stats(d.loc[d[feat] >= hi, "net_r"].to_numpy())
        print(f"\n[{feat}] bottom-decile(<= {lo:.4f}): {bot}")
        print(f"[{feat}] top-decile   (>= {hi:.4f}): {top}")

    # ─────────────── CANDIDATE FILTERS (keep-mask = accept) ───────────────
    print("\n" + "=" * 78)
    print("CANDIDATE FILTERS (net_r ledger surgery)")
    print("=" * 78)
    results = []

    def add(name, mask):
        # only evaluate over trades where feature is defined; undefined -> KEEP
        r = evaluate(tr, mask.fillna(True), name)
        results.append(r)
        print(f"\n{name}")
        print(f"  n {r['n_base']}->{r['n_kept']} (drop {r['n_dropped']}) "
              f"PF {r['pf_base']}->{r['pf_kept']} wr={r['wr_kept']}% "
              f"sumR_kept={r['sumr_kept']} deltaR={r['delta_r']} "
              f"(saved {r['saved']} losers, gave up {r['gave_up']} winners) "
              f"pos_years={r['pos_years']}")

    # F1: skip bottom-decile D1 ATR percentile (compressed daily vol)
    add("F1_skip_d1_atr_pct252_bottom10",
        ~(tr["d1_atr_pct252"] <= tr["d1_atr_pct252"].quantile(0.10)))
    # F2: skip top-decile D1 ATR percentile (blow-off high vol)
    add("F2_skip_d1_atr_pct252_top10",
        ~(tr["d1_atr_pct252"] >= tr["d1_atr_pct252"].quantile(0.90)))
    # F3: skip both tails (keep middle 80%)
    add("F3_keep_d1_atr_pct252_mid80",
        (tr["d1_atr_pct252"] > tr["d1_atr_pct252"].quantile(0.10)) &
        (tr["d1_atr_pct252"] < tr["d1_atr_pct252"].quantile(0.90)))
    # F4: skip bottom quartile raw D1 ATR (absolute compression)
    add("F4_skip_d1_atr14_bottom25",
        ~(tr["d1_atr14"] <= tr["d1_atr14"].quantile(0.25)))
    # F5: skip M15 ATR expansion top decile (chasing expansion into MR)
    add("F5_skip_m15_atr_exp_top10",
        ~(tr["m15_atr_exp"] >= tr["m15_atr_exp"].quantile(0.90)))
    # F6: skip M15 ATR contraction bottom decile
    add("F6_skip_m15_atr_exp_bottom10",
        ~(tr["m15_atr_exp"] <= tr["m15_atr_exp"].quantile(0.10)))
    # F7: skip entry-bar range spike (range ratio top decile)
    add("F7_skip_m15_range_ratio_top10",
        ~(tr["m15_range_ratio"] >= tr["m15_range_ratio"].quantile(0.90)))
    # F8: skip very tight ATR-normalized stops (bottom quartile)
    add("F8_skip_stop_atr_ratio_bottom25",
        ~(tr["stop_atr_ratio"] <= tr["stop_atr_ratio"].quantile(0.25)))
    # F9: skip very wide ATR-normalized stops (top decile)
    add("F9_skip_stop_atr_ratio_top10",
        ~(tr["stop_atr_ratio"] >= tr["stop_atr_ratio"].quantile(0.90)))
    # F10: combo — keep mid-vol D1 regime AND not a range spike
    add("F10_mid_d1vol_and_no_range_spike",
        (tr["d1_atr_pct252"] > tr["d1_atr_pct252"].quantile(0.10)) &
        (tr["d1_atr_pct252"] < tr["d1_atr_pct252"].quantile(0.90)) &
        (tr["m15_range_ratio"] < tr["m15_range_ratio"].quantile(0.90)))

    print("\n" + "=" * 78)
    print("SUMMARY (sorted by delta_r desc)")
    print("=" * 78)
    for r in sorted(results, key=lambda x: -x["delta_r"]):
        verdict = "PROMISING" if (r["pf_kept"] > BASELINE_PF and r["delta_r"] > 0
                                  and r["saved"] > r["gave_up"]) else ""
        print(f"  {r['name']:40s} PF {r['pf_kept']:.3f} deltaR {r['delta_r']:+8.1f} "
              f"drop {r['n_dropped']:5d} py {r['pos_years']:>6s} {verdict}")

    # coverage sanity: how many trades had each feature defined
    print("\nFEATURE COVERAGE (non-null):")
    for feat in ["d1_atr14", "d1_atr_pct252", "m15_atr_exp", "m15_range_ratio",
                 "stop_atr_ratio"]:
        print(f"  {feat}: {tr[feat].notna().sum()}/{len(tr)}")


if __name__ == "__main__":
    main()
