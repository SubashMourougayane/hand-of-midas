"""Detailed analysis of 2026 March-April-May trades — PLAIN-ENGLISH edition.

Pulls bt_trades for the window across baseline + PTP variants (XAU + EUR).
Reconstructs per-bar journey from raw OANDA M5 parquet.

Outputs:
  evidence/mar_apr_may_2026/
    trades_summary.csv       — one row per trade, friendly column names
    bar_walks.csv            — one row per (trade, bar) — full M5 journey
    monthly_breakdown.csv    — variant × month — friendly columns
    daily_breakdown.csv      — variant × day
    REPORT.md                — plain-english summary

Exit-reason cheat-sheet:
  TP        — full take-profit hit. Outcome = +target R (+ partial_R if PTP fired earlier).
  SL        — clean stop-loss, partial NEVER taken. Outcome = -1.0 R.
  SL_BE     — partial WAS taken, stop hit at break-even. Outcome = 0 on remainder + partial_R locked.
              For PTP+1R that's +0.5 R total. For PTP+2R that's +1.0 R total.
  TIMEOUT   — 72h max-hold reached. Outcome = close-vs-entry R (+ partial_R if taken).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from bt_engine.db.engine import make_engine


OUT = Path("/Users/subash/SUBASH/GoldDigger/bt_engine/evidence/mar_apr_may_2026")
DB_URL = os.environ.get("BT_ENGINE_DB_URL",
                        "postgresql+psycopg2://subash@localhost:5432/golddigger_bt")
WIN_START = pd.Timestamp("2026-03-01", tz="UTC")
WIN_END = pd.Timestamp("2026-06-01", tz="UTC")

XAU_M5 = Path("/tmp/oanda_xau_m5.parquet")
EUR_M5 = Path("/tmp/oanda_eur_m5.parquet")

STRATEGIES = (
    "fib_v2_xau_ensemble",
    "fib_v2_xau_ensemble_ptp1r",
    "fib_v2_xau_ensemble_ptp2r",
)

# Friendly names for output
NICE_NAME = {
    "fib_v2_xau_ensemble": "Baseline (no partial-TP)",
    "fib_v2_xau_ensemble_ptp1r": "PTP+1R (lock 0.5R at +1R MFE)",
    "fib_v2_xau_ensemble_ptp2r": "PTP+2R (lock 1.0R at +2R MFE)",
}


def load_trades(engine_db) -> pd.DataFrame:
    # Note: baseline evidence pack ran 6 variants (long, short, ensemble × symbols)
    # and tagged them all with strategy_id="fib_v2_xau_ensemble". We dedupe to the
    # ENSEMBLE-only rows by selecting one row per (entry_timestamp, symbol, side, leg)
    # for the baseline strategy. PTP variants ran ENSEMBLE only — no dedupe needed.
    sql = text("""
        WITH ranked AS (
            SELECT trade_id, trade_ref, strategy_id, symbol, side,
                   entry_timestamp, exit_timestamp, entry_price, exit_price,
                   stop_price, take_profit_price, risk_units,
                   bars_held, exit_reason, bracket_1r_outcome, cost_r, gross_r, net_r,
                   leg, regime, regime_at_entry, fib_diff, pivot_lb,
                   ext_target_pct, sl_buffer_pct,
                   partial_tp_at_r, partial_tp_pct, partial_taken, partial_r,
                   partial_fill_price, partial_fill_ts,
                   ROW_NUMBER() OVER (
                       PARTITION BY strategy_id, symbol, side, entry_timestamp, leg
                       ORDER BY trade_id
                   ) AS rn
            FROM bt_trades
            WHERE entry_timestamp >= :start AND entry_timestamp < :end
              AND strategy_id = ANY(:strats)
        )
        SELECT * FROM ranked WHERE rn = 1
        ORDER BY strategy_id, symbol, entry_timestamp
    """)
    with engine_db.connect() as conn:
        df = pd.read_sql(sql, conn, params={
            "start": WIN_START.to_pydatetime(),
            "end": WIN_END.to_pydatetime(),
            "strats": list(STRATEGIES),
        })
    for c in ("entry_timestamp", "exit_timestamp", "partial_fill_ts"):
        if c in df.columns and df[c].notna().any():
            df[c] = pd.to_datetime(df[c], utc=True)
    return df


def classify_outcome(row) -> str:
    """One-word plain-English outcome label."""
    r = row["exit_reason"]
    if r == "TP" and bool(row.get("partial_taken")):
        return "PARTIAL_THEN_TP"
    if r == "TP":
        return "TP_FULL"
    if r == "SL_BE":
        return "PARTIAL_THEN_BE"   # partial locked, stop hit at break-even
    if r == "SL":
        return "FULL_SL"           # clean loss, no partial taken
    if r == "TIMEOUT" and bool(row.get("partial_taken")):
        return "PARTIAL_THEN_TIMEOUT"
    if r == "TIMEOUT":
        return "TIMEOUT_NO_PARTIAL"
    return r or "UNKNOWN"


def load_m5(symbol: str) -> pd.DataFrame:
    path = XAU_M5 if "XAU" in symbol.upper() else EUR_M5
    df = pd.read_parquet(path)
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    return df.sort_values("timestamp").reset_index(drop=True)


def reconstruct_walks(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for sym in trades["symbol"].unique():
        m5 = load_m5(sym)
        m5 = m5[(m5["timestamp"] >= WIN_START - pd.Timedelta(days=5)) &
                (m5["timestamp"] < WIN_END + pd.Timedelta(days=10))].reset_index(drop=True)
        ts_arr = m5["timestamp"].values
        op_arr, hi_arr, lo_arr, cl_arr = (m5[c].values for c in ("open", "high", "low", "close"))

        sub = trades[trades["symbol"] == sym]
        for tr in sub.itertuples(index=False):
            entry_ts = pd.Timestamp(tr.entry_timestamp).to_datetime64()
            exit_ts = pd.Timestamp(tr.exit_timestamp).to_datetime64() if pd.notna(tr.exit_timestamp) else None
            start_idx = int(np.searchsorted(ts_arr, entry_ts, side="left"))
            end_idx = int(np.searchsorted(ts_arr, exit_ts, side="left")) if exit_ts is not None else start_idx + 100
            end_idx = min(end_idx + 1, len(m5))
            if start_idx >= len(m5):
                continue
            mfe = 0.0; mae = 0.0
            risk = float(tr.risk_units); entry_p = float(tr.entry_price); side = int(tr.side)
            ptp_trigger = tr.partial_tp_at_r if pd.notna(tr.partial_tp_at_r) else None
            partial_armed_emitted = False
            for k in range(start_idx, end_idx):
                bar_ts = ts_arr[k]
                o, h, l, c = float(op_arr[k]), float(hi_arr[k]), float(lo_arr[k]), float(cl_arr[k])
                if side > 0:
                    bar_mfe = (h - entry_p) / risk if risk > 0 else 0.0
                    bar_mae = (l - entry_p) / risk if risk > 0 else 0.0
                    unrealized = (c - entry_p) / risk if risk > 0 else 0.0
                else:
                    bar_mfe = (entry_p - l) / risk if risk > 0 else 0.0
                    bar_mae = (entry_p - h) / risk if risk > 0 else 0.0
                    unrealized = (entry_p - c) / risk if risk > 0 else 0.0
                mfe = max(mfe, bar_mfe); mae = min(mae, bar_mae)
                dist_stop_r = (float(tr.stop_price) - c) * side / risk if risk > 0 else 0.0
                dist_tp_r = (float(tr.take_profit_price) - c) * side / risk if pd.notna(tr.take_profit_price) and risk > 0 else None
                ptp_armed = 0
                if ptp_trigger is not None and not partial_armed_emitted and mfe >= float(ptp_trigger):
                    ptp_armed = 1; partial_armed_emitted = True
                rows.append({
                    "trade_id": str(tr.trade_id),
                    "trade_ref": tr.trade_ref,
                    "strategy_id": tr.strategy_id,
                    "symbol": tr.symbol, "side": side, "leg": tr.leg,
                    "bar_idx": k - start_idx,
                    "bar_ts": pd.Timestamp(bar_ts).tz_localize("UTC") if pd.Timestamp(bar_ts).tzinfo is None else pd.Timestamp(bar_ts),
                    "open": o, "high": h, "low": l, "close": c,
                    "bar_mfe_r": round(bar_mfe, 4),
                    "bar_mae_r": round(bar_mae, 4),
                    "running_mfe_r": round(mfe, 4),
                    "running_mae_r": round(mae, 4),
                    "unrealized_r_at_close": round(unrealized, 4),
                    "dist_to_stop_r_at_close": round(dist_stop_r, 4),
                    "dist_to_tp_r_at_close": round(dist_tp_r, 4) if dist_tp_r is not None else None,
                    "partial_armed_this_bar": ptp_armed,
                    "entry_price": entry_p,
                    "stop_price": float(tr.stop_price),
                    "tp_price": float(tr.take_profit_price) if pd.notna(tr.take_profit_price) else None,
                    "risk_units": risk,
                })
    return pd.DataFrame(rows)


def emit_monthly_clear(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per (strategy, symbol, month). PLAIN-ENGLISH column names."""
    if trades.empty:
        return pd.DataFrame()
    d = trades.copy()
    d["month"] = d["entry_timestamp"].dt.strftime("%Y-%m")
    d["outcome"] = d.apply(classify_outcome, axis=1)
    d["strategy"] = d["strategy_id"].map(NICE_NAME).fillna(d["strategy_id"])

    grp = d.groupby(["strategy", "symbol", "month"]).agg(
        total_trades=("net_r", "count"),
        wins=("net_r", lambda s: int((s > 0).sum())),
        net_R=("net_r", "sum"),
        sum_partial_R_locked=("partial_r", lambda s: float(s.fillna(0).sum())),
        full_TP=("outcome", lambda s: int((s == "TP_FULL").sum())),
        partial_then_TP=("outcome", lambda s: int((s == "PARTIAL_THEN_TP").sum())),
        partial_then_BE=("outcome", lambda s: int((s == "PARTIAL_THEN_BE").sum())),
        full_SL=("outcome", lambda s: int((s == "FULL_SL").sum())),
        partial_then_timeout=("outcome", lambda s: int((s == "PARTIAL_THEN_TIMEOUT").sum())),
        timeout_no_partial=("outcome", lambda s: int((s == "TIMEOUT_NO_PARTIAL").sum())),
        avg_bars_held=("bars_held", "mean"),
    ).reset_index()
    grp["win_rate_pct"] = (grp["wins"] / grp["total_trades"] * 100).round(2)
    grp["net_R"] = grp["net_R"].round(2)
    grp["sum_partial_R_locked"] = grp["sum_partial_R_locked"].round(2)
    grp["avg_bars_held"] = grp["avg_bars_held"].round(0).astype(int)
    # Reorder columns
    grp = grp[[
        "strategy", "symbol", "month",
        "total_trades", "wins", "win_rate_pct",
        "full_TP", "partial_then_TP", "partial_then_BE", "full_SL",
        "partial_then_timeout", "timeout_no_partial",
        "sum_partial_R_locked", "net_R", "avg_bars_held",
    ]]
    return grp


def emit_daily(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    d = trades.copy()
    d["day"] = d["entry_timestamp"].dt.strftime("%Y-%m-%d")
    d["strategy"] = d["strategy_id"].map(NICE_NAME).fillna(d["strategy_id"])
    grp = d.groupby(["strategy", "symbol", "day"]).agg(
        total_trades=("net_r", "count"),
        wins=("net_r", lambda s: int((s > 0).sum())),
        net_R=("net_r", "sum"),
    ).reset_index()
    grp["win_rate_pct"] = (grp["wins"] / grp["total_trades"] * 100).round(2)
    grp["net_R"] = grp["net_R"].round(3)
    return grp


def variant_headline(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per strategy_id: full 3-month summary."""
    rows = []
    for sid in trades["strategy_id"].unique():
        sub = trades[trades["strategy_id"] == sid]
        if sub.empty:
            continue
        wins = int((sub["net_r"] > 0).sum())
        gw = float(sub.loc[sub["net_r"] > 0, "net_r"].sum())
        gl = -float(sub.loc[sub["net_r"] < 0, "net_r"].sum())
        pf = gw / gl if gl > 0 else float("inf")
        avg_win = float(sub.loc[sub["net_r"] > 0, "net_r"].mean()) if wins > 0 else 0
        avg_loss_count = int((sub["net_r"] <= 0).sum())
        avg_loss = -float(sub.loc[sub["net_r"] < 0, "net_r"].mean()) if avg_loss_count > 0 else 0
        rr = avg_win / avg_loss if avg_loss > 0 else float("inf")
        out_counts = sub.apply(classify_outcome, axis=1).value_counts().to_dict()
        rows.append({
            "strategy": NICE_NAME.get(sid, sid),
            "total_trades": len(sub),
            "win_rate_pct": round(wins / len(sub) * 100, 2),
            "PF": round(pf, 2),
            "R:R": round(rr, 2),
            "net_R_3mo": round(float(sub["net_r"].sum()), 2),
            "partial_locked_R": round(float(sub["partial_r"].fillna(0).sum()), 2),
            "full_TP": out_counts.get("TP_FULL", 0),
            "partial_then_TP": out_counts.get("PARTIAL_THEN_TP", 0),
            "partial_then_BE": out_counts.get("PARTIAL_THEN_BE", 0),
            "full_SL": out_counts.get("FULL_SL", 0),
            "timeout": out_counts.get("TIMEOUT_NO_PARTIAL", 0) + out_counts.get("PARTIAL_THEN_TIMEOUT", 0),
        })
    return pd.DataFrame(rows)


def write_report(trades, monthly, headline) -> str:
    lines = []
    A = lines.append
    A("# 2026 Mar-Apr-May Trade Analysis — Plain English")
    A("")
    A(f"Window: **{WIN_START.date()} → {WIN_END.date()}** (3 months)")
    A(f"Strategies: baseline + PTP+1R + PTP+2R (same signals, different exit rules)")
    A(f"Symbols: XAUUSD.ecn + EURUSD.ecn")
    A(f"Total trade rows: **{len(trades):,}** (same signal fired across 3 strategy variants)")
    A("")
    A("---")
    A("")

    A("## How to read the exit outcomes")
    A("")
    A("Each closed trade falls into exactly one of these buckets:")
    A("")
    A("| Outcome | What happened | R-multiple result |")
    A("|---|---|---|")
    A("| `full_TP` | Price ran all the way to the +1.618 fib target. No partial booking happened first. | **+target R** (typically +5R to +10R) |")
    A("| `partial_then_TP` | Partial-TP fired (booked half at +1R or +2R MFE), then price kept going to target. | **+target R + locked partial R** (best case) |")
    A("| `partial_then_BE` | Partial-TP fired, stop moved to entry, then close hit break-even. Half position closed at +1R/+2R, other half at 0. | **+0.5R (PTP1) or +1.0R (PTP2)** |")
    A("| `full_SL` | Stop-loss hit. Partial-TP NEVER fired (MFE never reached trigger). Worst case. | **-1.0R** |")
    A("| `partial_then_timeout` | Partial-TP fired, then 72h time-stop kicked in at random close. | **close-vs-entry R + locked partial R** |")
    A("| `timeout_no_partial` | 72h time-stop at random close. No partial fired. | **close-vs-entry R** (usually small +/-) |")
    A("")
    A("**Key insight:** `partial_then_BE` is the safety net working. Setup failed (price came back) BUT we still walked away with +0.5R or +1.0R because we banked the partial before reversal.")
    A("")
    A("---")
    A("")

    A("## 3-Month Headline (each strategy)")
    A("")
    A("```")
    A(headline.to_string(index=False))
    A("```")
    A("")
    A("**Reading this:**")
    base = headline[headline["strategy"].str.startswith("Baseline")].iloc[0] if any(headline["strategy"].str.startswith("Baseline")) else None
    p1 = headline[headline["strategy"].str.startswith("PTP+1R")].iloc[0] if any(headline["strategy"].str.startswith("PTP+1R")) else None
    p2 = headline[headline["strategy"].str.startswith("PTP+2R")].iloc[0] if any(headline["strategy"].str.startswith("PTP+2R")) else None
    if base is not None and p1 is not None:
        A(f"- Baseline took **{int(base['total_trades'])}** trades, won **{base['win_rate_pct']}%** of them, "
          f"ended **{base['net_R_3mo']:+.1f}R** for the 3 months. PF={base['PF']:.2f}.")
        A(f"- PTP+1R took **{int(p1['total_trades'])}** trades (half of baseline because we only count distinct-strategy rows; "
          f"signals are SAME). Won **{p1['win_rate_pct']}%** counting partial-then-BE as wins. "
          f"Ended **{p1['net_R_3mo']:+.1f}R**. Of those, **{int(p1['partial_then_BE'])}** were rescued by partial-TP "
          f"(would have been full -1R losses without the safety net). Total partial profit locked: **+{p1['partial_locked_R']:.1f}R**.")
        A(f"- PTP+2R same signals, locked larger 1.0R per partial. **{p2['net_R_3mo']:+.1f}R** net. "
          f"Lower hit rate ({p2['win_rate_pct']}%) because trigger is harder to reach, but each partial worth 2x.")
    A("")

    A("## Why is this period bleeding?")
    A("")
    A("May 2026 was a hostile regime — almost all setups failed. Baseline took the full -1R loss on every fail. "
        "PTP variants softened it because price often spiked +1R favorably BEFORE failing.")
    A("")

    A("---")
    A("")
    A("## Monthly breakdown (variant × symbol × month)")
    A("")
    A("```")
    A(monthly.to_string(index=False))
    A("```")
    A("")
    A("---")
    A("")
    A("## Files in this folder")
    A("")
    A("- **trades_summary.csv** — one row per trade. Includes outcome, R-multiple, partial info, entry/exit prices.")
    A("- **bar_walks.csv** — one row per (trade × M5 bar). The full minute-by-minute journey of every trade.")
    A("  - Columns: bar_mfe_r, running_mfe_r, unrealized_r_at_close, dist_to_stop_r, dist_to_tp_r, partial_armed_this_bar.")
    A("- **monthly_breakdown.csv** — same data as the table above, sortable.")
    A("- **daily_breakdown.csv** — per-day totals if you want to drill into single days.")
    A("")
    A("---")
    A("")
    A("## How to look at a specific trade")
    A("")
    A("Pick a `trade_id` from trades_summary.csv. Filter bar_walks.csv by that trade_id to see every M5 bar from entry → exit.")
    A("")
    A("- `running_mfe_r` shows the highest favorable move so far. When this crosses 1.0 (PTP+1R) or 2.0 (PTP+2R), partial fires.")
    A("- `partial_armed_this_bar = 1` marks the exact bar where partial would have fired.")
    A("- `unrealized_r_at_close` shows the open P&L (in R) at end of that bar.")
    A("")
    return "\n".join(lines)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    engine_db = make_engine(DB_URL)
    print(f"[load] trades in [{WIN_START.date()} → {WIN_END.date()})")
    trades = load_trades(engine_db)
    print(f"  {len(trades):,} trades")
    if trades.empty:
        print("No trades."); return

    trades["outcome"] = trades.apply(classify_outcome, axis=1)
    trades["strategy"] = trades["strategy_id"].map(NICE_NAME).fillna(trades["strategy_id"])

    # Friendlier trades summary CSV
    nice_trades = trades[[
        "trade_id", "trade_ref", "strategy", "symbol", "leg", "side",
        "entry_timestamp", "exit_timestamp", "bars_held",
        "entry_price", "exit_price", "stop_price", "take_profit_price",
        "risk_units",
        "outcome", "exit_reason",
        "partial_tp_at_r", "partial_taken", "partial_r",
        "partial_fill_price", "partial_fill_ts",
        "bracket_1r_outcome", "cost_r", "net_r",
        "regime_at_entry", "fib_diff",
    ]].copy()
    nice_trades.columns = [
        "trade_id", "trade_ref", "strategy", "symbol", "leg", "side",
        "entry_ts", "exit_ts", "bars_held",
        "entry_price", "exit_price", "stop_price", "tp_price",
        "risk_units",
        "outcome", "raw_exit_reason",
        "partial_tp_trigger_R", "partial_taken", "partial_R_locked",
        "partial_fill_price", "partial_fill_ts",
        "outcome_R_total", "cost_R", "net_R",
        "regime_at_entry", "fib_diff",
    ]
    nice_trades.to_csv(OUT / "trades_summary.csv", index=False)
    print(f"saved trades_summary.csv ({len(nice_trades):,} rows)")

    monthly = emit_monthly_clear(trades)
    monthly.to_csv(OUT / "monthly_breakdown.csv", index=False)
    print(f"saved monthly_breakdown.csv ({len(monthly)} rows)")

    daily = emit_daily(trades)
    daily.to_csv(OUT / "daily_breakdown.csv", index=False)
    print(f"saved daily_breakdown.csv ({len(daily)} rows)")

    head = variant_headline(trades)
    head.to_csv(OUT / "variant_headline.csv", index=False)
    print(f"saved variant_headline.csv ({len(head)} rows)")

    print(f"[walks] reconstructing per-bar journey from raw M5...")
    walks = reconstruct_walks(trades)
    walks.to_csv(OUT / "bar_walks.csv", index=False)
    print(f"saved bar_walks.csv ({len(walks):,} bar-walks)")

    (OUT / "REPORT.md").write_text(write_report(trades, monthly, head))
    print(f"saved REPORT.md")


if __name__ == "__main__":
    main()
