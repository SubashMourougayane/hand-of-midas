"""M15 OTE mega-sweep — hunt an edge that beats PF 1.15.

Strategy family: sweep -> CHoCH -> OTE retrace (the FULL institutional model),
structure on M15 (with optional H4 trend gate), entry on M5. LONG only (short leg
proven dead across all XAU experiments).

Design for speed: the expensive part is the structural pass (find sweeps + CHoCH +
confluence). We do that ONCE per swing_k and cache a candidate table with ALL
metadata. Every grid config is then a cheap filter + re-price + M5 fill/sim.

Grid levers (all straight from the guide):
  - OTE_FIB       : 0.5 / 0.618 / 0.705 / 0.786          (guide fib levels)
  - swing_k       : 2 / 3 / 4 / 5                          (fractal strictness)
  - sweep_lookback: 3 / 6 / 10                             (how far back a swept low)
  - min_conf      : 3 / 4 / 5                              (guide: >=5 reasons)
  - require_fvg   : 0 / 1                                  (displacement leaves FVG)
  - sl_buf_atr    : 0.05 / 0.10 / 0.25 / 0.50             (SL below swept swing)
  - tp_mode       : bsl / 2R / 3R                          (guide TP=BSL, or R mult)
  - session       : all / killzone(NY 07-11 + London)     (guide kill zones)
  - h4_trend      : 0 / 1                                  (guide step1: 4H trend)
  - wait_bars     : 48 / 96                                (M5 bars to fill OTE)

Causal: swings confirmed k bars right; sweep+CHoCH from CLOSED M15; fill on M5 after
arm_ts. Cost $0.30/risk_units. Big-numbers audit gate applied to winners downstream.
"""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import load_data, _load_raw_m1, headline, gate, COST_USD  # noqa: E402
from research.ict_ote.structure import find_swings, fvg_zones, ob_zones  # noqa: E402
from research.ict_ote.run_ote_v2 import build_htf  # noqa: E402

FAMILY_DIR = Path("/Users/subash/SUBASH/GoldDigger/research/ict_ote")
LEADER = FAMILY_DIR / "mega_sweep_leaderboard.csv"


def build_candidates(m15: pd.DataFrame, htf4: pd.DataFrame, swing_k: int,
                     max_sweep_lb: int = 10) -> pd.DataFrame:
    """All LONG sweep->CHoCH legs on M15 structure, with metadata. One pass per k.

    A LONG candidate: swing LOW b that took out a prior swing low (sweep), followed
    by an M15 CLOSE above the last prior swing high (CHoCH up). Records the swept
    depth rank, confluence counts inside the leg, arm session, and H4 trend dir.
    """
    swings = find_swings(m15, swing_k)
    fvg = fvg_zones(m15)
    ob = ob_zones(m15)
    fvg_l = fvg[fvg["dir"] == +1].reset_index(drop=True)
    ob_l = ob[ob["dir"] == +1].reset_index(drop=True)

    hclose = m15["close"].values
    hts = m15["timestamp"].values
    bar_td = np.timedelta64(15, "m")

    # H4 trend: close vs ema50 on last-closed H4 bar. Precompute a lookup.
    h4 = htf4.copy()
    h4["ema50"] = h4["close"].ewm(span=50, adjust=False).mean()
    h4["trend_up"] = (h4["close"] > h4["ema50"]).astype(int)
    h4["valid_ts"] = h4["timestamp"] + np.timedelta64(240, "m")  # known at H4 close
    h4v = h4.dropna(subset=["ema50"]).reset_index(drop=True)
    h4_ts = h4v["valid_ts"].values
    h4_up = h4v["trend_up"].values

    lows = [s for s in swings if s.kind == "L"]
    highs = [s for s in swings if s.kind == "H"]

    rows = []
    for bi, b in enumerate(swings):
        if b.kind != "L":
            continue
        prior_lows = [s for s in swings[:bi] if s.kind == "L"]
        if not prior_lows:
            continue
        window = prior_lows[-max_sweep_lb:]
        swept = [s for s in window if b.price < s.price]
        if not swept:
            continue
        sweep_rank = len(window) - window.index(swept[-1])  # 1=nearest prior low
        prior_highs = [s for s in swings[:bi + 1] if s.kind == "H"]
        if not prior_highs:
            continue
        ref_high = prior_highs[-1]
        swing_hi, swing_lo = ref_high.price, b.price
        if swing_hi <= swing_lo:
            continue
        # CHoCH up: first M15 close above ref_high after b.confirm_ts
        start_h = int(np.searchsorted(hts, np.datetime64(b.confirm_ts), side="left"))
        choch_i = -1
        for j in range(start_h, min(len(m15), start_h + max_sweep_lb * 10)):
            if hclose[j] > swing_hi:
                choch_i = j
                break
        if choch_i < 0:
            continue
        arm_ts = pd.Timestamp(hts[choch_i]) + bar_td

        # confluence in leg window (lo_ts .. arm_ts) overlapping leg range
        lo_ts = b.bar_ts
        fv = fvg_l[(fvg_l["valid_ts"] > lo_ts) & (fvg_l["valid_ts"] <= arm_ts) &
                   (fvg_l["hi"] >= swing_lo) & (fvg_l["lo"] <= swing_hi)]
        ov = ob_l[(ob_l["valid_ts"] > lo_ts) & (ob_l["valid_ts"] <= arm_ts) &
                  (ob_l["hi"] >= swing_lo) & (ob_l["lo"] <= swing_hi)]
        n_fvg = int(len(fv) > 0)
        n_ob = int(len(ov) > 0)

        # H4 trend dir known at arm
        hi_idx = int(np.searchsorted(h4_ts, np.datetime64(arm_ts), side="right")) - 1
        h4_up_flag = int(h4_up[hi_idx]) if hi_idx >= 0 else 0

        arm_utc = arm_ts if arm_ts.tz is not None else arm_ts.tz_localize("UTC")
        ny_hr = arm_utc.tz_convert("America/New_York").hour
        rows.append({
            "swing_lo": swing_lo, "swing_hi": swing_hi, "lo_ts": lo_ts,
            "arm_ts": arm_ts, "sweep_rank": sweep_rank, "n_fvg": n_fvg,
            "n_ob": n_ob, "h4_up": h4_up_flag, "ny_hr": ny_hr,
        })
    return pd.DataFrame(rows)


def price_and_sim(cand: pd.DataFrame, m5: pd.DataFrame, *, ote_fib: float,
                  sl_buf_atr: float, tp_mode: str, wait_bars: int,
                  horizon: int = 288, cost_usd: float = COST_USD) -> pd.DataFrame:
    """Vectorised-ish fill + close-based bracket for a pre-filtered candidate set."""
    m5_ts = m5["timestamp"].values
    m5_lo = m5["low"].values
    m5_hi = m5["high"].values
    m5_cl = m5["close"].values
    m5_atr = m5["atr14_lag"].values
    yr = m5["year"].values
    n5 = len(m5)

    arm = cand["arm_ts"].values.astype("datetime64[ns]")
    starts = np.searchsorted(m5_ts, arm, side="left")
    lo = cand["swing_lo"].values
    hi = cand["swing_hi"].values

    outs = []
    for k in range(len(cand)):
        start = int(starts[k])
        if start >= n5 - 2:
            continue
        atr = m5_atr[start]
        if not np.isfinite(atr) or atr <= 0:
            continue
        swing_lo, swing_hi = lo[k], hi[k]
        rng = swing_hi - swing_lo
        ote = swing_hi - ote_fib * rng
        sl = swing_lo - sl_buf_atr * atr
        risk = ote - sl
        if risk <= 0:
            continue
        if tp_mode == "bsl":
            tp = swing_hi
        elif tp_mode == "2R":
            tp = ote + 2 * risk
        else:  # 3R
            tp = ote + 3 * risk
        rr = (tp - ote) / risk

        # fill
        end = min(n5 - 1, start + wait_bars)
        fill_i = -1
        for j in range(start, end + 1):
            if m5_cl[j] < sl:
                break
            if m5_lo[j] <= ote:
                fill_i = j
                break
        if fill_i < 0:
            continue
        # bracket
        hend = min(n5 - 1, fill_i + horizon)
        outcome = None
        exit_i = hend
        for j in range(fill_i, hend + 1):
            c = m5_cl[j]
            if c <= sl:
                outcome = (sl - ote) / risk; exit_i = j; break
            if c >= tp:
                outcome = (tp - ote) / risk; exit_i = j; break
        if outcome is None:
            outcome = (m5_cl[exit_i] - ote) / risk
        outs.append({"entry_ts": m5_ts[fill_i], "net_r": outcome - cost_usd / risk,
                     "bracket_r": outcome, "rr": rr, "year": yr[fill_i]})
    return pd.DataFrame(outs)


def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _cfgstr(cfg: dict) -> str:
    return (f"k{cfg['swing_k']} fib{cfg['ote_fib']} lb{cfg['sweep_lb']} "
            f"conf{cfg['min_conf']} fvg{cfg['require_fvg']} sl{cfg['sl_buf_atr']} "
            f"{cfg['tp_mode']} {cfg['session']} h4t{cfg['h4_trend']} w{cfg['wait_bars']}")


def _prog(ci, combos, t0, results, skipped, best_pf, best_row):
    done = ci + 1
    el = time.time() - t0
    rate = done / el if el > 0 else 0
    eta = (len(combos) - done) / rate if rate > 0 else 0
    bp = f"PF={best_pf:.3f}" if best_row else "none yet"
    _log(f"  {done:,}/{len(combos):,} ({100*done/len(combos):.0f}%) "
         f"| {el:.0f}s el, ETA {eta:.0f}s | kept={len(results):,} thin={skipped:,} "
         f"| best {bp}")


def main():
    _log("=== M15 OTE MEGA-SWEEP START ===")
    _log("Loading M1/M5/M15 …")
    m1, m5, m15 = load_data()
    _log(f"Loaded: m1={len(m1):,} m5={len(m5):,} m15={len(m15):,}")
    _log("Building H4 frame …")
    htf4 = build_htf(m1, "4h")
    _log(f"H4 bars: {len(htf4):,}")

    # cache candidates per swing_k
    cand_by_k = {}
    for k in (2, 3, 4, 5):
        t0 = time.time()
        _log(f"Building sweep->CHoCH candidates for swing_k={k} …")
        cand_by_k[k] = build_candidates(m15, htf4, k)
        c = cand_by_k[k]
        if len(c):
            _log(f"  k={k}: {len(c):,} candidates  "
                 f"(fvg={c['n_fvg'].mean()*100:.0f}% ob={c['n_ob'].mean()*100:.0f}% "
                 f"h4up={c['h4_up'].mean()*100:.0f}%)  [{time.time()-t0:.1f}s]")
        else:
            _log(f"  k={k}: 0 candidates  [{time.time()-t0:.1f}s]")

    grid = dict(
        swing_k=[2, 3, 4, 5],
        ote_fib=[0.5, 0.618, 0.705, 0.786],
        sweep_lb=[3, 6, 10],
        min_conf=[3, 4, 5],
        require_fvg=[0, 1],
        sl_buf_atr=[0.05, 0.10, 0.25, 0.50],
        tp_mode=["bsl", "2R", "3R"],
        session=["all", "kz"],
        h4_trend=[0, 1],
        wait_bars=[48, 96],
    )
    keys = list(grid)
    combos = list(itertools.product(*grid.values()))
    _log(f"GRID SIZE: {len(combos):,} configs across {len(keys)} levers")
    _log(f"Levers: " + ", ".join(f"{k}={len(v)}" for k, v in grid.items()))
    _log("Running grid … (progress every 500 configs; best-PF tracked live)")

    results = []
    t0 = time.time()
    skipped_thin = 0
    best_pf = 0.0
    best_row = None
    best_intraday_pf = 0.0
    best_intraday = None
    LOG_EVERY = 500
    for ci, vals in enumerate(combos):
        cfg = dict(zip(keys, vals))
        cand = cand_by_k[cfg["swing_k"]]
        if len(cand) == 0:
            continue
        # cheap filters
        sel = cand[cand["sweep_rank"] <= cfg["sweep_lb"]]
        # confluence tally: sweep(1)+choch(1)+discount(1)+fvg+ob
        conf = 3 + sel["n_fvg"] + sel["n_ob"]
        sel = sel[conf >= cfg["min_conf"]]
        if cfg["require_fvg"]:
            sel = sel[sel["n_fvg"] == 1]
        if cfg["session"] == "kz":
            sel = sel[(sel["ny_hr"] >= 2) & (sel["ny_hr"] <= 11)]  # London+NY AM
        if cfg["h4_trend"]:
            sel = sel[sel["h4_up"] == 1]
        if len(sel) < 30:
            skipped_thin += 1
            if (ci + 1) % LOG_EVERY == 0:
                _prog(ci, combos, t0, results, skipped_thin, best_pf, best_row)
            continue
        tr = price_and_sim(sel, m5, ote_fib=cfg["ote_fib"], sl_buf_atr=cfg["sl_buf_atr"],
                           tp_mode=cfg["tp_mode"], wait_bars=cfg["wait_bars"])
        if len(tr) < 30:
            skipped_thin += 1
            if (ci + 1) % LOG_EVERY == 0:
                _prog(ci, combos, t0, results, skipped_thin, best_pf, best_row)
            continue
        h = headline(tr)
        g = gate(h)
        row = {**cfg, "n": h["n"], "per_yr": round(h["trades_per_year"], 0),
               "pf": round(h["pf"], 3), "net_r": round(h["net"], 1),
               "mar": round(h["mar"], 2), "wr": round(h["wr"], 3),
               "dd": round(h["dd"], 1), "pos_years": h["pos_years"],
               "avg_rr": round(tr["rr"].mean(), 2), "gate_pass": g["ALL_PASS"]}
        results.append(row)
        # track running bests
        if h["n"] >= 100 and h["pf"] > best_pf:
            best_pf = h["pf"]; best_row = row
            _log(f"  ** NEW BEST PF={h['pf']:.3f} n={h['n']} /yr={h['trades_per_year']:.0f} "
                 f"MAR={h['mar']:.2f} pos={h['pos_years']} :: {_cfgstr(cfg)}")
        if h["trades_per_year"] >= 200 and h["n"] >= 200 and h["pf"] > best_intraday_pf:
            best_intraday_pf = h["pf"]; best_intraday = row
            _log(f"  >> NEW INTRADAY-FREQ BEST PF={h['pf']:.3f} /yr={h['trades_per_year']:.0f} "
                 f"MAR={h['mar']:.2f} pos={h['pos_years']} :: {_cfgstr(cfg)}")
        if g["ALL_PASS"]:
            _log(f"  ★★★ FULL GATE PASS :: PF={h['pf']:.3f} /yr={h['trades_per_year']:.0f} "
                 f"MAR={h['mar']:.2f} pos={h['pos_years']} :: {_cfgstr(cfg)}")
        if (ci + 1) % LOG_EVERY == 0:
            _prog(ci, combos, t0, results, skipped_thin, best_pf, best_row)

    res = pd.DataFrame(results)
    res.to_csv(LEADER, index=False)
    print(f"\nDone. {len(res)} configs with >=30 trades. ({time.time()-t0:.0f}s)")
    print(f"Leaderboard -> {LEADER}\n")

    # top by PF (require decent sample)
    good = res[res["n"] >= 100].sort_values("pf", ascending=False)
    print("=== TOP 20 by PF (n>=100) ===")
    cols = ["swing_k", "ote_fib", "sweep_lb", "min_conf", "require_fvg", "sl_buf_atr",
            "tp_mode", "session", "h4_trend", "wait_bars", "n", "per_yr", "pf",
            "net_r", "mar", "wr", "pos_years", "avg_rr", "gate_pass"]
    with pd.option_context("display.width", 240, "display.max_columns", 40):
        print(good[cols].head(20).to_string(index=False))
    print("\n=== TOP 10 that CLEAR intraday freq (per_yr>=200), by PF ===")
    hi_freq = res[(res["per_yr"] >= 200) & (res["n"] >= 200)].sort_values("pf", ascending=False)
    with pd.option_context("display.width", 240, "display.max_columns", 40):
        print(hi_freq[cols].head(10).to_string(index=False))
    print("\n=== Any FULL gate passes? ===")
    print(res[res["gate_pass"]][cols].to_string(index=False) if res["gate_pass"].any() else "  NONE cleared all 4 gates.")


if __name__ == "__main__":
    main()
