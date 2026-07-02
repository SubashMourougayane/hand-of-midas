"""WHALE-CHECKLIST LOCATION filters — POST-HOC RESEARCH ONLY. Zero prod edits.

Foot-Clan / "whale" checklist idea: 'not at a key level = NO TRADE'.
We test entry PROXIMITY to key structural levels as a QUALITY filter, and
whether the STOP sits protected just beyond a level.

Key levels (all CAUSAL via _causal_lib — known strictly before entry_ts):
  * PDH / PDL / PDC  — prior completed day high/low/close (known at day open)
  * Asia  H/L        — 0-7 UTC session extremes (known after 07:00 UTC)
  * London H/L       — 7-13 UTC session extremes (known after 13:00 UTC)
  * VWAP             — session (1D) anchored, cumulative to last closed M5 bar

Filters tested (KEEP = passes filter):
  L1  entry within X*ATR of ANY key level (proximity quality)
  L2  entry FAR from all levels = reject (open-space entry)  [inverse of L1]
  L3  per-level proximity (which level matters most)
  L4  STOP protected: stop sits just BEYOND a key level (whale-stop-hunt zone)
  L5  entry between VWAP and a level (confluence squeeze)

ATR reference: M15 ATR14 from last fully-closed M15 bar before entry (causal).
All level distances measured in ATR units so scale-invariant across years.

Baseline (in-coverage subset reported at runtime). Global baseline PF 1.516.

Run:
  python3 research-baseline/candidate_filters/loss_cut_permutations/whale_location.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _causal_lib as L  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# Causal ATR (M15) attach — reuse rolling_feature_causal + attach pattern
# ─────────────────────────────────────────────────────────────────────────

def build_m15_atr(m5: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """M15 ATR14 frame with close_ts. Value at bar = ATR of last `period`
    fully-closed M15 bars including this one. Usable when close_ts <= entry.
    """
    m15 = L.resample_causal(m5, "15min")
    m15 = m15.sort_values("bar_open_ts").reset_index(drop=True)
    prev_close = m15["close"].shift(1)
    tr = pd.concat([
        (m15["high"] - m15["low"]),
        (m15["high"] - prev_close).abs(),
        (m15["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    m15["atr"] = tr.rolling(period, min_periods=period).mean()
    return m15[["bar_open_ts", "close_ts", "atr"]].dropna().reset_index(drop=True)


def vwap_local(m5: pd.DataFrame, anchor: str = "1D") -> pd.DataFrame:
    """Session (1D)-anchored VWAP per M5 bar, cumulative within the anchor period
    up to and including each bar. Causal by construction. Local reimpl to avoid a
    pandas API bug in L.vwap_causal (SeriesGroupBy has no .clip). Value = VWAP AT
    each M5 bar's close; attach helper handles the +5min close-timing shift.
    """
    m = m5.copy()
    m["tp"] = (m["high"] + m["low"] + m["close"]) / 3.0
    v = m["volume"].clip(lower=1)
    m["pv"] = m["tp"] * v
    m["grp"] = m["timestamp"].dt.floor(anchor)
    m["cum_pv"] = m.groupby("grp")["pv"].cumsum()
    m["cum_v"] = v.groupby(m["grp"]).cumsum()
    m["vwap"] = m["cum_pv"] / m["cum_v"]
    return m[["timestamp", "vwap"]]


def attach_prior_bar_value(trades: pd.DataFrame, frame: pd.DataFrame,
                           col: str, out_col: str) -> pd.DataFrame:
    """Attach frame[col] from last row whose close_ts <= entry_ts. Causal."""
    ct = frame["close_ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    vals = frame[col].to_numpy()
    ent = trades["entry_timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    out = np.full(len(trades), np.nan)
    idx = np.searchsorted(ct, ent, side="right") - 1
    valid = idx >= 0
    out[valid] = vals[idx[valid]]
    t = trades.copy()
    t[out_col] = out
    return t


def attach_session_levels(trades: pd.DataFrame, sess: pd.DataFrame,
                          hi_col: str, lo_col: str,
                          out_hi: str, out_lo: str) -> pd.DataFrame:
    """Attach session hi/lo from last session whose close_ts <= entry_ts."""
    ct = sess["close_ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    hv = sess[hi_col].to_numpy()
    lv = sess[lo_col].to_numpy()
    ent = trades["entry_timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    oh = np.full(len(trades), np.nan)
    ol = np.full(len(trades), np.nan)
    idx = np.searchsorted(ct, ent, side="right") - 1
    valid = idx >= 0
    oh[valid] = hv[idx[valid]]
    ol[valid] = lv[idx[valid]]
    t = trades.copy()
    t[out_hi] = oh
    t[out_lo] = ol
    return t


# ─────────────────────────────────────────────────────────────────────────
# Metrics
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


def report(name: str, keep: pd.Series, trades: pd.DataFrame,
           base: dict, base_py: tuple) -> dict:
    kept = trades[keep].reset_index(drop=True)
    dropped = trades[~keep].reset_index(drop=True)
    s = stats(kept)
    py = posyears(kept)
    # delta_r: net R saved by dropping = -(sum_r of dropped)
    d_losers = -dropped.loc[dropped.net_r <= 0, "net_r"].sum()   # positive R saved
    d_winners = dropped.loc[dropped.net_r > 0, "net_r"].sum()    # positive R lost
    delta_r = float(d_losers - d_winners)  # net R change vs baseline
    print(f"\n=== {name} ===")
    print(f"  kept   n={s['n']:>6,d}  WR={s['wr']:>6.2f}  PF={s['pf']:>6.3f}  "
          f"sumR={s['sum_r']:>8.1f}  posyr={py[0]}/{py[1]}")
    print(f"  dropped n={len(dropped):>5,d}  losers_saved={d_losers:+.1f}R  "
          f"winners_lost={d_winners:+.1f}R  net_deltaR={delta_r:+.1f}R")
    print(f"  vs base PF {base['pf']:.3f} sumR {base['sum_r']:.1f} "
          f"posyr {base_py[0]}/{base_py[1]}")
    return dict(name=name, s=s, py=py, delta_r=delta_r,
                d_losers=d_losers, d_winners=d_winners, n_dropped=len(dropped))


def main() -> None:
    print("[LOAD] trades...")
    trades = L.load_trades()
    print(f"  {len(trades):,} trades")
    print("[LOAD] M5...")
    m5 = L.load_m5()
    print(f"  {len(m5):,} M5 bars  range {m5.timestamp.min()} → {m5.timestamp.max()}")

    # ── Causal features ──
    print("[BUILD] M15 ATR14 (causal)...")
    atrf = build_m15_atr(m5, 14)
    trades = attach_prior_bar_value(trades, atrf, "atr", "atr")

    print("[BUILD] prior-day levels (causal)...")
    pdl = L.prior_day_levels_causal(m5)  # pdh/pdl/pdc, close_ts=day open
    trades = attach_prior_bar_value(trades, pdl, "pdh", "pdh")
    trades = attach_prior_bar_value(trades, pdl, "pdl", "pdl")
    trades = attach_prior_bar_value(trades, pdl, "pdc", "pdc")

    print("[BUILD] Asia (0-7) + London (7-13) session H/L (causal)...")
    asia = L.session_levels_causal(m5, 0, 7, "asia")
    lon = L.session_levels_causal(m5, 7, 13, "london")
    trades = attach_session_levels(trades, asia, "asia_high", "asia_low",
                                   "asia_h", "asia_l")
    trades = attach_session_levels(trades, lon, "london_high", "london_low",
                                   "lon_h", "lon_l")

    print("[BUILD] session VWAP (causal, local)...")
    vw = vwap_local(m5, "1D")
    trades = L.attach_m5_value_at_or_before(trades, vw, "vwap", "vwap")

    # Filter to parquet coverage + valid ATR
    trades = trades.dropna(subset=["atr"]).reset_index(drop=True)
    trades = trades[trades["atr"] > 0].reset_index(drop=True)
    print(f"[COVERAGE] {len(trades):,} trades with causal ATR + levels")

    base = stats(trades)
    base_py = posyears(trades)
    print(f"\n### IN-COVERAGE BASELINE  n={base['n']:,}  WR={base['wr']}  "
          f"PF={base['pf']}  sumR={base['sum_r']}  posyr={base_py[0]}/{base_py[1]}")

    # ── distance-to-level in ATR units ──
    ep = trades["entry_price"]
    levels = {
        "pdh": trades["pdh"], "pdl": trades["pdl"], "pdc": trades["pdc"],
        "asia_h": trades["asia_h"], "asia_l": trades["asia_l"],
        "lon_h": trades["lon_h"], "lon_l": trades["lon_l"],
        "vwap": trades["vwap"],
    }
    dist = {}
    for k, v in levels.items():
        dist[k] = (ep - v).abs() / trades["atr"]
        trades[f"d_{k}"] = dist[k]
    # nearest level overall (min distance across all)
    dcols = [f"d_{k}" for k in levels]
    trades["d_nearest"] = trades[dcols].min(axis=1, skipna=True)
    # nearest among the classic S/R levels only (exclude vwap which is dynamic)
    sr_cols = ["d_pdh", "d_pdl", "d_asia_h", "d_asia_l", "d_lon_h", "d_lon_l"]
    trades["d_nearest_sr"] = trades[sr_cols].min(axis=1, skipna=True)

    results = []

    # ── L1: entry within X*ATR of ANY key level (proximity quality) ──
    for x in [0.25, 0.5, 1.0, 1.5, 2.0]:
        keep = trades["d_nearest"] <= x
        results.append(report(f"L1 near ANY level (incl vwap) d<= {x} ATR",
                               keep, trades, base, base_py))
    for x in [0.25, 0.5, 1.0, 1.5, 2.0]:
        keep = trades["d_nearest_sr"] <= x
        results.append(report(f"L1sr near ANY S/R level (no vwap) d<= {x} ATR",
                               keep, trades, base, base_py))

    # ── L2: FAR from all = reject (keep only close). Inverse framing kept below.
    #     Also test: reject trades in OPEN SPACE (far from everything) ──
    for x in [1.0, 2.0, 3.0]:
        keep = trades["d_nearest_sr"] <= x  # reject if farther than x
        results.append(report(f"L2 reject open-space (d_nearest_sr > {x} ATR dropped)",
                               keep, trades, base, base_py))

    # ── L3: per-level proximity (within 0.5 ATR of that specific level) ──
    for k in levels:
        keep = trades[f"d_{k}"] <= 0.5
        results.append(report(f"L3 near {k} (d<=0.5 ATR)", keep, trades, base, base_py))

    # ── L4: STOP protected — stop sits just BEYOND a key level ──
    # For each trade, the natural stop-hunt logic: a whale-protected stop is one
    # where the stop_price sits on the far side of a level from entry, within a
    # small band beyond it (level is between entry and stop, and close to stop).
    # We approximate: distance from stop to the level it is "hiding behind" small.
    sp = trades["stop_price"]
    # nearest level to the STOP, in ATR
    sdist = {}
    for k, v in levels.items():
        sdist[k] = (sp - v).abs() / trades["atr"]
    trades["s_nearest_sr"] = pd.concat(
        [sdist[k] for k in ["pdh", "pdl", "asia_h", "asia_l", "lon_h", "lon_l"]],
        axis=1).min(axis=1, skipna=True)
    # protected = a level sits between entry and stop (level crossed by the SL leg)
    # long: stop < entry, protected if some level in (stop, entry)
    prot = np.zeros(len(trades), dtype=bool)
    for k, v in levels.items():
        vv = v.to_numpy()
        lo = np.minimum(sp.to_numpy(), ep.to_numpy())
        hi = np.maximum(sp.to_numpy(), ep.to_numpy())
        prot |= (vv >= lo) & (vv <= hi) & np.isfinite(vv)
    trades["stop_protected"] = prot
    keep = trades["stop_protected"]
    results.append(report("L4 stop-protected (a key level between entry & stop)",
                          pd.Series(keep, index=trades.index), trades, base, base_py))
    # L4b: stop just beyond nearest level (within 0.5 ATR past it)
    keep = trades["s_nearest_sr"] <= 0.5
    results.append(report("L4b stop within 0.5 ATR of a S/R level",
                          keep, trades, base, base_py))

    # ── L5: VWAP-level confluence (entry near vwap AND near a S/R level) ──
    keep = (trades["d_vwap"] <= 1.0) & (trades["d_nearest_sr"] <= 1.0)
    results.append(report("L5 confluence (near vwap<=1ATR AND near S/R<=1ATR)",
                          keep, trades, base, base_py))

    # ── Directional-aware: mean-reversion longs should be near a SUPPORT (pdl/asia_l/lon_l),
    #     shorts near a RESISTANCE (pdh/asia_h/lon_h). Test that geometry. ──
    sup_cols = ["d_pdl", "d_asia_l", "d_lon_l"]
    res_cols = ["d_pdh", "d_asia_h", "d_lon_h"]
    trades["d_support"] = trades[sup_cols].min(axis=1, skipna=True)
    trades["d_resist"] = trades[res_cols].min(axis=1, skipna=True)
    is_long = trades["direction"] == "long"
    for x in [0.5, 1.0]:
        # long near support OR short near resistance (aligned mean-reversion bounce)
        keep = ((is_long & (trades["d_support"] <= x)) |
                (~is_long & (trades["d_resist"] <= x)))
        results.append(report(f"L6 aligned bounce (long@support|short@resist d<= {x}ATR)",
                              keep, trades, base, base_py))
        # counter: long near resistance | short near support (fading INTO level)
        keep2 = ((is_long & (trades["d_resist"] <= x)) |
                 (~is_long & (trades["d_support"] <= x)))
        results.append(report(f"L6c fade-into-level (long@resist|short@support d<= {x}ATR)",
                              keep2, trades, base, base_py))

    # ── PROMISING screen ──
    print("\n\n############ PROMISING SCREEN (PF>1.516 & delta_r>0 & posyr not worse) ############")
    for r in results:
        s, py = r["s"], r["py"]
        pf_ok = s["pf"] > 1.516
        dr_ok = r["delta_r"] > 0
        py_ok = py[1] > 0 and (py[0] / py[1]) >= (base_py[0] / base_py[1]) - 1e-9
        n_ok = s["n"] >= 200
        tag = "PROMISING" if (pf_ok and dr_ok and py_ok and n_ok) else "-"
        print(f"  [{tag:>9}] {r['name']:<52} PF {s['pf']:.3f} n {s['n']:>6} "
              f"deltaR {r['delta_r']:+7.1f} posyr {py[0]}/{py[1]}")


if __name__ == "__main__":
    main()
