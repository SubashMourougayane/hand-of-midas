"""Shared causal simulator for BTCUSDT pattern research.

Fork of causal_sim.py (XAU) with BTC-specific changes, SAME strict causal rules:
- All features derive from bars whose CLOSE timestamp is BEFORE entry timestamp.
- Entries on the M5 grid.
- M15 EMA/ATR use the PRIOR closed M15 bar (shift(1) lag).
- 1R / 2R bracket; close-based touch; horizon in bars.

BTC differences vs XAU:
- 24/7 market — NO session/ORB-close gating by weekday-hours; but session-hour
  FEATURES (ny_hr etc.) are still available for time-of-day patterns.
- Cost model is in BASIS POINTS of price (crypto taker fee + spread), not a fixed
  $/risk_units. Binance spot taker ≈ 10 bps round-trip; add ~2 bps spread ⇒ 12 bps
  default. cost_r = (cost_bps/1e4 * entry_price) / risk_units.
- contract size irrelevant for R-based sim (R is unit-free).
- Data: research/data/btc/BTCUSDT_M1.parquet (from binance_btc_download.py).

Output mirrors XAU harness:
    research/btc_<family>/<pattern>_trades.parquet + _headline.json
    research/results/MASTER_LEADERBOARD_BTC.csv
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BTC_M1 = Path("/Users/subash/SUBASH/GoldDigger/research/data/btc/BTCUSDT_M1.parquet")
M5_CACHE = Path("/tmp/btc_m5_causal.parquet")
M15_CACHE = Path("/tmp/btc_m15_causal.parquet")
LEADERBOARD = Path("/Users/subash/SUBASH/GoldDigger/research/results/MASTER_LEADERBOARD_BTC.csv")

# Causal window: start once we have clean 1m history, end at last full month.
START = pd.Timestamp("2019-10-01", tz="UTC")
END = pd.Timestamp("2026-07-01", tz="UTC")

# Round-trip cost in basis points of notional (taker fee + spread). Conservative.
COST_BPS = 12.0


def _load_raw_m1() -> pd.DataFrame:
    raw = pd.read_parquet(BTC_M1)
    raw = raw[(raw["timestamp"] >= START) & (raw["timestamp"] < END)]
    return raw.sort_values("timestamp").reset_index(drop=True)


def _build_m15(raw: pd.DataFrame) -> pd.DataFrame:
    m15 = raw.set_index("timestamp").resample("15min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    m15["ema8"] = m15["close"].ewm(span=8, adjust=False).mean()
    m15["ema20"] = m15["close"].ewm(span=20, adjust=False).mean()
    m15["ema50"] = m15["close"].ewm(span=50, adjust=False).mean()
    tr = pd.concat([
        (m15["high"] - m15["low"]),
        (m15["high"] - m15["close"].shift(1)).abs(),
        (m15["low"] - m15["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    m15["atr14"] = tr.rolling(14).mean()
    # Lag by 1: at entry on m15[i+1] open we only know m15[i] close + features.
    for c in ["ema8", "ema20", "ema50", "atr14", "open", "high", "low", "close"]:
        m15[f"{c}_lag"] = m15[c].shift(1)
    return m15.dropna().reset_index(drop=True)


def _build_m5(raw: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    m5 = raw.set_index("timestamp").resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    # Attach the LAST CLOSED M15 context to each M5 bar (floor to 15min → that
    # M15 bar's *_lag columns already = the bar before it, so strictly causal).
    m5_floor = m5["timestamp"].dt.floor("15min")
    ctx = m15.set_index("timestamp")
    ctx_aligned = ctx.reindex(m5_floor).reset_index(drop=True)
    out = pd.concat(
        [
            m5.reset_index(drop=True),
            ctx_aligned[["ema8_lag", "ema20_lag", "ema50_lag", "atr14_lag",
                         "open_lag", "high_lag", "low_lag", "close_lag"]],
        ],
        axis=1,
    ).dropna(subset=["ema8_lag"]).reset_index(drop=True)
    out["utc_hr"] = out["timestamp"].dt.hour
    out["ny_hr"] = out["timestamp"].dt.tz_convert("America/New_York").dt.hour
    out["ny_min"] = out["timestamp"].dt.tz_convert("America/New_York").dt.minute
    out["ny_date"] = out["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    out["utc_date"] = out["timestamp"].dt.date.astype(str)
    out["dow"] = out["timestamp"].dt.day_name()
    out["year"] = out["timestamp"].dt.year
    return out


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (m1, m5_with_ctx, m15_with_lag)."""
    if M5_CACHE.exists() and M15_CACHE.exists():
        m1 = _load_raw_m1()
        return m1, pd.read_parquet(M5_CACHE), pd.read_parquet(M15_CACHE)
    m1 = _load_raw_m1()
    m15 = _build_m15(m1)
    m5 = _build_m5(m1, m15)
    m15.to_parquet(M15_CACHE)
    m5.to_parquet(M5_CACHE)
    return m1, m5, m15


def simulate(
    signals: pd.DataFrame,
    m5_frame: pd.DataFrame,
    *,
    cost_bps: float = COST_BPS,
    horizon_bars: int = 288,   # 24h of M5 bars
    tp_mult: float = 1.0,
) -> pd.DataFrame:
    """signals = DataFrame[entry_index, side, risk_units]. Close-based bracket walk."""
    op = m5_frame["open"].values
    cl = m5_frame["close"].values
    ts = m5_frame["timestamp"].values
    yr = m5_frame["year"].values
    n = len(m5_frame)
    outs = []
    for sig in signals.itertuples(index=False):
        i = sig.entry_index
        side = sig.side
        risk = sig.risk_units
        if risk <= 0 or i >= n - 2:
            continue
        entry = op[i]
        stop = entry - risk * side
        tp = entry + tp_mult * risk * side
        end = min(n - 1, i + horizon_bars)
        outcome_r = 0.0
        exit_i = end
        for j in range(i, end + 1):
            c = cl[j]
            if side > 0:
                if c <= stop:
                    outcome_r = -1.0; exit_i = j; break
                if c >= tp:
                    outcome_r = tp_mult; exit_i = j; break
            else:
                if c >= stop:
                    outcome_r = -1.0; exit_i = j; break
                if c <= tp:
                    outcome_r = tp_mult; exit_i = j; break
        else:
            outcome_r = max(-1.0, min(tp_mult, side * (cl[exit_i] - entry) / risk))
        # Cost in R = (bps of entry notional) / risk_units.
        cost_r = (cost_bps / 1e4 * entry) / risk
        outs.append({
            "entry_ts": ts[i], "side": side, "entry_price": entry,
            "stop_price": stop, "tp_price": tp, "risk_units": risk,
            "exit_index": exit_i, "bracket_r": outcome_r,
            "cost_r": cost_r, "net_r": outcome_r - cost_r, "year": yr[i],
        })
    return pd.DataFrame(outs)


def headline(trades: pd.DataFrame) -> dict:
    if len(trades) == 0:
        return {"n": 0, "net": 0.0, "yr_r": 0.0, "wr": 0.0, "pf": 0.0,
                "dd": 0.0, "mar": 0.0, "pos_years": "0/0", "trades_per_year": 0.0}
    r = trades["net_r"].astype(float)
    n = len(r)
    net = float(r.sum())
    wr = float((r > 0).mean())
    gw = float(r[r > 0].sum())
    gl = float(-r[r < 0].sum())
    pf = gw / gl if gl > 0 else float("inf")
    eq = r.cumsum().values
    peak = np.maximum.accumulate(eq)
    dd = float((eq - peak).min())
    tstamps = pd.to_datetime(trades["entry_ts"])
    yrs = max(0.01, (tstamps.max() - tstamps.min()).total_seconds() / (365.25 * 86400))
    yr_r = net / yrs
    mar = yr_r / abs(dd) if dd != 0 else 0
    y = trades.groupby("year")["net_r"].sum()
    pos = int((y > 0).sum())
    total = int(len(y))
    return {
        "n": int(n), "net": net, "yr_r": yr_r, "wr": wr, "pf": pf,
        "dd": dd, "mar": mar, "pos_years": f"{pos}/{total}",
        "years_dict": y.round(2).to_dict(), "trades_per_year": n / yrs,
    }


def gate(h: dict) -> dict:
    pos, total = h["pos_years"].split("/")
    pos = int(pos); total = int(total) if total != "0" else 1
    return {
        "trades_yr_ge_200": h["trades_per_year"] >= 200,
        "pf_ge_1p3": h["pf"] >= 1.3,
        "mar_ge_1p5": h["mar"] >= 1.5,
        "pos_years_ge_7of8": pos >= max(7, total - 1),
        "ALL_PASS": (h["trades_per_year"] >= 200) and (h["pf"] >= 1.3)
                    and (h["mar"] >= 1.5) and pos >= max(7, total - 1),
    }


def persist(family: str, pattern_name: str, trades: pd.DataFrame,
            notes: str = "", extra: dict | None = None) -> dict:
    family_dir = Path(f"/Users/subash/SUBASH/GoldDigger/research/{family}")
    family_dir.mkdir(parents=True, exist_ok=True)
    h = headline(trades) if len(trades) else {}
    g = gate(h) if h else {}
    record = {"family": family, "pattern": pattern_name, "ts_run": int(time.time()),
              **h, **{f"gate_{k}": v for k, v in g.items()}, "notes": notes, **(extra or {})}
    if len(trades):
        trades.to_parquet(family_dir / f"{pattern_name}_trades.parquet")
    (family_dir / f"{pattern_name}_headline.json").write_text(json.dumps(record, indent=2, default=str))
    LEADERBOARD.parent.mkdir(parents=True, exist_ok=True)
    row_df = pd.DataFrame([record])
    if LEADERBOARD.exists():
        existing = pd.read_csv(LEADERBOARD)
        existing = existing[~((existing["family"] == family) & (existing["pattern"] == pattern_name))]
        out = pd.concat([existing, row_df], ignore_index=True)
    else:
        out = row_df
    out.to_csv(LEADERBOARD, index=False)
    return record


def print_headline(label: str, h: dict) -> None:
    if h.get("n", 0) == 0:
        print(f"  {label:<50s} ZERO"); return
    g = gate(h)
    flag = "  ★★★ PASS" if g.get("ALL_PASS") else ""
    print(f"  {label:<50s} n={h['n']:>6d} /yr={h['trades_per_year']:>5.0f} "
          f"net={h['net']:>+8.1f}R /yr={h['yr_r']:>+6.1f} WR={h['wr']*100:>5.1f}% "
          f"PF={h['pf']:>5.2f} DD={h['dd']:>+7.1f} MAR={h['mar']:>+5.2f} pos={h['pos_years']}{flag}")
