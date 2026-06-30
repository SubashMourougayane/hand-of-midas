"""Build static-file dashboard payloads.

Reads CSVs from `evidence/mar_apr_may_2026/` + queries DB `bt_trades.raw_features`
(JSONB) to extract the EXACT fib levels the engine used. Emits 5 `.js` files into
`evidence/mar_apr_may_2026/dashboard/data/`.

Output files (each loadable via <script src> under file://):
  trades.js     window.TRADES = [...]
  walks.js      window.WALKS = {trade_id: [bars]}
  monthly.js    window.MONTHLY = [...]
  daily.js      window.DAILY = [...]
  headline.js   window.HEADLINE = [...]

Usage:
  python scripts/build_dashboard.py
  python scripts/build_dashboard.py --evidence-dir /path/to/dir --out /path/to/dashboard/data
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from bt_engine.db.engine import make_engine


DEFAULT_EVIDENCE = Path("/Users/subash/SUBASH/GoldDigger/bt_engine/evidence/mar_apr_may_2026")
DEFAULT_OUT = DEFAULT_EVIDENCE / "dashboard" / "data"
DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)


def _jsonable(v):
    """Recursively coerce values into JSON-safe Python types."""
    if v is None:
        return None
    if isinstance(v, (str, bool)):
        return v
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        if pd.isna(v):
            return None
        return float(v)
    if isinstance(v, (pd.Timestamp,)):
        if pd.isna(v):
            return None
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return str(v)


def _emit_js(var_name: str, payload, out_path: Path) -> None:
    """Write `window.{var_name} = <json>;` to out_path."""
    body = json.dumps(_jsonable(payload), separators=(",", ":"), allow_nan=False)
    out_path.write_text(f"window.{var_name} = {body};\n")


def fetch_raw_features(trade_ids: list[str]) -> dict[str, dict]:
    """Pull raw_features JSONB for the given trade_ids. Returns {trade_id: dict}."""
    if not trade_ids:
        return {}
    engine_db = make_engine(DB_URL)
    sql = text("""
        SELECT trade_id, raw_features FROM bt_trades
        WHERE trade_id = ANY(CAST(:ids AS uuid[]))
    """)
    with engine_db.connect() as conn:
        rows = conn.execute(sql, {"ids": trade_ids}).fetchall()
    out = {}
    for trade_id, rf in rows:
        tid = str(trade_id)
        if rf is None:
            out[tid] = {}
        elif isinstance(rf, dict):
            out[tid] = rf
        else:
            try:
                out[tid] = json.loads(rf)
            except (TypeError, ValueError):
                out[tid] = {}
    return out


def build_trades(evidence_dir: Path) -> list[dict]:
    df = pd.read_csv(evidence_dir / "trades_summary.csv")
    # Pull raw_features for fib levels
    trade_ids = df["trade_id"].astype(str).tolist()
    rf_map = fetch_raw_features(trade_ids)

    rows = []
    for r in df.itertuples(index=False):
        tid = str(r.trade_id)
        rf = rf_map.get(tid, {})
        fib_L = rf.get("fib_L")
        fib_H = rf.get("fib_H")
        fib_diff = rf.get("fib_diff")
        fib_382 = rf.get("fib_382")
        fib_786 = rf.get("fib_786")
        fib_100 = rf.get("fib_100")
        # Best effort: derive missing keys from what we have
        if fib_diff is None and fib_L is not None and fib_H is not None:
            try:
                fib_diff = float(fib_H) - float(fib_L)
            except (TypeError, ValueError):
                fib_diff = None
        if fib_100 is None and fib_L is not None and r.side == 1:
            fib_100 = fib_L
        if fib_100 is None and fib_H is not None and r.side == -1:
            fib_100 = fib_H

        side = int(r.side)
        partial_trigger_r = (
            float(r.partial_tp_trigger_R)
            if not pd.isna(getattr(r, "partial_tp_trigger_R", None)) else None
        )
        risk_units = float(r.risk_units)
        entry_price = float(r.entry_price)
        ptp_trigger_price = None
        if partial_trigger_r is not None and risk_units > 0:
            ptp_trigger_price = entry_price + side * partial_trigger_r * risk_units

        rows.append({
            "trade_id": tid,
            "trade_ref": r.trade_ref,
            "strategy": r.strategy,
            "symbol": r.symbol,
            "leg": r.leg if not pd.isna(r.leg) else None,
            "side": side,
            "side_label": "LONG" if side > 0 else "SHORT",
            "entry_ts": r.entry_ts,
            "exit_ts": r.exit_ts if not pd.isna(r.exit_ts) else None,
            "bars_held": int(r.bars_held) if not pd.isna(r.bars_held) else None,
            "entry_price": entry_price,
            "exit_price": float(r.exit_price) if not pd.isna(r.exit_price) else None,
            "stop_price": float(r.stop_price),
            "tp_price": float(r.tp_price) if not pd.isna(r.tp_price) else None,
            "risk_units": risk_units,
            "outcome": r.outcome,
            "raw_exit_reason": r.raw_exit_reason if not pd.isna(r.raw_exit_reason) else None,
            "partial_trigger_r": partial_trigger_r,
            "partial_taken": bool(r.partial_taken) if not pd.isna(r.partial_taken) else False,
            "partial_r_locked": float(r.partial_R_locked) if not pd.isna(r.partial_R_locked) else 0.0,
            "partial_fill_price": float(r.partial_fill_price) if not pd.isna(r.partial_fill_price) else None,
            "partial_fill_ts": r.partial_fill_ts if not pd.isna(r.partial_fill_ts) else None,
            "ptp_trigger_price": ptp_trigger_price,
            "outcome_r_total": float(r.outcome_R_total) if not pd.isna(r.outcome_R_total) else 0.0,
            "cost_r": float(r.cost_R) if not pd.isna(r.cost_R) else 0.0,
            "net_r": float(r.net_R) if not pd.isna(r.net_R) else 0.0,
            "regime_at_entry": r.regime_at_entry if not pd.isna(r.regime_at_entry) else None,
            "fib_L": float(fib_L) if fib_L is not None else None,
            "fib_H": float(fib_H) if fib_H is not None else None,
            "fib_diff": float(fib_diff) if fib_diff is not None else None,
            "fib_382": float(fib_382) if fib_382 is not None else None,
            "fib_786": float(fib_786) if fib_786 is not None else None,
            "fib_100": float(fib_100) if fib_100 is not None else None,
        })
    return rows


def build_walks(evidence_dir: Path) -> dict[str, list[dict]]:
    df = pd.read_csv(evidence_dir / "bar_walks.csv")
    # Sort + group
    df = df.sort_values(["trade_id", "bar_idx"]).reset_index(drop=True)
    df["bar_ts"] = pd.to_datetime(df["bar_ts"], utc=True)
    # Epoch seconds for Lightweight Charts. Pandas tz-naive datetime64[us]
    # astype('int64') returns microseconds; divide by 1e6 to get seconds.
    df["t"] = (df["bar_ts"].dt.tz_convert("UTC").dt.tz_localize(None)
               .astype("int64") // 1_000_000).astype("int64")

    grouped: dict[str, list[dict]] = {}
    cols = ("t", "open", "high", "low", "close", "bar_mfe_r", "bar_mae_r",
            "running_mfe_r", "running_mae_r", "unrealized_r_at_close",
            "dist_to_stop_r_at_close", "dist_to_tp_r_at_close",
            "partial_armed_this_bar")
    for tid, sub in df.groupby("trade_id", sort=False):
        bars = []
        for r in sub.itertuples(index=False):
            bars.append({
                "t": int(r.t),
                "o": float(r.open), "h": float(r.high),
                "l": float(r.low), "c": float(r.close),
                "mfe": float(r.running_mfe_r),
                "mae": float(r.running_mae_r),
                "unr": float(r.unrealized_r_at_close),
                "ds": float(r.dist_to_stop_r_at_close),
                "dt": float(r.dist_to_tp_r_at_close) if not pd.isna(r.dist_to_tp_r_at_close) else None,
                "pa": int(r.partial_armed_this_bar),
            })
        grouped[str(tid)] = bars
    return grouped


def build_monthly(evidence_dir: Path) -> list[dict]:
    df = pd.read_csv(evidence_dir / "monthly_breakdown.csv")
    return [_jsonable(r._asdict()) for r in df.itertuples(index=False)]


def build_daily(evidence_dir: Path) -> list[dict]:
    df = pd.read_csv(evidence_dir / "daily_breakdown.csv")
    return [_jsonable(r._asdict()) for r in df.itertuples(index=False)]


def build_headline(evidence_dir: Path) -> list[dict]:
    df = pd.read_csv(evidence_dir / "variant_headline.csv")
    return [_jsonable(r._asdict()) for r in df.itertuples(index=False)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    evidence_dir = Path(args.evidence_dir)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[evidence] {evidence_dir}")
    print(f"[out] {out}")

    print("[trades]")
    trades = build_trades(evidence_dir)
    _emit_js("TRADES", trades, out / "trades.js")
    print(f"  {len(trades)} trades → trades.js ({(out / 'trades.js').stat().st_size / 1024:.1f} KB)")

    print("[walks]")
    walks = build_walks(evidence_dir)
    _emit_js("WALKS", walks, out / "walks.js")
    total_bars = sum(len(v) for v in walks.values())
    print(f"  {len(walks)} trades, {total_bars:,} bars → walks.js ({(out / 'walks.js').stat().st_size / (1024*1024):.1f} MB)")

    print("[monthly]")
    _emit_js("MONTHLY", build_monthly(evidence_dir), out / "monthly.js")

    print("[daily]")
    _emit_js("DAILY", build_daily(evidence_dir), out / "daily.js")

    print("[headline]")
    _emit_js("HEADLINE", build_headline(evidence_dir), out / "headline.js")

    print("Done.")


if __name__ == "__main__":
    main()
