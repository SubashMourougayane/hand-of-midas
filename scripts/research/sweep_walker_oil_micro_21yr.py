"""
Sweep Walker — Oil Micro M3 21yr research (v2).

Walks 21 years of Brent M3 data day-by-day. For each day, answers:

  Q1. Did production take a trade? If yes — outcome.
  Q2. Were there OTHER sweeps in the day that production missed?
  Q3. If production took no trade, were there MISSED OPPORTUNITIES that a
      looser sweep definition would have caught?
  Q4. On big-range days (top 20% of intraday volatility), how often does
      production catch the dominant sweep vs miss it?

NO fake numbers. NO phantom fills. Reuses production `_execute_trade` and
production `_slippage`. Same BE / SL ordering / fill semantics as live.

USAGE:
  python scripts/research/sweep_walker_oil_micro_21yr.py
  python scripts/research/sweep_walker_oil_micro_21yr.py --start 2020-01-01 --end 2020-12-31
  python scripts/research/sweep_walker_oil_micro_21yr.py --variants M3_ATR2.0_R50,H1_ATR2.0_R60

OUTPUT:
  scripts/output/sweep_walker_oil_micro_21yr.jsonl       (one row per day)
  scripts/output/sweep_walker_oil_micro_21yr_summary.csv (variant aggregates)
  Console: per-year + per-variant comparison + missed-opportunity table.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-oil-micro"))

from backtest.engine import (  # noqa: E402
    _execute_trade,
    _get_cached_data,
    _slippage,
    generate_signals as production_generate_signals,
)
from config import MICRO_ALPHA_SWEEP, ENGULFING_TOLERANCE  # noqa: E402


# ---------------------------------------------------------------------------
# Sweep events
# ---------------------------------------------------------------------------


@dataclass
class SweepEvent:
    sweep_idx: int       # global M3 frame index where the sweep was confirmed
    sweep_ts: pd.Timestamp
    direction: str       # "bullish" or "bearish"
    sweep_wick: float    # the wick high/low used as SL anchor
    sweep_ref: float     # the structural level (body close, ATR-band etc) for diagnostics
    variant: str
    notes: str = ""


# ---------------------------------------------------------------------------
# Variant detectors — each returns SweepEvent list for this day
# ---------------------------------------------------------------------------


def detect_m3_atr(day_m3: pd.DataFrame, m3_global_offset: int,
                  atr_period: int, atr_mult: float, retrace_pct: float,
                  variant_name: str) -> list[SweepEvent]:
    """M3 wick > N×ATR(M3, period) AND closes back inside (retrace_pct)."""
    n = len(day_m3)
    if n < atr_period + 2:
        return []

    h = day_m3["mid_high"].values
    l = day_m3["mid_low"].values
    c = day_m3["mid_close"].values
    o = day_m3["mid_open"].values
    pc = np.empty(n)
    pc[:] = np.nan
    pc[1:] = c[:-1]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = pd.Series(tr).rolling(atr_period, min_periods=atr_period).mean().values

    out: list[SweepEvent] = []
    body_top = np.maximum(o, c)
    body_bot = np.minimum(o, c)
    upper_wick = h - body_top
    lower_wick = body_bot - l

    for i in range(atr_period, n):
        a = atr[i]
        if not (a > 0):
            continue
        # Bearish wick: swept up + closed back down
        if upper_wick[i] > atr_mult * a:
            wick_size = upper_wick[i]
            wick_retrace = (h[i] - c[i]) / max(wick_size, 1e-9)
            if wick_retrace >= retrace_pct:
                out.append(SweepEvent(
                    sweep_idx=m3_global_offset + i,
                    sweep_ts=day_m3.index[i],
                    direction="bearish",
                    sweep_wick=float(h[i]),
                    sweep_ref=float(body_top[i]),
                    variant=variant_name,
                    notes=f"wick={wick_size:.2f} atr={a:.2f}",
                ))
        # Bullish wick: swept down + closed back up
        if lower_wick[i] > atr_mult * a:
            wick_size = lower_wick[i]
            wick_retrace = (c[i] - l[i]) / max(wick_size, 1e-9)
            if wick_retrace >= retrace_pct:
                out.append(SweepEvent(
                    sweep_idx=m3_global_offset + i,
                    sweep_ts=day_m3.index[i],
                    direction="bullish",
                    sweep_wick=float(l[i]),
                    sweep_ref=float(body_bot[i]),
                    variant=variant_name,
                    notes=f"wick={wick_size:.2f} atr={a:.2f}",
                ))
    return out


def detect_h1_atr(day_h1: pd.DataFrame, day_m3: pd.DataFrame,
                  full_h1_atr: pd.Series, m3_indexer: dict,
                  atr_mult: float, retrace_pct: float,
                  variant_name: str) -> list[SweepEvent]:
    """H1 wick > N×ATR(H1) AND closes back inside.
    Maps the H1 sweep to first M3 bar after it (so engulfing window starts
    on M3 bars, identical to how the production engine works after an H1
    sweep).
    """
    out: list[SweepEvent] = []
    for ts, bar in day_h1.iterrows():
        atr_val = full_h1_atr.get(ts, np.nan)
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        bo, bh, bl, bc = bar["mid_open"], bar["mid_high"], bar["mid_low"], bar["mid_close"]
        body_top = max(bo, bc)
        body_bot = min(bo, bc)
        upper_wick = bh - body_top
        lower_wick = body_bot - bl

        m3_after = day_m3[day_m3.index > ts]
        if m3_after.empty:
            continue
        global_idx = m3_indexer.get(m3_after.index[0])
        if global_idx is None:
            continue

        if upper_wick > atr_mult * atr_val:
            wick_retrace = (bh - bc) / max(upper_wick, 1e-9)
            if wick_retrace >= retrace_pct:
                out.append(SweepEvent(
                    sweep_idx=global_idx, sweep_ts=ts, direction="bearish",
                    sweep_wick=float(bh), sweep_ref=float(body_top),
                    variant=variant_name,
                    notes=f"upper_wick={upper_wick:.2f} atr_h1={atr_val:.2f}",
                ))
        if lower_wick > atr_mult * atr_val:
            wick_retrace = (bc - bl) / max(lower_wick, 1e-9)
            if wick_retrace >= retrace_pct:
                out.append(SweepEvent(
                    sweep_idx=global_idx, sweep_ts=ts, direction="bullish",
                    sweep_wick=float(bl), sweep_ref=float(body_bot),
                    variant=variant_name,
                    notes=f"lower_wick={lower_wick:.2f} atr_h1={atr_val:.2f}",
                ))
    return out


# ---------------------------------------------------------------------------
# Per-sweep entry simulation — REUSES production fill mechanics
# ---------------------------------------------------------------------------


@dataclass
class SimulatedTrade:
    sweep_variant: str
    direction: str
    sweep_ts: pd.Timestamp
    entry_idx: int
    entry: float
    sl: float
    tp: float
    risk: float
    exit_reason: str
    exit_price: float
    pnl_per_unit: float
    bars_held: int
    sweep_wick: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sweep_ts"] = self.sweep_ts.isoformat() if isinstance(self.sweep_ts, pd.Timestamp) else self.sweep_ts
        return d


def simulate_sweep_trade(oil_m3: pd.DataFrame, sweep: SweepEvent,
                         cfg: dict, sl_buffer: float, tp_multiplier: float,
                         use_break_even: bool, be_trigger_pct: float,
                         partial_tp_at_pct: float, partial_tp_size: float,
                         partial_arms_be: bool, max_bars: int,
                         skip_first_bar: bool, min_sl: float,
                         seed_int: int) -> Optional[SimulatedTrade]:
    """For a detected sweep, find an engulfing M3 bar then walk forward via
    production _execute_trade. Returns None if no engulfing in window or
    risk-too-small.
    """
    sweep_idx = sweep.sweep_idx
    if sweep_idx + max_bars >= len(oil_m3):
        return None

    eng_end_idx = min(sweep_idx + int(cfg["engulfing_window_hours"] * 60 / 3),
                      len(oil_m3) - 1)
    start_idx = sweep_idx + (2 if skip_first_bar else 1)

    for j in range(start_idx, eng_end_idx + 1):
        if j - 1 < 0:
            continue
        co = oil_m3["mid_open"].iat[j]
        cc = oil_m3["mid_close"].iat[j]
        po = oil_m3["mid_open"].iat[j - 1]
        pc = oil_m3["mid_close"].iat[j - 1]
        br = oil_m3["mid_high"].iat[j] - oil_m3["mid_low"].iat[j]
        ct, cb = max(co, cc), min(co, cc)
        pt, pb = max(po, pc), min(po, pc)
        tol = ENGULFING_TOLERANCE

        if sweep.direction == "bullish":
            if not (cc > co and cb <= pb + tol and ct >= pt - tol):
                continue
            np.random.seed(seed_int)
            entry = oil_m3["ask_close"].iat[j] + _slippage(br)
            slv = sweep.sweep_wick - sl_buffer
            risk = entry - slv
            if risk < min_sl:
                slv = entry - min_sl
                risk = min_sl
            tpv = entry + risk * tp_multiplier
            direction = "long"
        else:
            if not (cc < co and cb <= pb + tol and ct >= pt - tol):
                continue
            np.random.seed(seed_int)
            entry = oil_m3["bid_close"].iat[j] - _slippage(br)
            slv = sweep.sweep_wick + sl_buffer
            risk = slv - entry
            if risk < min_sl:
                slv = entry + min_sl
                risk = min_sl
            tpv = entry - risk * tp_multiplier
            direction = "short"

        if risk < 0.01:
            continue

        np.random.seed(seed_int + 1)
        result = _execute_trade(
            oil_m3, j, entry, slv, tpv, direction, max_bars,
            use_break_even=use_break_even,
            be_trigger_pct=be_trigger_pct,
            trail_after_be_pct=0.0,
            partial_tp_at_pct=partial_tp_at_pct,
            partial_tp_size=partial_tp_size,
            partial_arms_be=partial_arms_be,
            entry_mode="market",
        )
        if result is None:
            continue
        return SimulatedTrade(
            sweep_variant=sweep.variant,
            direction=direction,
            sweep_ts=sweep.sweep_ts,
            entry_idx=j,
            entry=float(entry),
            sl=float(slv),
            tp=float(tpv),
            risk=float(risk),
            exit_reason=result.get("exit_reason", "?"),
            exit_price=float(result.get("exit_price", entry)),
            pnl_per_unit=float(result.get("pnl_per_unit", 0.0)),
            bars_held=int(result.get("bars_held", 0)),
            sweep_wick=float(sweep.sweep_wick),
        )
    return None


# ---------------------------------------------------------------------------
# ATR helpers
# ---------------------------------------------------------------------------


def _h1_atr_series(h1: pd.DataFrame, period: int = 14) -> pd.Series:
    h = h1["mid_high"]
    l = h1["mid_low"]
    c = h1["mid_close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _daily_atr(daily_high: pd.Series, daily_low: pd.Series,
               daily_close: pd.Series, period: int = 14) -> pd.Series:
    pc = daily_close.shift(1)
    tr = pd.concat([daily_high - daily_low,
                    (daily_high - pc).abs(),
                    (daily_low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2005-01-01")
    parser.add_argument("--end", default="2026-12-31")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-trades-per-day", type=int, default=10,
                        help="Cap per-day per-variant. Production caps at 3.")
    parser.add_argument("--variants", default="all",
                        help="Comma-separated subset (e.g. 'M3_ATR2.0_R50')")
    parser.add_argument("--output-dir", default="scripts/output")
    parser.add_argument("--no-jsonl", action="store_true",
                        help="Skip per-day JSONL output (huge for 21yr)")
    args = parser.parse_args()

    print(f"  Loading Brent data...")
    data = _get_cached_data()
    oil_h1: pd.DataFrame = data["oil_h1"]
    oil_m3: pd.DataFrame = data["oil_m3"]

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1)
    oil_h1 = oil_h1[(oil_h1.index >= start) & (oil_h1.index < end)]
    oil_m3 = oil_m3[(oil_m3.index >= start) & (oil_m3.index < end)]
    if len(oil_h1) == 0:
        print(f"  ERROR: no H1 data in range {args.start} → {args.end}")
        print(f"  CSV data range: see backtest/engine.py _load_candles")
        sys.exit(1)
    print(f"  Bars: H1={len(oil_h1):,} M3={len(oil_m3):,}")
    print(f"  Range: {oil_h1.index[0]} → {oil_h1.index[-1]}")

    m3_indexer: dict[pd.Timestamp, int] = {ts: i for i, ts in enumerate(oil_m3.index)}
    h1_atr = _h1_atr_series(oil_h1, period=14)

    # ---- Production replay (single pass over full frame) ----
    print(f"  Running production strategy replay...")
    t0 = time.time()
    all_dates = sorted(set(oil_h1.index.date))
    bias_dict = {d: "neutral" for d in all_dates}
    prod_signals = production_generate_signals(oil_h1, oil_m3, bias_dict)
    prod_by_date: dict[date, list] = {}
    for s in prod_signals:
        d = s.date.date() if hasattr(s.date, "date") else s.date
        prod_by_date.setdefault(d, []).append(s)
    print(f"  Production replay: {len(prod_signals):,} signals in {time.time()-t0:.1f}s")

    cfg = MICRO_ALPHA_SWEEP
    print(f"  Simulating production signals through fill model...")
    prod_trades_by_date: dict[date, list[dict]] = {}
    t0 = time.time()
    for d, sigs in prod_by_date.items():
        for s in sigs:
            try:
                idx = oil_m3.index.get_loc(s.date)
            except KeyError:
                continue
            np.random.seed(args.seed + 1)
            result = _execute_trade(
                oil_m3, idx, s.entry, s.sl, s.tp,
                "long" if s.direction == "long" else "short",
                cfg["max_bars"],
                use_break_even=True,
                be_trigger_pct=cfg.get("be_trigger_pct", 0.5),
                partial_tp_at_pct=cfg.get("partial_tp_at_pct", 0.0),
                partial_tp_size=cfg.get("partial_tp_size", 0.0),
                partial_arms_be=cfg.get("partial_arms_be", False),
                entry_mode="market",
            )
            if result is None:
                continue
            prod_trades_by_date.setdefault(d, []).append({
                "direction": s.direction,
                "entry": float(s.entry),
                "sl": float(s.sl),
                "tp": float(s.tp),
                "risk": float(s.risk),
                "exit_price": float(result["exit_price"]),
                "pnl_per_unit": float(result["pnl_per_unit"]),
                "exit_reason": result["exit_reason"],
                "bars_held": int(result["bars_held"]),
            })
    print(f"  Simulated {sum(len(v) for v in prod_trades_by_date.values())} production trades in {time.time()-t0:.1f}s")

    # ---- Variants ----
    all_variants = [
        {"name": "M3_ATR1.5_R50", "kind": "m3_atr", "atr": 1.5, "retrace": 0.50, "atr_period": 14},
        {"name": "M3_ATR2.0_R50", "kind": "m3_atr", "atr": 2.0, "retrace": 0.50, "atr_period": 14},
        {"name": "M3_ATR2.5_R60", "kind": "m3_atr", "atr": 2.5, "retrace": 0.60, "atr_period": 14},
        {"name": "M3_ATR3.0_R70", "kind": "m3_atr", "atr": 3.0, "retrace": 0.70, "atr_period": 14},
        {"name": "H1_ATR1.5_R50", "kind": "h1_atr", "atr": 1.5, "retrace": 0.50},
        {"name": "H1_ATR2.0_R60", "kind": "h1_atr", "atr": 2.0, "retrace": 0.60},
    ]
    if args.variants != "all":
        wanted = set(args.variants.split(","))
        all_variants = [v for v in all_variants if v["name"] in wanted]
    print(f"  Variants: {[v['name'] for v in all_variants]}")

    # ---- Aggregator ----
    def _new_agg() -> dict:
        return {"sweeps_total": 0, "trades_taken": 0, "wins": 0, "losses": 0,
                "scratches": 0, "pnl_total": 0.0, "by_year": {},
                "days_with_sweep": 0, "days_no_prod_trade_but_sweep": 0,
                "days_no_prod_trade_and_caught": 0,
                "days_no_prod_trade_and_caught_pnl": 0.0}
    agg = {v["name"]: _new_agg() for v in all_variants}
    agg["production"] = _new_agg()

    # ---- Open output streams ----
    out_jsonl_path = os.path.join(args.output_dir,
                                  "sweep_walker_oil_micro_21yr.jsonl")
    os.makedirs(args.output_dir, exist_ok=True)
    print(f"  Output: {out_jsonl_path}{' (skipped via --no-jsonl)' if args.no_jsonl else ''}")
    f_out = None if args.no_jsonl else open(out_jsonl_path, "w")
    print()

    n_days = len(all_dates)
    progress_every = max(1, n_days // 50)
    rows_written = 0
    t0 = time.time()

    for day_i, d in enumerate(all_dates):
        if day_i % progress_every == 0:
            elapsed = time.time() - t0
            rate = (day_i + 1) / max(elapsed, 0.1)
            eta = (n_days - day_i - 1) / max(rate, 0.1)
            print(f"  [{day_i+1}/{n_days}] {d} · rate={rate:.1f}d/s · eta={eta:.0f}s", flush=True)

        day_h1 = oil_h1[oil_h1.index.date == d]
        day_m3 = oil_m3[oil_m3.index.date == d]
        if len(day_h1) < 6 or len(day_m3) < 100:
            continue

        scan_window_m3 = day_m3[(day_m3.index.hour >= 8) & (day_m3.index.hour < 23)]
        if scan_window_m3.empty:
            continue
        intraday_high = float(scan_window_m3["mid_high"].max())
        intraday_low = float(scan_window_m3["mid_low"].min())
        intraday_range = intraday_high - intraday_low

        first_m3_ts = day_m3.index[0]
        m3_global_offset = m3_indexer[first_m3_ts]

        # Production results for this day
        prod_trades = prod_trades_by_date.get(d, [])
        prod_pnl = sum(t["pnl_per_unit"] for t in prod_trades)
        prod_wins = sum(1 for t in prod_trades if t["pnl_per_unit"] > 0)
        prod_losses = sum(1 for t in prod_trades if t["pnl_per_unit"] < 0)
        prod_scratches = sum(1 for t in prod_trades if t["pnl_per_unit"] == 0)
        agg["production"]["sweeps_total"] += len(prod_trades)
        agg["production"]["trades_taken"] += len(prod_trades)
        agg["production"]["wins"] += prod_wins
        agg["production"]["losses"] += prod_losses
        agg["production"]["scratches"] += prod_scratches
        agg["production"]["pnl_total"] += prod_pnl
        ya = agg["production"]["by_year"].setdefault(d.year,
            {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        ya["trades"] += len(prod_trades); ya["wins"] += prod_wins
        ya["losses"] += prod_losses; ya["pnl"] += prod_pnl

        prod_took_trade = len(prod_trades) > 0

        # Per-variant
        sweeps_by_variant: dict[str, list] = {}
        trades_by_variant: dict[str, list] = {}
        for v in all_variants:
            try:
                if v["kind"] == "m3_atr":
                    sweeps = detect_m3_atr(
                        day_m3, m3_global_offset,
                        atr_period=v["atr_period"], atr_mult=v["atr"],
                        retrace_pct=v["retrace"], variant_name=v["name"],
                    )
                else:  # h1_atr
                    sweeps = detect_h1_atr(
                        day_h1, day_m3, h1_atr, m3_indexer,
                        atr_mult=v["atr"], retrace_pct=v["retrace"],
                        variant_name=v["name"],
                    )
            except Exception as e:
                print(f"    [{v['name']}] {d} ERROR: {e}", flush=True)
                continue

            agg[v["name"]]["sweeps_total"] += len(sweeps)
            if len(sweeps) > 0:
                agg[v["name"]]["days_with_sweep"] += 1
                if not prod_took_trade:
                    agg[v["name"]]["days_no_prod_trade_but_sweep"] += 1
            sweeps_by_variant[v["name"]] = [
                {"ts": s.sweep_ts.isoformat() if hasattr(s.sweep_ts, "isoformat") else str(s.sweep_ts),
                 "dir": s.direction, "wick": s.sweep_wick, "ref": s.sweep_ref,
                 "notes": s.notes}
                for s in sweeps
            ]

            seen_keys = set()
            taken: list[SimulatedTrade] = []
            day_v_pnl = 0.0
            for s in sweeps:
                if len(taken) >= args.max_trades_per_day:
                    break
                key = (s.sweep_ts.replace(second=0, microsecond=0), s.direction)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                trade = simulate_sweep_trade(
                    oil_m3, s, cfg,
                    sl_buffer=cfg["sl_buffer"], tp_multiplier=cfg["tp_multiplier"],
                    use_break_even=True,
                    be_trigger_pct=cfg.get("be_trigger_pct", 0.5),
                    partial_tp_at_pct=cfg.get("partial_tp_at_pct", 0.0),
                    partial_tp_size=cfg.get("partial_tp_size", 0.0),
                    partial_arms_be=cfg.get("partial_arms_be", False),
                    max_bars=cfg["max_bars"],
                    skip_first_bar=cfg.get("skip_first_bar", True),
                    min_sl=cfg.get("min_sl", 0.10),
                    seed_int=args.seed + day_i,
                )
                if trade is None:
                    continue
                taken.append(trade)
                day_v_pnl += trade.pnl_per_unit
                agg[v["name"]]["trades_taken"] += 1
                if trade.pnl_per_unit > 0: agg[v["name"]]["wins"] += 1
                elif trade.pnl_per_unit < 0: agg[v["name"]]["losses"] += 1
                else: agg[v["name"]]["scratches"] += 1
                agg[v["name"]]["pnl_total"] += trade.pnl_per_unit
                ya = agg[v["name"]]["by_year"].setdefault(d.year,
                    {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
                ya["trades"] += 1
                if trade.pnl_per_unit > 0: ya["wins"] += 1
                elif trade.pnl_per_unit < 0: ya["losses"] += 1
                ya["pnl"] += trade.pnl_per_unit

            # Track: when production took NO trade but variant DID — what's the variant's PnL?
            if not prod_took_trade and len(taken) > 0:
                agg[v["name"]]["days_no_prod_trade_and_caught"] += 1
                agg[v["name"]]["days_no_prod_trade_and_caught_pnl"] += day_v_pnl

            trades_by_variant[v["name"]] = [t.to_dict() for t in taken]

        # Write per-day row
        if f_out:
            row = {
                "date": str(d),
                "year": d.year,
                "intraday_high": intraday_high,
                "intraday_low": intraday_low,
                "intraday_range": round(intraday_range, 4),
                "production": {
                    "n_trades": len(prod_trades),
                    "wins": prod_wins, "losses": prod_losses, "scratches": prod_scratches,
                    "pnl_per_unit": round(prod_pnl, 4),
                    "trades": prod_trades,
                },
                "variants": {
                    name: {
                        "n_sweeps": len(sweeps_by_variant.get(name, [])),
                        "n_trades_taken": len(trades_by_variant.get(name, [])),
                        "sweeps": sweeps_by_variant.get(name, []),
                        "trades": trades_by_variant.get(name, []),
                    }
                    for name in [v["name"] for v in all_variants]
                },
            }
            f_out.write(json.dumps(row, default=str) + "\n")
            rows_written += 1

    if f_out:
        f_out.close()
    elapsed = time.time() - t0

    # ---- Summary ----
    print()
    print("=" * 100)
    print(f"  DONE — {n_days} days walked in {elapsed:.0f}s ({n_days/max(elapsed,1):.1f} days/sec)")
    if f_out:
        print(f"  JSONL: {out_jsonl_path}")
    print("=" * 100)
    print()
    print("Per-variant aggregate (whole period):")
    print(f"  {'Variant':<25s} {'Sweeps':>9s} {'Trades':>8s} {'Wins':>6s} {'Losses':>7s} "
          f"{'WR%':>6s} {'TotPnL/u':>11s} {'Avg/Tr':>8s}  {'NoProd→Caught':>14s} {'PnL_when_caught':>16s}")
    print(f"  {'-'*25} {'-'*9} {'-'*8} {'-'*6} {'-'*7} {'-'*6} {'-'*11} {'-'*8}  {'-'*14} {'-'*16}")
    for name, a in agg.items():
        if a["trades_taken"] == 0:
            wr = 0; avg = 0
        else:
            wr = 100 * a["wins"] / max(a["wins"] + a["losses"], 1)
            avg = a["pnl_total"] / a["trades_taken"]
        print(f"  {name:<25s} {a['sweeps_total']:>9,d} {a['trades_taken']:>8,d} "
              f"{a['wins']:>6,d} {a['losses']:>7,d} {wr:>5.1f}% "
              f"{a['pnl_total']:>11,.2f} {avg:>8,.4f}  "
              f"{a['days_no_prod_trade_and_caught']:>14,d} "
              f"{a['days_no_prod_trade_and_caught_pnl']:>16,.2f}")
    print()
    print("Reading guide:")
    print("  - 'production' = live engine replay (what we actually trade today).")
    print("  - 'M3_ATR*' / 'H1_ATR*' = LOOSER sweep definitions; bigger Sweeps")
    print("    count, but compare TotPnL/u to production to see if quality holds.")
    print("  - 'NoProd→Caught' = days production took NO trade but this variant")
    print("    DID find a trade. KEY METRIC for 'are we missing setups on quiet")
    print("    days?'")
    print("  - 'PnL_when_caught' = total per-unit P&L on those NoProd days.")
    print("    Positive number = real missed-opportunity. Negative = we'd have")
    print("    LOST money trading those — strategy is right to skip them.")
    print()

    # ---- Per-year ----
    print("Per-year P&L per unit (col format: pnl(trades)):")
    years = sorted(set().union(*[a["by_year"].keys() for a in agg.values()]))
    variant_names = ["production"] + [v["name"] for v in all_variants]
    header = f"  {'Year':<6s}"
    for name in variant_names:
        header += f" {name[:18]:>20s}"
    print(header)
    for y in years:
        row = f"  {y:<6d}"
        for name in variant_names:
            ya = agg[name]["by_year"].get(y, {"pnl": 0.0, "trades": 0})
            row += f" {ya['pnl']:>11,.2f}({ya['trades']:>4,d})"
        print(row)

    # ---- CSV summary ----
    csv_path = os.path.join(args.output_dir,
                            "sweep_walker_oil_micro_21yr_summary.csv")
    with open(csv_path, "w") as f:
        f.write("variant,sweeps_total,trades_taken,wins,losses,scratches,"
                "win_rate_pct,total_pnl_per_unit,avg_pnl_per_trade,"
                "days_with_sweep,days_no_prod_trade_but_sweep,"
                "days_no_prod_trade_and_caught,days_no_prod_trade_and_caught_pnl\n")
        for name, a in agg.items():
            if a["trades_taken"] == 0:
                wr = 0; avg = 0
            else:
                wr = 100 * a["wins"] / max(a["wins"] + a["losses"], 1)
                avg = a["pnl_total"] / a["trades_taken"]
            f.write(f"{name},{a['sweeps_total']},{a['trades_taken']},"
                    f"{a['wins']},{a['losses']},{a['scratches']},"
                    f"{wr:.2f},{a['pnl_total']:.4f},{avg:.4f},"
                    f"{a['days_with_sweep']},{a['days_no_prod_trade_but_sweep']},"
                    f"{a['days_no_prod_trade_and_caught']},"
                    f"{a['days_no_prod_trade_and_caught_pnl']:.4f}\n")
    print(f"\n  Summary CSV: {csv_path}")

    # ---- Bottom-line interpretation ----
    print()
    print("=" * 100)
    print("BOTTOM LINE")
    print("=" * 100)
    prod_total = agg["production"]["pnl_total"]
    prod_trades_n = agg["production"]["trades_taken"]
    print(f"  Production: {prod_trades_n:,} trades, total PnL/unit = {prod_total:+,.2f}")
    print()
    print("  Per variant — DAYS WHERE PRODUCTION TOOK NO TRADE BUT VARIANT DID:")
    print("  (these are the truly missed setups — a positive PnL_when_caught means")
    print("   the variant would have made money on days production sat out)")
    print()
    for v in all_variants:
        a = agg[v["name"]]
        d_caught = a["days_no_prod_trade_and_caught"]
        pnl_caught = a["days_no_prod_trade_and_caught_pnl"]
        d_swept = a["days_no_prod_trade_but_sweep"]
        if d_caught == 0:
            avg = 0
        else:
            avg = pnl_caught / d_caught
        print(f"    {v['name']:<25s}  caught {d_caught:>5,d} days  "
              f"PnL/unit {pnl_caught:>+10,.2f}  avg/day {avg:>+7.3f}  "
              f"(out of {d_swept:,} days swept)")
    print()
    print("  CAVEAT: This is research only. Even a profitable variant here is NOT")
    print("  shippable without project-filter-sweep-workflow validation:")
    print("  multi-seed, yearly slice, DD stress, parity-harness check.")


if __name__ == "__main__":
    main()
