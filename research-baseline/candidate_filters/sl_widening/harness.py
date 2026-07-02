"""SL Widening research harness — post-hoc M5 bracket replay.

Zero strategy code edits. Reads existing BT trades from run b6604240, then for
each candidate SL rule replays the SAME trade's bracket walk on raw M5 bars
using the new SL. Same TP, same partial-TP+1R (50%) logic, same time-in-trade.

Causality rule: D1_ATR14 for a trade with entry_ts T comes ONLY from D1 bars
whose bar_open_ts + 24h <= T. No look-ahead.

Rules tested:
  R0: baseline (as-is, sl_price from DB)
  R1: sl = pivot_L(H for short) - k * D1_ATR14, k in {0.25, 0.50, 0.75, 1.00}
  R2: sl = max_hybrid(sl_baseline, sl_L - k * D1_ATR14) — widen only if new is wider

Bracket walk semantics — copied from bt_engine/core/bracket.py:
  - SL hit (close-based): close <= sl (long) / close >= sl (short) → -1R on remainder + partial_r
  - TP hit: close >= tp (long) / close <= tp (short) → tp_R + partial_r
  - Partial TP+1R fires at MFE >= +1R → bank 0.5R, move SL to BE
  - After BE: SL_BE outcome = 0R on remainder + 0.5R partial
  - Max hold: use existing bars_held from BT as hold cap
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)
RUN_ID = "b6604240-14f4-464f-86b4-0d0e32755838"
M5_PATH = Path("/tmp/oanda_xau_m5.parquet")
OUT_DIR = Path(__file__).parent
COST_USD = 0.65


@dataclass
class TradeRow:
    trade_id: str
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    side: int
    leg: str
    entry_price: float
    stop_price: float
    take_profit: float
    risk_units: float
    bars_held: int
    fib_L: float
    fib_H: float
    fib_diff: float
    net_r_baseline: float
    exit_reason_baseline: str


def load_trades(eng) -> list[TradeRow]:
    q = text("""
        SELECT trade_id::text, entry_timestamp, exit_timestamp,
               side, leg, entry_price, stop_price, take_profit_price,
               risk_units, bars_held, net_r, exit_reason,
               (raw_features->>'fib_L')::numeric as fib_L,
               (raw_features->>'fib_H')::numeric as fib_H,
               (raw_features->>'fib_diff')::numeric as fib_diff
        FROM bt_trades WHERE run_id = :rid AND exit_timestamp IS NOT NULL
        ORDER BY entry_timestamp
    """)
    with eng.connect() as c:
        df = pd.read_sql(q, c, params={"rid": RUN_ID})
    trades = []
    for _, r in df.iterrows():
        trades.append(TradeRow(
            trade_id=str(r["trade_id"]),
            entry_ts=pd.Timestamp(r["entry_timestamp"]).tz_convert("UTC") if pd.Timestamp(r["entry_timestamp"]).tz is not None else pd.Timestamp(r["entry_timestamp"]).tz_localize("UTC"),
            exit_ts=pd.Timestamp(r["exit_timestamp"]).tz_convert("UTC") if pd.Timestamp(r["exit_timestamp"]).tz is not None else pd.Timestamp(r["exit_timestamp"]).tz_localize("UTC"),
            side=int(r["side"]),
            leg=str(r["leg"]),
            entry_price=float(r["entry_price"]),
            stop_price=float(r["stop_price"]),
            take_profit=float(r["take_profit_price"]),
            risk_units=float(r["risk_units"]),
            bars_held=int(r["bars_held"] or 0),
            fib_L=float(r["fib_l"]),
            fib_H=float(r["fib_h"]),
            fib_diff=float(r["fib_diff"]),
            net_r_baseline=float(r["net_r"] or 0.0),
            exit_reason_baseline=str(r["exit_reason"] or ""),
        ))
    return trades


def load_m5() -> pd.DataFrame:
    m5 = pd.read_parquet(M5_PATH)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return m5


def build_d1_atr(m5: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Build D1 ATR14 causally.

    Returns DataFrame with columns:
      - d1_open_ts (start of day)
      - d1_close_ts (d1_open_ts + 24h) — atr is only usable for trades with entry_ts >= this
      - atr14
    """
    d1 = (m5.set_index("timestamp")
              .resample("1D", label="left", closed="left")
              .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
              .dropna().reset_index())
    d1 = d1.rename(columns={"timestamp": "d1_open_ts"})
    if d1["d1_open_ts"].dt.tz is None:
        d1["d1_open_ts"] = d1["d1_open_ts"].dt.tz_localize("UTC")
    d1["prev_close"] = d1["close"].shift(1)
    trng = pd.concat([
        (d1["high"] - d1["low"]),
        (d1["high"] - d1["prev_close"]).abs(),
        (d1["low"] - d1["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    d1["atr14"] = trng.rolling(period, min_periods=period).mean()
    d1["d1_close_ts"] = d1["d1_open_ts"] + pd.Timedelta("1D")
    return d1.dropna(subset=["atr14"]).reset_index(drop=True)


def attach_atr_causal(trades: list[TradeRow], d1: pd.DataFrame) -> pd.DataFrame:
    """For each trade, pick D1 ATR14 from last D1 bar whose close_ts <= entry_ts."""
    d1_close = d1["d1_close_ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    d1_atr = d1["atr14"].to_numpy()
    out = []
    for t in trades:
        ts_np = t.entry_ts.tz_convert("UTC").tz_localize(None).to_datetime64()
        mask = d1_close <= ts_np
        if not mask.any():
            atr = np.nan
        else:
            idx = int(mask.sum() - 1)
            atr = float(d1_atr[idx])
        out.append({
            "trade_id": t.trade_id,
            "entry_ts": t.entry_ts,
            "d1_atr14": atr,
        })
    return pd.DataFrame(out)


def replay_bracket(
    m5_arr: dict,
    t: TradeRow,
    new_sl: float,
    partial_tp_at_r: float = 1.0,
    partial_tp_pct: float = 0.5,
) -> tuple[float, str, int]:
    """Replay one trade's bracket on M5 bars using new SL.

    m5_arr: dict with keys ts_naive/high/low/close — precomputed numpy arrays (hot path).
    """
    side = t.side
    entry = t.entry_price
    tp = t.take_profit
    risk = t.risk_units
    if risk <= 0:
        return 0.0, "NORISK", 0

    ts_naive = m5_arr["ts"]
    hi = m5_arr["high"]
    lo = m5_arr["low"]
    cl = m5_arr["close"]

    entry_np = t.entry_ts.tz_convert("UTC").tz_localize(None).to_datetime64()
    exit_np = t.exit_ts.tz_convert("UTC").tz_localize(None).to_datetime64()

    start_idx = int(np.searchsorted(ts_naive, entry_np, side="right"))  # bar STRICTLY after entry
    end_idx = int(np.searchsorted(ts_naive, exit_np, side="right"))     # up to exit inclusive
    end_idx = min(end_idx, len(ts_naive) - 1)

    partial_r = 0.0
    stop_price = new_sl
    stop_is_be = False
    bars_held = 0

    for i in range(start_idx, end_idx + 1):
        bars_held += 1
        close = float(cl[i])
        high = float(hi[i])
        low = float(lo[i])

        # MFE-based partial-TP trigger (uses high/low for intra-bar MFE)
        if partial_tp_at_r is not None and not stop_is_be:
            if side > 0:
                mfe = (high - entry) / risk
            else:
                mfe = (entry - low) / risk
            if mfe >= partial_tp_at_r:
                partial_r = partial_tp_at_r * partial_tp_pct
                stop_price = entry  # move SL to BE
                stop_is_be = True

        hit_stop = (side > 0 and close <= stop_price) or (side < 0 and close >= stop_price)
        hit_tp = (side > 0 and close >= tp) or (side < 0 and close <= tp)

        if hit_stop:
            r_remainder = 0.0 if stop_is_be else -1.0
            outcome_r = r_remainder + partial_r
            cost_r = COST_USD / risk if risk > 0 else 0.0
            return outcome_r - cost_r, "SL_BE" if stop_is_be else "SL", bars_held
        if hit_tp:
            tp_r_val = (tp - entry) * side / risk
            outcome_r = tp_r_val + partial_r
            cost_r = COST_USD / risk if risk > 0 else 0.0
            return outcome_r - cost_r, "TP", bars_held

    # Timeout — mark-to-market at end_idx close
    close = float(cl[end_idx])
    timeout_r = (close - entry) * side / risk
    outcome_r = timeout_r + partial_r
    cost_r = COST_USD / risk if risk > 0 else 0.0
    return outcome_r - cost_r, "TIMEOUT", bars_held


def new_sl_pivot_atr(t: TradeRow, atr: float, k: float) -> float:
    """SL = pivot_L (long) - k*ATR, or pivot_H (short) + k*ATR."""
    if t.side > 0:
        return t.fib_L - k * atr
    return t.fib_H + k * atr


def new_sl_hybrid(t: TradeRow, atr: float, k: float) -> float:
    """max_hybrid: widen only if ATR-scaled is wider than baseline."""
    atr_sl = new_sl_pivot_atr(t, atr, k)
    if t.side > 0:
        return min(t.stop_price, atr_sl)  # long: wider means lower
    return max(t.stop_price, atr_sl)      # short: wider means higher


def evaluate_rule(
    trades: list[TradeRow], atr_df: pd.DataFrame, m5_arr: dict,
    rule_name: str, rule_fn,
) -> pd.DataFrame:
    """Apply rule_fn to every trade; replay; return per-trade result."""
    atr_map = dict(zip(atr_df["trade_id"], atr_df["d1_atr14"]))
    rows = []
    t0 = time.time()
    for i, t in enumerate(trades):
        atr = atr_map.get(t.trade_id, np.nan)
        if np.isnan(atr):
            new_sl = t.stop_price  # no ATR available → fall back to baseline SL
            new_risk = t.risk_units
        else:
            new_sl = rule_fn(t, atr)
            new_risk = abs(t.entry_price - new_sl)
        # Wider SL means smaller position for constant-$-risk. Model B in production scales
        # position via risk_units → we CANNOT re-scale here per-trade because we lack the sizer state.
        # Instead: hold R denomination constant by using new_risk as the new denominator.
        # This means net_r reported is w.r.t. the WIDER stop, so 1R = new (larger) $ per trade.
        # Cross-rule comparison MUST be in $, not R.
        # ↳ For that we approximate $ = net_r * new_risk (assuming 1-unit qty).
        t_new = TradeRow(**{**t.__dict__, "stop_price": new_sl, "risk_units": max(new_risk, 0.01)})
        net_r, reason, bars = replay_bracket(m5_arr, t_new, new_sl)
        rows.append({
            "trade_id": t.trade_id,
            "entry_ts": t.entry_ts,
            "year": t.entry_ts.year,
            "leg": t.leg,
            "side": t.side,
            "d1_atr14": atr,
            "new_sl": new_sl,
            "new_risk": new_risk,
            "old_risk": t.risk_units,
            "net_r_new": net_r,
            "reason_new": reason,
            "bars_new": bars,
            "net_r_baseline": t.net_r_baseline,
            "reason_baseline": t.exit_reason_baseline,
        })
        if (i + 1) % 2000 == 0:
            elapsed = time.time() - t0
            print(f"  [{rule_name}] {i+1}/{len(trades)} done, {elapsed:.1f}s", flush=True)
    return pd.DataFrame(rows)


def headline(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    if n == 0:
        return {"label": label, "n": 0}
    # $ pnl per trade = net_r * new_risk (approx 1-unit qty). For comparison
    # against baseline we compute $ = baseline_net_r * old_risk.
    df = df.copy()
    df["pnl_new"] = df["net_r_new"] * df["new_risk"]
    df["pnl_base"] = df["net_r_baseline"] * df["old_risk"]
    n_win = int((df["net_r_new"] > 0).sum())
    wr = 100.0 * n_win / n
    profit = float(df.loc[df["net_r_new"] > 0, "pnl_new"].sum())
    loss = float(-df.loc[df["net_r_new"] <= 0, "pnl_new"].sum())
    pf = profit / loss if loss > 0 else float("inf")
    return {
        "label": label,
        "n": n,
        "wr": wr,
        "sum_r_new": float(df["net_r_new"].sum()),
        "sum_pnl_new": float(df["pnl_new"].sum()),
        "sum_pnl_base": float(df["pnl_base"].sum()),
        "delta_pnl": float(df["pnl_new"].sum() - df["pnl_base"].sum()),
        "pf": pf,
        "avg_risk_new": float(df["new_risk"].mean()),
        "avg_risk_base": float(df["old_risk"].mean()),
    }


def main():
    print(f"[{time.strftime('%H:%M:%S')}] loading trades + M5...", flush=True)
    eng = create_engine(DB_URL)
    trades = load_trades(eng)
    print(f"  {len(trades):,} trades loaded", flush=True)
    m5 = load_m5()
    print(f"  {len(m5):,} M5 bars loaded", flush=True)
    # Precompute numpy arrays ONCE — hot path avoids per-trade pandas ops.
    m5_arr = {
        "ts": m5["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(),
        "high": m5["high"].to_numpy(dtype=np.float64),
        "low": m5["low"].to_numpy(dtype=np.float64),
        "close": m5["close"].to_numpy(dtype=np.float64),
    }
    print(f"  m5_arr precomputed: ts_naive+high+low+close", flush=True)
    d1 = build_d1_atr(m5)
    print(f"  {len(d1):,} D1 bars with ATR14", flush=True)
    atr_df = attach_atr_causal(trades, d1)
    valid_atr = atr_df["d1_atr14"].notna().sum()
    print(f"  {valid_atr:,} / {len(atr_df):,} trades have causal ATR14", flush=True)

    # Baseline recompute — same SL as DB, sanity check the replay matches
    print(f"\n[{time.strftime('%H:%M:%S')}] BASELINE (replay w/ existing SL)", flush=True)
    df_base = evaluate_rule(trades, atr_df, m5_arr, "R0_baseline",
                             lambda t, atr: t.stop_price)
    df_base.to_parquet(OUT_DIR / "R0_baseline.parquet")
    print("  headline:", headline(df_base, "R0_baseline"), flush=True)

    # ATR-widening rules
    rules = [
        ("R1_k025", 0.25),
        ("R1_k050", 0.50),
        ("R1_k075", 0.75),
        ("R1_k100", 1.00),
    ]
    for name, k in rules:
        print(f"\n[{time.strftime('%H:%M:%S')}] {name} (SL = pivot ∓ {k}×D1_ATR14)", flush=True)
        df = evaluate_rule(trades, atr_df, m5_arr, name,
                            lambda t, atr, kk=k: new_sl_pivot_atr(t, atr, kk))
        df.to_parquet(OUT_DIR / f"{name}.parquet")
        print("  headline:", headline(df, name), flush=True)

    # Hybrid: max of baseline SL and ATR SL
    for name, k in [("R2_hybrid_k050", 0.50), ("R2_hybrid_k100", 1.00)]:
        print(f"\n[{time.strftime('%H:%M:%S')}] {name} (hybrid max({k}×ATR, baseline))", flush=True)
        df = evaluate_rule(trades, atr_df, m5_arr, name,
                            lambda t, atr, kk=k: new_sl_hybrid(t, atr, kk))
        df.to_parquet(OUT_DIR / f"{name}.parquet")
        print("  headline:", headline(df, name), flush=True)

    print(f"\n[{time.strftime('%H:%M:%S')}] DONE", flush=True)


if __name__ == "__main__":
    main()
