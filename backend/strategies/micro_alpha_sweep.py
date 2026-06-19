"""
Micro Alpha-Sweep: Rolling 4-hour consolidation windows every 2 hours.

Signal generation matches live scheduler exactly:
- Full 24hr coverage with midnight wrap (windows: 22-02, 00-04, ..., 16-20)
- Market close skip: windows whose consolidation includes hour 21 are excluded
- Walks each H1 bar chronologically (simulates scheduler poll)
- For each bar, checks ALL active windows
- For each window, checks ALL completed scan bars (not just current)
- Deduplicates by (sweep_bar_ts, window_start)

Phase 4 refactor (2026-06-19): added `cfg` parameter. Strategy now accepts
the config dict the caller passes (dependency injection). Old behavior
imported `backend.config.ALPHA_SWEEP` (Gold Macro's config — wrong for
Gold Micro). Master RCA D2: 'asia_min_range' (Gold Macro) vs 'min_range'
(Gold Micro) silently agreed on 5.0 today but would drift if either
changed. Fix: cfg parameter eliminates the import path.

Backward compat: cfg defaults to None → falls back to old ALPHA_SWEEP
import. Existing callers don't break.
"""
import numpy as np
import pandas as pd
from datetime import timedelta
from backend.strategies.base import Signal
from backend.config import ALPHA_SWEEP, slippage, ENGULFING_TOLERANCE


MICRO_CONFIG = {
    "consol_hours": 4,
    "scan_gap_hours": 2,
    "scan_after_hours": 6,
    "market_close_start": 21,
    "market_close_end": 22,
    "max_trades_per_day": 3,
}


def _cfg_min_range(cfg: dict) -> float:
    """Return min consolidation range from cfg, supporting both naming
    conventions: 'min_range' (Gold/Oil Micro) and 'asia_min_range' (Gold Macro
    legacy callers). Master RCA D2 fix.
    """
    if "min_range" in cfg:
        return cfg["min_range"]
    return cfg["asia_min_range"]


def _hours_in_range(start: int, end: int) -> set:
    """Return set of hours in [start, end) handling midnight wrap."""
    if start < end:
        return set(range(start, end))
    return set(range(start, 24)) | set(range(0, end))


def _hour_past(current: int, target: int) -> bool:
    """Check if current hour is past target (within last 12 hours)."""
    diff = (current - target) % 24
    return 0 < diff <= 12


def generate_signals(
    gold_h1: pd.DataFrame,
    gold_m3: pd.DataFrame,
    daily_bias: dict,
    disable_market_close: bool | None = None,
    cfg: dict | None = None,
) -> list[Signal]:
    """
    disable_market_close: Filter — drop the 21–22 UTC market-close block.
      Inherited from Oil Micro config; Gold Micro doesn't actually close at
      that hour. Default False (legacy = block 21-22 UTC). True = scan
      through. None reads from cfg.disable_market_close (default False).

    cfg: config dict. Defaults to backend.config.ALPHA_SWEEP for backward
      compat with old Gold Macro callers. Phase 4 refactor: Gold Micro live
      scheduler + BT both pass MICRO_ALPHA_SWEEP from backend-micro/config.py
      (single source of truth, eliminates D2 key drift).
    """
    if cfg is None:
        cfg = ALPHA_SWEEP
    mcfg = MICRO_CONFIG
    if disable_market_close is None:
        disable_market_close = cfg.get("disable_market_close", False)
    close_start = mcfg["market_close_start"]
    signals = []

    dates = sorted(set(gold_h1.index.date))

    for date in dates:
        day_h1 = gold_h1[gold_h1.index.date == date]
        # Phase 4 — removed `if len(day_h1) < 6: continue`. Was a guard
        # against thin BT historical days but blocked live signals before
        # 6 H1 bars accumulated mid-day. Same fix as Oil Micro Phase 5.5.

        bias = daily_bias.get(date, "none")
        # Cap rework Jun 18: signal-gen no longer caps at max_trades_per_day.
        # Engine execution loop caps on FILLED trades only.
        traded_sweeps = set()

        for bar_ts, bar in day_h1.iterrows():
            now_hour = bar_ts.hour

            # Skip during market close (same as live) — bypassed when
            # disable_market_close is on (Gold Micro doesn't actually close
            # at this hour; the gate was inherited from Oil Micro).
            if not disable_market_close:
                if mcfg["market_close_start"] <= now_hour < mcfg["market_close_end"]:
                    continue

            # Check all windows (0, 2, 4, ..., 22) — same as live scheduler
            for start_hour in range(0, 24, mcfg["scan_gap_hours"]):
                end_hour = (start_hour + mcfg["consol_hours"]) % 24
                scan_end_hour = (start_hour + mcfg["consol_hours"] + mcfg["scan_after_hours"]) % 24

                # Skip windows whose consolidation overlaps market close.
                # Bypassed when disable_market_close is on.
                consol_hours = _hours_in_range(start_hour, end_hour)
                if not disable_market_close and close_start in consol_hours:
                    continue

                # Check if consolidation is done
                if not _hour_past(now_hour, end_hour):
                    continue

                # Check if scan window hasn't expired
                if _hour_past(now_hour, scan_end_hour):
                    continue

                # Build consolidation range (handles midnight wrap).
                # Phase 4 lookahead fix: gate by index <= bar_ts so consol
                # only includes bars that have closed at this iteration.
                # Without this, consol can pull future bars (e.g. 22:00 of
                # date D when iterating at 03:00 of date D for window 22-2)
                # — same lookahead bug Oil Micro had pre-Phase-5.5.
                consol = day_h1[(day_h1.index.hour.isin(consol_hours))
                                & (day_h1.index <= bar_ts)]
                if len(consol) < 2:
                    continue

                range_high = consol["mid_high"].max()
                range_low = consol["mid_low"].min()
                consol_range = range_high - range_low
                # D2 fix: use _cfg_min_range so 'min_range' and 'asia_min_range'
                # both resolve. Gold Micro passes MICRO_ALPHA_SWEEP (key=
                # 'min_range'); legacy Gold Macro passes ALPHA_SWEEP (key=
                # 'asia_min_range').
                if consol_range < _cfg_min_range(cfg):
                    continue

                bearish_level = range_high + cfg["sweep_threshold"]
                bullish_level = range_low - cfg["sweep_threshold"]

                # Check ALL scan bars up to current bar (handles midnight wrap).
                # Phase 4 fix: scan_bars must occur AFTER consol's last bar.
                # Without this, a 03:00 sweep on date D could be paired with
                # a consol formed from 18-21 of date D (later same day) when
                # iterating at bar_ts=22:00 — temporally backward sweep,
                # impossible in real time. Gate: scan_bar.index > max(consol.index).
                scan_hours = _hours_in_range(end_hour, scan_end_hour)
                consol_last = consol.index.max()
                scan_bars = day_h1[(day_h1.index.hour.isin(scan_hours))
                                   & (day_h1.index <= bar_ts)
                                   & (day_h1.index > consol_last)]

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

                    # Dedup: already traded this sweep for this window
                    sk = (sbar_ts, start_hour)
                    if sk in traded_sweeps:
                        continue

                    # Bias filter (Variant C)
                    if bias != "neutral":
                        if sweep_dir == "bullish" and bias != "bullish":
                            continue
                        if sweep_dir == "bearish" and bias != "bearish":
                            continue

                    # Engulfing search.
                    # Phase 4 parity contract: m3_window must contain the FULL
                    # expected bar count. If short, skip without consuming sweep.
                    # Reason: when live's 50-bar M3 view truncates the early bars
                    # of the engulfing window, the strategy's `for j in range(
                    # start_idx, len(m3_window))` starts at a different bar
                    # index than BT's full-history call → picks a different
                    # first engulfing → live and BT diverge. Discovered Phase 4,
                    # Gold Micro 06-12 21:33 vs 21:45 mismatch (cron 06-13 00:00
                    # had only 6 bars for 15-bar window).
                    eng_end = sbar_ts + timedelta(hours=cfg["engulfing_window_hours"])
                    m3_window = gold_m3[(gold_m3.index > sbar_ts) & (gold_m3.index <= eng_end)]
                    expected_m3_bars = int(cfg["engulfing_window_hours"] * 20)  # 20 bars/hr at M3
                    if len(m3_window) < expected_m3_bars:
                        # Truncated window — don't fire AND don't consume sweep
                        # (BT will never hit this branch with full history; live
                        # will retry next cron when more M3 bars are available).
                        # Only consume sweep if engulfing window is fully past
                        # AND still under-filled (real data gap, not view limit).
                        # The `traded_sweeps.add(sk)` below was wrong — it
                        # consumed sweeps even when next cron would have data.
                        if len(m3_window) < 3:
                            traded_sweeps.add(sk)
                        continue

                    start_idx = 2 if cfg["skip_first_bar"] else 1
                    found = False

                    for j in range(start_idx, len(m3_window)):
                        idx = gold_m3.index.get_loc(m3_window.index[j])
                        co = gold_m3["mid_open"].iat[idx]
                        cc = gold_m3["mid_close"].iat[idx]
                        po = gold_m3["mid_open"].iat[idx - 1]
                        pc = gold_m3["mid_close"].iat[idx - 1]
                        br = gold_m3["mid_high"].iat[idx] - gold_m3["mid_low"].iat[idx]

                        ct, cb = max(co, cc), min(co, cc)
                        pt, pb = max(po, pc), min(po, pc)

                        tol = ENGULFING_TOLERANCE
                        if sweep_dir == "bullish" and not (cc > co and cb <= pb + tol and ct >= pt - tol):
                            continue
                        if sweep_dir == "bearish" and not (cc < co and cb <= pb + tol and ct >= pt - tol):
                            continue

                        # Entry calculation
                        if sweep_dir == "bullish":
                            entry = gold_m3["ask_close"].iat[idx] + slippage(br)
                            slv = sweep_wick - cfg["sl_buffer"]
                            risk = entry - slv
                            if risk < cfg["min_sl"]:
                                slv = entry - cfg["min_sl"]
                                risk = cfg["min_sl"]
                            if risk < 0.3 or risk > consol_range * 0.8:
                                continue
                            tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                            tpv = range_high - tp_buf
                            if tpv - entry < risk * 0.8:
                                continue
                            signals.append(Signal(
                                date=gold_m3.index[idx], entry=entry, sl=slv, tp=tpv,
                                direction="long", risk=risk,
                                strategy="micro_alpha_sweep", max_bars=cfg["max_bars"], timeframe="M3",
                                metadata={"sweep_dir": sweep_dir, "sweep_wick": sweep_wick,
                                          "consol_range": consol_range,
                                          "window": f"{start_hour}-{end_hour}",
                                          "sweep_time": sbar_ts.isoformat(),
                                          "start_hour": start_hour},
                            ))
                        else:
                            entry = gold_m3["bid_close"].iat[idx] - slippage(br)
                            slv = sweep_wick + cfg["sl_buffer"]
                            risk = slv - entry
                            if risk < cfg["min_sl"]:
                                slv = entry + cfg["min_sl"]
                                risk = cfg["min_sl"]
                            if risk < 0.3 or risk > consol_range * 0.8:
                                continue
                            tp_buf = cfg.get("tp_structure_buffer", consol_range * cfg["tp_multiplier"])
                            tpv = range_low + tp_buf
                            if entry - tpv < risk * 0.8:
                                continue
                            signals.append(Signal(
                                date=gold_m3.index[idx], entry=entry, sl=slv, tp=tpv,
                                direction="short", risk=risk,
                                strategy="micro_alpha_sweep", max_bars=cfg["max_bars"], timeframe="M3",
                                metadata={"sweep_dir": sweep_dir, "sweep_wick": sweep_wick,
                                          "consol_range": consol_range,
                                          "window": f"{start_hour}-{end_hour}",
                                          "sweep_time": sbar_ts.isoformat(),
                                          "start_hour": start_hour},
                            ))

                        traded_sweeps.add(sk)
                        found = True
                        break

                    if not found:
                        traded_sweeps.add(sk)
                    if found:
                        break  # One trade per sweep, move to next window

    return signals
