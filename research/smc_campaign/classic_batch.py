"""Classic-indicator batch — VWAP, trendline-breakout, SMA golden-cross — to the dot.

Three popular families, each STANDALONE and as an S1 CONFLUENCE filter, all fully
causal (every indicator from bars whose close ts < entry ts) and run through the
same gauntlet: base PF/MAR, delay+1/2/3 reprice, cost $0.30-0.80, bootstrap
P(net<=0), IS19-23/OOS24-26, 8-year table, Model B $5k.

FAMILIES:
  A. VWAP  — session VWAP (reset at NY-midnight, typical price, volume-weighted,
     causal cumulative). Signal: price reclaims/rejects VWAP after a stretch +
     M5 MSS. Long below-VWAP reclaim, short above-VWAP reject. TP 2R/3R.
  B. Trendline breakout — objective proxy = break of an N-bar linear-regression
     channel (close crosses regression + k*resid_std). No repaint: regression on
     the PRIOR N closed bars only. Long up-break, short down-break. TP 2R/3R.
  C. SMA golden/death cross — SMA50 x SMA200 on prior closes. Enter on the cross
     bar's next open, trend-follow. TP 3R/timeout. The classic dead one.
  + Confluence: S1 setups that ALSO agree with each family's directional filter.

cost $0.30/risk_units. Gate: PF>=1.3, MAR>=1.5, >=150/yr, 7-8/8yr, delay+1 PF>=1.2.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger/bt_engine")

from research.smc_campaign.framework import MTF, sim_price_bracket, _log
from research.smc_campaign.sweep_engine import fill_setups
from research.smc_campaign.combined_numbers import headline, print_headline, model_b
from research.smc_campaign.strategies_fast import universe_s1, _price
import logging
logging.disable(logging.CRITICAL)

# CAUSAL FILL RULE: a signal detected on bar i (using close[i]) must fill at the
# OPEN of bar i+1 — never bar i's own open (that is same-bar look-ahead: entering
# at open[i] while already knowing close[i] and the SL/TP derived from it, which
# produced the phantom +66,000R first pass). We stamp arm_ts = ts[i+1] so the
# market fill lands on the next bar's open.


# ---------- causal indicators on m5 ----------
def add_session_vwap(m5: pd.DataFrame) -> np.ndarray:
    """Session VWAP reset at NY-midnight (ny_date boundary). Uses typical price
    (h+l+c)/3 × volume, cumulative WITHIN the day, LAGGED by one bar (value known
    only after the bar closes) so entry at bar k sees VWAP through k-1."""
    tp = (m5["high"].values + m5["low"].values + m5["close"].values) / 3.0
    vol = m5["volume"].values.astype(float)
    ny = m5["timestamp"].dt.tz_convert("America/New_York")
    ndate = ny.dt.date.astype(str).values
    vwap = np.full(len(m5), np.nan)
    cum_pv = 0.0; cum_v = 0.0; cur = None
    for i in range(len(m5)):
        if ndate[i] != cur:
            cur = ndate[i]; cum_pv = 0.0; cum_v = 0.0
        # value BEFORE adding this bar = causal (through prior bars)
        vwap[i] = (cum_pv / cum_v) if cum_v > 0 else np.nan
        cum_pv += tp[i] * max(vol[i], 1.0); cum_v += max(vol[i], 1.0)
    return vwap


def add_sma(m5: pd.DataFrame, n: int) -> np.ndarray:
    """SMA of close, shifted 1 (prior-bar value = causal)."""
    return pd.Series(m5["close"].values).rolling(n).mean().shift(1).values


def regchan(m5: pd.DataFrame, n: int):
    """Rolling linreg on PRIOR n closes → predicted level at current bar + resid std.
    Both shifted so bar k uses bars k-n..k-1 only. Returns (pred, std)."""
    c = m5["close"].values
    x = np.arange(n)
    pred = np.full(len(c), np.nan); std = np.full(len(c), np.nan)
    sx = x.sum(); sxx = (x * x).sum(); denom = n * sxx - sx * sx
    for i in range(n, len(c)):
        y = c[i - n:i]  # prior n closes
        sy = y.sum(); sxy = (x * y).sum()
        b = (n * sxy - sx * sy) / denom
        a = (sy - b * sx) / n
        pred[i] = a + b * n  # extrapolate to current bar
        std[i] = y.std()
    return pred, std


# ---------- family A: VWAP reclaim/reject + MSS ----------
def vwap_setups(m5, *, side_mode, tp_mode, sl_buf_atr=0.5, session=("ny",)):
    vwap = add_session_vwap(m5)
    c = m5["close"].values; o = m5["open"].values
    hi = m5["high"].values; lo = m5["low"].values
    atr = m5["atr14_lag"].values; ts = m5["timestamp"].values
    ny = m5["timestamp"].dt.tz_convert("America/New_York"); nyh = ny.dt.hour.values
    n = len(m5)
    in_sess = np.zeros(n, bool)
    if "ny" in session: in_sess |= (nyh >= 8) & (nyh < 12)
    if "london" in session: in_sess |= (nyh >= 3) & (nyh < 8)
    setups = []
    for i in range(3, n - 1):
        if not in_sess[i] or not np.isfinite(vwap[i]) or atr[i] <= 0:
            continue
        # bullish reclaim: prior bar closed below vwap, this bar closes back above
        recl_long = c[i - 1] < vwap[i - 1] and c[i] > vwap[i]
        recl_short = c[i - 1] > vwap[i - 1] and c[i] < vwap[i]
        side = 0.0
        if recl_long and side_mode in ("long", "both"): side = 1.0
        elif recl_short and side_mode in ("short", "both"): side = -1.0
        if side == 0.0:
            continue
        entry = c[i]  # next-bar market fill via fill_setups market mode not used; limit at close
        risk = max(atr[i] * 1.0, 1e-6)
        sl = entry - risk * (1 if side > 0 else -1)
        rmult = {"2R": 2.0, "3R": 3.0}[tp_mode]
        tp = entry + rmult * risk * (1 if side > 0 else -1)
        setups.append((ts[i + 1], side, entry, tp, sl, "market"))
    if not setups:
        return None
    df = pd.DataFrame(setups, columns=["arm_ts", "side", "entry_price", "tp_price", "sl_price", "fill_mode"])
    df["arm_ts"] = pd.to_datetime(df["arm_ts"]); return df.sort_values("arm_ts").reset_index(drop=True)


# ---------- family B: regression-channel breakout ----------
def trend_setups(m5, *, chan_n, k_std, tp_mode, session=("ny", "london")):
    pred, std = regchan(m5, chan_n)
    c = m5["close"].values; atr = m5["atr14_lag"].values; ts = m5["timestamp"].values
    ny = m5["timestamp"].dt.tz_convert("America/New_York"); nyh = ny.dt.hour.values
    n = len(m5)
    in_sess = np.zeros(n, bool)
    if "ny" in session: in_sess |= (nyh >= 8) & (nyh < 12)
    if "london" in session: in_sess |= (nyh >= 3) & (nyh < 8)
    setups = []
    for i in range(chan_n + 1, n - 1):
        if not in_sess[i] or not np.isfinite(pred[i]) or std[i] <= 0 or atr[i] <= 0:
            continue
        up = c[i] > pred[i] + k_std * std[i] and c[i - 1] <= pred[i - 1] + k_std * std[i - 1]
        dn = c[i] < pred[i] - k_std * std[i] and c[i - 1] >= pred[i - 1] - k_std * std[i - 1]
        side = 1.0 if up else (-1.0 if dn else 0.0)
        if side == 0.0:
            continue
        entry = c[i]; risk = max(atr[i] * 1.0, 1e-6)
        sl = entry - risk * (1 if side > 0 else -1)
        rmult = {"2R": 2.0, "3R": 3.0}[tp_mode]
        tp = entry + rmult * risk * (1 if side > 0 else -1)
        setups.append((ts[i + 1], side, entry, tp, sl, "market"))
    if not setups:
        return None
    df = pd.DataFrame(setups, columns=["arm_ts", "side", "entry_price", "tp_price", "sl_price", "fill_mode"])
    df["arm_ts"] = pd.to_datetime(df["arm_ts"]); return df.sort_values("arm_ts").reset_index(drop=True)


# ---------- family C: SMA golden/death cross ----------
def sma_cross_setups(m5, *, fast, slow, tp_mode, session=None):
    sf = add_sma(m5, fast); ss = add_sma(m5, slow)
    c = m5["close"].values; atr = m5["atr14_lag"].values; ts = m5["timestamp"].values
    n = len(m5); setups = []
    for i in range(slow + 1, n - 1):
        if not np.isfinite(sf[i]) or not np.isfinite(ss[i]) or atr[i] <= 0:
            continue
        golden = sf[i] > ss[i] and sf[i - 1] <= ss[i - 1]
        death = sf[i] < ss[i] and sf[i - 1] >= ss[i - 1]
        side = 1.0 if golden else (-1.0 if death else 0.0)
        if side == 0.0:
            continue
        entry = c[i]; risk = max(atr[i] * 2.0, 1e-6)  # wider stop for slow signal
        sl = entry - risk * (1 if side > 0 else -1)
        rmult = {"2R": 2.0, "3R": 3.0}[tp_mode]
        tp = entry + rmult * risk * (1 if side > 0 else -1)
        setups.append((ts[i + 1], side, entry, tp, sl, "market"))
    if not setups:
        return None
    df = pd.DataFrame(setups, columns=["arm_ts", "side", "entry_price", "tp_price", "sl_price", "fill_mode"])
    df["arm_ts"] = pd.to_datetime(df["arm_ts"]); return df.sort_values("arm_ts").reset_index(drop=True)


# ---------- S1 confluence: keep S1 setups agreeing with a directional filter ----------
def s1_base_setups(mtf):
    s = universe_s1(mtf, "15min", 4)
    m = (s["side"] == 1) & (s["depth"] <= 6) & ((3 + s["fvg"] + s["ob"]) >= 5) & (s["h4up"] == 1)
    m &= (s["ny_hr"] >= 2) & (s["ny_hr"] <= 11)
    s = s[m]
    if len(s) == 0: return None
    side = s["side"].values.astype(float); rng = (s["swing_hi"] - s["swing_lo"]).values
    entry = s["swing_hi"].values - 0.786 * rng; ssl = s["swing_lo"].values
    sl, tp, risk = _price(side, entry, ssl, 0.10, "3R", np.abs(entry - ssl))
    return pd.DataFrame({"arm_ts": s["arm_ts"].values, "side": side, "entry_price": entry,
                         "tp_price": tp, "sl_price": sl})


def audit(mtf, setups, label, do_year=False):
    print("\n" + "=" * 96)
    print(f"### {label} ###")
    if setups is None or len(setups) < 40:
        print(f"  {0 if setups is None else len(setups)} setups — SKIP"); return None
    sig = fill_setups(setups, mtf.m5, wait_bars=96, slip_atr=0.05)
    base = sim_price_bracket(sig, mtf.m5, horizon=288)
    if len(base) < 40:
        print(f"  {len(base)} fills — SKIP"); return None
    print_headline(f"{label} base", headline(base))
    op = mtf.m5["open"].values; n = len(mtf.m5)
    for d in (1, 2, 3):
        s = sig.copy(); s["fill_index"] = s["fill_index"].astype(int) + d
        s = s[s["fill_index"] < n - 2].reset_index(drop=True)
        s["entry_price"] = op[s["fill_index"].values]
        s["risk_units"] = (s["entry_price"] - s["sl_price"]).abs(); s = s[s["risk_units"] > 0]
        if len(s) > 20:
            print_headline(f"{label} delay+{d}", headline(sim_price_bracket(s, mtf.m5)))
    for cc in (0.30, 0.50, 0.80):
        print_headline(f"{label} cost${cc}", headline(sim_price_bracket(sig, mtf.m5, cost_usd=cc)))
    r = base["net_r"].values; rng = np.random.default_rng(13)
    boots = np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(1200)])
    _log(f"  bootstrap net={r.sum():+.1f}R P(net<=0)={(boots <= 0).mean():.4f}")
    print_headline(f"{label} IS19-23", headline(base[base.year <= 2023]))
    print_headline(f"{label} OOS24-26", headline(base[base.year >= 2024]))
    if do_year:
        yt = base.groupby("year")["net_r"].agg(["sum", "count"]).round(1)
        for y, row in yt.iterrows():
            print(f"    {int(y)}: {row['sum']:>+8.1f}R ({int(row['count'])})")
    mb = model_b(base, 0.015)
    print(f"  ModelB $5k@1.5%: ${mb['total']:,.0f} ({mb['total']/5000:.1f}x) maxDD ${mb['maxdd']:,.0f}")
    return headline(base)


def main():
    mtf = MTF()
    print("\n" + "#" * 96)
    print("# CLASSIC BATCH — VWAP / trendline-breakout / SMA-cross — XAUUSD, to the dot")
    print("#" * 96)
    res = []
    # A. VWAP
    for sm in ("both", "long", "short"):
        for tp in ("2R", "3R"):
            for sess in (("ny",), ("london", "ny")):
                lab = f"VWAP {sm}/{tp}/{'+'.join(sess)}"
                h = audit(mtf, vwap_setups(mtf.m5, side_mode=sm, tp_mode=tp, session=sess), lab)
                if h: res.append((lab, h))
    # B. trendline
    for cn in (20, 50, 100):
        for ks in (1.0, 2.0):
            for tp in ("2R", "3R"):
                lab = f"TREND n{cn}/k{ks}/{tp}"
                h = audit(mtf, trend_setups(mtf.m5, chan_n=cn, k_std=ks, tp_mode=tp), lab)
                if h: res.append((lab, h))
    # C. SMA cross
    for fs, sl in ((50, 200), (20, 50), (9, 21)):
        for tp in ("2R", "3R"):
            lab = f"SMAx {fs}/{sl}/{tp}"
            h = audit(mtf, sma_cross_setups(mtf.m5, fast=fs, slow=sl, tp_mode=tp), lab)
            if h: res.append((lab, h))
    # + S1 confluence with each directional filter
    s1 = s1_base_setups(mtf)
    if s1 is not None:
        vwap = add_session_vwap(mtf.m5)
        m5idx = pd.Series(np.arange(len(mtf.m5)), index=mtf.m5["timestamp"].dt.tz_localize(None).values)
        # S1 ∧ price>VWAP (long-only S1, keep if entry above session VWAP)
        arm_naive = pd.to_datetime(s1["arm_ts"]).dt.tz_localize(None).values
        pos = np.searchsorted(mtf.m5["timestamp"].dt.tz_localize(None).values, arm_naive, "right") - 1
        pos = np.clip(pos, 0, len(mtf.m5) - 1)
        above = s1["entry_price"].values > vwap[pos]
        for name, mask in [("S1∧aboveVWAP", above), ("S1∧belowVWAP", ~above)]:
            h = audit(mtf, s1[mask].reset_index(drop=True), name)
            if h: res.append((name, h))

    print("\n" + "#" * 96 + "\n# SUMMARY (gate PF>=1.3 MAR>=1.5 150/yr 7-8/8 delay+1)")
    print(f"{'variant':<26}{'n':>6}{'/yr':>5}{'PF':>6}{'MAR':>6}{'netR':>9}{'pos':>6}")
    for lab, h in sorted(res, key=lambda x: -x[1]["mar"]):
        print(f"{lab:<26}{h['n']:>6}{h['per_yr']:>5.0f}{h['pf']:>6.2f}{h['mar']:>6.2f}{h['net']:>+9.1f}{h['pos']:>6}")


if __name__ == "__main__":
    main()
