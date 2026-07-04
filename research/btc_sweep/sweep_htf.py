"""BTC higher-timeframe sweep (H1 / H4 / D1) — where BTC edge historically lives.

M5 sweep was an honest zero (gross PF~1.0). This tests trend/breakout/momentum on
higher timeframes with multi-day horizons, the regime BTC trend-following actually
targets (turtle/Donchian, MA-cross, momentum).

STRICT CAUSALITY (same bar as the M5 harness):
  - resample M1 → HTF bars (label='left', closed='left').
  - EVERY indicator is shift(1)-lagged: the decision at bar i uses only bars ≤ i-1.
  - entry fills at bar i OPEN. bracket walk close-based on the SAME HTF bars.
  - risk from lagged ATR or the Donchian channel width (both known at i-1).
  - cost = 12 bps round-trip of notional (crypto taker+spread), same as M5.

Gate: ≥ (low bar for HTF) trades — HTF fires far less than 200/yr, so we report
the gates honestly but ALSO surface any high-PF/high-MAR HTF candidate even if the
trade-count gate (designed for intraday) can't be met. A real HTF trend edge with
PF≥1.5 / MAR≥1 / 7-8 pos years is a legitimate find regardless of the 200/yr bar.
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


def load_htf(rule: str) -> pd.DataFrame:
    """M1 → HTF OHLC with shift(1)-lagged indicators. rule ∈ {'1h','4h','1D'}."""
    raw = pd.read_parquet(BTC_M1)
    raw = raw[(raw["timestamp"] >= START) & (raw["timestamp"] < END)]
    b = raw.set_index("timestamp").resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    # Indicators on the bar's own close, THEN lag by 1 so entry@open[i] only sees ≤i-1.
    for span in (10, 20, 50, 100, 200):
        b[f"ema{span}"] = b["close"].ewm(span=span, adjust=False).mean()
    tr = pd.concat([
        (b["high"] - b["low"]),
        (b["high"] - b["close"].shift(1)).abs(),
        (b["low"] - b["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    b["atr"] = tr.rolling(14).mean()
    b["roc"] = b["close"].pct_change(20)  # 20-bar momentum
    # Donchian channels (rolling max/min of prior bars) — computed then lagged.
    for w in (20, 40, 55):
        b[f"dc_hi{w}"] = b["high"].rolling(w).max()
        b[f"dc_lo{w}"] = b["low"].rolling(w).min()
    # Lag EVERYTHING used for decisions.
    lag_cols = [c for c in b.columns if c not in ("timestamp", "open", "high", "low", "close", "volume")]
    for c in lag_cols:
        b[f"{c}_lag"] = b[c].shift(1)
    b["year"] = b["timestamp"].dt.year
    return b.dropna().reset_index(drop=True)


def simulate_htf(sigs: pd.DataFrame, b: pd.DataFrame, *, tp_mult: float,
                 horizon_bars: int, cost_bps: float = COST_BPS) -> pd.DataFrame:
    op, cl = b["open"].values, b["close"].values
    ts, yr = b["timestamp"].values, b["year"].values
    n = len(b)
    outs = []
    for s in sigs.itertuples(index=False):
        i, side, risk = s.entry_index, s.side, s.risk_units
        if risk <= 0 or i >= n - 2:
            continue
        entry = op[i]; stop = entry - risk * side; tp = entry + tp_mult * risk * side
        end = min(n - 1, i + horizon_bars); outcome = 0.0; xi = end
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
        cost_r = (cost_bps / 1e4 * entry) / risk
        outs.append({"entry_ts": ts[i], "side": side, "entry_price": entry,
                     "bracket_r": outcome, "cost_r": cost_r,
                     "net_r": outcome - cost_r, "year": yr[i]})
    return pd.DataFrame(outs)


def headline(tr: pd.DataFrame) -> dict:
    if len(tr) == 0:
        return {"n": 0, "pf": 0, "mar": 0, "pos_years": "0/0", "trades_per_year": 0, "net": 0, "yr_r": 0, "wr": 0}
    r = tr["net_r"].astype(float); n = len(r); net = float(r.sum())
    gw = float(r[r > 0].sum()); gl = float(-r[r < 0].sum())
    pf = gw / gl if gl > 0 else float("inf")
    eq = r.cumsum().values; dd = float((eq - np.maximum.accumulate(eq)).min())
    t = pd.to_datetime(tr["entry_ts"]); yrs = max(0.01, (t.max() - t.min()).total_seconds() / (365.25 * 86400))
    y = tr.groupby("year")["net_r"].sum(); pos = int((y > 0).sum()); tot = int(len(y))
    return {"n": n, "net": net, "yr_r": net / yrs, "wr": float((r > 0).mean()),
            "pf": pf, "dd": dd, "mar": (net / yrs) / abs(dd) if dd else 0,
            "pos_years": f"{pos}/{tot}", "trades_per_year": n / yrs}


def pr(label, h):
    if h["n"] == 0:
        print(f"  {label:<48s} ZERO"); return
    star = "  ★" if (h["pf"] >= 1.5 and h["mar"] >= 1.0 and int(h["pos_years"].split("/")[0]) >= 6) else ""
    print(f"  {label:<48s} n={h['n']:>5d} /yr={h['trades_per_year']:>4.0f} net={h['net']:>+7.1f}R "
          f"/yr={h['yr_r']:>+6.1f} WR={h['wr']*100:>4.1f}% PF={h['pf']:>5.2f} MAR={h['mar']:>+5.2f} pos={h['pos_years']}{star}")


def dedup(idx, cd):
    if len(idx) == 0: return idx
    idx = np.sort(idx); k = [idx[0]]
    for i in idx[1:]:
        if i - k[-1] >= cd: k.append(i)
    return np.array(k)


def gen_donchian(b, *, side, w, atr_sl):
    """Turtle breakout: bar opens beyond prior N-bar Donchian channel (lagged)."""
    op = b["open"].values
    hi = b[f"dc_hi{w}_lag"].values; lo = b[f"dc_lo{w}_lag"].values
    atr = b["atr_lag"].values
    if side > 0:
        sig = (op > hi) & (atr > 0)
    else:
        sig = (op < lo) & (atr > 0)
    idx = dedup(np.where(sig)[0], cd=w)  # don't re-enter same breakout
    return pd.DataFrame({"entry_index": idx, "side": side, "risk_units": atr[idx] * atr_sl})


def gen_macross(b, *, side, fast, slow, atr_sl):
    """Trend: fast EMA above/below slow EMA (both lagged) — regime continuation, enter
    on the bar after a fresh cross."""
    f = b[f"ema{fast}_lag"].values; s = b[f"ema{slow}_lag"].values
    fp = b[f"ema{fast}_lag"].shift(1).values; sp = b[f"ema{slow}_lag"].shift(1).values
    atr = b["atr_lag"].values
    if side > 0:
        sig = (f > s) & (fp <= sp) & (atr > 0)  # fresh golden cross
    else:
        sig = (f < s) & (fp >= sp) & (atr > 0)  # fresh death cross
    idx = np.where(sig)[0]
    return pd.DataFrame({"entry_index": idx, "side": side, "risk_units": atr[idx] * atr_sl})


def gen_momentum(b, *, side, thr, atr_sl):
    """Momentum: lagged 20-bar ROC beyond threshold → ride continuation."""
    roc = b["roc_lag"].values; atr = b["atr_lag"].values
    if side > 0:
        sig = (roc > thr) & (atr > 0)
    else:
        sig = (roc < -thr) & (atr > 0)
    idx = dedup(np.where(sig)[0], cd=10)
    return pd.DataFrame({"entry_index": idx, "side": side, "risk_units": atr[idx] * atr_sl})


def run():
    results = []
    for tf, rule, horizon in [("H1", "1h", 168), ("H4", "4h", 180), ("D1", "1D", 60)]:
        b = load_htf(rule)
        print(f"\n{'='*100}\n{tf}: {len(b):,} bars  {b['timestamp'].min()}→{b['timestamp'].max()}  horizon={horizon} bars")
        # Donchian
        for side, w, sl, tp in product([1, -1], [20, 40, 55], [1.0, 2.0], [2.0, 3.0]):
            h = headline(simulate_htf(gen_donchian(b, side=side, w=w, atr_sl=sl), b, tp_mult=tp, horizon_bars=horizon))
            pr(f"{tf} donch {'L' if side>0 else 'S'} w{w} sl{sl} tp{tp}", h)
            results.append((f"{tf}_donch_{side}_{w}_{sl}_{tp}", h))
        # MA cross
        for side, (fa, sl_ema), sl, tp in product([1, -1], [(10, 50), (20, 100), (50, 200)], [1.5, 2.5], [3.0, 4.0]):
            h = headline(simulate_htf(gen_macross(b, side=side, fast=fa, slow=sl_ema, atr_sl=sl), b, tp_mult=tp, horizon_bars=horizon))
            pr(f"{tf} macross {'L' if side>0 else 'S'} {fa}/{sl_ema} sl{sl} tp{tp}", h)
            results.append((f"{tf}_ma_{side}_{fa}_{sl_ema}_{sl}_{tp}", h))
        # Momentum
        for side, thr, sl, tp in product([1, -1], [0.05, 0.10, 0.20], [1.5, 2.5], [2.0, 3.0]):
            h = headline(simulate_htf(gen_momentum(b, side=side, thr=thr, atr_sl=sl), b, tp_mult=tp, horizon_bars=horizon))
            pr(f"{tf} mom {'L' if side>0 else 'S'} thr{thr} sl{sl} tp{tp}", h)
            results.append((f"{tf}_mom_{side}_{thr}_{sl}_{tp}", h))

    print(f"\n{'='*100}\nCANDIDATES (PF≥1.5, MAR≥1.0, ≥6/8 pos years):")
    cands = [(n, h) for n, h in results if h["n"] > 20 and h["pf"] >= 1.5 and h["mar"] >= 1.0
             and int(h["pos_years"].split("/")[0]) >= 6]
    for n, h in sorted(cands, key=lambda x: -x[1]["mar"]):
        print(f"  ★ {n:<40s} PF={h['pf']:.2f} MAR={h['mar']:.2f} /yr={h['trades_per_year']:.0f} pos={h['pos_years']} n={h['n']}")
    if not cands:
        print("  (none — honest zero on HTF too)")
    # save leaderboard
    rows = [{"config": n, **h} for n, h in results]
    pd.DataFrame(rows).to_csv(Path(__file__).parent / "htf_leaderboard.csv", index=False)
    print(f"\n{len(results)} configs → htf_leaderboard.csv")


if __name__ == "__main__":
    run()
