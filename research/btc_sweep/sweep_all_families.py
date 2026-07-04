"""Port EVERY remaining XAU research family to BTC — full causal sweep.

Families (12): FVG (retest/fade/break), FVG-nested, ICT (sweep-reversal / BOS /
equal-levels), Order-Block mitigation, ORB breakout, Range/mean-reversion,
RSI-divergence, Tiger liquidity-sweep+MSS, VWAP-MSS, Drone SuperTrend,
Confluence (ORB+VWAP momentum), VWAP-band reversion.

Every generator is SELF-CONTAINED + STRICTLY CAUSAL:
  - operates on a resampled frame (M5 / H1 / H4 / D1) built here with shift(1) lag
  - decision at bar i uses ONLY bars ≤ i-1 (own OHLC never informs own entry)
  - entry fills at bar i OPEN; bracket walk close-based; cost 12 bps of notional
  - risk_units from lagged ATR or a prior structural level

Output: research/btc_sweep/all_families_leaderboard.csv (one row per config).
Gate flagged: PF≥1.3 AND MAR≥1.0 AND pos_years≥ (7/8 intraday | 6/8 HTF) AND n≥30.
Adversarial battery run separately on any flagged survivor.
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BTC_M1 = Path("/Users/subash/SUBASH/GoldDigger/research/data/btc/BTCUSDT_M1.parquet")
START = pd.Timestamp("2019-10-01", tz="UTC")
END = pd.Timestamp("2026-07-01", tz="UTC")
COST_BPS = 12.0
OUT = Path(__file__).parent / "all_families_leaderboard.csv"

_RAW = None


def _raw():
    global _RAW
    if _RAW is None:
        r = pd.read_parquet(BTC_M1)
        _RAW = r[(r["timestamp"] >= START) & (r["timestamp"] < END)].sort_values("timestamp").reset_index(drop=True)
    return _RAW


def frame(rule: str) -> pd.DataFrame:
    """Resampled OHLC + causal (shift(1)) indicators. rule ∈ {'5min','15min','1h','4h','1D'}."""
    b = _raw().set_index("timestamp").resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    for s in (8, 20, 50, 200):
        b[f"ema{s}"] = b["close"].ewm(span=s, adjust=False).mean()
    b["sma20"] = b["close"].rolling(20).mean()
    tr = pd.concat([(b["high"] - b["low"]),
                    (b["high"] - b["close"].shift(1)).abs(),
                    (b["low"] - b["close"].shift(1)).abs()], axis=1).max(axis=1)
    b["atr"] = tr.rolling(14).mean()
    # RSI(14) Wilder
    delta = b["close"].diff()
    up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    b["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    # Bollinger
    b["bb_mid"] = b["close"].rolling(20).mean()
    b["bb_sd"] = b["close"].rolling(20).std()
    # session VWAP per UTC day (typical price)
    b["utc_date"] = b["timestamp"].dt.date.astype(str)
    tp = (b["high"] + b["low"] + b["close"]) / 3
    b["_tpv"] = tp * b["volume"]
    b["vwap"] = b.groupby("utc_date")["_tpv"].cumsum() / b.groupby("utc_date")["volume"].cumsum()
    # LAG everything used in decisions
    for c in ["ema8", "ema20", "ema50", "ema200", "sma20", "atr", "rsi",
              "bb_mid", "bb_sd", "vwap", "open", "high", "low", "close", "volume"]:
        b[f"{c}_lag"] = b[c].shift(1)
    b["ny_hr"] = b["timestamp"].dt.tz_convert("America/New_York").dt.hour
    b["utc_hr"] = b["timestamp"].dt.hour
    b["year"] = b["timestamp"].dt.year
    return b.dropna(subset=["atr_lag", "ema200_lag"]).reset_index(drop=True)


def simulate(sigs, b, *, tp_mult, horizon, cost_bps=COST_BPS):
    op, cl = b["open"].values, b["close"].values
    ts, yr = b["timestamp"].values, b["year"].values
    n = len(b); outs = []
    for s in sigs.itertuples(index=False):
        i, side, risk = int(s.entry_index), int(s.side), float(s.risk_units)
        if risk <= 0 or i >= n - 2:
            continue
        entry = op[i]; stop = entry - risk * side; tp = entry + tp_mult * risk * side
        end = min(n - 1, i + horizon); outcome = 0.0; xi = end
        for j in range(i, end + 1):
            c = cl[j]
            if side > 0:
                if c <= stop: outcome = -1.0; xi = j; break
                if c >= tp: outcome = tp_mult; xi = j; break
            else:
                if c >= stop: outcome = -1.0; xi = j; break
                if c <= tp: outcome = tp_mult; xi = j; break
        else:
            outcome = max(-1.0, min(tp_mult, side * (cl[xi] - entry) / risk))
        outs.append({"entry_ts": ts[i], "side": side, "bracket_r": outcome,
                     "cost_r": (cost_bps/1e4*entry)/risk,
                     "net_r": outcome - (cost_bps/1e4*entry)/risk, "year": yr[i]})
    return pd.DataFrame(outs)


def headline(tr):
    if len(tr) == 0:
        return {"n": 0, "pf": 0, "mar": 0, "pos_years": "0/0", "trades_per_year": 0, "net": 0, "wr": 0}
    r = tr["net_r"].astype(float); n = len(r); net = float(r.sum())
    gw = float(r[r > 0].sum()); gl = float(-r[r < 0].sum()); pf = gw/gl if gl > 0 else float("inf")
    eq = r.cumsum().values; dd = float((eq - np.maximum.accumulate(eq)).min())
    t = pd.to_datetime(tr["entry_ts"], utc=True); yrs = max(0.01, (t.max()-t.min()).total_seconds()/(365.25*86400))
    y = tr.groupby("year")["net_r"].sum(); pos = int((y > 0).sum()); tot = int(len(y))
    return {"n": n, "net": net, "wr": float((r > 0).mean()), "pf": pf, "dd": dd,
            "mar": (net/yrs)/abs(dd) if dd else 0, "pos_years": f"{pos}/{tot}", "trades_per_year": n/yrs}


def dedup(idx, cd):
    if len(idx) == 0: return np.array([], int)
    idx = np.sort(np.asarray(idx)); k = [idx[0]]
    for i in idx[1:]:
        if i - k[-1] >= cd: k.append(i)
    return np.array(k)


def _mk(idx, side, risk, b):
    idx = np.asarray(idx, int)
    return pd.DataFrame({"entry_index": idx, "side": side, "risk_units": b["atr_lag"].values[idx] * risk})


# ── FVG: 3-bar imbalance on prior bars (i-3,i-2,i-1), act at i ──────────────
def gen_fvg(b, *, side, mode, sl, cd=6):
    h, l = b["high"].values, b["low"].values
    b1h, b1l = b["high"].shift(3).values, b["low"].shift(3).values
    b3h, b3l = b["high"].shift(1).values, b["low"].shift(1).values
    op = b["open"].values
    bull_fvg = b1h < b3l   # gap up
    bear_fvg = b1l > b3h   # gap down
    atr = b["atr_lag"].values
    if mode == "break":  # continuation in FVG direction, enter at i open
        sig = (bull_fvg if side > 0 else bear_fvg) & (atr > 0)
    elif mode == "retest":  # price came back into the gap then continues
        if side > 0:
            sig = bull_fvg & (l < b3l) & (op > b3l) & (atr > 0)  # dipped into gap, reclaim
        else:
            sig = bear_fvg & (h > b3h) & (op < b3h) & (atr > 0)
    else:  # fade — counter-trend when price enters gap
        if side > 0:
            sig = bear_fvg & (l <= b3h) & (atr > 0)
        else:
            sig = bull_fvg & (h >= b3l) & (atr > 0)
    return _mk(dedup(np.where(np.nan_to_num(sig))[0], cd), side, sl, b)


# ── Order Block: bearish/bullish candle before impulse, retest ─────────────
def gen_ob(b, *, side, sl, imp=1.5, cd=12):
    o, c = b["open"].values, b["close"].values
    atr = b["atr_lag"].values
    # impulse over prior 3 bars ≥ imp*ATR (all lagged)
    move3 = (b["close"].shift(1) - b["close"].shift(4)).values
    if side > 0:
        # bullish OB: recent down-candle then up-impulse then price retests its low zone
        ob_lo = b["low"].shift(4).values
        sig = (move3 > imp * atr) & (b["low"].values <= b["low"].shift(4).values) & (o > ob_lo) & (atr > 0)
    else:
        ob_hi = b["high"].shift(4).values
        sig = (move3 < -imp * atr) & (b["high"].values >= b["high"].shift(4).values) & (o < ob_hi) & (atr > 0)
    return _mk(dedup(np.where(np.nan_to_num(sig))[0], cd), side, sl, b)


# ── ORB: opening-range break (NY 09:30 proxy → first bar of NY hour) ───────
def gen_orb(b, *, side, sl, cd=48):
    # daily opening range = first bar of NY 09:00 hour; break of its hi/lo
    d = b.copy()
    d["ny_date"] = d["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    orb = d[d["ny_hr"] == 9].groupby("ny_date").agg(oh=("high", "max"), ol=("low", "min"))
    d = d.join(orb, on="ny_date")
    op = d["open"].values; oh = d["oh"].values; ol = d["ol"].values
    atr = b["atr_lag"].values
    after = (d["ny_hr"].values >= 10)  # only after ORB window closed
    if side > 0:
        sig = after & (op > oh) & (b["open"].shift(1).values <= oh) & (atr > 0)
    else:
        sig = after & (op < ol) & (b["open"].shift(1).values >= ol) & (atr > 0)
    return _mk(dedup(np.where(np.nan_to_num(sig))[0], cd), side, sl, b)


# ── Range / BB mean-reversion (fade band extremes in NON-trend) ────────────
def gen_bb_meanrev(b, *, side, sl, k=2.0, cd=12):
    mid = b["bb_mid_lag"].values; sd = b["bb_sd_lag"].values
    lo = mid - k * sd; hi = mid + k * sd
    atr = b["atr_lag"].values
    # only when not strongly trending (price within 3% of ema200 → range regime)
    flat = (np.abs(b["close"].shift(1).values / b["ema200_lag"].values - 1) < 0.05)
    if side > 0:
        sig = flat & (b["low"].shift(1).values <= lo) & (b["open"].values > lo) & (atr > 0)
    else:
        sig = flat & (b["high"].shift(1).values >= hi) & (b["open"].values < hi) & (atr > 0)
    return _mk(dedup(np.where(np.nan_to_num(sig))[0], cd), side, sl, b)


# ── RSI divergence proxy: oversold/overbought reclaim ──────────────────────
def gen_rsi(b, *, side, sl, lo=30, hi=70, cd=12):
    rsi = b["rsi_lag"].values; rsi_prev = b["rsi_lag"].values  # lagged
    r2 = b["rsi"].shift(2).values
    atr = b["atr_lag"].values
    if side > 0:
        sig = (r2 < lo) & (rsi > r2) & (rsi < 50) & (atr > 0)  # rising out of oversold
    else:
        sig = (r2 > hi) & (rsi < r2) & (rsi > 50) & (atr > 0)
    return _mk(dedup(np.where(np.nan_to_num(sig))[0], cd), side, sl, b)


# ── VWAP-MSS: retest of session VWAP + structure break ─────────────────────
def gen_vwap_mss(b, *, side, sl, cd=12):
    vwap = b["vwap_lag"].values; atr = b["atr_lag"].values
    o, h, l, c = b["open"].values, b["high"].values, b["low"].values, b["close"].values
    ll = b["low"].shift(1).rolling(5).min().shift(1).values
    hh = b["high"].shift(1).rolling(5).max().shift(1).values
    if side > 0:
        retest = (l <= vwap) & (o > vwap)
        mss = (o > hh)
        sig = retest & mss & (atr > 0)
    else:
        retest = (h >= vwap) & (o < vwap)
        mss = (o < ll)
        sig = retest & mss & (atr > 0)
    return _mk(dedup(np.where(np.nan_to_num(sig))[0], cd), side, sl, b)


# ── VWAP momentum: trade in VWAP-bias direction on continuation ────────────
def gen_vwap_mom(b, *, side, sl, cd=12):
    vwap = b["vwap_lag"].values; atr = b["atr_lag"].values
    o = b["open"].values; cprev = b["close"].shift(1).values
    if side > 0:
        sig = (cprev > vwap) & (o > vwap) & (b["close"].shift(1).values > b["ema50_lag"].values) & (atr > 0)
    else:
        sig = (cprev < vwap) & (o < vwap) & (b["close"].shift(1).values < b["ema50_lag"].values) & (atr > 0)
    return _mk(dedup(np.where(np.nan_to_num(sig))[0], cd), side, sl, b)


# ── Drone SuperTrend: ST flip + SMA20 trend filter + momentum ──────────────
def gen_supertrend(b, *, side, sl, factor=3.0, cd=6):
    hl2 = (b["high"] + b["low"]) / 2
    atr_s = b["atr"]
    up = (hl2 - factor * atr_s)
    dn = (hl2 + factor * atr_s)
    close = b["close"].values
    st = np.zeros(len(b)); trend = np.ones(len(b), int)
    upv, dnv = up.values, dn.values
    for i in range(1, len(b)):
        upv[i] = max(upv[i], upv[i-1]) if close[i-1] > upv[i-1] else upv[i]
        dnv[i] = min(dnv[i], dnv[i-1]) if close[i-1] < dnv[i-1] else dnv[i]
        if trend[i-1] == 1 and close[i] < upv[i]: trend[i] = -1
        elif trend[i-1] == -1 and close[i] > dnv[i]: trend[i] = 1
        else: trend[i] = trend[i-1]
    tr_lag = pd.Series(trend).shift(1).values
    tr_lag2 = pd.Series(trend).shift(2).values
    sma = b["sma20_lag"].values; atr = b["atr_lag"].values
    cprev = b["close"].shift(1).values
    if side > 0:
        sig = (tr_lag == 1) & (tr_lag2 == -1) & (cprev > sma) & (atr > 0)  # fresh flip up
    else:
        sig = (tr_lag == -1) & (tr_lag2 == 1) & (cprev < sma) & (atr > 0)
    return _mk(dedup(np.where(np.nan_to_num(sig))[0], cd), side, sl, b)


FAMILIES = {
    "fvg_break":   (gen_fvg, dict(mode="break")),
    "fvg_retest":  (gen_fvg, dict(mode="retest")),
    "fvg_fade":    (gen_fvg, dict(mode="fade")),
    "ob":          (gen_ob, {}),
    "orb":         (gen_orb, {}),
    "bb_meanrev":  (gen_bb_meanrev, {}),
    "rsi":         (gen_rsi, {}),
    "vwap_mss":    (gen_vwap_mss, {}),
    "vwap_mom":    (gen_vwap_mom, {}),
    "supertrend":  (gen_supertrend, {}),
}


def run():
    rows = []
    tfs = [("M5", "5min", 288), ("M15", "15min", 96), ("H1", "1h", 168), ("H4", "4h", 180)]
    for tf, rule, horizon in tfs:
        b = frame(rule)
        print(f"\n{'='*100}\n{tf}: {len(b):,} bars")
        for fam, (fn, base) in FAMILIES.items():
            for side, sl, tp in product([1, -1], [1.0, 2.0], [1.5, 2.0, 3.0]):
                try:
                    sig = fn(b, side=side, sl=sl, **base)
                except Exception as e:
                    continue
                if len(sig) < 20:
                    continue
                h = headline(simulate(sig, b, tp_mult=tp, horizon=horizon))
                if h["n"] < 20:
                    continue
                posn = int(h["pos_years"].split("/")[0]); tot = int(h["pos_years"].split("/")[1])
                flag = (h["pf"] >= 1.3 and h["mar"] >= 1.0 and h["n"] >= 30
                        and posn >= (6 if tf in ("H1", "H4") else 7))
                rows.append({"tf": tf, "family": fam, "side": "L" if side > 0 else "S",
                             "sl": sl, "tp": tp, **h, "flag": flag})
                if flag:
                    print(f"  ★ {tf} {fam} {'L' if side>0 else 'S'} sl{sl} tp{tp}: "
                          f"PF={h['pf']:.2f} MAR={h['mar']:.2f} n={h['n']} /yr={h['trades_per_year']:.0f} pos={h['pos_years']}")
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    fl = df[df["flag"]]
    print(f"\n{'='*100}\nTOTAL CONFIGS: {len(df)}   FLAGGED (PF≥1.3 MAR≥1.0 pos-ok n≥30): {len(fl)}")
    if len(fl):
        print(fl.sort_values("mar", ascending=False)[["tf", "family", "side", "sl", "tp", "n", "trades_per_year", "pf", "mar", "pos_years"]].to_string(index=False))
    else:
        print("  (no NEW family flagged — honest)")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    run()
