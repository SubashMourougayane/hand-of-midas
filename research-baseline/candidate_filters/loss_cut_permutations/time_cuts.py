"""TIME-BASED LOSS CUTS — POST-HOC RESEARCH ONLY. Zero production code changes.

Family: itemised AT-ENTRY-knowable time filters + causal max-hold early exit.
Baseline run b6604240 (27,950 trades, 8279.2R, PF 1.516, 48.9% WR, 21/21 pos yrs,
$850,710 total pnl_usd).

GOAL: cut losers to SAVE profit we currently give back. Not chasing more profit.

Categories
==========
A. HOUR-BUCKET SKIPS. Skip entries whose UTC (or NY) hour falls in a set. Every
   hour bucket is knowable at entry_ts (it's just the clock). PURE LEDGER SURGERY:
   drop matching trades, recompute net-R / PF / pos-years / $ saved.

B. SESSION OPEN/CLOSE PROXIMITY SKIPS. Skip entries within N minutes of a known
   session open/close (London open 07:00 UTC, NY open 13:00/12:00, London close
   16:00, NY close 21:00, Asia open 23:00). Clock-only → knowable at entry_ts.

C. DAY-OF-WEEK SKIPS. Skip Mon / Tue / ... entries. Clock-only.

D. FRIDAY-LATE SKIP (weekend-gap avoidance). Skip Fri entries at/after hour H.

E. CAUSAL MAX-HOLD EARLY EXIT. Replay each trade's M5 bracket. If, at the close
   of bar K after entry, the trade is not yet at >= +X R (MFE-based), close at
   that bar's close. This decision is made bar-by-bar from bars already closed —
   it is CAUSAL (no outcome label). Vary K and X.

Every category-A..D rule is knowable_at_entry=TRUE (pure clock).
Category-E is knowable_at_entry=TRUE (per-bar decision on closed bars).

NOTE the honest prior from exploration: EVERY hour bucket and EVERY day-of-week
bucket is net-POSITIVE in aggregate. So category A..D can at best trim marginal
buckets; they will NOT flip a big loser bucket (there isn't one). We report the
truth either way.

Run:  python3 research-baseline/candidate_filters/loss_cut_permutations/time_cuts.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _causal_lib as L  # noqa: E402

COST_USD = 0.65
OUT_DIR = Path(__file__).resolve().parent


# ─────────────────────────────────────────────────────────────────────────
# Metrics helpers
# ─────────────────────────────────────────────────────────────────────────

def pf_of(net_r: pd.Series) -> float:
    prof = net_r[net_r > 0].sum()
    loss = -net_r[net_r <= 0].sum()
    return float(prof / loss) if loss > 0 else float("inf")


def pos_years(df: pd.DataFrame, r_col: str = "net_r") -> tuple[int, int]:
    g = df.groupby("year")[r_col].sum()
    return int((g > 0).sum()), int(len(g))


def summarise_skip(base: pd.DataFrame, kept_mask: pd.Series, name: str,
                   rule: str) -> dict:
    """Ledger surgery: keep trades where kept_mask is True. Report vs baseline."""
    dropped = base[~kept_mask]
    kept = base[kept_mask]
    n_drop = len(dropped)
    # $ saved = -(sum of dropped pnl_usd). Positive means dropped were net losers.
    dropped_pnl = float(dropped["pnl_usd"].sum())
    dropped_r = float(dropped["net_r"].sum())
    # delta_r vs baseline: net R change = -(R of the trades we removed)
    delta_r = -dropped_r
    py_k, ty_k = pos_years(kept)
    return {
        "name": name,
        "rule": rule,
        "knowable_at_entry": True,
        "n": int(len(kept)),
        "n_dropped": int(n_drop),
        "baseline_pf": round(pf_of(base["net_r"]), 3),
        "filtered_pf": round(pf_of(kept["net_r"]), 3),
        "baseline_r": round(float(base["net_r"].sum()), 1),
        "filtered_r": round(float(kept["net_r"].sum()), 1),
        "delta_r": round(delta_r, 1),
        "dropped_pnl_usd": round(dropped_pnl, 0),
        "dollars_saved": round(-dropped_pnl, 0),  # +ve = we removed net-losing $
        "pos_years": f"{py_k}/{ty_k}",
        "filtered_wr": round(100.0 * (kept["net_r"] > 0).mean(), 2),
    }


# ─────────────────────────────────────────────────────────────────────────
# Category E: causal max-hold early exit (M5 bracket replay)
# ─────────────────────────────────────────────────────────────────────────

def replay_maxhold(m5_arr: dict, row, K: int, X: float,
                   partial_tp_at_r: float = 1.0, partial_tp_pct: float = 0.5):
    """Replay one trade's bracket. Standard partial-TP+1R/BE logic, PLUS a causal
    early-exit: at the close of bar K (K bars after entry), if MFE-so-far < X R
    AND partial not yet taken, exit at that bar's close (mark-to-market). This is
    a per-bar decision using only bars already closed → causal.

    Returns (net_r, reason, bars_held).
    """
    side = int(row.side)
    entry = float(row.entry_price)
    tp = float(row.take_profit_price)
    risk = float(row.risk_units)
    if risk <= 0:
        return 0.0, "NORISK", 0

    ts = m5_arr["ts"]
    hi = m5_arr["high"]
    lo = m5_arr["low"]
    cl = m5_arr["close"]

    entry_np = row.entry_timestamp.tz_convert("UTC").tz_localize(None).to_datetime64()
    exit_np = row.exit_timestamp.tz_convert("UTC").tz_localize(None).to_datetime64()

    start_idx = int(np.searchsorted(ts, entry_np, side="right"))
    end_idx = int(np.searchsorted(ts, exit_np, side="right"))
    end_idx = min(end_idx, len(ts) - 1)

    stop_price = float(row.stop_price)
    partial_r = 0.0
    stop_is_be = False
    bars_held = 0
    mfe_r = 0.0
    cost_r = COST_USD / risk

    for i in range(start_idx, end_idx + 1):
        bars_held += 1
        close = float(cl[i]); high = float(hi[i]); low = float(lo[i])

        # running MFE in R (intra-bar)
        if side > 0:
            bar_mfe = (high - entry) / risk
        else:
            bar_mfe = (entry - low) / risk
        mfe_r = max(mfe_r, bar_mfe)

        # partial-TP+1R
        if partial_tp_at_r is not None and not stop_is_be and bar_mfe >= partial_tp_at_r:
            partial_r = partial_tp_at_r * partial_tp_pct
            stop_price = entry
            stop_is_be = True

        hit_stop = (side > 0 and close <= stop_price) or (side < 0 and close >= stop_price)
        hit_tp = (side > 0 and close >= tp) or (side < 0 and close <= tp)

        if hit_stop:
            r_rem = 0.0 if stop_is_be else -1.0
            return r_rem + partial_r - cost_r, ("SL_BE" if stop_is_be else "SL"), bars_held
        if hit_tp:
            tp_r = (tp - entry) * side / risk
            return tp_r + partial_r - cost_r, "TP", bars_held

        # CAUSAL max-hold early exit: at bar K, if not progressing (MFE < X) and no
        # partial banked yet, bail at this close. Decision uses only closed bars.
        if bars_held >= K and not stop_is_be and mfe_r < X:
            mtm_r = (close - entry) * side / risk
            return mtm_r + partial_r - cost_r, "EARLY_CUT", bars_held

    # natural timeout (same as baseline horizon)
    close = float(cl[end_idx])
    to_r = (close - entry) * side / risk
    return to_r + partial_r - cost_r, "TIMEOUT", bars_held


def replay_baseline(m5_arr: dict, row):
    """Replay with NO early-exit — sanity check the replay reproduces the DB net_r."""
    return replay_maxhold(m5_arr, row, K=10**9, X=-10**9)


def run_maxhold_rule(base: pd.DataFrame, m5_arr: dict, K: int, X: float,
                     name: str, replay_base_r: float) -> dict:
    """delta_r is measured vs the REPLAY baseline (same engine, no early-exit),
    NOT vs the DB, so the imperfect replay-vs-DB gap cancels out and delta_r
    isolates the pure effect of the early-exit rule."""
    rows = []
    for r in base.itertuples(index=False):
        nr, reason, bars = replay_maxhold(m5_arr, r, K, X)
        rows.append((r.year, nr, reason))
    res = pd.DataFrame(rows, columns=["year", "net_r", "reason"])
    py, ty = pos_years(res)
    n_cut = int((res["reason"] == "EARLY_CUT").sum())
    return {
        "name": name,
        "rule": f"exit at bar K={K} close if MFE < {X}R and partial not taken (causal per-bar)",
        "knowable_at_entry": True,
        "n": int(len(res)),
        "n_early_cut": n_cut,
        "baseline_pf": round(pf_of(base["net_r"]), 3),
        "filtered_pf": round(pf_of(res["net_r"]), 3),
        "baseline_r": round(float(base["net_r"].sum()), 1),
        "filtered_r": round(float(res["net_r"].sum()), 1),
        # delta vs DB (for reference) AND vs same-engine replay baseline (the honest one)
        "delta_r": round(float(res["net_r"].sum() - replay_base_r), 1),
        "delta_r_vs_db": round(float(res["net_r"].sum() - base["net_r"].sum()), 1),
        "pos_years": f"{py}/{ty}",
        "filtered_wr": round(100.0 * (res["net_r"] > 0).mean(), 2),
    }


# ─────────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] loading trades...", flush=True)
    df = L.load_trades()
    df = df.reset_index(drop=True)
    df["entry_hr"] = df["entry_timestamp"].dt.hour
    df["entry_min"] = df["entry_timestamp"].dt.minute
    df["mins_utc"] = df["entry_hr"] * 60 + df["entry_min"]
    df["dow"] = df["entry_timestamp"].dt.dayofweek  # 0=Mon
    df["ny_hr"] = pd.to_numeric(df["ny_hr"], errors="coerce")

    base_r = float(df["net_r"].sum())
    base_pf = pf_of(df["net_r"])
    base_pnl = float(df["pnl_usd"].sum())
    print(f"  baseline: n={len(df)} R={base_r:.1f} PF={base_pf:.3f} "
          f"$={base_pnl:,.0f} posYrs={pos_years(df)}", flush=True)

    results: list[dict] = []

    # ============ CATEGORY A: HOUR-BUCKET SKIPS ============
    # Rank UTC hours by sum_r; test skipping the worst 1..N hours.
    hr_r = df.groupby("entry_hr")["net_r"].agg(["sum", "count", "mean"]).sort_values("sum")
    print("\n=== worst UTC hours by sum_r ===\n", hr_r.head(8), flush=True)
    worst_hours = list(hr_r.index)  # ascending sum_r

    for topn in [1, 2, 3, 4, 5, 6, 8]:
        skip = set(worst_hours[:topn])
        mask = ~df["entry_hr"].isin(skip)
        results.append(summarise_skip(
            df, mask, f"A_skip_worst{topn}_utc_hours",
            f"entry_utc_hour NOT IN {sorted(skip)}"))

    # Also: skip low-avgR "dead" hours (avgR < 0.15) as a family
    dead = set(hr_r[hr_r["mean"] < 0.15].index)
    if dead:
        mask = ~df["entry_hr"].isin(dead)
        results.append(summarise_skip(
            df, mask, "A_skip_utc_hours_avgR_lt_0.15",
            f"entry_utc_hour NOT IN {sorted(dead)}"))

    # NY-hour version (feature col ny_hr) — skip worst by sum_r
    nyr = df.dropna(subset=["ny_hr"]).groupby("ny_hr")["net_r"].sum().sort_values()
    worst_ny = list(nyr.index)
    for topn in [1, 2, 3, 4]:
        skip = set(worst_ny[:topn])
        mask = ~df["ny_hr"].isin(skip)
        results.append(summarise_skip(
            df, mask, f"A_skip_worst{topn}_ny_hours",
            f"ny_hr NOT IN {[int(x) for x in sorted(skip)]}"))

    # ============ CATEGORY B: SESSION OPEN/CLOSE PROXIMITY ============
    # Known session boundaries in UTC minutes-of-day.
    boundaries = {
        "london_open_0700": 7 * 60,
        "ny_open_1300": 13 * 60,
        "london_close_1600": 16 * 60,
        "ny_close_2100": 21 * 60,
        "asia_open_2300": 23 * 60,
    }
    for N in [15, 30, 60]:
        # skip if within N minutes AFTER any boundary (typical whipsaw window)
        def near_after(mins, bset=boundaries, NN=N):
            return any(0 <= (mins - b) < NN for b in bset.values())
        mask_after = ~df["mins_utc"].apply(near_after)
        results.append(summarise_skip(
            df, mask_after, f"B_skip_within{N}m_after_session_boundary",
            f"NOT (0 <= mins_utc - boundary < {N}) for boundary in "
            f"{{420,780,960,1260,1380}}"))
        # skip if within N minutes on EITHER side of any boundary
        def near_both(mins, bset=boundaries, NN=N):
            return any(abs(mins - b) < NN for b in bset.values())
        mask_both = ~df["mins_utc"].apply(near_both)
        results.append(summarise_skip(
            df, mask_both, f"B_skip_within{N}m_around_session_boundary",
            f"NOT (|mins_utc - boundary| < {N}) for boundary in "
            f"{{420,780,960,1260,1380}}"))

    # ============ CATEGORY C: DAY-OF-WEEK SKIPS ============
    dow_r = df.groupby("dow")["net_r"].agg(["sum", "count"]).sort_values("sum")
    print("\n=== dow by sum_r (0=Mon) ===\n", dow_r, flush=True)
    dow_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    for d in [0, 1, 2, 3, 4]:
        mask = df["dow"] != d
        results.append(summarise_skip(
            df, mask, f"C_skip_{dow_names[d]}",
            f"entry_dayofweek != {d}"))
    # skip the single worst dow
    worst_dow = int(dow_r.index[0])
    mask = df["dow"] != worst_dow
    results.append(summarise_skip(
        df, mask, f"C_skip_worst_dow_{dow_names[worst_dow]}",
        f"entry_dayofweek != {worst_dow}"))

    # ============ CATEGORY D: FRIDAY-LATE SKIP ============
    for H in [16, 18, 19, 20, 21]:
        mask = ~((df["dow"] == 4) & (df["entry_hr"] >= H))
        results.append(summarise_skip(
            df, mask, f"D_skip_fri_from_{H:02d}utc",
            f"NOT (dayofweek==4 AND entry_utc_hour >= {H})"))

    # ============ CATEGORY E: CAUSAL MAX-HOLD EARLY EXIT ============
    print(f"\n[{time.strftime('%H:%M:%S')}] loading M5 for bracket replay...", flush=True)
    m5 = L.load_m5()
    m5_arr = {
        "ts": m5["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(),
        "high": m5["high"].to_numpy(dtype=np.float64),
        "low": m5["low"].to_numpy(dtype=np.float64),
        "close": m5["close"].to_numpy(dtype=np.float64),
    }
    print(f"  M5 rows: {len(m5):,}", flush=True)

    # Sanity: replay baseline (no early exit) must approximate DB net_r.
    print(f"[{time.strftime('%H:%M:%S')}] replay parity check (no early exit)...", flush=True)
    par = []
    for r in df.itertuples(index=False):
        nr, _, _ = replay_baseline(m5_arr, r)
        par.append(nr)
    par = np.array(par)
    db = df["net_r"].to_numpy()
    corr = float(np.corrcoef(par, db)[0, 1])
    mae = float(np.mean(np.abs(par - db)))
    replay_base_r = float(par.sum())
    print(f"  replay vs DB: corr={corr:.4f} MAE={mae:.4f}R "
          f"replay_sumR={replay_base_r:.1f} db_sumR={db.sum():.1f}", flush=True)
    parity_ok = corr > 0.95 and mae < 0.15
    print(f"  NOTE: Category-E delta_r is measured vs replay baseline "
          f"({replay_base_r:.1f}R) so the replay-vs-DB gap cancels.", flush=True)

    # max-hold grid: K bars (M15-equiv -> M5 bars: 1 M15 = 3 M5; use M5 bars directly)
    # K in M5 bars. Trade horizon is bars_held (M5). Test K = 6,12,24,48 M5 bars
    # (=0.5h,1h,2h,4h) with X threshold 0R (still under water) and 0.5R.
    print(f"[{time.strftime('%H:%M:%S')}] running max-hold grid...", flush=True)
    for K in [6, 12, 24, 48]:
        for X in [0.0, 0.5]:
            name = f"E_maxhold_K{K}m5_X{X}R"
            res = run_maxhold_rule(df, m5_arr, K, X, name, replay_base_r)
            results.append(res)
            print(f"  {name}: PF {res['filtered_pf']} dR_vs_replay {res['delta_r']} "
                  f"cuts {res['n_early_cut']} posYrs {res['pos_years']}", flush=True)

    # ─────────────────────────── report ───────────────────────────
    rep = pd.DataFrame(results)
    rep.to_parquet(OUT_DIR / "time_cuts_results.parquet")
    rep.to_csv(OUT_DIR / "time_cuts_results.csv", index=False)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    print("\n" + "=" * 100)
    print(f"BASELINE: n={len(df)} R={base_r:.1f} PF={base_pf:.3f} $={base_pnl:,.0f} "
          f"posYrs={pos_years(df)}  |  replay parity ok={parity_ok}")
    print("=" * 100)
    cols_skip = ["name", "n", "n_dropped", "filtered_pf", "delta_r",
                 "dollars_saved", "pos_years", "filtered_wr"]
    skip_rep = rep[rep["name"].str.startswith(("A_", "B_", "C_", "D_"))]
    print("\n--- SKIP rules (ledger surgery) ---")
    print(skip_rep[cols_skip].to_string(index=False))

    cols_mh = ["name", "n_early_cut", "filtered_pf", "delta_r", "pos_years", "filtered_wr"]
    mh_rep = rep[rep["name"].str.startswith("E_")]
    print("\n--- MAX-HOLD early-exit (causal) ---")
    print(mh_rep[cols_mh].to_string(index=False))

    print(f"\n[{time.strftime('%H:%M:%S')}] DONE in {time.time()-t0:.1f}s -> "
          f"{OUT_DIR/'time_cuts_results.csv'}", flush=True)


if __name__ == "__main__":
    main()
