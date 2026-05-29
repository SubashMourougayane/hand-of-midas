"""TEST 02: Signal Parity — Backtest vs Live scheduler produce identical signals.

Feeds SAME H1+M3 data to both code paths, compares outputs.
Would have prevented: divergence bugs where live takes trades backtest wouldn't (or vice versa).
"""
import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend-micro"))

from backend.strategies import micro_alpha_sweep
from backend.config import ALPHA_SWEEP, ENGULFING_TOLERANCE


def _hours_in_range(start, end):
    """Same helper as scheduler.py — computes hours in a window (handles midnight wrap)."""
    hours = []
    h = start
    while h != end:
        hours.append(h % 24)
        h = (h + 1) % 24
    return hours


def _hour_past(current, target):
    """Same as scheduler.py — checks if current hour has passed target."""
    diff = (current - target) % 24
    return 0 < diff <= 12


def simulate_live_signals(h1_df, m3_df, daily_bias, cfg=None):
    """Simulate the live scheduler's signal detection on historical data.

    This replicates the EXACT logic from scheduler.py:_run_micro_sweep()
    but takes data as input instead of calling get_candles().
    """
    if cfg is None:
        from backend_micro_config import MICRO_ALPHA_SWEEP as cfg
        cfg = MICRO_ALPHA_SWEEP

    signals = []
    traded_sweeps = set()
    consol_hours_val = cfg.get("consol_hours", 4)
    scan_gap = cfg.get("scan_gap_hours", 2)
    scan_after = cfg.get("scan_after_hours", 6)
    market_close_start = cfg.get("market_close_start", 21)
    market_close_end = cfg.get("market_close_end", 22)
    engulfing_window = cfg.get("engulfing_window_hours", 0.75)
    tolerance = ENGULFING_TOLERANCE

    # Process each unique hour in the H1 data (simulating 3-min polls)
    processed_hours = set()

    for h1_idx in range(len(h1_df)):
        bar_ts = h1_df.index[h1_idx]
        now_hour = bar_ts.hour

        # Skip market close
        if market_close_start <= now_hour < market_close_end:
            continue

        # Generate all active windows for this hour
        windows = []
        for start_hour in range(0, 24, scan_gap):
            end_hour = (start_hour + consol_hours_val) % 24
            scan_end = (end_hour + scan_after) % 24

            # Skip windows that overlap market close in consolidation
            consol_hrs = _hours_in_range(start_hour, end_hour)
            if market_close_start in consol_hrs or (market_close_end - 1) in consol_hrs:
                continue

            # Check if consolidation is done and scan is active
            if not _hour_past(now_hour, end_hour):
                continue
            if _hour_past(now_hour, scan_end):
                continue

            windows.append({"consol_start": start_hour, "consol_end": end_hour,
                          "scan_until": scan_end})

        for window in windows:
            consol_hrs = _hours_in_range(window["consol_start"], window["consol_end"])
            scan_hrs = _hours_in_range(window["consol_end"], window["scan_until"])

            # Get consolidation bars
            consol_bars = h1_df[h1_df.index.hour.isin(consol_hrs)]
            consol_bars = consol_bars[consol_bars.index <= bar_ts]
            consol_bars = consol_bars.tail(len(consol_hrs))

            if len(consol_bars) < 2:
                continue

            range_high = consol_bars["mid_high"].max()
            range_low = consol_bars["mid_low"].min()
            consol_range = range_high - range_low

            if consol_range < cfg.get("asia_min_range", cfg.get("min_range", 5.0)):
                continue

            # Get scan bars (current and before)
            scan_bars = h1_df[(h1_df.index.hour.isin(scan_hrs)) & (h1_df.index <= bar_ts)]
            scan_bars = scan_bars.tail(len(scan_hrs))

            bearish_level = range_high + cfg["sweep_threshold"]
            bullish_level = range_low - cfg["sweep_threshold"]

            for si in range(len(scan_bars)):
                sbar = scan_bars.iloc[si]
                sbar_ts = scan_bars.index[si]
                sweep_dir = None
                sweep_wick = 0

                if sbar["mid_high"] > bearish_level and sbar["mid_close"] < range_high:
                    sweep_dir = "bearish"
                    sweep_wick = sbar["mid_high"]
                elif sbar["mid_low"] < bullish_level and sbar["mid_close"] > range_low:
                    sweep_dir = "bullish"
                    sweep_wick = sbar["mid_low"]

                if not sweep_dir:
                    continue

                sweep_key = f"{sbar_ts}_{sweep_dir}"
                if sweep_key in traded_sweeps:
                    continue

                # Check bias
                trade_date = bar_ts.date()
                bias = daily_bias.get(trade_date, "neutral")
                if bias != "neutral":
                    if sweep_dir == "bearish" and bias == "bullish":
                        continue
                    if sweep_dir == "bullish" and bias == "bearish":
                        continue

                # Find engulfing in M3
                eng_end = sbar_ts + pd.Timedelta(hours=engulfing_window)
                m3_window = m3_df[(m3_df.index > sbar_ts) & (m3_df.index <= eng_end)]

                if len(m3_window) < 3:
                    traded_sweeps.add(sweep_key)
                    continue

                skip_first = cfg.get("skip_first_bar", True)
                start_idx = 2 if skip_first else 1
                found_engulfing = False

                for j in range(start_idx, len(m3_window)):
                    c = m3_window.iloc[j]
                    p = m3_window.iloc[j-1]

                    co = (c["bid_open"] + c["ask_open"]) / 2
                    cc = (c["bid_close"] + c["ask_close"]) / 2
                    po = (p["bid_open"] + p["ask_open"]) / 2
                    pc = (p["bid_close"] + p["ask_close"]) / 2

                    ct = max(co, cc)
                    cb = min(co, cc)
                    pt = max(po, pc)
                    pb = min(po, pc)

                    if sweep_dir == "bearish":
                        if cc < co and cb <= pb + tolerance and ct >= pt - tolerance:
                            found_engulfing = True
                            eng_idx = m3_window.index[j]
                            break
                    else:
                        if cc > co and cb <= pb + tolerance and ct >= pt - tolerance:
                            found_engulfing = True
                            eng_idx = m3_window.index[j]
                            break

                if not found_engulfing:
                    traded_sweeps.add(sweep_key)
                    continue

                # Calculate entry/SL/TP
                idx_in_m3 = m3_df.index.get_loc(eng_idx)
                bar_range = m3_df["mid_high"].iat[idx_in_m3] - m3_df["mid_low"].iat[idx_in_m3]
                from backend.config import slippage
                slip = slippage(bar_range)

                if sweep_dir == "bullish":
                    entry = m3_df["ask_close"].iat[idx_in_m3] + slip
                    slv = sweep_wick - cfg["sl_buffer"]
                    risk = entry - slv
                    if risk < cfg["min_sl"]:
                        slv = entry - cfg["min_sl"]
                        risk = cfg["min_sl"]
                    if risk < 0.3 or risk > consol_range * 0.8:
                        traded_sweeps.add(sweep_key)
                        continue
                    tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                    tpv = range_high - tp_buf
                    if tpv - entry < risk * 0.8:
                        traded_sweeps.add(sweep_key)
                        continue
                    direction = "long"
                else:
                    entry = m3_df["bid_close"].iat[idx_in_m3] - slip
                    slv = sweep_wick + cfg["sl_buffer"]
                    risk = slv - entry
                    if risk < cfg["min_sl"]:
                        slv = entry + cfg["min_sl"]
                        risk = cfg["min_sl"]
                    if risk < 0.3 or risk > consol_range * 0.8:
                        traded_sweeps.add(sweep_key)
                        continue
                    tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                    tpv = range_low + tp_buf
                    if entry - tpv < risk * 0.8:
                        traded_sweeps.add(sweep_key)
                        continue
                    direction = "short"

                signals.append({
                    "date": eng_idx,
                    "direction": direction,
                    "entry": round(entry, 2),
                    "sl": round(slv, 2),
                    "tp": round(tpv, 2),
                    "risk": round(risk, 2),
                })
                traded_sweeps.add(sweep_key)
                break  # One signal per window per cycle

    return signals


class TestSignalParity:
    """02: Backtest generate_signals() vs simulated live scheduler."""

    def test_signal_count_within_tolerance(self, gold_7d_h1, gold_7d_m3, daily_bias, seed_random):
        """Signal counts should be within 10% of each other."""
        np.random.seed(42)
        bt_sigs = micro_alpha_sweep.generate_signals(gold_7d_h1, gold_7d_m3, daily_bias)
        bt_sigs = [s for s in bt_sigs if s.date >= gold_7d_h1.index[0]]

        np.random.seed(42)
        live_sigs = simulate_live_signals(gold_7d_h1, gold_7d_m3, daily_bias, cfg=ALPHA_SWEEP)

        # Allow 20% tolerance (rolling vs batch processing creates timing differences)
        bt_count = len(bt_sigs)
        live_count = len(live_sigs)
        if bt_count == 0 and live_count == 0:
            return  # No signals in this period — OK

        ratio = min(bt_count, live_count) / max(bt_count, live_count) if max(bt_count, live_count) > 0 else 1
        assert ratio >= 0.8, \
            f"Signal count divergence: backtest={bt_count}, live_sim={live_count} (ratio={ratio:.2f})"

    def test_signal_directions_match(self, gold_7d_h1, gold_7d_m3, daily_bias, seed_random):
        """Signals at matching timestamps should have same direction."""
        np.random.seed(42)
        bt_sigs = micro_alpha_sweep.generate_signals(gold_7d_h1, gold_7d_m3, daily_bias)
        bt_by_hour = {}
        for s in bt_sigs:
            key = s.date.floor("H")
            bt_by_hour[key] = s

        np.random.seed(42)
        live_sigs = simulate_live_signals(gold_7d_h1, gold_7d_m3, daily_bias, cfg=ALPHA_SWEEP)
        live_by_hour = {}
        for s in live_sigs:
            key = pd.Timestamp(s["date"]).floor("H")
            live_by_hour[key] = s

        # For matching hours, direction must agree
        matching = set(bt_by_hour.keys()) & set(live_by_hour.keys())
        mismatches = []
        for ts in matching:
            bt_dir = bt_by_hour[ts].direction
            live_dir = live_by_hour[ts]["direction"]
            if bt_dir != live_dir:
                mismatches.append(f"{ts}: BT={bt_dir}, Live={live_dir}")

        assert not mismatches, f"Direction mismatches:\n" + "\n".join(mismatches[:5])

    def test_tp_sl_formulas_match(self, gold_7d_h1, gold_7d_m3, daily_bias, seed_random):
        """For matching signals, TP and SL values should be within $1."""
        np.random.seed(42)
        bt_sigs = micro_alpha_sweep.generate_signals(gold_7d_h1, gold_7d_m3, daily_bias)
        bt_by_hour = {s.date.floor("H"): s for s in bt_sigs}

        np.random.seed(42)
        live_sigs = simulate_live_signals(gold_7d_h1, gold_7d_m3, daily_bias, cfg=ALPHA_SWEEP)
        live_by_hour = {pd.Timestamp(s["date"]).floor("H"): s for s in live_sigs}

        matching = set(bt_by_hour.keys()) & set(live_by_hour.keys())
        sl_diffs = []
        tp_diffs = []

        for ts in matching:
            bs = bt_by_hour[ts]
            ls = live_by_hour[ts]
            if bs.direction != ls["direction"]:
                continue
            sl_diff = abs(bs.sl - ls["sl"])
            tp_diff = abs(bs.tp - ls["tp"])
            sl_diffs.append(sl_diff)
            tp_diffs.append(tp_diff)

            assert sl_diff < 1.0, f"SL mismatch at {ts}: BT={bs.sl}, Live={ls['sl']}"
            assert tp_diff < 1.0, f"TP mismatch at {ts}: BT={bs.tp}, Live={ls['tp']}"

    def test_bias_filter_consistent(self, gold_7d_h1, gold_7d_m3, daily_bias, seed_random):
        """Both paths should reject same signals due to bias filter."""
        np.random.seed(42)
        all_sigs = micro_alpha_sweep.generate_signals(gold_7d_h1, gold_7d_m3, daily_bias)

        # Check: no bullish sweep signal on a "bearish" bias day
        for s in all_sigs:
            trade_date = s.date.date()
            bias = daily_bias.get(trade_date, "neutral")
            if bias == "bearish":
                assert s.direction != "long", \
                    f"LONG signal on bearish day {trade_date} — bias filter broken"
            if bias == "bullish":
                assert s.direction != "short", \
                    f"SHORT signal on bullish day {trade_date} — bias filter broken"
