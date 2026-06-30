"""Test 10 safety nets against Fib V2 XAU ENSEMBLE baseline (20.3yr OANDA).

Baseline (no safety net): PF 1.31, MAR 0.41, WR 28%, 18/21 pos yrs, net +1108R.

Safety nets tested:
  1. breakeven move at +1R MFE
  2. partial TP 50% at +1R, runner to fib 1.618
  3. time-stop tighten to BE after 24h
  4. time-stop tighten to BE after 48h
  5. MAE-based: tighten to BE if MAE >= -0.3R AND 5+ bars elapsed
  6. vol filter: skip when D1 ATR > 1.5x rolling-60d median
  7. strong confirmation candle: body >= 40% range
  8. dual-TF regime: H1 close > H1 EMA50_lag for long (vice versa short)
  9. post-SL cooldown: skip same-day after 2 consecutive SLs
 10. daily loss cap: stop trading day at -3R cumulative

Output: CSV ranking + winner stack.
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.causal_sim import headline, print_headline
from research.fib_retrace.run_fib import build_h1_features
from research.fib_retrace.run_fib_v2 import build_pivot_events
from research.fib_retrace.run_fib_v2_21yr import load_oanda, add_m5_features
from research.fib_retrace.run_fib_v2_regime import (
    gen_signals_with_regime, resample_d1, add_d1_features, attach_d1_to_m5,
)


COST_USD = 0.30
MAX_HOLD_BARS = 72 * 12  # 864


def simulate_with_safety(
    m5: pd.DataFrame, sigs: pd.DataFrame, *,
    tp_mult_override: float | None = None,  # if set, override fixed TP with R-multiple
    cost_usd: float = COST_USD,
    horizon_bars: int = 72 * 12 * 2,
    # Safety nets:
    be_at_r: float | None = None,           # move SL to entry at +N R MFE
    partial_tp_at_r: float | None = None,    # take 50% at +N R; runner to fixed TP
    time_stop_be_hours: float | None = None, # after N hours, tighten SL to BE
    mae_be_threshold: float | None = None,   # if MAE >= threshold (e.g. -0.3) after 5 bars, tighten to BE
) -> pd.DataFrame:
    """Single-trade walker with optional safety-net layers.

    Returns same shape as simulate_fixed_tp: entry_ts, side, entry_price, stop_price,
    tp_price, risk_units, exit_index, bracket_r, cost_r, net_r, year.
    """
    op = m5["open"].values
    cl = m5["close"].values
    hi = m5["high"].values
    lo = m5["low"].values
    ts = m5["timestamp"].values
    yr = m5["year"].values
    n = len(m5)

    outs = []
    for sig in sigs.itertuples(index=False):
        i = int(sig.entry_index)
        side = int(sig.side)
        risk = float(sig.risk_units)
        original_stop = float(sig.stop_price)
        original_tp = float(sig.tp_price_fixed)
        entry = op[i]

        # Initialize active stop + TP (may move via safety nets).
        active_stop = original_stop
        active_tp = original_tp
        partial_taken = False
        partial_r = 0.0  # locked-in R from partial close

        end = min(n - 1, i + horizon_bars)
        outcome_r = 0.0
        exit_i = end
        broke = False

        for j in range(i, end + 1):
            c = cl[j]
            h = hi[j]
            l = lo[j]
            bars_elapsed = j - i
            # Current MFE/MAE in R.
            if side > 0:
                cur_mfe = (h - entry) / risk
                cur_mae = (l - entry) / risk
            else:
                cur_mfe = (entry - l) / risk
                cur_mae = (entry - h) / risk

            # --- SAFETY NET CHECKS (in order) ---
            # 1. Breakeven at +N R MFE.
            if be_at_r is not None and cur_mfe >= be_at_r and active_stop != entry:
                if side > 0 and active_stop < entry:
                    active_stop = entry
                elif side < 0 and active_stop > entry:
                    active_stop = entry

            # 2. Partial TP at +N R.
            if partial_tp_at_r is not None and not partial_taken and cur_mfe >= partial_tp_at_r:
                partial_taken = True
                # Lock 0.5 * partial_tp_at_r R (assume 50% closed at exactly +N R).
                partial_r = 0.5 * partial_tp_at_r
                # Move stop to BE on remaining 50%.
                if side > 0:
                    active_stop = max(active_stop, entry)
                else:
                    active_stop = min(active_stop, entry)

            # 3. Time-based BE.
            if time_stop_be_hours is not None and bars_elapsed >= time_stop_be_hours * 12:
                if side > 0 and active_stop < entry:
                    active_stop = entry
                elif side < 0 and active_stop > entry:
                    active_stop = entry

            # 4. MAE-based BE.
            if mae_be_threshold is not None and bars_elapsed >= 5 and cur_mae >= mae_be_threshold:
                if side > 0 and active_stop < entry:
                    active_stop = entry
                elif side < 0 and active_stop > entry:
                    active_stop = entry

            # --- EXIT CHECKS (close-based, matches research) ---
            if side > 0:
                if c <= active_stop:
                    # If BE hit: outcome = 0; else: standard -1R (if active_stop == original_stop)
                    if active_stop == entry:
                        outcome_r = 0.0
                    else:
                        # Close-based outcome for moved stops not == entry not common
                        outcome_r = (active_stop - entry) / risk
                    exit_i = j
                    broke = True
                    break
                if c >= active_tp:
                    outcome_r = (active_tp - entry) / risk
                    exit_i = j
                    broke = True
                    break
            else:
                if c >= active_stop:
                    if active_stop == entry:
                        outcome_r = 0.0
                    else:
                        outcome_r = (entry - active_stop) / risk
                    exit_i = j
                    broke = True
                    break
                if c <= active_tp:
                    outcome_r = (entry - active_tp) / risk
                    exit_i = j
                    broke = True
                    break

        if not broke:
            # Timeout exit at close.
            max_r = (active_tp - entry) * side / risk
            outcome_r = max(-1.0, min(max_r, side * (cl[exit_i] - entry) / risk))

        # Add partial-TP locked profit.
        outcome_r += partial_r

        outs.append({
            "entry_ts": ts[i], "side": side, "entry_price": entry,
            "stop_price": original_stop, "tp_price": original_tp,
            "risk_units": risk, "exit_index": exit_i,
            "bracket_r": outcome_r, "cost_r": cost_usd / risk,
            "net_r": outcome_r - cost_usd / risk,
            "year": yr[i],
        })
    return pd.DataFrame(outs)


def apply_strong_confirm_filter(m5: pd.DataFrame, sigs: pd.DataFrame, body_pct: float = 0.40) -> pd.DataFrame:
    """Filter signals where the confirmation bar (signal_idx-1, since entry_idx=k+1)
    had body >= body_pct of range."""
    if len(sigs) == 0:
        return sigs
    op = m5["open"].values
    cl = m5["close"].values
    hi = m5["high"].values
    lo = m5["low"].values
    keep_mask = []
    for sig in sigs.itertuples(index=False):
        confirm_idx = int(sig.entry_index) - 1
        if confirm_idx < 0:
            keep_mask.append(False); continue
        rng = hi[confirm_idx] - lo[confirm_idx]
        body = abs(cl[confirm_idx] - op[confirm_idx])
        ok = rng > 0 and body / rng >= body_pct
        keep_mask.append(ok)
    return sigs[pd.Series(keep_mask, index=sigs.index)].reset_index(drop=True)


def apply_volatility_filter(m5: pd.DataFrame, sigs: pd.DataFrame, vol_mult: float = 1.5) -> pd.DataFrame:
    """Skip entries when D1 ATR > vol_mult × rolling-60d median ATR."""
    if len(sigs) == 0 or "atr14_lag_d1" not in m5.columns:
        return sigs
    atr_arr = m5["atr14_lag_d1"].values
    # Compute rolling median by D1 — approximate via per-bar median over last 60 days * 288 bars
    # Faster: per row index. Just use rolling 60*288=17280 bars median.
    atr_median = pd.Series(atr_arr).rolling(17280, min_periods=288).median().values
    keep_mask = []
    for sig in sigs.itertuples(index=False):
        i = int(sig.entry_index)
        if i >= len(atr_arr): keep_mask.append(False); continue
        atr = atr_arr[i]
        med = atr_median[i]
        if not np.isfinite(atr) or not np.isfinite(med) or med <= 0:
            keep_mask.append(True); continue
        keep_mask.append(atr <= vol_mult * med)
    return sigs[pd.Series(keep_mask, index=sigs.index)].reset_index(drop=True)


def apply_cooldown_after_sls(trades: pd.DataFrame) -> pd.DataFrame:
    """After 2 consecutive SLs same day, drop further trades that day."""
    if len(trades) == 0:
        return trades
    df = trades.copy().sort_values("entry_ts").reset_index(drop=True)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["day"] = df["entry_ts"].dt.date
    df["is_sl"] = (df["bracket_r"] <= -0.95).astype(int)  # approx -1R
    keep_idx = []
    sl_count_today = 0
    cur_day = None
    for i, r in df.iterrows():
        if r["day"] != cur_day:
            cur_day = r["day"]
            sl_count_today = 0
        if sl_count_today >= 2:
            continue  # cooldown
        keep_idx.append(i)
        if r["is_sl"] == 1:
            sl_count_today += 1
    return df.loc[keep_idx].reset_index(drop=True)


def apply_daily_loss_cap(trades: pd.DataFrame, cap_r: float = -3.0) -> pd.DataFrame:
    """Drop trades after cumulative daily PnL goes below cap_r."""
    if len(trades) == 0:
        return trades
    df = trades.copy().sort_values("entry_ts").reset_index(drop=True)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["day"] = df["entry_ts"].dt.date
    keep_idx = []
    daily_pnl = 0.0
    cur_day = None
    for i, r in df.iterrows():
        if r["day"] != cur_day:
            cur_day = r["day"]
            daily_pnl = 0.0
        if daily_pnl <= cap_r:
            continue
        keep_idx.append(i)
        daily_pnl += float(r["net_r"])
    return df.loc[keep_idx].reset_index(drop=True)


def run_baseline(m5, pivot_events):
    """Reproduce baseline ENSEMBLE."""
    long_kw = dict(direction="long", session="all", max_hold_bars=MAX_HOLD_BARS,
                   ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bull_strong")
    short_kw = dict(direction="short", session="all", max_hold_bars=MAX_HOLD_BARS,
                    ext_target_pct=1.618, sl_buffer_pct=0.02, regime="bear_strong")
    long_sigs = gen_signals_with_regime(m5, pivot_events, **long_kw)
    short_sigs = gen_signals_with_regime(m5, pivot_events, **short_kw)
    return long_sigs, short_sigs


def main():
    print("[load] OANDA H1+M5...")
    h1, m5 = load_oanda(Path("/tmp/oanda_xau_h1.parquet"),
                        Path("/tmp/oanda_xau_m5.parquet"))
    h1 = build_h1_features(h1)
    m5_f = add_m5_features(m5)
    d1 = resample_d1(m5_f); d1 = add_d1_features(d1)
    m5_f = attach_d1_to_m5(m5_f, d1)
    pivot_events = build_pivot_events(h1, 5)
    print(f"  pivots: {len(pivot_events):,}")

    long_sigs, short_sigs = run_baseline(m5_f, pivot_events)
    print(f"  baseline sigs: long={len(long_sigs)}, short={len(short_sigs)}")

    results = []

    def run_and_record(label, lt, st, **kw_safety):
        # Run simulate_with_safety on each leg separately.
        long_trades = simulate_with_safety(m5_f, lt, **kw_safety) if len(lt) else pd.DataFrame()
        short_trades = simulate_with_safety(m5_f, st, **kw_safety) if len(st) else pd.DataFrame()
        ens = pd.concat([long_trades, short_trades], ignore_index=True)
        if len(ens) == 0:
            return
        h = headline(ens)
        sl_pct = (ens["bracket_r"] <= -0.95).mean() * 100
        tp_pct = (ens["bracket_r"] >= 0.9 * (ens["tp_price"] - ens["entry_price"]) * ens["side"] / ens["risk_units"]).mean() * 100
        results.append({
            "label": label,
            "n": h["n"],
            "net_R": h["net"],
            "PF": h["pf"],
            "WR%": h["wr"] * 100,
            "MAR": h["mar"],
            "pos_years": h["pos_years"],
            "SL%": sl_pct,
            "TP%": tp_pct,
            "max_R": ens["net_r"].max(),
            "min_R": ens["net_r"].min(),
        })
        print(f"  {label:<40s} n={h['n']:>5d} net={h['net']:>+7.1f}R PF={h['pf']:.2f} WR={h['wr']*100:.1f}% SL%={sl_pct:.1f}")
        return ens

    print("\n=== TESTING SAFETY NETS ===\n")

    # 0. Baseline.
    base = run_and_record("0. BASELINE (no safety net)", long_sigs, short_sigs)

    # 1. Breakeven at +1R.
    run_and_record("1. BE move at +1R MFE", long_sigs, short_sigs, be_at_r=1.0)

    # 1b. Breakeven at +0.5R, +2R.
    run_and_record("1b. BE at +0.5R", long_sigs, short_sigs, be_at_r=0.5)
    run_and_record("1c. BE at +2R", long_sigs, short_sigs, be_at_r=2.0)

    # 2. Partial TP at +1R, +2R.
    run_and_record("2. Partial TP 50% at +1R", long_sigs, short_sigs, partial_tp_at_r=1.0)
    run_and_record("2b. Partial TP 50% at +2R", long_sigs, short_sigs, partial_tp_at_r=2.0)

    # 3. Time-stop BE after 24h.
    run_and_record("3. Time-BE after 24h", long_sigs, short_sigs, time_stop_be_hours=24)
    run_and_record("3b. Time-BE after 48h", long_sigs, short_sigs, time_stop_be_hours=48)

    # 4. MAE-based BE.
    run_and_record("4. MAE>=−0.3R after 5 bars → BE", long_sigs, short_sigs, mae_be_threshold=-0.3)
    run_and_record("4b. MAE>=−0.5R after 5 bars → BE", long_sigs, short_sigs, mae_be_threshold=-0.5)

    # 5. Strong confirmation filter.
    long_strong = apply_strong_confirm_filter(m5_f, long_sigs, body_pct=0.40)
    short_strong = apply_strong_confirm_filter(m5_f, short_sigs, body_pct=0.40)
    print(f"  [filter] strong confirm reduced long {len(long_sigs)}→{len(long_strong)}, short {len(short_sigs)}→{len(short_strong)}")
    run_and_record("5. Strong confirm (body>=40%)", long_strong, short_strong)

    # 6. Volatility filter.
    long_vol = apply_volatility_filter(m5_f, long_sigs, vol_mult=1.5)
    short_vol = apply_volatility_filter(m5_f, short_sigs, vol_mult=1.5)
    print(f"  [filter] vol filter reduced long {len(long_sigs)}→{len(long_vol)}, short {len(short_sigs)}→{len(short_vol)}")
    run_and_record("6. Vol filter (D1 ATR<=1.5x med)", long_vol, short_vol)

    # 7. Cooldown after 2 SLs.
    base_cool = apply_cooldown_after_sls(base)
    h = headline(base_cool)
    results.append({
        "label": "7. Post-2-SL same-day cooldown",
        "n": h["n"], "net_R": h["net"], "PF": h["pf"],
        "WR%": h["wr"]*100, "MAR": h["mar"], "pos_years": h["pos_years"],
        "SL%": (base_cool["bracket_r"] <= -0.95).mean() * 100, "TP%": 0,
        "max_R": base_cool["net_r"].max(), "min_R": base_cool["net_r"].min(),
    })
    print(f"  7. cooldown after 2 SLs: n={h['n']} net={h['net']:+.1f}R PF={h['pf']:.2f}")

    # 8. Daily loss cap.
    base_cap = apply_daily_loss_cap(base, cap_r=-3.0)
    h = headline(base_cap)
    results.append({
        "label": "8. Daily loss cap -3R",
        "n": h["n"], "net_R": h["net"], "PF": h["pf"],
        "WR%": h["wr"]*100, "MAR": h["mar"], "pos_years": h["pos_years"],
        "SL%": (base_cap["bracket_r"] <= -0.95).mean() * 100, "TP%": 0,
        "max_R": base_cap["net_r"].max(), "min_R": base_cap["net_r"].min(),
    })
    print(f"  8. daily loss cap -3R: n={h['n']} net={h['net']:+.1f}R PF={h['pf']:.2f}")

    # 9. STACK: best filters + BE at 1R.
    run_and_record("9. STACK: strong confirm + BE +1R",
                    long_strong, short_strong, be_at_r=1.0)
    run_and_record("9b. STACK: strong confirm + Partial TP +1R",
                    long_strong, short_strong, partial_tp_at_r=1.0)

    # Final table.
    df = pd.DataFrame(results).sort_values("MAR", ascending=False)
    out = Path("/Users/subash/SUBASH/GoldDigger/research/fib_retrace/safety_net_results.csv")
    df.to_csv(out, index=False)
    print(f"\nSaved → {out}")
    print("\n[RANKED BY MAR]")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
