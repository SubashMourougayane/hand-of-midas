"""BTC strategy sweep — port the XAU-survivor pattern families to BTCUSDT.

Every signal generator is self-contained + STRICTLY CAUSAL:
  - entry index i on the M5 grid; entry fills at m5.open[i]
  - ALL decision features use ONLY bars with close BEFORE m5.timestamp[i]:
      * M15 context via the harness's *_lag columns (already shift(1)-lagged)
      * any rolling/window feature computed on m5 uses .shift(1) so bar i's
        own OHLC never informs its own entry decision
  - risk_units from a prior-bar reference (ATR_lag or structural swing), never
    from the entry bar or future
  - bracket walk is close-based, 24h horizon, cost in bps (crypto)

Families (mirrors the XAU winners + BTC-native):
  A. Fib retrace V2         (the live XAU strategy — pullback into fib zone)
  B. EMA20 pullback/retest  (TraderzDen survivor analog)
  C. Prior-day-high/low break + trend (Martin Luke analog)
  D. ATR-compression breakout (squeeze)
  E. VWAP-session mean-revert / momentum (VWAP-MSS analog)

Output → research/btc_<family>/... + MASTER_LEADERBOARD_BTC.csv via harness.persist
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim_btc import (
    load_data, simulate, headline, gate, persist, print_headline,
)


# ─────────────────────────────────────────────────────────────────────────────
# Signal generators. Each returns DataFrame[entry_index, side, risk_units].
# ─────────────────────────────────────────────────────────────────────────────

# Min bars between consecutive entries (cooldown). A setup that stays valid for
# an hour otherwise counts as 12 near-identical M5 entries → inflated, untradeable
# trade counts. 24 M5 bars = 2h cooldown. Applied AFTER signal detection; purely
# a de-duplication of overlapping identical setups, introduces no look-ahead.
COOLDOWN_BARS = 24


def _dedup(idx: np.ndarray, cooldown: int = COOLDOWN_BARS) -> np.ndarray:
    if len(idx) == 0:
        return idx
    idx = np.sort(idx)
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= cooldown:
            keep.append(i)
    return np.array(keep)

def _prep(m5: pd.DataFrame) -> pd.DataFrame:
    """Add causal (shift(1)) M5-level helper features shared by generators."""
    d = m5.copy()
    # Regime from the LAGGED M15 EMAs (already causal).
    d["bull"] = d["ema8_lag"] > d["ema20_lag"]
    d["bear"] = d["ema8_lag"] < d["ema20_lag"]
    d["strong_bull"] = (d["ema8_lag"] > d["ema20_lag"]) & (d["ema20_lag"] > d["ema50_lag"])
    d["strong_bear"] = (d["ema8_lag"] < d["ema20_lag"]) & (d["ema20_lag"] < d["ema50_lag"])
    # ATR in price units from the lagged M15 ATR (causal). Used for risk sizing.
    d["atr"] = d["atr14_lag"]
    return d


def gen_ema_pullback(m5: pd.DataFrame, *, side: int, atr_sl: float,
                     regime: str) -> pd.DataFrame:
    """EMA20 pullback continuation. LONG: strong-bull regime + price dipped to/below
    lagged EMA20 on the PRIOR bar then this bar opens above it (reclaim). Risk = atr_sl×ATR.
    Fully causal: EMA20_lag + prior-bar low are both known before entry."""
    d = m5
    prior_low = d["low"].shift(1)
    prior_high = d["high"].shift(1)
    ema = d["ema20_lag"]
    reg = {"any": pd.Series(True, index=d.index),
           "trend": d["strong_bull"] if side > 0 else d["strong_bear"]}[regime]
    if side > 0:
        touched = prior_low <= ema            # pulled back to EMA last bar
        reclaim = d["open"] > ema             # opening back above → continuation
        sig = reg & touched & reclaim
    else:
        touched = prior_high >= ema
        reclaim = d["open"] < ema
        sig = reg & touched & reclaim
    idx = _dedup(np.where(sig.values & (d["atr"].values > 0))[0])
    return pd.DataFrame({"entry_index": idx, "side": side,
                         "risk_units": d["atr"].values[idx] * atr_sl})


def gen_pdh_break(m5: pd.DataFrame, *, side: int, atr_sl: float,
                  regime: str) -> pd.DataFrame:
    """Prior-UTC-day high/low breakout in trend (Martin Luke analog).
    LONG: strong-bull + this bar's OPEN breaks above prior completed UTC day's high.
    PDH/PDL computed from days STRICTLY before today → causal."""
    d = m5.copy()
    # daily high/low of each UTC date, then map PRIOR day's value onto each bar.
    daily = d.groupby("utc_date").agg(dh=("high", "max"), dl=("low", "min"))
    dates = list(daily.index)
    prior = {dates[k]: (daily.iloc[k - 1]["dh"], daily.iloc[k - 1]["dl"])
             for k in range(1, len(dates))}
    pdh = d["utc_date"].map(lambda x: prior.get(x, (np.nan, np.nan))[0]).values
    pdl = d["utc_date"].map(lambda x: prior.get(x, (np.nan, np.nan))[1]).values
    op = d["open"].values
    prev_op = d["open"].shift(1).values  # ensure this is a fresh break (prior bar below)
    reg = (d["strong_bull"] if side > 0 else d["strong_bear"]).values if regime == "trend" else np.ones(len(d), bool)
    atr = d["atr"].values
    if side > 0:
        sig = reg & (op > pdh) & (prev_op <= pdh) & (atr > 0) & ~np.isnan(pdh)
    else:
        sig = reg & (op < pdl) & (prev_op >= pdl) & (atr > 0) & ~np.isnan(pdl)
    idx = _dedup(np.where(sig)[0])
    return pd.DataFrame({"entry_index": idx, "side": side,
                         "risk_units": atr[idx] * atr_sl})


def gen_atr_squeeze_break(m5: pd.DataFrame, *, side: int, atr_sl: float,
                          lookback: int) -> pd.DataFrame:
    """ATR-compression breakout. When lagged ATR is in its low quantile over a
    lookback (squeeze), trade the break of the prior N-bar range. All windows
    end at bar i-1 (shift(1)) → causal."""
    d = m5
    atr = d["atr"]
    atr_med = atr.rolling(lookback).median().shift(1)
    squeeze = (atr.shift(1) < 0.8 * atr_med)
    hh = d["high"].shift(1).rolling(lookback).max().shift(1)
    ll = d["low"].shift(1).rolling(lookback).min().shift(1)
    op = d["open"]
    if side > 0:
        sig = squeeze & (op > hh)
    else:
        sig = squeeze & (op < ll)
    sig = sig & (atr > 0)
    idx = _dedup(np.where(sig.fillna(False).values)[0])
    return pd.DataFrame({"entry_index": idx, "side": side,
                         "risk_units": d["atr"].values[idx] * atr_sl})


def gen_fib_retrace(m5: pd.DataFrame, *, side: int, atr_sl: float,
                    lb: int, fib: float, tol: float) -> pd.DataFrame:
    """Fib retracement V2 analog. Find the prior swing (rolling hi/lo over lb bars,
    all shift(1)); when price retraces to the fib level of that swing (within tol×ATR)
    in the trend direction, enter continuation. Swing + fib computed from bars ≤ i-1."""
    d = m5
    swing_hi = d["high"].shift(1).rolling(lb).max().shift(1)
    swing_lo = d["low"].shift(1).rolling(lb).min().shift(1)
    rng = (swing_hi - swing_lo)
    reg = d["strong_bull"] if side > 0 else d["strong_bear"]
    atr = d["atr"]
    if side > 0:
        # retrace DOWN into fib of the up-swing: level = hi - fib*range
        level = swing_hi - fib * rng
        near = (d["low"].shift(1) <= level + tol * atr) & (d["open"] >= level - tol * atr)
    else:
        level = swing_lo + fib * rng
        near = (d["high"].shift(1) >= level - tol * atr) & (d["open"] <= level + tol * atr)
    sig = reg & near & (atr > 0) & (rng > 0)
    idx = _dedup(np.where(sig.fillna(False).values)[0])
    return pd.DataFrame({"entry_index": idx, "side": side,
                         "risk_units": d["atr"].values[idx] * atr_sl})


# ─────────────────────────────────────────────────────────────────────────────

def run():
    m1, m5_raw, m15 = load_data()
    m5 = _prep(m5_raw)
    print(f"BTC M5 bars: {len(m5):,}  years: {sorted(set(m5['year']))}")
    print("=" * 120)

    results = []

    def _eval(family, name, sigs, tp_mult, horizon):
        if len(sigs) == 0:
            return
        tr = simulate(sigs, m5, tp_mult=tp_mult, horizon_bars=horizon)
        h = headline(tr)
        print_headline(f"{family}/{name}", h)
        rec = persist(f"btc_{family}", name, tr, notes=f"tp{tp_mult} hz{horizon}")
        results.append(rec)

    # ── A. Fib retrace V2 ──
    print("\n── A · Fib retrace V2 ──")
    for side, lb, fib, tol, sl, tp in product(
        [1, -1], [10, 20, 40], [0.382, 0.618], [0.25, 0.5], [0.5, 1.0], [1.0, 2.0]
    ):
        s = gen_fib_retrace(m5, side=side, atr_sl=sl, lb=lb, fib=fib, tol=tol)
        nm = f"{'long' if side>0 else 'short'}_lb{lb}_fib{fib}_tol{tol}_sl{sl}_tp{tp}"
        _eval("fib", nm, s, tp, 288)

    # ── B. EMA20 pullback ──
    print("\n── B · EMA20 pullback ──")
    for side, sl, reg, tp in product([1, -1], [0.5, 1.0, 1.5], ["any", "trend"], [1.0, 2.0]):
        s = gen_ema_pullback(m5, side=side, atr_sl=sl, regime=reg)
        nm = f"{'long' if side>0 else 'short'}_sl{sl}_{reg}_tp{tp}"
        _eval("ema_pullback", nm, s, tp, 288)

    # ── C. Prior-day break ──
    print("\n── C · Prior-day high/low break ──")
    for side, sl, reg, tp in product([1, -1], [0.5, 1.0, 1.5], ["any", "trend"], [1.0, 2.0, 3.0]):
        s = gen_pdh_break(m5, side=side, atr_sl=sl, regime=reg)
        nm = f"{'long' if side>0 else 'short'}_sl{sl}_{reg}_tp{tp}"
        _eval("pdh_break", nm, s, tp, 288)

    # ── D. ATR squeeze breakout ──
    print("\n── D · ATR squeeze breakout ──")
    for side, sl, lbk, tp in product([1, -1], [0.5, 1.0], [12, 24, 48], [1.0, 2.0]):
        s = gen_atr_squeeze_break(m5, side=side, atr_sl=sl, lookback=lbk)
        nm = f"{'long' if side>0 else 'short'}_sl{sl}_lb{lbk}_tp{tp}"
        _eval("squeeze", nm, s, tp, 288)

    # ── Leaderboard: gate-passers ──
    print("\n" + "=" * 120)
    passers = [r for r in results if r.get("gate_ALL_PASS")]
    print(f"\nTOTAL CONFIGS: {len(results)}   GATE-PASSERS: {len(passers)}")
    for r in sorted(passers, key=lambda x: -x.get("mar", 0)):
        print(f"  ★ {r['family']}/{r['pattern']:<45s} PF={r['pf']:.2f} MAR={r['mar']:.2f} "
              f"/yr={r['trades_per_year']:.0f} pos={r['pos_years']}")
    if not passers:
        print("  (none cleared the gates — honest zero)")


if __name__ == "__main__":
    run()
