"""Run M15 OB Retest TP=3R on BRENT to test cross-symbol generalisation."""
from __future__ import annotations

import sys
sys.path.insert(0, "/Users/subash/SUBASH/GoldDigger")

import numpy as np
import pandas as pd

from research.harness.causal_sim import simulate, headline, print_headline, persist

BRENT_PARQUET = "/Users/subash/SUBASH/quant-analysis/data/parquet/BRENT_M1.parquet"
# BRENT cost — measured spread median = ~5 points × $0.01/point = $0.05 USD
BRENT_COST_USD = 0.05


def load_brent():
    df = pd.read_parquet(BRENT_PARQUET)
    df = df.reset_index().rename(columns={"ts": "timestamp", "tickvol": "volume"})
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.dropna().sort_values("timestamp").reset_index(drop=True)
    return df


def build_frames(m1: pd.DataFrame):
    m5 = m1.set_index("timestamp").resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    m15 = m1.set_index("timestamp").resample("15min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    # M15 indicators
    m15["ema8"] = m15["close"].ewm(span=8, adjust=False).mean()
    m15["ema20"] = m15["close"].ewm(span=20, adjust=False).mean()
    m15["ema50"] = m15["close"].ewm(span=50, adjust=False).mean()
    tr = pd.concat([
        (m15["high"] - m15["low"]),
        (m15["high"] - m15["close"].shift(1)).abs(),
        (m15["low"] - m15["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    m15["atr14"] = tr.rolling(14).mean()
    for c in ["ema8", "ema20", "ema50", "atr14", "open", "high", "low", "close"]:
        m15[f"{c}_lag"] = m15[c].shift(1)
    m15 = m15.dropna().reset_index(drop=True)
    # Merge prior-M15 onto M5
    m5_floor = m5["timestamp"].dt.floor("15min")
    ctx = m15.set_index("timestamp")
    ctx_aligned = ctx.reindex(m5_floor).reset_index(drop=True)
    m5 = pd.concat(
        [m5.reset_index(drop=True),
         ctx_aligned[["ema8_lag","ema20_lag","ema50_lag","atr14_lag","open_lag","high_lag","low_lag","close_lag"]]],
        axis=1,
    ).dropna(subset=["ema8_lag"]).reset_index(drop=True)
    m5["ny_hr"] = m5["timestamp"].dt.tz_convert("America/New_York").dt.hour
    m5["ny_min"] = m5["timestamp"].dt.tz_convert("America/New_York").dt.minute
    m5["ny_date"] = m5["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    m5["year"] = m5["timestamp"].dt.year
    return m5, m15


def detect_obs(m15: pd.DataFrame, atr_mult: float = 1.5) -> list[dict]:
    closes = m15["close"].values
    opens = m15["open"].values
    highs = m15["high"].values
    lows = m15["low"].values
    atr = m15["atr14"].values
    ts = m15["timestamp"].values
    obs = []
    for i in range(20, len(m15) - 3):
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        move_up = closes[i+3] - opens[i+1]
        if move_up >= atr_mult * atr[i] and closes[i] < opens[i]:
            obs.append({"side": 1, "top": float(highs[i]), "bot": float(lows[i]),
                        "confirmed_ts": ts[i+3]})
        move_dn = opens[i+1] - closes[i+3]
        if move_dn >= atr_mult * atr[i] and closes[i] > opens[i]:
            obs.append({"side": -1, "top": float(highs[i]), "bot": float(lows[i]),
                        "confirmed_ts": ts[i+3]})
    return obs


def generate_signals(obs, m5, *, expiry_bars: int = 192) -> pd.DataFrame:
    high = m5["high"].values
    low = m5["low"].values
    atr_lag = m5["atr14_lag"].values
    ts = m5["timestamp"].values
    signals = []
    for ob in obs:
        start = np.searchsorted(ts, np.datetime64(ob["confirmed_ts"]), side="right")
        end = min(len(m5), start + expiry_bars)
        for i in range(start, end):
            in_zone = False
            if ob["side"] == 1:
                if low[i] <= ob["top"] and high[i] >= ob["bot"]:
                    in_zone = True
            else:
                if high[i] >= ob["bot"] and low[i] <= ob["top"]:
                    in_zone = True
            if not in_zone:
                continue
            risk = atr_lag[i]
            if not np.isfinite(risk) or risk <= 0: break
            signals.append({"entry_index": i + 1, "side": ob["side"], "risk_units": float(risk)})
            break
    return pd.DataFrame(signals)


def run():
    print("loading BRENT...")
    m1 = load_brent()
    print(f"BRENT M1 bars: {len(m1):,}")
    m5, m15 = build_frames(m1)
    print(f"M5: {len(m5):,}  M15: {len(m15):,}")

    print()
    print("=" * 110)
    print("BRENT — M15 OB Retest sweep")
    print("=" * 110)
    print(f"Cost assumption: $0.05/risk (median BRENT spread ~$0.05)")
    print()

    for atr_mult in [1.5, 2.0]:
        obs = detect_obs(m15, atr_mult=atr_mult)
        print(f"ATR mult {atr_mult}: {len(obs)} OBs detected")

        for expiry in [96, 192, 384]:
            sig = generate_signals(obs, m5, expiry_bars=expiry)
            if len(sig) < 100:
                continue
            for tp in [2.0, 3.0, 4.0]:
                t = simulate(sig, m5, cost_usd=BRENT_COST_USD, tp_mult=tp)
                h = headline(t)
                label = f"BRENT OB ATR{atr_mult} exp{expiry} TP{tp}R"
                print_headline(label, h)
                persist("order_block", f"brent_atr{atr_mult}_exp{expiry}_tp{tp}", t,
                        notes=label, extra={"symbol": "BRENT", "cost_usd": BRENT_COST_USD})
            print()


if __name__ == "__main__":
    run()
