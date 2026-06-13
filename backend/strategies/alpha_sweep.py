"""
Alpha-Sweep (formerly V4): Session Sweep + M3 Engulfing.
Ported from generate_portfolio_dashboard.py lines 140-182.
"""
import numpy as np
import pandas as pd
from backend.strategies.base import Signal
from backend.config import ALPHA_SWEEP, slippage, ENGULFING_TOLERANCE


def generate_signals(
    gold_h1: pd.DataFrame,
    gold_m3: pd.DataFrame,
    daily_bias: dict,
    rr_lower_bound: float | None = None,
) -> list[Signal]:
    """
    Generate Alpha-Sweep signals.
    gold_h1: H1 candles with session labels (needs 'session_asia', 'session_london' columns or use hour filter)
    gold_m3: M3 candles with bid/ask
    daily_bias: {date: 'bullish'|'bearish'} from previous day close
    rr_lower_bound: Filter #16 — minimum (tp - entry) / risk ratio to keep a signal.
        None (default) = read from ALPHA_SWEEP config (currently 0.8).
        Pass 1.5 to filter aggressively. Higher = fewer trades but cleaner R:R.
    """
    cfg = ALPHA_SWEEP
    if rr_lower_bound is None:
        rr_lower_bound = cfg.get("rr_lower_bound", 0.8)
    signals = []

    dates = sorted(set(gold_h1.index.date))

    for date in dates:
        day_h1 = gold_h1[gold_h1.index.date == date]
        asia = day_h1[(day_h1.index.hour >= 0) & (day_h1.index.hour < 8)]
        scan_window = day_h1[(day_h1.index.hour >= cfg["scan_start"]) & (day_h1.index.hour < cfg["scan_end"])]

        if len(asia) < 3 or len(scan_window) < 2:
            continue

        ah = asia["mid_high"].max()
        al = asia["mid_low"].min()
        ar = ah - al

        if ar < cfg["asia_min_range"]:
            continue

        bias = daily_bias.get(date, "none")

        # Detect ALL sweeps in scan window
        sweeps = []
        for i in range(len(scan_window)):
            bh = scan_window["mid_high"].iloc[i]
            bl = scan_window["mid_low"].iloc[i]
            bc = scan_window["mid_close"].iloc[i]

            if bh > ah + cfg["sweep_threshold"] and bc < ah:
                sweeps.append(("bearish", bh, scan_window.index[i]))
            elif bl < al - cfg["sweep_threshold"] and bc > al:
                sweeps.append(("bullish", bl, scan_window.index[i]))

        if not sweeps:
            continue

        # Process each sweep (up to max_trades_per_day)
        day_trades = 0
        max_per_day = cfg.get("max_trades_per_day", 3)

        for sweep_dir, sweep_wick, sweep_time in sweeps:
            if day_trades >= max_per_day:
                break

            # Bias filter (Variant C: neutral = allow both directions)
            if bias != "neutral":
                if sweep_dir == "bullish" and bias != "bullish":
                    continue
                if sweep_dir == "bearish" and bias != "bearish":
                    continue

            # Find M3 engulfing within window
            end_time = sweep_time + pd.Timedelta(hours=cfg["engulfing_window_hours"])
            m3_window = gold_m3[(gold_m3.index > sweep_time) & (gold_m3.index <= end_time)]

            if len(m3_window) < 3:
                continue

            start_idx = 2 if cfg["skip_first_bar"] else 1

            for j in range(start_idx, len(m3_window)):
                idx = gold_m3.index.get_loc(m3_window.index[j])
                co = gold_m3["mid_open"].iat[idx]
                cc = gold_m3["mid_close"].iat[idx]
                po = gold_m3["mid_open"].iat[idx - 1]
                pc = gold_m3["mid_close"].iat[idx - 1]
                br = gold_m3["mid_high"].iat[idx] - gold_m3["mid_low"].iat[idx]

                ct = max(co, cc)
                cb = min(co, cc)
                pt = max(po, pc)
                pb = min(po, pc)

                tol = ENGULFING_TOLERANCE
                if sweep_dir == "bullish" and not (cc > co and cb <= pb + tol and ct >= pt - tol):
                    continue
                if sweep_dir == "bearish" and not (cc < co and cb <= pb + tol and ct >= pt - tol):
                    continue

                if sweep_dir == "bullish":
                    entry = gold_m3["ask_close"].iat[idx] + slippage(br)
                    slv = sweep_wick - cfg["sl_buffer"]
                    risk = entry - slv

                    if risk < cfg["min_sl"]:
                        slv = entry - cfg["min_sl"]
                        risk = cfg["min_sl"]

                    if risk < 0.3 or risk > ar * 0.8:
                        continue

                    tp_buf = cfg.get("tp_structure_buffer", ar * cfg["tp_multiplier"])
                    tpv = ah - tp_buf
                    if tpv - entry < risk * rr_lower_bound:
                        continue

                    signals.append(Signal(
                        date=gold_m3.index[idx],
                        entry=entry, sl=slv, tp=tpv,
                        direction="long", risk=risk,
                        strategy="alpha_sweep", max_bars=cfg["max_bars"], timeframe="M3",
                        metadata={"asia_high": ah, "asia_low": al, "sweep_dir": sweep_dir, "sweep_wick": sweep_wick},
                    ))
                else:
                    entry = gold_m3["bid_close"].iat[idx] - slippage(br)
                    slv = sweep_wick + cfg["sl_buffer"]
                    risk = slv - entry

                    if risk < cfg["min_sl"]:
                        slv = entry + cfg["min_sl"]
                        risk = cfg["min_sl"]

                    if risk < 0.3 or risk > ar * 0.8:
                        continue

                    tp_buf = cfg.get("tp_structure_buffer", ar * cfg["tp_multiplier"])
                    tpv = al + tp_buf
                    if entry - tpv < risk * rr_lower_bound:
                        continue

                    signals.append(Signal(
                        date=gold_m3.index[idx],
                        entry=entry, sl=slv, tp=tpv,
                        direction="short", risk=risk,
                        strategy="alpha_sweep", max_bars=cfg["max_bars"], timeframe="M3",
                        metadata={"asia_high": ah, "asia_low": al, "sweep_dir": sweep_dir, "sweep_wick": sweep_wick},
                    ))

                day_trades += 1
                break  # One engulfing per sweep

    return signals
