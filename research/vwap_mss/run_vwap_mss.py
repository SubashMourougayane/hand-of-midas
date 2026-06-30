"""Tom Crown VWAP-MSS strategy — causal port on XAUUSD.

Rules (literal Pine port + strict causality):
  1. VWAP_lag: cumsum(typ * vol) / cumsum(vol) per UTC day, shifted 1 bar (so at
     bar t we use VWAP computed THROUGH bar t-1 close).
  2. ATR_lag = ATR14 shifted 1.
  3. localHigh_lag = high.shift(1).rolling(swing).max(); localLow_lag same.
  4. Bias: prior_close vs vwap_lag (both lagged).
  5. Retest detection on bar t:
       Short: high_t >= vwap_lag AND open_t < vwap_lag AND
              close_t < vwap_lag + 0.25 * atr_lag
       Long: low_t <= vwap_lag AND open_t > vwap_lag AND
              close_t > vwap_lag - 0.25 * atr_lag
  6. Upon retest, ARM for `wait_window` bars.
     Short trigger: close[t+k] < localLow_lag[t] AND close[t+k] < close[t+k-1]
     Long trigger: close[t+k] > localHigh_lag[t] AND close[t+k] > close[t+k-1]
  7. ENTRY on NEXT bar OPEN after trigger candle closes.
  8. SL = localHigh + atr_lag * atr_mult (short) / localLow - atr_lag * atr_mult (long).
     (localHigh/Low captured at retest bar from PRIOR lagged values.)
  9. TP = RR * (entry - stop)*side.
 10. Invalidation: if bar high > armed_SL during wait, cancel.

Timeframe: configurable M5 or M15 (resample).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.harness.causal_sim import (  # noqa
    load_data, headline, persist, print_headline, gate, COST_USD
)


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    return (m1.set_index("timestamp")
            .resample(rule, label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"})
            .dropna().reset_index())


def build_features(df: pd.DataFrame, swing_lookback: int, atr_period: int = 14) -> pd.DataFrame:
    out = df.copy()
    out["ny_hr"] = out["timestamp"].dt.tz_convert("America/New_York").dt.hour
    out["ny_date"] = out["timestamp"].dt.tz_convert("America/New_York").dt.date.astype(str)
    out["utc_date"] = out["timestamp"].dt.tz_convert("UTC").dt.date.astype(str)
    out["year"] = out["timestamp"].dt.year

    typ = (out["high"] + out["low"] + out["close"]) / 3.0
    pv = typ * out["volume"]
    pv_cum = pv.groupby(out["utc_date"]).cumsum()
    v_cum = out["volume"].groupby(out["utc_date"]).cumsum()
    vwap_now = pv_cum / v_cum.replace(0, np.nan)
    out["vwap_lag"] = vwap_now.groupby(out["utc_date"]).shift(1)

    tr = pd.concat([
        (out["high"] - out["low"]),
        (out["high"] - out["close"].shift(1)).abs(),
        (out["low"] - out["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out["atr_lag"] = tr.rolling(atr_period).mean().shift(1)

    out["localHigh_lag"] = out["high"].shift(1).rolling(swing_lookback).max()
    out["localLow_lag"] = out["low"].shift(1).rolling(swing_lookback).min()

    out["close_lag"] = out["close"].shift(1)
    return out


def session_mask(ny_hr: np.ndarray, session: str) -> np.ndarray:
    if session == "all": return np.ones_like(ny_hr, dtype=bool)
    if session == "london": return (ny_hr >= 3) & (ny_hr < 12)
    if session == "ny": return (ny_hr >= 8) & (ny_hr < 17)
    if session == "overlap": return (ny_hr >= 8) & (ny_hr < 12)
    if session == "london_ny": return (ny_hr >= 3) & (ny_hr < 17)
    raise ValueError(session)


def gen_signals(
    df: pd.DataFrame, *, direction: str, session: str,
    retest_prox: float, atr_mult: float, wait_window: int,
) -> pd.DataFrame:
    """Returns DataFrame[entry_index, side, risk_units, stop_price, tp_R_mult=None].
    Will be combined with rr in simulate.
    """
    side = +1 if direction == "long" else -1
    op = df["open"].values
    hi = df["high"].values
    lo = df["low"].values
    cl = df["close"].values
    cl_lag = df["close_lag"].values
    vwap_lag = df["vwap_lag"].values
    atr_lag = df["atr_lag"].values
    lh_lag = df["localHigh_lag"].values
    ll_lag = df["localLow_lag"].values
    ny_hr = df["ny_hr"].values
    sess = session_mask(ny_hr, session)
    n = len(df)

    # bias on PRIOR close
    if side > 0:
        bias = cl_lag > vwap_lag
        retest = (lo <= vwap_lag) & (op > vwap_lag) & \
                 (cl > (vwap_lag - retest_prox * atr_lag)) & \
                 (cl < vwap_lag)  # close pulled back NEAR/below but not full break
    else:
        bias = cl_lag < vwap_lag
        retest = (hi >= vwap_lag) & (op < vwap_lag) & \
                 (cl < (vwap_lag + retest_prox * atr_lag)) & \
                 (cl > vwap_lag)  # mirror: close pulled up near but not breaking
    # Validity
    valid = np.isfinite(vwap_lag) & np.isfinite(atr_lag) & np.isfinite(lh_lag) & np.isfinite(ll_lag)
    retest_mask = retest & bias & sess & valid

    sig_rows = []
    last_day = ""
    days = df["ny_date"].values
    retest_idx = np.flatnonzero(retest_mask)
    for r_i in retest_idx:
        if r_i >= n - wait_window - 2:
            continue
        if days[r_i] == last_day:
            continue  # one setup per day per direction
        # Snapshot SL at retest bar
        if side > 0:
            stop = ll_lag[r_i] - atr_lag[r_i] * atr_mult
            local_break = lh_lag[r_i]
            if not np.isfinite(stop) or stop >= cl[r_i]:
                continue
        else:
            stop = lh_lag[r_i] + atr_lag[r_i] * atr_mult
            local_break = ll_lag[r_i]
            if not np.isfinite(stop) or stop <= cl[r_i]:
                continue
        if not np.isfinite(local_break):
            continue
        # Search forward wait_window bars for trigger
        triggered = -1
        for k in range(1, wait_window + 1):
            j = r_i + k
            if j >= n - 2:
                break
            # Invalidate if price hits SL before trigger
            if side > 0 and lo[j] <= stop:
                break
            if side < 0 and hi[j] >= stop:
                break
            # Trigger: close crosses local_break with momentum (close beyond + close > prior close direction)
            if side > 0:
                if cl[j] > local_break and cl[j] > cl[j - 1]:
                    triggered = j; break
            else:
                if cl[j] < local_break and cl[j] < cl[j - 1]:
                    triggered = j; break
        if triggered < 0:
            continue
        entry_idx = triggered + 1
        if entry_idx >= n - 2:
            continue
        entry_price = op[entry_idx]
        if side > 0:
            risk = entry_price - stop
        else:
            risk = stop - entry_price
        if risk <= 0 or not np.isfinite(risk):
            continue
        if risk > 0.01 * entry_price:
            continue
        last_day = days[r_i]
        sig_rows.append({"entry_index": int(entry_idx), "side": int(side),
                         "risk_units": float(risk), "stop_price": float(stop)})
    return pd.DataFrame(sig_rows) if sig_rows else pd.DataFrame(
        columns=["entry_index", "side", "risk_units", "stop_price"])


def simulate_rr(df: pd.DataFrame, sigs: pd.DataFrame, *, rr: float,
                horizon_bars: int, cost_usd: float = COST_USD) -> pd.DataFrame:
    op = df["open"].values; cl = df["close"].values; ts = df["timestamp"].values
    yr = df["year"].values
    n = len(df)
    outs = []
    for sig in sigs.itertuples(index=False):
        i = int(sig.entry_index)
        side = int(sig.side)
        risk = float(sig.risk_units)
        stop = float(sig.stop_price)
        entry = op[i]
        tp = entry + rr * risk * side
        end = min(n - 1, i + horizon_bars)
        outcome_r = 0.0; exit_i = end; broke = False
        for j in range(i, end + 1):
            c = cl[j]
            if side > 0:
                if c <= stop: outcome_r = -1.0; exit_i = j; broke=True; break
                if c >= tp:   outcome_r = rr; exit_i = j; broke=True; break
            else:
                if c >= stop: outcome_r = -1.0; exit_i = j; broke=True; break
                if c <= tp:   outcome_r = rr; exit_i = j; broke=True; break
        if not broke:
            outcome_r = max(-1.0, min(rr, side * (cl[exit_i] - entry) / risk))
        outs.append({"entry_ts": ts[i], "side": side, "entry_price": entry,
                     "stop_price": stop, "tp_price": tp, "risk_units": risk,
                     "exit_index": exit_i, "bracket_r": outcome_r,
                     "cost_r": cost_usd / risk,
                     "net_r": outcome_r - cost_usd / risk,
                     "year": yr[i]})
    return pd.DataFrame(outs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["1", "2"], default="1")
    args = ap.parse_args()

    print("[load] m1+m5 cached...")
    m1, m5, _ = load_data()
    print("[prep] M5 + M15 frames...")
    tf_frames = {"M5": m5, "M15": resample(m1, "15min")}
    for k, df in tf_frames.items():
        if "ny_hr" not in df.columns:
            df["ny_hr"] = df["timestamp"].dt.tz_convert("America/New_York").dt.hour
            df["year"] = df["timestamp"].dt.year

    all_rows = []

    if args.phase == "1":
        print("\n=== Phase 1: coarse sweep ===\n")
        # M5 grid
        for tf_name in ["M5", "M15"]:
            base = tf_frames[tf_name]
            for swing in [5]:
                feat = build_features(base, swing_lookback=swing)
                for direction in ["long", "short"]:
                    for session in ["all", "london", "ny", "london_ny", "overlap"]:
                        for atr_mult in [1.2]:
                            for retest_prox in [0.25]:
                                for wait in [5]:
                                    sigs = gen_signals(feat,
                                                       direction=direction, session=session,
                                                       retest_prox=retest_prox, atr_mult=atr_mult,
                                                       wait_window=wait)
                                    if len(sigs) == 0: continue
                                    horizon = 288 if tf_name == "M5" else 96
                                    for rr in [2.0, 3.0, 4.0]:
                                        trades = simulate_rr(feat, sigs, rr=rr, horizon_bars=horizon)
                                        if len(trades) == 0: continue
                                        h = headline(trades); g = gate(h)
                                        label = f"{direction}_{tf_name}_sw{swing}_sess{session}_atr{atr_mult}_prox{retest_prox}_wait{wait}_RR{rr}"
                                        all_rows.append({
                                            "tf": tf_name, "direction": direction, "session": session,
                                            "swing": swing, "atr_mult": atr_mult, "retest_prox": retest_prox,
                                            "wait": wait, "rr": rr, **h,
                                            **{f"gate_{k}": v for k, v in g.items()},
                                            "label": label,
                                        })
                                        if h["pf"] >= 1.3:
                                            print_headline(label, h)
                                            persist("vwap_mss", label, trades, notes="VWAP-MSS phase1")
    else:
        print("\n=== Phase 2: deep grid ===\n")
        for tf_name in ["M5", "M15"]:
            base = tf_frames[tf_name]
            for swing in [3, 5, 7, 10]:
                feat = build_features(base, swing_lookback=swing)
                for direction in ["long", "short"]:
                    for session in ["london", "ny", "london_ny", "overlap"]:
                        for atr_mult in [0.8, 1.2, 1.5, 2.0]:
                            for retest_prox in [0.25, 0.5, 1.0]:
                                for wait in [3, 5, 8]:
                                    sigs = gen_signals(feat,
                                                       direction=direction, session=session,
                                                       retest_prox=retest_prox, atr_mult=atr_mult,
                                                       wait_window=wait)
                                    if len(sigs) == 0: continue
                                    horizon = 288 if tf_name == "M5" else 96
                                    for rr in [2.0, 3.0, 4.0]:
                                        trades = simulate_rr(feat, sigs, rr=rr, horizon_bars=horizon)
                                        if len(trades) == 0: continue
                                        h = headline(trades); g = gate(h)
                                        label = f"{direction}_{tf_name}_sw{swing}_sess{session}_atr{atr_mult}_prox{retest_prox}_wait{wait}_RR{rr}"
                                        all_rows.append({
                                            "tf": tf_name, "direction": direction, "session": session,
                                            "swing": swing, "atr_mult": atr_mult, "retest_prox": retest_prox,
                                            "wait": wait, "rr": rr, **h,
                                            **{f"gate_{k}": v for k, v in g.items()},
                                            "label": label,
                                        })
                                        if h["pf"] >= 1.5 and "/" in h["pos_years"]:
                                            pos = int(h["pos_years"].split("/")[0])
                                            if pos >= 6:
                                                print_headline(label, h)
                                                persist("vwap_mss", label, trades, notes="VWAP-MSS phase2")

    if not all_rows:
        print("[NO ROWS]"); return
    lb = pd.DataFrame(all_rows)
    out_path = Path(f"/Users/subash/SUBASH/GoldDigger/research/vwap_mss/sweep_p{args.phase}.csv")
    lb.to_csv(out_path, index=False)
    print(f"\nSaved → {out_path}")
    top = lb.sort_values("mar", ascending=False).head(20)
    print("\n[TOP 20 by MAR]\n")
    cols = ["tf", "direction", "session", "swing", "atr_mult", "retest_prox",
            "wait", "rr", "n", "trades_per_year", "pf", "mar", "pos_years"]
    print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
