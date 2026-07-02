"""STREAK / SEQUENCE loss-cut research (strictly causal).

Question: on the Fib V2 intraday baseline (27,950 trades, PF 1.516), can a rule
decided ONLY from PRIOR CLOSED trades cut losses without giving back more in
winners?  Families tested:
  A. Loss-streak cooldown       : skip next entry after N consecutive closed losers
  B. Big-R loss cooldown        : skip next entry after a closed loss <= -X R
  C. Drawdown throttle          : skip entries while running equity DD >= X R
  D. Same-leg loss autocorrelation: does the leg (A vs D) that just lost predict
                                    the next same-leg loss? -> per-leg streak cut

STRICT CAUSALITY (the whole point):
  A trade i can only be gated by information KNOWN at its entry_timestamp T_i.
  A prior trade j provides information (its net_r / win-loss / leg) ONLY if it
  had already CLOSED: exit_timestamp(j) <= T_i.  Trades that are still OPEN at
  T_i cannot inform the decision (their outcome is future / look-ahead).
  We therefore build the "streak state" from the set of trades whose
  exit_timestamp <= entry_timestamp(i), in exit order.  This is knowable at
  entry with zero look-ahead.

Overlap note: Fib V2 fires concurrent trades (A long + D short can co-exist,
and same-leg trades overlap). So at entry i there may be trades still open.
Those are simply excluded from the streak state (we only ever count CLOSED
priors).  This is honest and non-look-ahead.

All post-hoc on existing bt_trades. Zero strategy/BT/live edits.
Run:  python3 streak_cuts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _causal_lib as L  # noqa: E402


BASE_PF = 1.516


# ─────────────────────────────────────────────────────────────────────────
# Core: causal streak-state walk
# ─────────────────────────────────────────────────────────────────────────

def build_causal_prior_state(df: pd.DataFrame) -> pd.DataFrame:
    """For each trade i (in entry order) compute streak/DD state derivable ONLY
    from trades that CLOSED before entry_i (exit_ts <= entry_i). No look-ahead.

    Adds columns:
      prior_closed        : count of trades closed before this entry
      loss_streak         : consecutive closed losers immediately before (all legs)
      loss_streak_leg     : consecutive closed losers for THIS trade's leg
      last_closed_r       : net_r of the most-recent CLOSED trade
      last_closed_leg_r   : net_r of most-recent CLOSED trade of THIS leg
      run_equity          : cumulative net_r of all CLOSED priors
      run_peak            : running peak of run_equity over closed priors
      run_dd              : run_peak - run_equity (>=0), i.e. current drawdown in R
    """
    d = df.sort_values("entry_timestamp").reset_index(drop=True).copy()

    entry = d["entry_timestamp"].to_numpy()
    exit_ = d["exit_timestamp"].to_numpy()
    net_r = d["net_r"].to_numpy()
    leg = d["leg"].to_numpy()

    # Order trades by CLOSE time to replay realized outcomes as they became known.
    close_order = np.argsort(exit_, kind="stable")
    closed_exit_sorted = exit_[close_order]
    closed_r_sorted = net_r[close_order]
    closed_leg_sorted = leg[close_order]

    # Precompute, walking in close order, the streak/equity AFTER each close event.
    n_closed = len(close_order)
    all_streak_after = np.zeros(n_closed, dtype=int)
    equity_after = np.zeros(n_closed, dtype=float)
    peak_after = np.zeros(n_closed, dtype=float)
    # per-leg streak after each close
    leg_names = list(pd.unique(leg))
    leg_streak_state = {lg: 0 for lg in leg_names}
    leg_streak_after = {lg: np.zeros(n_closed, dtype=int) for lg in leg_names}
    leg_last_r_after = {lg: np.full(n_closed, np.nan) for lg in leg_names}

    streak = 0
    equity = 0.0
    peak = 0.0
    for k in range(n_closed):
        r = closed_r_sorted[k]
        lg = closed_leg_sorted[k]
        if r <= 0:
            streak += 1
            leg_streak_state[lg] += 1
        else:
            streak = 0
            leg_streak_state[lg] = 0
        equity += r
        if equity > peak:
            peak = equity
        all_streak_after[k] = streak
        equity_after[k] = equity
        peak_after[k] = peak
        for lg2 in leg_names:
            leg_streak_after[lg2][k] = leg_streak_state[lg2]
        # last realized r per leg
        for lg2 in leg_names:
            if k == 0:
                leg_last_r_after[lg2][k] = np.nan
            else:
                leg_last_r_after[lg2][k] = leg_last_r_after[lg2][k - 1]
        leg_last_r_after[lg][k] = r  # overwrite this leg's last r

    # For each entry i, find how many closes happened strictly before entry_i.
    # idx = number of closed trades with exit <= entry_i  -> state index (idx-1).
    idx = np.searchsorted(closed_exit_sorted, entry, side="right") - 1

    prior_closed = idx + 1
    loss_streak = np.where(idx >= 0, all_streak_after[idx.clip(min=0)], 0)
    run_equity = np.where(idx >= 0, equity_after[idx.clip(min=0)], 0.0)
    run_peak = np.where(idx >= 0, peak_after[idx.clip(min=0)], 0.0)
    last_closed_r = np.where(idx >= 0, closed_r_sorted[idx.clip(min=0)], np.nan)

    loss_streak_leg = np.zeros(len(d), dtype=int)
    last_closed_leg_r = np.full(len(d), np.nan)
    for i in range(len(d)):
        lg = leg[i]
        if idx[i] >= 0:
            loss_streak_leg[i] = leg_streak_after[lg][idx[i]]
            last_closed_leg_r[i] = leg_last_r_after[lg][idx[i]]

    d["prior_closed"] = prior_closed
    d["loss_streak"] = loss_streak
    d["loss_streak_leg"] = loss_streak_leg
    d["last_closed_r"] = last_closed_r
    d["last_closed_leg_r"] = last_closed_leg_r
    d["run_equity"] = run_equity
    d["run_peak"] = run_peak
    d["run_dd"] = np.maximum(0.0, run_peak - run_equity)
    return d


# ─────────────────────────────────────────────────────────────────────────
# Evaluation helpers
# ─────────────────────────────────────────────────────────────────────────

def pf_of(net_r: np.ndarray) -> float:
    prof = net_r[net_r > 0].sum()
    loss = -net_r[net_r <= 0].sum()
    return float(prof / loss) if loss > 0 else float("inf")


def evaluate(d: pd.DataFrame, keep_mask: np.ndarray, name: str, rule: str) -> dict:
    """keep_mask=True means the trade is TAKEN. Dropped trades = filtered out.
    delta_r = -(sum of net_r of DROPPED trades) = R saved by dropping.
      dropped losers add positive delta_r (good), dropped winners subtract.
    """
    kept = d[keep_mask]
    dropped = d[~keep_mask]
    n_kept = len(kept)
    n_drop = len(dropped)
    base_r = float(d["net_r"].sum())
    kept_r = float(kept["net_r"].sum())
    delta_r = kept_r - base_r  # net R change vs baseline (=-sum(dropped))
    filt_pf = pf_of(kept["net_r"].to_numpy()) if n_kept else 0.0
    # positive years on kept set
    g = kept.groupby("year")["net_r"].sum() if n_kept else pd.Series(dtype=float)
    pos_years = int((g > 0).sum())
    tot_years = int(d["year"].nunique())
    dropped_losers = int((dropped["net_r"] <= 0).sum())
    dropped_winners = int((dropped["net_r"] > 0).sum())
    dropped_loser_r = float(-dropped.loc[dropped.net_r <= 0, "net_r"].sum())  # R saved
    dropped_winner_r = float(dropped.loc[dropped.net_r > 0, "net_r"].sum())   # R lost
    return {
        "name": name, "rule": rule,
        "n_kept": n_kept, "n_dropped": n_drop,
        "dropped_losers": dropped_losers, "dropped_winners": dropped_winners,
        "r_saved_from_losers": round(dropped_loser_r, 1),
        "r_lost_from_winners": round(dropped_winner_r, 1),
        "base_pf": BASE_PF, "filt_pf": round(filt_pf, 3),
        "base_r": round(base_r, 1), "kept_r": round(kept_r, 1),
        "delta_r": round(delta_r, 1),
        "pos_years": f"{pos_years}/{tot_years}",
    }


def show(res: dict):
    print(f"\n[{res['name']}] {res['rule']}")
    print(f"  kept={res['n_kept']} dropped={res['n_dropped']} "
          f"(losers={res['dropped_losers']} winners={res['dropped_winners']})")
    print(f"  R saved from losers=+{res['r_saved_from_losers']}  "
          f"R lost from winners=-{res['r_lost_from_winners']}")
    print(f"  PF {res['base_pf']} -> {res['filt_pf']}   "
          f"R {res['base_r']} -> {res['kept_r']} (delta {res['delta_r']:+})   "
          f"pos-years {res['pos_years']}")


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    df = L.load_trades()
    d = build_causal_prior_state(df)
    print("=" * 78)
    print(f"BASELINE  n={len(d)}  R={d.net_r.sum():.1f}  PF={pf_of(d.net_r.to_numpy()):.3f}  "
          f"pos-years={int((d.groupby('year').net_r.sum()>0).sum())}/{d.year.nunique()}")
    print("=" * 78)

    # Diagnostic: how many trades even HAVE a prior streak? Concurrency check.
    print(f"\nDiagnostic: trades with >=1 prior CLOSED trade: {(d.prior_closed>0).sum()}/{len(d)}")
    print("loss_streak distribution (all legs):")
    print(d["loss_streak"].value_counts().sort_index().head(12).to_string())

    # --- Autocorrelation diagnostic: does last closed outcome predict next? ---
    print("\n--- AUTOCORRELATION: does prior CLOSED outcome predict THIS trade? ---")
    for k in range(0, 6):
        sub = d[d.loss_streak == k]
        if len(sub):
            print(f"  after {k} consec losers: n={len(sub):5d}  "
                  f"WR={100*(sub.net_r>0).mean():5.2f}%  "
                  f"meanR={sub.net_r.mean():+.4f}  PF={pf_of(sub.net_r.to_numpy()):.3f}")
    # last closed R sign
    prev_loser = d[d.last_closed_r <= 0]
    prev_winner = d[d.last_closed_r > 0]
    print(f"  prev closed LOSER : n={len(prev_loser)} WR={100*(prev_loser.net_r>0).mean():.2f}% "
          f"meanR={prev_loser.net_r.mean():+.4f} PF={pf_of(prev_loser.net_r.to_numpy()):.3f}")
    print(f"  prev closed WINNER: n={len(prev_winner)} WR={100*(prev_winner.net_r>0).mean():.2f}% "
          f"meanR={prev_winner.net_r.mean():+.4f} PF={pf_of(prev_winner.net_r.to_numpy()):.3f}")

    # --- Same-leg autocorrelation ---
    print("\n--- SAME-LEG AUTOCORRELATION: does last SAME-LEG loss predict next? ---")
    for lg in d.leg.unique():
        sl = d[d.leg == lg]
        pl = sl[sl.last_closed_leg_r <= 0]
        pw = sl[sl.last_closed_leg_r > 0]
        print(f"  {lg}:")
        print(f"    after same-leg LOSER : n={len(pl)} WR={100*(pl.net_r>0).mean():.2f}% "
              f"meanR={pl.net_r.mean():+.4f} PF={pf_of(pl.net_r.to_numpy()):.3f}")
        print(f"    after same-leg WINNER: n={len(pw)} WR={100*(pw.net_r>0).mean():.2f}% "
              f"meanR={pw.net_r.mean():+.4f} PF={pf_of(pw.net_r.to_numpy()):.3f}")
        for k in range(1, 5):
            s = sl[sl.loss_streak_leg == k]
            if len(s):
                print(f"    same-leg streak={k}: n={len(s):5d} WR={100*(s.net_r>0).mean():5.2f}% "
                      f"meanR={s.net_r.mean():+.4f} PF={pf_of(s.net_r.to_numpy()):.3f}")

    results = []

    # ============ FAMILY A: loss-streak cooldown (all legs) ============
    print("\n" + "=" * 78)
    print("FAMILY A: skip entry when prior closed loss-streak >= N")
    print("=" * 78)
    for N in (2, 3, 4, 5):
        keep = ~(d.loss_streak >= N).to_numpy()
        r = evaluate(d, keep, f"A_streak>={N}",
                     f"loss_streak >= {N} -> skip (prior CLOSED trades only)")
        results.append(r); show(r)

    # ============ FAMILY A2: per-leg loss-streak cooldown ============
    print("\n" + "=" * 78)
    print("FAMILY A2: skip entry when SAME-LEG prior closed loss-streak >= N")
    print("=" * 78)
    for N in (2, 3, 4):
        keep = ~(d.loss_streak_leg >= N).to_numpy()
        r = evaluate(d, keep, f"A2_legstreak>={N}",
                     f"loss_streak_leg >= {N} -> skip that leg's entry")
        results.append(r); show(r)

    # ============ FAMILY B: big-R loss cooldown ============
    print("\n" + "=" * 78)
    print("FAMILY B: skip entry when most-recent CLOSED trade lost <= -X R")
    print("=" * 78)
    for X in (1.0, 1.5, 2.0):
        keep = ~((d.last_closed_r <= -X)).to_numpy()
        r = evaluate(d, keep, f"B_lastloss<=-{X}",
                     f"last_closed_r <= -{X} -> skip next entry")
        results.append(r); show(r)

    # ============ FAMILY C: drawdown throttle ============
    print("\n" + "=" * 78)
    print("FAMILY C: skip entry while running equity DD >= X R (of closed priors)")
    print("=" * 78)
    # scan DD thresholds relative to observed DD distribution
    print(f"  run_dd distribution: median={d.run_dd.median():.1f} "
          f"p90={d.run_dd.quantile(.9):.1f} max={d.run_dd.max():.1f}")
    for X in (5, 10, 20, 40, 80):
        keep = ~(d.run_dd >= X).to_numpy()
        r = evaluate(d, keep, f"C_dd>={X}R",
                     f"run_dd >= {X}R -> skip entry (equity of CLOSED priors)")
        results.append(r); show(r)

    # ============ FAMILY B2: same-leg last big loss ============
    print("\n" + "=" * 78)
    print("FAMILY B2: skip that leg when its most-recent CLOSED trade lost <= -X R")
    print("=" * 78)
    for X in (1.0, 1.5):
        keep = ~((d.last_closed_leg_r <= -X)).to_numpy()
        r = evaluate(d, keep, f"B2_leglastloss<=-{X}",
                     f"last_closed_leg_r <= -{X} -> skip that leg")
        results.append(r); show(r)

    # ---- Summary table ----
    print("\n" + "=" * 78)
    print("SUMMARY (delta_r>0 AND filt_pf>baseline AND pos-years not degraded = candidate)")
    print("=" * 78)
    tot_years = d.year.nunique()
    for r in results:
        flag = ""
        if r["filt_pf"] > BASE_PF and r["delta_r"] > 0 and r["pos_years"] == f"{tot_years}/{tot_years}":
            flag = "  <<< PROMISING"
        elif r["filt_pf"] > BASE_PF and r["delta_r"] > 0:
            flag = "  (pf up, r up, but pos-years degraded)"
        print(f"  {r['name']:22s} PF {r['filt_pf']:.3f}  deltaR {r['delta_r']:+8.1f}  "
              f"drop L/W {r['dropped_losers']}/{r['dropped_winners']}  "
              f"posyr {r['pos_years']}{flag}")


if __name__ == "__main__":
    main()
