"""S9 — SMT divergence (correlated-pair), quantised to PDF pg22-24. Fully causal.

Setup (to the dot):
  - Two correlated assets: XAU (traded) + XAG (reference). Corr >75% positive (0.75 ✓).
  - At a liquidity level, ONE asset sweeps a prior swing (grabs liquidity) while the
    OTHER FAILS to sweep its corresponding swing => SMT divergence.
    * Bearish SMT (short XAU): XAU makes a HIGHER high than its prior swing high (sweeps
      buy-side liquidity) BUT XAG fails to make a higher high (no confirmation) at the
      same swing. Guide: "select the pair which grabbed liquidity" -> it reverses.
    * Bullish SMT (long XAU): XAU makes a LOWER low (sweeps sell-side) but XAG does NOT.
  - Confirm on LTF (M5): CHoCH / close beyond the SMT line (the swept swing level).
    Guide: "Shift to 5 Min, wait for CHoCH or next candle close beyond SMT line."
  - Entry after confirmation. SL below/above the liquidity sweep. TP = R multiple.

Causality: swings on BOTH assets confirmed k bars right; divergence known only at the
later of the two swing confirm times; entry armed at the M5 confirmation close after.
Everything from CLOSED bars. Trades XAU only (our tradeable, cost $0.30/risk_units).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import headline, gate, print_headline, COST_USD  # noqa: E402
from research.smc_campaign import primitives as P  # noqa: E402
from research.smc_campaign.framework import _log, sim_price_bracket, resample  # noqa: E402
from research.smc_campaign.sweep_engine import fill_setups, OUT  # noqa: E402

XAU_M15 = "/tmp/oanda_xau_m15.parquet"
XAG_M15 = "/tmp/oanda_xag_m15.parquet"
XAU_M5 = "/tmp/oanda_xau_m5.parquet"


def _load(path):
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def build_m5_exec(xau_m5_raw: pd.DataFrame) -> pd.DataFrame:
    """M5 execution frame with atr14_lag + year (mirror causal_sim m5 shape).
    ATR from last-CLOSED M15 would be ideal; here use M5 ATR lagged (causal)."""
    df = xau_m5_raw.copy()
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14_lag"] = tr.rolling(14).mean().shift(1)  # lagged: known at bar open
    df["year"] = df["timestamp"].dt.year
    return df.dropna(subset=["atr14_lag"]).reset_index(drop=True)


def build_smt_setups(xau15, xag15, *, k=3, sides=(1, -1)):
    """Detect SMT divergences. Returns arm_ts, side, sweep_level(=SMT line), rref.
    The 'entry' after LTF confirm is set at the SMT line (the swept swing level) — the
    reversal is expected to push back through it. SL beyond the sweep extreme."""
    sw_au = P.find_swings(xau15, k=k, tf_min=15)
    sw_ag = P.find_swings(xag15, k=k, tf_min=15)
    # index XAG swings by kind + confirm order for "was there a matching sweep" lookup
    ag_hi = [(s.confirm_ts, s.price, s.bar_ts) for s in sw_ag if s.kind == "H"]
    ag_lo = [(s.confirm_ts, s.price, s.bar_ts) for s in sw_ag if s.kind == "L"]

    def _naive_arr(lst):
        if not lst:
            return np.array([], dtype="datetime64[ns]"), np.array([]), np.array([], dtype="datetime64[ns]")
        ct = pd.to_datetime([t for t, _, _ in lst]).tz_localize(None).values.astype("datetime64[ns]")
        px = np.array([p for _, p, _ in lst])
        bt = pd.to_datetime([b for _, _, b in lst]).tz_localize(None).values.astype("datetime64[ns]")
        return ct, px, bt
    ag_hi_ct, ag_hi_px, ag_hi_bt = _naive_arr(ag_hi)
    ag_lo_ct, ag_lo_px, ag_lo_bt = _naive_arr(ag_lo)

    au_highs = [s for s in sw_au if s.kind == "H"]
    au_lows = [s for s in sw_au if s.kind == "L"]

    rows = []
    # Bearish SMT (short XAU): XAU makes HH (sweeps prior high) while XAG does NOT make HH
    for a, b in zip(au_highs, au_highs[1:]):
        if b.price <= a.price:
            continue  # need XAU higher-high (buy-side sweep)
        # find the XAG high swing nearest before b.confirm (its "matching" high)
        bconf = np.datetime64(pd.Timestamp(b.confirm_ts).tz_localize(None))
        # XAG's two most recent confirmed highs at b.confirm
        pos = np.searchsorted(ag_hi_ct, bconf, side="right")
        if pos < 2:
            continue
        ag_prev, ag_last = ag_hi_px[pos - 2], ag_hi_px[pos - 1]
        # divergence: XAG did NOT make a higher high (failed to confirm XAU's sweep)
        if ag_last < ag_prev:  # XAG made lower high => SMT divergence, XAU should reverse down
            if -1 in sides:
                rows.append((b.confirm_ts, -1, a.price, b.price))  # smt line=prior high, sweep extreme=b.price
    # Bullish SMT (long XAU): XAU makes LL (sell-side sweep) while XAG does NOT
    for a, b in zip(au_lows, au_lows[1:]):
        if b.price >= a.price:
            continue
        bconf = np.datetime64(pd.Timestamp(b.confirm_ts).tz_localize(None))
        pos = np.searchsorted(ag_lo_ct, bconf, side="right")
        if pos < 2:
            continue
        ag_prev, ag_last = ag_lo_px[pos - 2], ag_lo_px[pos - 1]
        if ag_last > ag_prev:  # XAG made higher low => divergence, XAU should reverse up
            if 1 in sides:
                rows.append((b.confirm_ts, 1, a.price, b.price))
    return pd.DataFrame(rows, columns=["div_ts", "side", "smt_line", "sweep_extreme"])


def confirm_and_price(setups, xau15, *, confirm_bars=8, sl_buf=0.15, tp_mode="2R"):
    """LTF confirmation: after div_ts, wait for an M15 close beyond the SMT line in the
    reversal direction (proxy for the pg24 '5M CHoCH / close beyond SMT line'). Entry at
    that confirming close; SL beyond the sweep extreme; TP = R multiple. arm_ts = confirm."""
    cl = xau15["close"].values
    ts = xau15["timestamp"].values
    ts_naive = xau15["timestamp"].dt.tz_localize(None).values.astype("datetime64[ns]")
    td = np.timedelta64(15, "m")
    n = len(xau15)
    rows = []
    for r in setups.itertuples(index=False):
        d = np.datetime64(pd.Timestamp(r.div_ts).tz_localize(None))
        start = int(np.searchsorted(ts_naive, d, side="left"))
        end = min(n - 1, start + confirm_bars)
        fi = -1
        for j in range(start, end + 1):
            if r.side > 0 and cl[j] > r.smt_line:   # bullish: close back above SMT line
                fi = j; break
            if r.side < 0 and cl[j] < r.smt_line:   # bearish: close back below
                fi = j; break
        if fi < 0:
            continue
        arm_ts = pd.Timestamp(ts[fi]) + td
        entry = cl[fi]
        ssl = r.sweep_extreme
        rref = abs(entry - ssl)
        if rref <= 0:
            continue
        pad = sl_buf * rref
        sl = ssl - pad if r.side > 0 else ssl + pad
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        mult = 3.0 if tp_mode == "3R" else 2.0
        tp = entry + mult * risk * r.side
        rows.append({"arm_ts": arm_ts, "side": int(r.side), "entry_price": entry,
                     "tp_price": tp, "sl_price": sl, "fill_mode": "market"})
    return pd.DataFrame(rows)


def main():
    _log("=== S9 SMT (XAU/XAG divergence) ===")
    xau15 = _load(XAU_M15); xag15 = _load(XAG_M15)
    # align to common timestamps
    common = pd.Index(xau15["timestamp"]).intersection(pd.Index(xag15["timestamp"]))
    xau15 = xau15[xau15["timestamp"].isin(common)].reset_index(drop=True)
    xag15 = xag15[xag15["timestamp"].isin(common)].reset_index(drop=True)
    _log(f"aligned M15: {len(xau15):,} bars")
    xau_m5 = build_m5_exec(_load(XAU_M5))
    _log(f"XAU M5 exec: {len(xau_m5):,} bars")

    grid_k = [2, 3, 4]
    grid_cb = [4, 8, 12]
    grid_sl = [0.1, 0.25, 0.5]
    grid_tp = ["2R", "3R"]
    grid_sides = [(1,), (-1,), (1, -1)]
    _log("running SMT sweep …")
    results = []
    best_pf = 0.0
    for k in grid_k:
        setups_all = build_smt_setups(xau15, xag15, k=k, sides=(1, -1))
        _log(f"k={k}: {len(setups_all)} raw SMT divergences")
        for cb in grid_cb:
            for sl in grid_sl:
                for tp in grid_tp:
                    for sides in grid_sides:
                        sub = setups_all[setups_all["side"].isin(sides)]
                        if len(sub) < 30:
                            continue
                        sp = confirm_and_price(sub, xau15, confirm_bars=cb, sl_buf=sl, tp_mode=tp)
                        if len(sp) < 30:
                            continue
                        sig = fill_setups(sp, xau_m5, wait_bars=1, slip_atr=0.05)
                        if len(sig) < 30:
                            continue
                        tr = sim_price_bracket(sig, xau_m5, horizon=288)
                        if len(tr) < 30:
                            continue
                        h = headline(tr); g = gate(h)
                        row = {"k": k, "confirm_bars": cb, "sl_buf": sl, "tp_mode": tp,
                               "sides": str(sides), "n": h["n"], "per_yr": round(h["trades_per_year"]),
                               "pf": round(h["pf"], 3), "net_r": round(h["net"], 1),
                               "mar": round(h["mar"], 2), "wr": round(h["wr"], 3),
                               "pos_years": h["pos_years"], "gate_pass": g["ALL_PASS"]}
                        results.append(row)
                        if h["n"] >= 80 and h["pf"] > best_pf:
                            best_pf = h["pf"]
                            _log(f"  ** BEST PF={h['pf']:.3f} n={h['n']} /yr={h['trades_per_year']:.0f} "
                                 f"MAR={h['mar']:.2f} pos={h['pos_years']} :: k{k} cb{cb} sl{sl} {tp} {sides}")
                        if g["ALL_PASS"]:
                            _log(f"  ★ GATE PASS :: {row}")
    res = pd.DataFrame(results)
    path = OUT / "S9_leaderboard.csv"
    res.to_csv(path, index=False)
    _log(f"DONE [S9] {len(res)} configs, {int(res.gate_pass.sum()) if len(res) else 0} gate-passes, "
         f"best PF={best_pf:.3f} -> {path}")
    if len(res):
        top = res[res["n"] >= 80].sort_values("pf", ascending=False).head(8)
        _log(f"TOP by PF (n>=80):\n{top.to_string(index=False)}")


if __name__ == "__main__":
    main()
