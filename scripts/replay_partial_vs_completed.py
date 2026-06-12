"""Historical replay: do partial-bar fires underperform completed-bar fires?

Runs the LIVE _run_micro_sweep_core function (dry_run=True) over historical
M3+H1+D bars, tick-by-tick at 3-minute resolution. For each fired signal:
  - Classify as "partial" (sweep H1 bar still open at fire time) or
    "completed" (sweep H1 bar already closed)
  - Forward-walk M3 to determine SL/TP/MAX_HOLD outcome
  - Record per-unit P&L and R-multiple

NO production code change. Pure historical replay using the live signal-gen
function as a black box.

Usage:
    python scripts/replay_partial_vs_completed.py
    python scripts/replay_partial_vs_completed.py --start 2010-01-01
    python scripts/replay_partial_vs_completed.py --start 2026-05-13  # last 30d

Output: scripts/output/fire_analysis.csv

Smoke test: with --start <30 days ago>, today's two live trades should
reproduce as fires (partial-type, since they fired before sweep H1 closed).
"""
from __future__ import annotations
import os
import sys
import csv
import argparse
import time as _time

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend-micro"))


# ──────────────────────────────────────────────────────────────────────────
# Stubs — make scheduler runnable without DB / broker / logger
# ──────────────────────────────────────────────────────────────────────────

import scanner.scheduler as sched  # noqa: E402


def _fake_execute(sql, params=None, fetch=False):
    """Stub the scheduler's DB calls. Returns 0/empty so all DB checks pass."""
    s = str(sql)
    if fetch and "COUNT(*)" in s:
        return [{"cnt": 0}]
    return [] if fetch else None


sched.execute = _fake_execute
sched.get_open_trades = lambda *a, **k: []

# Silence the structured logger — millions of debug calls would flood stdout
import scanner._log as _log  # noqa: E402
_log.debug = lambda *a, **k: None
_log.info = lambda *a, **k: None
_log.warn = lambda *a, **k: None
_log.error = lambda *a, **k: None
_log.exception = lambda *a, **k: None


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _isoZ(ts: pd.Timestamp) -> str:
    """Return ISO-8601 with Z suffix (matches live get_candles output)."""
    return ts.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _build_h1_records(h1_df: pd.DataFrame) -> list[dict]:
    """Convert H1 DataFrame to list-of-dicts the scheduler expects."""
    out = []
    for ts, row in h1_df.iterrows():
        out.append({
            "timestamp": _isoZ(ts),
            "_dt": ts,
            "bid_open": float(row["bid_open"]),
            "bid_high": float(row["bid_high"]),
            "bid_low": float(row["bid_low"]),
            "bid_close": float(row["bid_close"]),
            "ask_open": float(row["ask_open"]),
            "ask_high": float(row["ask_high"]),
            "ask_low": float(row["ask_low"]),
            "ask_close": float(row["ask_close"]),
            "volume": int(row.get("volume", 0)),
        })
    return out


def _build_d_records(d_df: pd.DataFrame) -> list[dict]:
    out = []
    for ts, row in d_df.iterrows():
        out.append({
            "timestamp": _isoZ(ts),
            "_dt": ts,
            "bid_open": float(row["bid_open"]),
            "bid_high": float(row["bid_high"]),
            "bid_low": float(row["bid_low"]),
            "bid_close": float(row["bid_close"]),
            "ask_open": float(row["ask_open"]),
            "ask_high": float(row["ask_high"]),
            "ask_low": float(row["ask_low"]),
            "ask_close": float(row["ask_close"]),
            "volume": int(row.get("volume", 0)),
        })
    return out


def _build_provisional_h1(m3_slice: pd.DataFrame, h1_open_start: pd.Timestamp) -> dict | None:
    """Aggregate M3 bars within the still-open H1 hour into a provisional H1 bar.
    Returns None if no M3 bars yet."""
    if len(m3_slice) == 0:
        return None
    return {
        "timestamp": _isoZ(h1_open_start),
        "_dt": h1_open_start,
        "bid_open": float(m3_slice["bid_open"].iloc[0]),
        "bid_high": float(m3_slice["bid_high"].max()),
        "bid_low": float(m3_slice["bid_low"].min()),
        "bid_close": float(m3_slice["bid_close"].iloc[-1]),
        "ask_open": float(m3_slice["ask_open"].iloc[0]),
        "ask_high": float(m3_slice["ask_high"].max()),
        "ask_low": float(m3_slice["ask_low"].min()),
        "ask_close": float(m3_slice["ask_close"].iloc[-1]),
        "volume": int(m3_slice["volume"].sum()) if "volume" in m3_slice.columns else 0,
    }


def _find_sweep_bar_ts(h1_visible: list[dict], sweep_wick: float, sweep_dir: str) -> pd.Timestamp | None:
    """Reverse-engineer the sweep H1 bar from the dry_run signal's sweep_wick.
    Searches newest-first (the sweep is usually recent)."""
    for c in reversed(h1_visible):
        mid_h = (c["bid_high"] + c["ask_high"]) / 2
        mid_l = (c["bid_low"] + c["ask_low"]) / 2
        if sweep_dir == "bullish" and abs(mid_l - sweep_wick) < 0.05:
            return c["_dt"]
        if sweep_dir == "bearish" and abs(mid_h - sweep_wick) < 0.05:
            return c["_dt"]
    return None


def _find_outcome(m3_arr_index, m3_arr_bidlow, m3_arr_bidhigh, m3_arr_asklow,
                  m3_arr_askhigh, m3_arr_bidclose, m3_arr_askclose,
                  fire_idx: int, direction: str, entry: float, sl: float, tp: float,
                  max_hold_bars: int = 80) -> tuple:
    """Walk M3 forward bar-by-bar (after the fire bar). Numpy-array based for speed.
    Returns (exit_reason, exit_price, exit_idx, bars_held)."""
    end_idx = min(len(m3_arr_index) - 1, fire_idx + max_hold_bars)
    for j in range(fire_idx + 1, end_idx + 1):
        if direction == "long":
            if m3_arr_bidlow[j] <= sl:
                return "SL", float(sl), j, j - fire_idx
            if m3_arr_bidhigh[j] >= tp:
                return "TP", float(tp), j, j - fire_idx
        else:
            if m3_arr_askhigh[j] >= sl:
                return "SL", float(sl), j, j - fire_idx
            if m3_arr_asklow[j] <= tp:
                return "TP", float(tp), j, j - fire_idx
    # MAX_HOLD: exit at last bar mid
    j = end_idx
    if j == fire_idx:
        return "NO_DATA", float(entry), fire_idx, 0
    exit_price = float((m3_arr_bidclose[j] + m3_arr_askclose[j]) / 2)
    return "MAX_HOLD", exit_price, j, j - fire_idx


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="ISO date, e.g. 2026-05-13. Default: last 30 days.")
    ap.add_argument("--end", default=None, help="ISO date, default: M3 last bar")
    ap.add_argument("--out", default=os.path.join(ROOT, "scripts/output/fire_analysis.csv"))
    args = ap.parse_args()

    print("Loading CSVs...")
    m3_df = pd.read_csv(os.path.join(ROOT, "data/raw/XAU_USD_M3.csv"))
    m3_df["timestamp"] = pd.to_datetime(m3_df["timestamp"], utc=True, format="mixed")
    m3_df = m3_df.set_index("timestamp").sort_index()
    print(f"  M3: {len(m3_df):,} bars, {m3_df.index[0]} → {m3_df.index[-1]}")

    h1_df = pd.read_csv(os.path.join(ROOT, "data/raw/XAU_USD_H1.csv"))
    h1_df["timestamp"] = pd.to_datetime(h1_df["timestamp"], utc=True, format="mixed")
    h1_df = h1_df.set_index("timestamp").sort_index()
    print(f"  H1: {len(h1_df):,} bars")

    d_df = pd.read_csv(os.path.join(ROOT, "data/raw/XAU_USD_D.csv"))
    d_df["timestamp"] = pd.to_datetime(d_df["timestamp"], utc=True, format="mixed")
    d_df = d_df.set_index("timestamp").sort_index()
    print(f"  D: {len(d_df):,} bars")

    # Date window
    end_ts = pd.Timestamp(args.end, tz="UTC") if args.end else m3_df.index[-1]
    start_ts = pd.Timestamp(args.start, tz="UTC") if args.start else (end_ts - pd.Timedelta(days=30))
    print(f"\nReplay window: {start_ts} → {end_ts}")

    # Slice m3 to replay window. Need pre-window M3 history for the "previous bar"
    # logic in engulfing detection (need ~50 M3 bars of lookback).
    pre_window_buffer = pd.Timedelta(hours=6)
    m3_replay = m3_df[(m3_df.index >= start_ts - pre_window_buffer) & (m3_df.index <= end_ts)]
    print(f"  M3 ticks in window: {len(m3_replay):,}")

    # Convert M3 to numpy arrays for fast forward-walk
    m3_arr_index = m3_replay.index.values
    m3_arr_bidlow = m3_replay["bid_low"].values
    m3_arr_bidhigh = m3_replay["bid_high"].values
    m3_arr_asklow = m3_replay["ask_low"].values
    m3_arr_askhigh = m3_replay["ask_high"].values
    m3_arr_bidclose = m3_replay["bid_close"].values
    m3_arr_askclose = m3_replay["ask_close"].values

    # Pre-build H1 and D record lists
    print("Building record caches...")
    h1_all = _build_h1_records(h1_df)
    d_all = _build_d_records(d_df)
    h1_dt_list = [r["_dt"] for r in h1_all]
    d_dt_list = [r["_dt"] for r in d_all]

    # Output
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    out_file = open(args.out, "w", newline="")
    writer = csv.writer(out_file)
    writer.writerow([
        "fire_ts", "sweep_bar_ts", "fire_type", "partial_minutes",
        "direction", "bias", "entry", "sl", "tp", "risk", "tp_distance",
        "sweep_wick", "consol_range",
        "exit_reason", "exit_price", "exit_ts", "bars_held",
        "pnl_per_unit", "r_multiple",
    ])

    # State management
    sched._traded_sweeps = {"date": None, "keys": set()}
    sched._daily_state = {"trades": 0, "date": None}
    sched._startup_cooldown_until = None

    # 5-min cooldown after each fire (mimics live's gd_signals cooldown query)
    last_fire_ts: pd.Timestamp | None = None

    current_date = None
    n_signals = 0
    n_partial = 0
    n_completed = 0
    t_start = _time.time()
    last_pct = -1
    total_ticks = len(m3_replay)

    print(f"\nReplaying {total_ticks:,} ticks...")
    for i in range(len(m3_arr_index)):
        tick = pd.Timestamp(m3_arr_index[i])
        if tick.tz is None:
            tick = tick.tz_localize("UTC")

        # Skip pre-window (only used as lookback)
        if tick < start_ts:
            continue

        # Reset daily state at midnight UTC
        if tick.date() != current_date:
            current_date = tick.date()
            sched._traded_sweeps = {"date": current_date, "keys": set()}
            sched._daily_state = {"trades": 0, "date": current_date}
            last_fire_ts = None

        # Active windows
        try:
            active = sched._get_active_windows(tick.to_pydatetime())
        except Exception:
            active = []
        if not active:
            continue

        # 5-min cooldown
        if last_fire_ts is not None and (tick - last_fire_ts).total_seconds() < 300:
            continue

        # Build h1_visible: completed H1 bars + provisional from M3
        h1_open_start = tick.floor("h")
        # bisect-style: first h1 index >= h1_open_start
        # h1_dt_list is sorted; use Python's bisect on a tz-aware list
        # Convert to a search using pd.Index
        # NB: this is the slow path; could be optimized with pd.Series.searchsorted
        lo, hi = 0, len(h1_dt_list)
        while lo < hi:
            mid = (lo + hi) // 2
            if h1_dt_list[mid] < h1_open_start:
                lo = mid + 1
            else:
                hi = mid
        h1_idx = lo
        h1_completed = h1_all[max(0, h1_idx - 60):h1_idx]

        # Provisional bar
        # m3 in [h1_open_start, tick]
        # Use array searchsorted
        m3_open_idx_start = m3_replay.index.searchsorted(h1_open_start, side="left")
        m3_in_open = m3_replay.iloc[m3_open_idx_start:i + 1]
        if len(m3_in_open) > 0:
            prov = _build_provisional_h1(m3_in_open, h1_open_start)
            h1_visible = h1_completed + [prov]
        else:
            h1_visible = h1_completed

        if len(h1_visible) < 6:
            continue

        # m3_visible: last 100 M3 bars
        m3_visible_df = m3_replay.iloc[max(0, i - 99):i + 1]
        if len(m3_visible_df) < 3:
            continue
        m3_visible = []
        for ts, row in m3_visible_df.iterrows():
            m3_visible.append({
                "timestamp": _isoZ(ts),
                "bid_open": float(row["bid_open"]),
                "bid_high": float(row["bid_high"]),
                "bid_low": float(row["bid_low"]),
                "bid_close": float(row["bid_close"]),
                "ask_open": float(row["ask_open"]),
                "ask_high": float(row["ask_high"]),
                "ask_low": float(row["ask_low"]),
                "ask_close": float(row["ask_close"]),
            })

        # Daily candles: 5 most-recent before today's date
        # Use bisect on d_dt_list against tick.normalize()
        today_floor = tick.normalize()
        lo, hi = 0, len(d_dt_list)
        while lo < hi:
            mid = (lo + hi) // 2
            if d_dt_list[mid] < today_floor:
                lo = mid + 1
            else:
                hi = mid
        d_idx = lo
        d_visible = d_all[max(0, d_idx - 5):d_idx]
        if len(d_visible) < 2:
            continue

        # Call live signal-gen
        try:
            sigs = sched._run_micro_sweep_core(
                now=tick.to_pydatetime(),
                active_windows=active,
                h1_candles=h1_visible,
                daily_candles=d_visible,
                m3_candles=m3_visible,
                dry_run=True,
            )
        except Exception:
            continue

        if not sigs:
            continue

        for sig in sigs:
            sweep_wick = sig.get("sweep_wick")
            sweep_dir_resolved = "bullish" if sig["direction"] == "long" else "bearish"
            sweep_bar_ts = _find_sweep_bar_ts(h1_visible, sweep_wick, sweep_dir_resolved)
            if sweep_bar_ts is None:
                continue

            sweep_close_ts = sweep_bar_ts + pd.Timedelta(hours=1)
            if tick < sweep_close_ts:
                fire_type = "partial"
                partial_minutes = -((sweep_close_ts - tick).total_seconds() / 60.0)
                n_partial += 1
            else:
                fire_type = "completed"
                partial_minutes = (tick - sweep_close_ts).total_seconds() / 60.0
                n_completed += 1

            # Forward-walk for outcome
            exit_reason, exit_price, exit_idx, bars_held = _find_outcome(
                m3_arr_index, m3_arr_bidlow, m3_arr_bidhigh,
                m3_arr_asklow, m3_arr_askhigh, m3_arr_bidclose, m3_arr_askclose,
                fire_idx=i,
                direction=sig["direction"],
                entry=float(sig["entry"]),
                sl=float(sig["sl"]),
                tp=float(sig["tp"]),
            )

            entry_p = float(sig["entry"])
            risk = abs(entry_p - float(sig["sl"]))
            tp_distance = abs(float(sig["tp"]) - entry_p)
            if sig["direction"] == "long":
                pnl_per_unit = exit_price - entry_p
            else:
                pnl_per_unit = entry_p - exit_price
            r_mult = pnl_per_unit / risk if risk > 0 else 0.0

            exit_ts_iso = pd.Timestamp(m3_arr_index[exit_idx]).isoformat() if exit_idx is not None else ""

            writer.writerow([
                tick.isoformat(),
                sweep_bar_ts.isoformat(),
                fire_type,
                f"{partial_minutes:.1f}",
                sig["direction"],
                sig.get("bias", ""),
                f"{entry_p:.2f}",
                f"{float(sig['sl']):.2f}",
                f"{float(sig['tp']):.2f}",
                f"{risk:.2f}",
                f"{tp_distance:.2f}",
                f"{sweep_wick:.2f}",
                f"{float(sig.get('consol_range', 0)):.2f}",
                exit_reason,
                f"{exit_price:.2f}",
                exit_ts_iso,
                bars_held,
                f"{pnl_per_unit:.2f}",
                f"{r_mult:.3f}",
            ])
            n_signals += 1
            last_fire_ts = tick

        if n_signals > 0 and n_signals % 50 == 0:
            out_file.flush()

        # Progress
        pct = int((i / total_ticks) * 100)
        if pct != last_pct and pct % 5 == 0:
            elapsed = _time.time() - t_start
            eta = elapsed / max(1, i + 1) * (total_ticks - i - 1)
            print(f"  {pct:3d}% | tick={tick} | sigs={n_signals} (P={n_partial} C={n_completed}) | "
                  f"elapsed={elapsed/60:.1f}m | ETA={eta/60:.1f}m")
            last_pct = pct

    out_file.close()
    elapsed = _time.time() - t_start
    print(f"\nDone. {n_signals} signals (partial={n_partial}, completed={n_completed}) "
          f"written to {args.out}")
    print(f"Runtime: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
