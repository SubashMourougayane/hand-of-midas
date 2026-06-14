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
    anti_trend_threshold: float | None = None,
    anti_trend_lookback_h: int = 4,
) -> list[Signal]:
    """
    Generate Alpha-Sweep signals.
    gold_h1: H1 candles with session labels (needs 'session_asia', 'session_london' columns or use hour filter)
    gold_m3: M3 candles with bid/ask
    daily_bias: {date: 'bullish'|'bearish'} from previous day close
    anti_trend_threshold: Filter #4 — skip entry if prior `lookback_h` H1 close-to-close
      move exceeds threshold × ATR_14 in the SAME direction as the entry.
      None or 0 = no filter (legacy). Typical values 1.5/2.0/2.5.
    anti_trend_lookback_h: H1 bars to use for the "recent move" measurement (default 4).
    """
    cfg = ALPHA_SWEEP
    if anti_trend_threshold is None:
        anti_trend_threshold = cfg.get("anti_trend_threshold", 0.0)
    signals = []

    if anti_trend_threshold > 0:
        _h1_hl = gold_h1["mid_high"] - gold_h1["mid_low"]
        _h1_hp = (gold_h1["mid_high"] - gold_h1["mid_close"].shift(1)).abs()
        _h1_lp = (gold_h1["mid_low"] - gold_h1["mid_close"].shift(1)).abs()
        _h1_tr = pd.concat([_h1_hl, _h1_hp, _h1_lp], axis=1).max(axis=1)
        atr_h1 = _h1_tr.rolling(14, min_periods=14).mean()
    else:
        atr_h1 = None

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

                # Filter #4: skip if prior N-hour move already extended in the entry direction
                if anti_trend_threshold > 0 and atr_h1 is not None:
                    sig_ts = gold_m3.index[idx]
                    h1_now = atr_h1.index.asof(sig_ts)
                    if h1_now is not None:
                        atr_val = atr_h1.loc[h1_now]
                        if not pd.isna(atr_val) and atr_val > 0:
                            prior_close = gold_h1["mid_close"].asof(sig_ts - pd.Timedelta(hours=anti_trend_lookback_h))
                            curr_close = gold_h1["mid_close"].asof(sig_ts)
                            if prior_close is not None and curr_close is not None and not pd.isna(prior_close) and not pd.isna(curr_close):
                                move = curr_close - prior_close
                                # bullish sweep -> LONG entry: skip if move already > threshold*ATR up
                                if sweep_dir == "bullish" and move > anti_trend_threshold * atr_val:
                                    continue
                                # bearish sweep -> SHORT entry: skip if move already < -threshold*ATR down
                                if sweep_dir == "bearish" and move < -anti_trend_threshold * atr_val:
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
                    if tpv - entry < risk * 0.8:
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
                    if entry - tpv < risk * 0.8:
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
