"""Oil Micro Alpha-Sweep — single source of truth for signal generation.

Extracted from `backend-oil-micro/backtest/engine.py` (Phase 5.1 of refactor
plan REFACTOR_PLAN_LIVE_BT_UNIFY.md). BT engine and live scheduler now
import `generate_signals` from this module — no parallel reimplementation.

Strategy: rolling 4hr consolidation windows every 2hr on H1, sweep + M3
engulfing reversal on BCO_USD. Same DNA as Gold Micro
(backend/strategies/micro_alpha_sweep.py); different config thresholds.

Behaviour preserved exactly from the inline `engine.py` implementation:
the function returns the same Signal list bit-for-bit. Phase 0 baseline
tests verify this. NO logic changes in Phase 5.1 — extraction only.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from backend.strategies.base import Signal
from config import MICRO_ALPHA_SWEEP, ENGULFING_TOLERANCE


def _slippage(bar_range: float) -> float:
    return 0.03 + bar_range * 0.01 + np.random.uniform(0, 0.005)


def _hours_in_range(start: int, end: int) -> set:
    if start < end:
        return set(range(start, end))
    return set(range(start, 24)) | set(range(0, end))


def _hour_past(current: int, target: int) -> bool:
    diff = (current - target) % 24
    return 0 < diff <= 12


def generate_signals(oil_h1: pd.DataFrame, oil_m3: pd.DataFrame, daily_bias: dict) -> list[Signal]:
    """Generate Oil Micro Alpha-Sweep signals using rolling 4hr windows."""
    cfg = MICRO_ALPHA_SWEEP
    close_start = cfg["market_close_start"]
    signals = []

    dates = sorted(set(oil_h1.index.date))

    for date in dates:
        day_h1 = oil_h1[oil_h1.index.date == date]
        # Phase 5.5 — removed `if len(day_h1) < 6: continue`. Was a guard
        # against thin BT historical days but blocked live signals before
        # 6 H1 bars accumulated mid-day (e.g. 04:18 SHORT can't fire until
        # 06:03 cron has 6 bars closed, by which time the staleness window
        # has expired). Downstream `len(consol) < 2` and `len(m3_window) < 3`
        # already gate insufficient-data cases robustly.

        bias = daily_bias.get(date, "neutral")
        # Cap rework Jun 18: signal-gen no longer caps at max_trades_per_day.
        # Caller (execution loop) caps on FILLED trades only — matches live
        # behavior post-cap-fix where LIMIT_TTL_EXPIRED doesn't count.
        traded_sweeps = set()

        for bar_ts, bar in day_h1.iterrows():
            now_hour = bar_ts.hour

            if cfg["market_close_start"] <= now_hour < cfg["market_close_end"]:
                continue

            for start_hour in range(0, 24, cfg["scan_gap_hours"]):
                end_hour = (start_hour + cfg["consol_hours"]) % 24
                scan_end_hour = (start_hour + cfg["consol_hours"] + cfg["scan_after_hours"]) % 24

                consol_hours = _hours_in_range(start_hour, end_hour)
                if close_start in consol_hours:
                    continue

                if not _hour_past(now_hour, end_hour):
                    continue

                if _hour_past(now_hour, scan_end_hour):
                    continue

                # Gate consol by index <= bar_ts (current iteration). Prevents
                # lookahead: at outer bar_ts=03:00, consol must NOT include
                # 22:00, 23:00 of the same date (those bars haven't formed
                # yet). scan_bars already had this gate (line 98). consol
                # was missing it — silent BT lookahead bug discovered
                # 2026-06-19 during Phase 5.5 parity drill-down.
                consol = day_h1[(day_h1.index.hour.isin(consol_hours))
                                & (day_h1.index <= bar_ts)]
                if len(consol) < 2:
                    continue

                range_high = consol["mid_high"].max()
                range_low = consol["mid_low"].min()
                consol_range = range_high - range_low
                if consol_range < cfg["min_range"]:
                    continue

                bearish_level = range_high + cfg["sweep_threshold"]
                bullish_level = range_low - cfg["sweep_threshold"]

                scan_hours = _hours_in_range(end_hour, scan_end_hour)
                scan_bars = day_h1[(day_h1.index.hour.isin(scan_hours)) & (day_h1.index <= bar_ts)]

                for sbar_ts, sb in scan_bars.iterrows():
                    sweep_dir = None
                    sweep_wick = None
                    if sb["mid_high"] > bearish_level and sb["mid_close"] < range_high:
                        sweep_dir = "bearish"
                        sweep_wick = sb["mid_high"]
                    elif sb["mid_low"] < bullish_level and sb["mid_close"] > range_low:
                        sweep_dir = "bullish"
                        sweep_wick = sb["mid_low"]

                    if not sweep_dir:
                        continue

                    sk = (sbar_ts, start_hour)
                    if sk in traded_sweeps:
                        continue

                    if bias != "neutral":
                        if sweep_dir == "bullish" and bias != "bullish":
                            continue
                        if sweep_dir == "bearish" and bias != "bearish":
                            continue

                    # Phase 4 parity contract: m3_window must contain the FULL
                    # expected bar count. If short, skip without consuming
                    # sweep (BT has full history; live retries next cron when
                    # more M3 bars arrive). Discovered Phase 4 / Gold Micro
                    # 06-12 21:33 vs 21:45 mismatch — applies here too.
                    eng_end = sbar_ts + timedelta(hours=cfg["engulfing_window_hours"])
                    m3_window = oil_m3[(oil_m3.index > sbar_ts) & (oil_m3.index <= eng_end)]
                    expected_m3_bars = int(cfg["engulfing_window_hours"] * 20)  # 20 bars/hr at M3
                    if len(m3_window) < expected_m3_bars:
                        if len(m3_window) < 3:
                            traded_sweeps.add(sk)
                        continue

                    start_idx = 2 if cfg["skip_first_bar"] else 1
                    found = False

                    for j in range(start_idx, len(m3_window)):
                        idx = oil_m3.index.get_loc(m3_window.index[j])
                        co = oil_m3["mid_open"].iat[idx]
                        cc = oil_m3["mid_close"].iat[idx]
                        po = oil_m3["mid_open"].iat[idx - 1]
                        pc = oil_m3["mid_close"].iat[idx - 1]
                        br = oil_m3["mid_high"].iat[idx] - oil_m3["mid_low"].iat[idx]

                        ct, cb = max(co, cc), min(co, cc)
                        pt, pb = max(po, pc), min(po, pc)

                        tol = ENGULFING_TOLERANCE
                        if sweep_dir == "bullish" and not (cc > co and cb <= pb + tol and ct >= pt - tol):
                            continue
                        if sweep_dir == "bearish" and not (cc < co and cb <= pb + tol and ct >= pt - tol):
                            continue

                        if sweep_dir == "bullish":
                            entry = oil_m3["ask_close"].iat[idx] + _slippage(br)
                            slv = sweep_wick - cfg["sl_buffer"]
                            risk = entry - slv
                            if risk < cfg["min_sl"]:
                                slv = entry - cfg["min_sl"]
                                risk = cfg["min_sl"]
                            if risk < 0.01 or risk > consol_range * 0.8:
                                continue
                            tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                            tpv = range_high - tp_buf
                            if tpv - entry < risk * 0.8:
                                continue
                            signals.append(Signal(
                                date=oil_m3.index[idx], entry=entry, sl=slv, tp=tpv,
                                direction="long", risk=risk,
                                strategy="micro_alpha_sweep_oil", max_bars=cfg["max_bars"], timeframe="M3",
                                metadata={"sweep_dir": sweep_dir, "sweep_wick": sweep_wick,
                                          "consol_range": consol_range, "window": f"{start_hour}-{end_hour}",
                                          "sweep_time": sbar_ts.isoformat(), "start_hour": start_hour,
                                          # BT-LOOKAHEAD fix (2026-06-20): see micro_alpha_sweep.py
                                          "emit_h1_bar": bar_ts.isoformat()},
                            ))
                        else:
                            entry = oil_m3["bid_close"].iat[idx] - _slippage(br)
                            slv = sweep_wick + cfg["sl_buffer"]
                            risk = slv - entry
                            if risk < cfg["min_sl"]:
                                slv = entry + cfg["min_sl"]
                                risk = cfg["min_sl"]
                            if risk < 0.01 or risk > consol_range * 0.8:
                                continue
                            tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                            tpv = range_low + tp_buf
                            if entry - tpv < risk * 0.8:
                                continue
                            signals.append(Signal(
                                date=oil_m3.index[idx], entry=entry, sl=slv, tp=tpv,
                                direction="short", risk=risk,
                                strategy="micro_alpha_sweep_oil", max_bars=cfg["max_bars"], timeframe="M3",
                                metadata={"sweep_dir": sweep_dir, "sweep_wick": sweep_wick,
                                          "consol_range": consol_range, "window": f"{start_hour}-{end_hour}",
                                          "sweep_time": sbar_ts.isoformat(), "start_hour": start_hour,
                                          "emit_h1_bar": bar_ts.isoformat()},
                            ))

                        traded_sweeps.add(sk)
                        found = True
                        break

                    if not found:
                        traded_sweeps.add(sk)
                    if found:
                        break

    return signals
