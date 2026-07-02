"""WICK / ABSORPTION proxy filters — POST-HOC RESEARCH ONLY. Zero prod edits.

Whale-checklist idea: 'absorption — price stalls / wicks at the level'. We have
NO tick delta, so we PROXY absorption with candle GEOMETRY + volume, computed
strictly from bars whose CLOSE timestamp <= entry_ts (BIBLE rule 1).

Fib V2 is intraday MEAN-REVERSION: longs fade down into a support/fib zone,
shorts fade up into a resistance/fib zone. "Absorption" for a mean-reversion
LONG = a REJECTION of lower prices => a long LOWER wick on the last closed bar
(sellers pushed down, buyers absorbed and closed it back up). For a SHORT =
rejection of higher prices => a long UPPER wick. So the tradeable proxy is
DIRECTION-AWARE wick rejection at the signal, plus volume confirmation and
consecutive-rejection candle counts.

Signal bar = the LAST fully-closed bar before entry_ts, on M5 and on M15
(the strategy's native timeframe). Both provably causal via close_ts.

Features (all CAUSAL — from bars whose close_ts <= entry_ts):
  * rej_wick_ratio  : direction-aligned rejection-wick length / total range of
                      the last closed bar. Long trade -> lower wick; short -> upper.
  * opp_wick_ratio  : the OPPOSITE wick ratio (continuation wick).
  * body_ratio      : |close-open| / range (small body + big wick = indecision/absorb).
  * vol_spike       : signal-bar volume / rolling mean of prior N bar volumes
                      (min_periods=full window, shifted so it excludes... it is the
                      signal bar's own volume vs the trailing mean of PRIOR bars).
  * n_rej           : consecutive prior bars (incl signal) with an aligned rejection
                      wick > threshold (stack of rejections at the zone).

Filters KEEP trades that show absorption confirmation. We report kept PF/WR/net-R,
dropped losers saved vs winners lost (net delta_R), and pos-years.

Baseline: global PF 1.516 (b6604240). In-coverage baseline reported at runtime.

Run:
  python3 research-baseline/candidate_filters/loss_cut_permutations/wick_absorption.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _causal_lib as L  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# Causal signal-bar geometry attach
# ─────────────────────────────────────────────────────────────────────────

def build_bar_geometry(m5: pd.DataFrame, tf: str, vol_win: int = 20) -> pd.DataFrame:
    """Resample M5 -> tf, compute per-bar wick/body geometry + trailing volume
    baseline, return frame keyed by close_ts. Value at a bar is derived only from
    THAT bar's own OHLCV plus a trailing mean of PRIOR bars' volume. Usable for a
    trade iff bar.close_ts <= entry_ts (handled by attach via searchsorted).
    """
    b = L.resample_causal(m5, tf).sort_values("bar_open_ts").reset_index(drop=True)
    o, h, l, c = b["open"], b["high"], b["low"], b["close"]
    rng = (h - l).replace(0, np.nan)
    upper_wick = h - np.maximum(o, c)
    lower_wick = np.minimum(o, c) - l
    body = (c - o).abs()
    b["upper_wick_ratio"] = (upper_wick / rng).clip(0, 1)
    b["lower_wick_ratio"] = (lower_wick / rng).clip(0, 1)
    b["body_ratio"] = (body / rng).clip(0, 1)
    b["bar_range"] = (h - l)
    # trailing volume mean of PRIOR bars (shift(1) so signal bar's own vol excluded
    # from its own baseline); min_periods=full window => no partial-window leak.
    prior_vol_mean = b["volume"].shift(1).rolling(vol_win, min_periods=vol_win).mean()
    b["vol_spike"] = b["volume"] / prior_vol_mean
    # aligned-rejection streak needs direction, computed after attach. Keep raw wicks.
    keep = ["bar_open_ts", "close_ts", "open", "high", "low", "close",
            "upper_wick_ratio", "lower_wick_ratio", "body_ratio", "bar_range",
            "vol_spike"]
    return b[keep].dropna(subset=["upper_wick_ratio"]).reset_index(drop=True)


def attach_last_closed_bar(trades: pd.DataFrame, bars: pd.DataFrame,
                           cols: list[str], suffix: str) -> pd.DataFrame:
    """Attach bar[cols] from the LAST bar whose close_ts <= entry_ts. Causal."""
    ct = bars["close_ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    ent = trades["entry_timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    idx = np.searchsorted(ct, ent, side="right") - 1
    valid = idx >= 0
    t = trades.copy()
    for col in cols:
        vals = bars[col].to_numpy()
        out = np.full(len(trades), np.nan)
        out[valid] = vals[idx[valid]]
        t[f"{col}_{suffix}"] = out
    t[f"_idx_{suffix}"] = np.where(valid, idx, -1)
    return t


def aligned_rej_streak(trades: pd.DataFrame, bars: pd.DataFrame, suffix: str,
                       thresh: float = 0.4, max_look: int = 4) -> np.ndarray:
    """Count consecutive bars ending at the last-closed bar (index _idx_{suffix})
    that show an aligned rejection wick >= thresh. Long -> lower wick; short ->
    upper wick. Walks BACKWARD from the last closed bar only (all causal)."""
    up = bars["upper_wick_ratio"].to_numpy()
    lo = bars["lower_wick_ratio"].to_numpy()
    idxs = trades[f"_idx_{suffix}"].to_numpy()
    is_long = (trades["direction"] == "long").to_numpy()
    out = np.zeros(len(trades), dtype=int)
    for i in range(len(trades)):
        j = idxs[i]
        if j < 0:
            continue
        arr = lo if is_long[i] else up  # aligned rejection wick
        cnt = 0
        for k in range(max_look):
            jj = j - k
            if jj < 0:
                break
            if arr[jj] >= thresh:
                cnt += 1
            else:
                break
        out[i] = cnt
    return out


# ─────────────────────────────────────────────────────────────────────────
# Metrics (mirror sibling harnesses)
# ─────────────────────────────────────────────────────────────────────────

def stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return dict(n=0, wr=0.0, pf=0.0, sum_r=0.0)
    wr = 100.0 * (df.net_r > 0).mean()
    prof = df.loc[df.net_r > 0, "net_r"].sum()
    loss = -df.loc[df.net_r <= 0, "net_r"].sum()
    pf = prof / loss if loss > 0 else float("inf")
    return dict(n=n, wr=round(wr, 2), pf=round(float(pf), 3),
                sum_r=round(float(df.net_r.sum()), 1))


def posyears(df: pd.DataFrame) -> tuple[int, int]:
    if df.empty:
        return 0, 0
    g = df.groupby("year")["net_r"].sum()
    return int((g > 0).sum()), int(len(g))


def report(name: str, rule: str, keep: pd.Series, trades: pd.DataFrame,
           base: dict, base_py: tuple, results: list) -> None:
    keep = pd.Series(keep, index=trades.index).fillna(False)
    kept = trades[keep].reset_index(drop=True)
    dropped = trades[~keep].reset_index(drop=True)
    s = stats(kept)
    py = posyears(kept)
    d_losers = -dropped.loc[dropped.net_r <= 0, "net_r"].sum()   # R saved
    d_winners = dropped.loc[dropped.net_r > 0, "net_r"].sum()    # R lost
    delta_r = float(d_losers - d_winners)
    print(f"\n=== {name} ===")
    print(f"  kept n={s['n']:>6,d} WR={s['wr']:>6.2f} PF={s['pf']:>6.3f} "
          f"sumR={s['sum_r']:>8.1f} posyr={py[0]}/{py[1]}")
    print(f"  dropped n={len(dropped):>5,d} losers_saved={d_losers:+.1f}R "
          f"winners_lost={d_winners:+.1f}R net_deltaR={delta_r:+.1f}R")
    results.append(dict(name=name, rule=rule, s=s, py=py, delta_r=delta_r,
                        n_dropped=len(dropped)))


def main() -> None:
    print("[LOAD] trades..."); trades = L.load_trades()
    print(f"  {len(trades):,} trades")
    print("[LOAD] M5..."); m5 = L.load_m5()
    print(f"  {len(m5):,} M5 bars {m5.timestamp.min()} -> {m5.timestamp.max()}")

    print("[BUILD] M15 signal-bar geometry (causal)...")
    g15 = build_bar_geometry(m5, "15min", vol_win=20)
    print("[BUILD] M5 signal-bar geometry (causal)...")
    g5 = build_bar_geometry(m5, "5min", vol_win=20)

    trades = attach_last_closed_bar(
        trades, g15,
        ["upper_wick_ratio", "lower_wick_ratio", "body_ratio", "vol_spike"], "m15")
    trades = attach_last_closed_bar(
        trades, g5,
        ["upper_wick_ratio", "lower_wick_ratio", "body_ratio", "vol_spike"], "m5")

    # direction-aligned rejection wick on the last closed bar
    is_long = (trades["direction"] == "long")
    trades["rej_wick_m15"] = np.where(is_long, trades["lower_wick_ratio_m15"],
                                      trades["upper_wick_ratio_m15"])
    trades["opp_wick_m15"] = np.where(is_long, trades["upper_wick_ratio_m15"],
                                      trades["lower_wick_ratio_m15"])
    trades["rej_wick_m5"] = np.where(is_long, trades["lower_wick_ratio_m5"],
                                     trades["upper_wick_ratio_m5"])

    trades["n_rej_m15"] = aligned_rej_streak(trades, g15, "m15", thresh=0.4, max_look=4)
    trades["n_rej_m5"] = aligned_rej_streak(trades, g5, "m5", thresh=0.4, max_look=4)

    # coverage: need M15 geometry present (and vol_spike finite)
    cov = trades.dropna(subset=["rej_wick_m15", "vol_spike_m15",
                                "rej_wick_m5", "vol_spike_m5"]).reset_index(drop=True)
    print(f"[COVERAGE] {len(cov):,} trades with causal M5+M15 geometry")

    base = stats(cov); base_py = posyears(cov)
    print(f"\n### IN-COVERAGE BASELINE n={base['n']:,} WR={base['wr']} "
          f"PF={base['pf']} sumR={base['sum_r']} posyr={base_py[0]}/{base_py[1]}")

    # Quintile diagnostics — is there ANY monotone signal?
    print("\n--- QUINTILE DIAGNOSTICS (rej_wick_m15) ---")
    for row in L.quintile_table(cov, "rej_wick_m15"):
        print(f"  {row}")
    print("--- QUINTILE DIAGNOSTICS (vol_spike_m15) ---")
    for row in L.quintile_table(cov, "vol_spike_m15"):
        print(f"  {row}")
    print("--- QUINTILE DIAGNOSTICS (rej_wick_m5) ---")
    for row in L.quintile_table(cov, "rej_wick_m5"):
        print(f"  {row}")

    results: list = []

    # W1: aligned rejection wick on last closed M15 bar
    for x in [0.2, 0.3, 0.4, 0.5, 0.6]:
        report(f"W1 M15 rej_wick >= {x}", f"rej_wick_m15 >= {x}",
               cov["rej_wick_m15"] >= x, cov, base, base_py, results)

    # W2: aligned rejection wick on last closed M5 bar
    for x in [0.3, 0.4, 0.5, 0.6]:
        report(f"W2 M5 rej_wick >= {x}", f"rej_wick_m5 >= {x}",
               cov["rej_wick_m5"] >= x, cov, base, base_py, results)

    # W3: small body + big aligned wick = indecision/absorption (M15)
    for wx, bx in [(0.4, 0.4), (0.5, 0.35), (0.5, 0.3)]:
        report(f"W3 M15 rej_wick>={wx} & body<={bx}",
               f"rej_wick_m15 >= {wx} and body_ratio_m15 <= {bx}",
               (cov["rej_wick_m15"] >= wx) & (cov["body_ratio_m15"] <= bx),
               cov, base, base_py, results)

    # W4: volume spike on the signal (M15) — real participation at the level
    for vx in [1.0, 1.25, 1.5, 2.0]:
        report(f"W4 M15 vol_spike >= {vx}", f"vol_spike_m15 >= {vx}",
               cov["vol_spike_m15"] >= vx, cov, base, base_py, results)

    # W5: absorption combo = rejection wick + volume spike (M15)
    for wx, vx in [(0.4, 1.25), (0.5, 1.25), (0.4, 1.5), (0.3, 1.5)]:
        report(f"W5 M15 rej_wick>={wx} & vol_spike>={vx}",
               f"rej_wick_m15 >= {wx} and vol_spike_m15 >= {vx}",
               (cov["rej_wick_m15"] >= wx) & (cov["vol_spike_m15"] >= vx),
               cov, base, base_py, results)

    # W6: consecutive aligned-rejection candles at the zone (M15 stack)
    for n in [1, 2, 3]:
        report(f"W6 M15 n_rej >= {n}", f"n_rej_m15 >= {n}",
               cov["n_rej_m15"] >= n, cov, base, base_py, results)
    for n in [2, 3]:
        report(f"W6b M5 n_rej >= {n}", f"n_rej_m5 >= {n}",
               cov["n_rej_m5"] >= n, cov, base, base_py, results)

    # W7: multi-timeframe absorption: aligned wick on BOTH M15 and M5
    for x in [0.3, 0.4]:
        report(f"W7 MTF rej_wick M15>={x} & M5>={x}",
               f"rej_wick_m15 >= {x} and rej_wick_m5 >= {x}",
               (cov["rej_wick_m15"] >= x) & (cov["rej_wick_m5"] >= x),
               cov, base, base_py, results)

    # W8: full absorption checklist (wick + vol + streak)
    report("W8 full: M15 rej>=0.4 & vol>=1.25 & n_rej>=2",
           "rej_wick_m15 >= 0.4 and vol_spike_m15 >= 1.25 and n_rej_m15 >= 2",
           (cov["rej_wick_m15"] >= 0.4) & (cov["vol_spike_m15"] >= 1.25)
           & (cov["n_rej_m15"] >= 2), cov, base, base_py, results)

    # INVERSE sanity: does the OPPOSITE (continuation wick, no absorption) lose more?
    report("INV M15 opp_wick >= 0.4 (continuation, expect WORSE)",
           "upper/lower opposite wick >= 0.4",
           cov["opp_wick_m15"] >= 0.4, cov, base, base_py, results)

    # ── PROMISING screen ──
    print("\n\n############ PROMISING SCREEN "
          "(PF>1.516 & delta_r>0 & posyr not worse & n>=200) ############")
    base_ratio = base_py[0] / base_py[1] if base_py[1] else 0
    for r in results:
        s, py = r["s"], r["py"]
        pf_ok = s["pf"] > 1.516
        dr_ok = r["delta_r"] > 0
        py_ok = py[1] > 0 and (py[0] / py[1]) >= base_ratio - 1e-9
        n_ok = s["n"] >= 200
        tag = "PROMISING" if (pf_ok and dr_ok and py_ok and n_ok) else "-"
        print(f"  [{tag:>9}] {r['name']:<44} PF {s['pf']:.3f} n {s['n']:>6} "
              f"deltaR {r['delta_r']:+7.1f} posyr {py[0]}/{py[1]}")


if __name__ == "__main__":
    main()
