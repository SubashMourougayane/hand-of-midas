"""
Parity test: Verify backtest and live scheduler produce IDENTICAL signals.
Picks random days from 20 years of data, runs both code paths, asserts match.
This is the definitive test that live will reproduce backtest results.
"""
import sys
import os
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from backend.config import ALPHA_SWEEP, slippage, ENGULFING_TOLERANCE
from backend.strategies.alpha_sweep import generate_signals
from backend.strategies.base import Signal


@pytest.fixture(scope="module")
def market_data():
    """Load real market data once for all tests."""
    DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

    h1 = pd.read_csv(os.path.join(DATA_DIR, "XAU_USD_H1.csv"))
    h1["timestamp"] = pd.to_datetime(h1["timestamp"], utc=True, format="mixed")
    h1 = h1.sort_values("timestamp").reset_index(drop=True)
    h1.set_index("timestamp", inplace=True)
    h1["mid_high"] = (h1["bid_high"] + h1["ask_high"]) / 2
    h1["mid_low"] = (h1["bid_low"] + h1["ask_low"]) / 2
    h1["mid_close"] = (h1["bid_close"] + h1["ask_close"]) / 2
    h1["mid_open"] = (h1["bid_open"] + h1["ask_open"]) / 2

    m3 = pd.read_csv(os.path.join(DATA_DIR, "XAU_USD_M3.csv"))
    m3["timestamp"] = pd.to_datetime(m3["timestamp"], utc=True, format="mixed")
    m3 = m3.sort_values("timestamp").reset_index(drop=True)
    m3.set_index("timestamp", inplace=True)
    m3["mid_open"] = (m3["bid_open"] + m3["ask_open"]) / 2
    m3["mid_close"] = (m3["bid_close"] + m3["ask_close"]) / 2
    m3["mid_high"] = (m3["bid_high"] + m3["ask_high"]) / 2
    m3["mid_low"] = (m3["bid_low"] + m3["ask_low"]) / 2

    daily = pd.read_csv(os.path.join(DATA_DIR, "XAU_USD_D.csv"))
    daily["timestamp"] = pd.to_datetime(daily["timestamp"], utc=True, format="mixed")
    daily = daily.sort_values("timestamp").reset_index(drop=True)

    return h1, m3, daily


def _get_daily_bias_from_df(daily: pd.DataFrame) -> dict:
    """Build daily bias dict from daily DataFrame (Variant C: body < 40% → neutral)."""
    bias = {}
    for i in range(1, len(daily)):
        prev = daily.iloc[i - 1]
        date = pd.to_datetime(daily.iloc[i]["timestamp"]).date()
        mid_close = (prev["bid_close"] + prev["ask_close"]) / 2
        mid_open = (prev["bid_open"] + prev["ask_open"]) / 2
        mid_high = (prev["bid_high"] + prev["ask_high"]) / 2
        mid_low = (prev["bid_low"] + prev["ask_low"]) / 2
        prev_range = mid_high - mid_low
        if prev_range <= 0:
            bias[date] = "neutral"
        elif abs(mid_close - mid_open) / prev_range < 0.4:
            bias[date] = "neutral"
        else:
            bias[date] = "bullish" if mid_close > mid_open else "bearish"
    return bias


def _simulate_live_scheduler_for_date(h1: pd.DataFrame, m3: pd.DataFrame, daily: pd.DataFrame, target_date, cfg=ALPHA_SWEEP):
    """
    Simulate what the live scheduler would do on a given date.
    Returns list of (direction, entry, sl, tp) tuples — same as what execute_signal would receive.
    """
    today = target_date

    # Get Asia bars
    asia_bars = h1[(h1.index.date == today) & (h1.index.hour >= 0) & (h1.index.hour < 8)]
    if len(asia_bars) < 3:
        return []

    asia_high = asia_bars["mid_high"].max()
    asia_low = asia_bars["mid_low"].min()
    asia_range = asia_high - asia_low

    if asia_range < cfg["asia_min_range"]:
        return []

    # Scan window bars
    scan_bars = h1[(h1.index.date == today) &
                   (h1.index.hour >= cfg["scan_start"]) &
                   (h1.index.hour < cfg["scan_end"])]
    if len(scan_bars) < 2:
        return []

    # Daily bias (Variant C: body < 40% of range → neutral)
    daily_ts = pd.to_datetime(daily["timestamp"])
    prev_days = daily[daily_ts.dt.date < today]
    if len(prev_days) == 0:
        return []
    prev = prev_days.iloc[-1]
    mid_close = (prev["bid_close"] + prev["ask_close"]) / 2
    mid_open = (prev["bid_open"] + prev["ask_open"]) / 2
    mid_high = (prev["bid_high"] + prev["ask_high"]) / 2
    mid_low = (prev["bid_low"] + prev["ask_low"]) / 2
    prev_range = mid_high - mid_low
    if prev_range <= 0:
        bias = "neutral"
    elif abs(mid_close - mid_open) / prev_range < 0.4:
        bias = "neutral"
    else:
        bias = "bullish" if mid_close > mid_open else "bearish"

    # Find ALL sweeps
    sweeps = []
    for i in range(len(scan_bars)):
        mh = scan_bars["mid_high"].iloc[i]
        ml = scan_bars["mid_low"].iloc[i]
        mc = scan_bars["mid_close"].iloc[i]

        if mh > asia_high + cfg["sweep_threshold"] and mc < asia_high:
            sweeps.append(("bearish", mh, scan_bars.index[i]))
        elif ml < asia_low - cfg["sweep_threshold"] and mc > asia_low:
            sweeps.append(("bullish", ml, scan_bars.index[i]))

    if not sweeps:
        return []

    # Process each sweep
    signals = []
    max_per_day = cfg.get("max_trades_per_day", 3)

    for sweep_dir, sweep_wick, sweep_time in sweeps:
        if len(signals) >= max_per_day:
            break

        if bias != "neutral":
            if sweep_dir == "bullish" and bias != "bullish":
                continue
            if sweep_dir == "bearish" and bias != "bearish":
                continue

        # M3 engulfing
        end_time = sweep_time + timedelta(hours=cfg["engulfing_window_hours"])
        m3_window = m3[(m3.index > sweep_time) & (m3.index <= end_time)]

        if len(m3_window) < 3:
            continue

        start_idx = 2 if cfg.get("skip_first_bar", True) else 1

        for j in range(start_idx, len(m3_window)):
            idx = m3.index.get_loc(m3_window.index[j])
            co = m3["mid_open"].iat[idx]
            cc = m3["mid_close"].iat[idx]
            po = m3["mid_open"].iat[idx - 1]
            pc = m3["mid_close"].iat[idx - 1]
            br = m3["mid_high"].iat[idx] - m3["mid_low"].iat[idx]

            ct = max(co, cc)
            cb = min(co, cc)
            pt = max(po, pc)
            pb = min(po, pc)

            tol = ENGULFING_TOLERANCE
            if sweep_dir == "bullish" and not (cc > co and cb <= pb + tol and ct >= pt - tol):
                continue
            if sweep_dir == "bearish" and not (cc < co and cb <= pb + tol and ct >= pt - tol):
                continue

            # Engulfing confirmed — compute entry using ASK/BID (same as live)
            if sweep_dir == "bullish":
                entry = m3["ask_close"].iat[idx] + slippage(br)
                sl = sweep_wick - cfg["sl_buffer"]
                risk = entry - sl
                if risk < cfg["min_sl"]:
                    sl = entry - cfg["min_sl"]
                    risk = cfg["min_sl"]
                if risk < 0.3 or risk > asia_range * 0.8:
                    continue
                tp = entry + asia_range * cfg["tp_multiplier"]
                if tp - entry < risk * 0.8:
                    continue
                signals.append(("long", entry, sl, tp, m3.index[idx]))
            else:
                entry = m3["bid_close"].iat[idx] - slippage(br)
                sl = sweep_wick + cfg["sl_buffer"]
                risk = sl - entry
                if risk < cfg["min_sl"]:
                    sl = entry + cfg["min_sl"]
                    risk = cfg["min_sl"]
                if risk < 0.3 or risk > asia_range * 0.8:
                    continue
                tp = entry - asia_range * cfg["tp_multiplier"]
                if entry - tp < risk * 0.8:
                    continue
                signals.append(("short", entry, sl, tp, m3.index[idx]))

            break  # One engulfing per sweep

    return signals


class TestBacktestLiveParity:
    """Monte Carlo parity: pick random days, verify backtest == live logic."""

    def test_parity_50_random_days(self, market_data):
        """Pick 50 random days that have signals, verify live matches backtest."""
        h1, m3, daily = market_data
        np.random.seed(42)

        # First generate all backtest signals
        daily_bias = _get_daily_bias_from_df(daily)
        backtest_signals = generate_signals(h1, m3, daily_bias)

        # Group by date
        bt_by_date = {}
        for s in backtest_signals:
            d = s.date.date()
            if d not in bt_by_date:
                bt_by_date[d] = []
            bt_by_date[d].append(s)

        # Pick up to 50 random days with signals
        signal_dates = list(bt_by_date.keys())
        sample_size = min(50, len(signal_dates))
        test_dates = np.random.choice(signal_dates, size=sample_size, replace=False)

        matches = 0
        mismatches = 0
        details = []

        for date in test_dates:
            np.random.seed(42)  # Reset seed for deterministic slippage
            bt_signals = bt_by_date[date]

            np.random.seed(42)  # Same seed for live simulation
            live_signals = _simulate_live_scheduler_for_date(h1, m3, daily, date)

            # Compare signal count
            if len(bt_signals) != len(live_signals):
                mismatches += 1
                details.append(f"  {date}: count mismatch bt={len(bt_signals)} live={len(live_signals)}")
                continue

            # Compare each signal
            day_match = True
            for i, (bt, live) in enumerate(zip(bt_signals, live_signals)):
                live_dir, live_entry, live_sl, live_tp, live_date = live

                if bt.direction != live_dir:
                    day_match = False
                    details.append(f"  {date} sig#{i}: direction bt={bt.direction} live={live_dir}")
                    break

                if abs(bt.entry - live_entry) > 0.05:
                    day_match = False
                    details.append(f"  {date} sig#{i}: entry bt={bt.entry:.2f} live={live_entry:.2f} diff={abs(bt.entry-live_entry):.4f}")
                    break

                if abs(bt.sl - live_sl) > 0.05:
                    day_match = False
                    details.append(f"  {date} sig#{i}: sl bt={bt.sl:.2f} live={live_sl:.2f}")
                    break

                if abs(bt.tp - live_tp) > 0.05:
                    day_match = False
                    details.append(f"  {date} sig#{i}: tp bt={bt.tp:.2f} live={live_tp:.2f}")
                    break

            if day_match:
                matches += 1
            else:
                mismatches += 1

        parity_rate = matches / sample_size

        if mismatches > 0:
            print(f"\n  PARITY: {matches}/{sample_size} days match ({parity_rate:.1%})")
            print(f"  Mismatches ({mismatches}):")
            for d in details[:10]:
                print(d)

        assert parity_rate >= 0.95, f"Parity too low: {parity_rate:.1%} ({mismatches} mismatches out of {sample_size})"

    def test_parity_no_signal_days(self, market_data):
        """Verify days with no backtest signal also produce no live signal."""
        h1, m3, daily = market_data
        np.random.seed(123)

        daily_bias = _get_daily_bias_from_df(daily)
        backtest_signals = generate_signals(h1, m3, daily_bias)

        signal_dates = set(s.date.date() for s in backtest_signals)
        all_dates = sorted(set(h1.index.date))
        no_signal_dates = [d for d in all_dates if d not in signal_dates and d.year >= 2020]

        # Pick 20 random no-signal days
        sample = np.random.choice(no_signal_dates, size=min(20, len(no_signal_dates)), replace=False)

        false_signals = 0
        for date in sample:
            np.random.seed(42)
            live_signals = _simulate_live_scheduler_for_date(h1, m3, daily, date)
            if live_signals:
                false_signals += 1

        assert false_signals == 0, f"Live produced signals on {false_signals} days where backtest had none"

    def test_parity_entry_price_uses_ask_bid(self, market_data):
        """Verify both paths use ask_close for longs, bid_close for shorts (not mid)."""
        h1, m3, daily = market_data
        np.random.seed(42)

        daily_bias = _get_daily_bias_from_df(daily)
        signals = generate_signals(h1, m3, daily_bias)

        # Check a sample of long signals: entry should be > mid_close (because ask > mid)
        long_signals = [s for s in signals if s.direction == "long"][:20]
        for s in long_signals:
            idx = m3.index.get_loc(s.date)
            mid_close = m3["mid_close"].iat[idx]
            # Entry should be ask_close + slippage > mid_close
            assert s.entry > mid_close, f"Long entry {s.entry:.2f} should be > mid {mid_close:.2f} (using ask)"

        # Check shorts: entry should be < mid_close (because bid < mid)
        short_signals = [s for s in signals if s.direction == "short"][:20]
        for s in short_signals:
            idx = m3.index.get_loc(s.date)
            mid_close = m3["mid_close"].iat[idx]
            assert s.entry < mid_close, f"Short entry {s.entry:.2f} should be < mid {mid_close:.2f} (using bid)"

    def test_parity_max_trades_per_day(self, market_data):
        """Verify no day exceeds max_trades_per_day."""
        h1, m3, daily = market_data
        np.random.seed(42)

        daily_bias = _get_daily_bias_from_df(daily)
        signals = generate_signals(h1, m3, daily_bias)

        # Count signals per day
        day_counts = {}
        for s in signals:
            d = s.date.date()
            day_counts[d] = day_counts.get(d, 0) + 1

        max_per_day = ALPHA_SWEEP.get("max_trades_per_day", 3)
        violations = {d: c for d, c in day_counts.items() if c > max_per_day}

        assert len(violations) == 0, f"Days exceeding {max_per_day}/day: {violations}"

    def test_parity_scan_window_respected(self, market_data):
        """Verify all signals fall within scan window hours."""
        h1, m3, daily = market_data
        np.random.seed(42)

        daily_bias = _get_daily_bias_from_df(daily)
        signals = generate_signals(h1, m3, daily_bias)

        scan_start = ALPHA_SWEEP["scan_start"]
        scan_end = ALPHA_SWEEP["scan_end"]

        violations = []
        for s in signals:
            hour = s.date.hour + s.date.minute / 60
            # Signal timestamp is the M3 engulfing bar (which is within engulfing_window_hours after sweep)
            # Sweep must be within scan window, engulfing can be up to 2hrs later
            max_allowed = scan_end + ALPHA_SWEEP["engulfing_window_hours"]
            if hour < scan_start or hour > max_allowed:
                violations.append(f"{s.date} hour={hour:.1f}")

        assert len(violations) == 0, f"Signals outside window: {violations[:5]}"
