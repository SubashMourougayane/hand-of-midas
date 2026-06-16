"""Oil Micro backtest engine — rolling 4hr windows on BCO_USD with Combined V1+V2 bias."""
import numpy as np
import pandas as pd
import time
from datetime import timedelta
from dataclasses import dataclass, field
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.strategies.base import Signal
from backend.execution.limit_price import compute_limit_price
from config import YEARLY_CAPITAL, RISK_PCT, MAX_UNITS, STRATEGY_RISK, MICRO_ALPHA_SWEEP, ENGULFING_TOLERANCE, DATA_DIR

_DATA_CACHE = {}


def _load_candles(filename: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, filename)
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed")
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    if "bid_open" in df.columns and "ask_open" in df.columns:
        df["mid_open"] = (df["bid_open"] + df["ask_open"]) / 2
        df["mid_high"] = (df["bid_high"] + df["ask_high"]) / 2
        df["mid_low"] = (df["bid_low"] + df["ask_low"]) / 2
        df["mid_close"] = (df["bid_close"] + df["ask_close"]) / 2
    elif "open" in df.columns:
        df["mid_open"] = df["open"]
        df["mid_high"] = df["high"]
        df["mid_low"] = df["low"]
        df["mid_close"] = df["close"]
        df["bid_open"] = df["open"]
        df["bid_high"] = df["high"]
        df["bid_low"] = df["low"]
        df["bid_close"] = df["close"]
        df["ask_open"] = df["open"]
        df["ask_high"] = df["high"]
        df["ask_low"] = df["low"]
        df["ask_close"] = df["close"]
    return df


def _get_cached_data():
    if not _DATA_CACHE:
        t0 = time.time()
        _DATA_CACHE["oil_d"] = _load_candles("BCO_USD_D.csv")
        _DATA_CACHE["oil_h1"] = _load_candles("BCO_USD_H1.csv")
        _DATA_CACHE["oil_m3"] = _load_candles("BCO_USD_M3.csv")
        print(f"  Oil Micro data loaded in {time.time()-t0:.1f}s (H1={len(_DATA_CACHE['oil_h1'])}, M3={len(_DATA_CACHE['oil_m3'])})")
    return _DATA_CACHE


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
        if len(day_h1) < 6:
            continue

        bias = daily_bias.get(date, "neutral")
        day_trades = 0
        max_per_day = cfg["max_trades_per_day"]
        traded_sweeps = set()

        for bar_ts, bar in day_h1.iterrows():
            if day_trades >= max_per_day:
                break

            now_hour = bar_ts.hour

            if cfg["market_close_start"] <= now_hour < cfg["market_close_end"]:
                continue

            for start_hour in range(0, 24, cfg["scan_gap_hours"]):
                if day_trades >= max_per_day:
                    break

                end_hour = (start_hour + cfg["consol_hours"]) % 24
                scan_end_hour = (start_hour + cfg["consol_hours"] + cfg["scan_after_hours"]) % 24

                consol_hours = _hours_in_range(start_hour, end_hour)
                if close_start in consol_hours:
                    continue

                if not _hour_past(now_hour, end_hour):
                    continue

                if _hour_past(now_hour, scan_end_hour):
                    continue

                consol = day_h1[day_h1.index.hour.isin(consol_hours)]
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
                    if day_trades >= max_per_day:
                        break

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

                    eng_end = sbar_ts + timedelta(hours=cfg["engulfing_window_hours"])
                    m3_window = oil_m3[(oil_m3.index > sbar_ts) & (oil_m3.index <= eng_end)]
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
                                          "consol_range": consol_range, "window": f"{start_hour}-{end_hour}"},
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
                                          "consol_range": consol_range, "window": f"{start_hour}-{end_hour}"},
                            ))

                        traded_sweeps.add(sk)
                        day_trades += 1
                        found = True
                        break

                    if not found:
                        traded_sweeps.add(sk)
                    if found:
                        break
                if day_trades >= max_per_day:
                    break

    return signals


@dataclass
class BacktestTrade:
    date: str
    year: int
    month: int
    strategy: str
    direction: str
    entry: float
    sl: float
    tp: float
    exit_price: float
    pnl_unit: float
    pnl_sized: float
    units: float
    status: str
    bars_held: int
    hold_human: str
    risk: float
    r_mult: float
    equity_after: float


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    total_pnl: float = 0
    win_rate: float = 0
    profit_factor: float = 0
    max_drawdown_pct: float = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    # Filter #27 — limit-order entry stats. would_have_won_count is INFORMATIONAL
    # LOOKAHEAD; do not use it to rank variants in ship decisions.
    missed_signals: int = 0
    would_have_won_count: int = 0
    total_signals: int = 0
    filled_signals: int = 0


def _execute_trade(df, bar_start, entry, sl, tp, direction, max_bars, use_break_even=True,
                   be_trigger_pct=0.5, trail_after_be_pct=0.0,
                   partial_tp_at_pct=0.0, partial_tp_size=0.0, partial_arms_be=False,
                   entry_mode="market", limit_price=None, limit_ttl_bars=0,
                   limit_fill_strict=False):
    """Simple fill model for Oil Micro — walks M3 bars.

    be_trigger_pct: fraction of distance to TP that triggers BE move.
      Default 0.5 (production), Filter #5 ships 0.35.
    trail_after_be_pct: post-BE trail fraction. 0.0 = no trail (legacy).
      Filter #6 tests 0.5 (high-water-mark, ratchets only in favorable direction).
    partial_tp_at_pct / partial_tp_size: Filter #7. Bank `partial_tp_size`
      of position at `entry + partial_tp_at_pct × (tp − entry)`. 0.0 = off.
    partial_arms_be: Variant B. Partial fire also arms BE on that bar.
    """
    # Filter #27: limit-order entry pre-walk. Mirrors backend/execution/fill_model.py.
    if entry_mode == "limit" and limit_ttl_bars > 0 and limit_price is not None:
        fill_bar_idx = None
        ttl_end = min(bar_start + limit_ttl_bars, len(df) - 1)
        for fb in range(bar_start + 1, ttl_end + 1):
            if direction == "long":
                bid_low = df["bid_low"].iat[fb] if "bid_low" in df.columns else df["mid_low"].iat[fb]
                bid_close = df["bid_close"].iat[fb] if "bid_close" in df.columns else df["mid_close"].iat[fb]
                touched = bid_low <= limit_price
                sustained = bid_close <= limit_price
            else:
                ask_high = df["ask_high"].iat[fb] if "ask_high" in df.columns else df["mid_high"].iat[fb]
                ask_close = df["ask_close"].iat[fb] if "ask_close" in df.columns else df["mid_close"].iat[fb]
                touched = ask_high >= limit_price
                sustained = ask_close >= limit_price
            if touched and (sustained if limit_fill_strict else True):
                fill_bar_idx = fb
                break
        if fill_bar_idx is None:
            # Lookahead: would have won if filled at limit?
            rng_state = np.random.get_state()
            try:
                hypo = _execute_trade(df, ttl_end, limit_price, sl, tp, direction, max_bars,
                    use_break_even=use_break_even, be_trigger_pct=be_trigger_pct,
                    trail_after_be_pct=trail_after_be_pct,
                    partial_tp_at_pct=partial_tp_at_pct, partial_tp_size=partial_tp_size,
                    partial_arms_be=partial_arms_be, entry_mode="market")
            finally:
                np.random.set_state(rng_state)
            wwl = bool((hypo is not None) and (hypo.get("pnl_per_unit", 0) > 0))
            return {"exit_price": limit_price, "pnl_per_unit": 0.0,
                    "exit_reason": "missed_unfilled", "bars_held": 0,
                    "filled": False, "would_have_won": wwl}
        # Filled — set entry and bar_start to fill bar
        entry = limit_price
        bar_start = fill_bar_idx

    use_partial = (partial_tp_at_pct > 0 and partial_tp_size > 0)
    partial_target = entry + (tp - entry) * partial_tp_at_pct
    partial_done = False
    partial_pnl_per_unit = 0.0
    runner_size = 1.0 - partial_tp_size if use_partial else 1.0
    partial_size = partial_tp_size if use_partial else 0.0

    be_triggered = False
    be_sl = None
    hwm = entry  # post-BE high-water-mark (longs) / low-water-mark (shorts)

    for i in range(1, max_bars + 1):
        idx = bar_start + i
        if idx >= len(df):
            return {"exit_price": entry, "pnl_per_unit": 0, "exit_reason": "DATA_END", "bars_held": i}

        bar_high = df["ask_high"].iat[idx] if "ask_high" in df.columns else df["mid_high"].iat[idx]
        bar_low = df["bid_low"].iat[idx] if "bid_low" in df.columns else df["mid_low"].iat[idx]

        current_sl = be_sl if be_triggered else sl

        if direction == "long":
            if bar_low <= current_sl:
                runner_pnl = current_sl - entry
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                base = "BE_SL" if be_triggered else "SL"
                reason = f"PARTIAL+{base}" if partial_done else base
                return {"exit_price": current_sl, "pnl_per_unit": blended, "exit_reason": reason, "bars_held": i}
            # Partial TP fire (Filter #7)
            if use_partial and not partial_done and bar_high >= partial_target:
                partial_pnl_per_unit = partial_target - entry
                partial_done = True
                if partial_arms_be and not be_triggered:
                    be_triggered = True
                    be_sl = entry + 0.01
                    hwm = bar_high
            if bar_high >= tp:
                runner_pnl = tp - entry
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                reason = "PARTIAL+TP" if partial_done else "TP"
                return {"exit_price": tp, "pnl_per_unit": blended, "exit_reason": reason, "bars_held": i}
            if use_break_even and not be_triggered:
                mid = (bar_high + bar_low) / 2
                target_be = entry + (tp - entry) * be_trigger_pct
                if mid >= target_be:
                    be_triggered = True
                    be_sl = entry + 0.01
                    hwm = bar_high
            # Post-BE trail
            if be_triggered and trail_after_be_pct > 0:
                if bar_high > hwm:
                    hwm = bar_high
                proposed = entry + (hwm - entry) * trail_after_be_pct
                if proposed > be_sl:
                    be_sl = proposed
        else:
            if bar_high >= current_sl:
                runner_pnl = entry - current_sl
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                base = "BE_SL" if be_triggered else "SL"
                reason = f"PARTIAL+{base}" if partial_done else base
                return {"exit_price": current_sl, "pnl_per_unit": blended, "exit_reason": reason, "bars_held": i}
            # Partial TP fire (Filter #7)
            if use_partial and not partial_done and bar_low <= partial_target:
                partial_pnl_per_unit = entry - partial_target
                partial_done = True
                if partial_arms_be and not be_triggered:
                    be_triggered = True
                    be_sl = entry - 0.01
                    hwm = bar_low
            if bar_low <= tp:
                runner_pnl = entry - tp
                blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
                reason = "PARTIAL+TP" if partial_done else "TP"
                return {"exit_price": tp, "pnl_per_unit": blended, "exit_reason": reason, "bars_held": i}
            if use_break_even and not be_triggered:
                mid = (bar_high + bar_low) / 2
                target_be = entry - (entry - tp) * be_trigger_pct
                if mid <= target_be:
                    be_triggered = True
                    be_sl = entry - 0.01
                    hwm = bar_low
            # Post-BE trail (shorts)
            if be_triggered and trail_after_be_pct > 0:
                if bar_low < hwm:
                    hwm = bar_low
                proposed = entry - (entry - hwm) * trail_after_be_pct
                if proposed < be_sl:
                    be_sl = proposed

    # Max hold exit
    exit_idx = min(bar_start + max_bars, len(df) - 1)
    exit_price = df["mid_close"].iat[exit_idx]
    runner_pnl = (exit_price - entry) if direction == "long" else (entry - exit_price)
    blended = partial_pnl_per_unit * partial_size + runner_pnl * runner_size
    reason = "PARTIAL+MAX_HOLD" if partial_done else "MAX_HOLD"
    return {"exit_price": exit_price, "pnl_per_unit": blended, "exit_reason": reason, "bars_held": max_bars}


def run_backtest(
    strategies: list[str] = None,
    start_date: str = "2006-01-01",
    end_date: str = "2026-12-31",
    capital: float = YEARLY_CAPITAL,
    risk_pct: float = RISK_PCT,
    seed: int = 42,
    be_trigger_pct: float | None = None,
    trail_after_be_pct: float | None = None,
    partial_tp_at_pct: float | None = None,
    partial_tp_size: float | None = None,
    partial_arms_be: bool | None = None,
    entry_mode: str | None = None,
    limit_offset_pct=None,
    limit_ttl_bars: int | None = None,
    limit_fill_strict: bool | None = None,
) -> BacktestResult:
    """Run Oil Micro portfolio backtest.

    be_trigger_pct: BE trigger fraction override. None = read from MICRO_ALPHA_SWEEP config.
    trail_after_be_pct: post-BE trail fraction override. None = read from config.
    partial_tp_at_pct / partial_tp_size: Filter #7 overrides (None = config default).
    partial_arms_be: Filter #7 Variant B (None = config default).
    entry_mode/limit_offset_pct/limit_ttl_bars/limit_fill_strict: Filter #27.
      See backend/backtest/engine.py for full semantics.
    """
    if be_trigger_pct is None:
        be_trigger_pct = MICRO_ALPHA_SWEEP["be_trigger_pct"]
    if trail_after_be_pct is None:
        trail_after_be_pct = MICRO_ALPHA_SWEEP.get("trail_after_be_pct", 0.0)
    if partial_tp_at_pct is None:
        partial_tp_at_pct = MICRO_ALPHA_SWEEP.get("partial_tp_at_pct", 0.0)
    if partial_tp_size is None:
        partial_tp_size = MICRO_ALPHA_SWEEP.get("partial_tp_size", 0.0)
    if partial_arms_be is None:
        partial_arms_be = MICRO_ALPHA_SWEEP.get("partial_arms_be", False)
    if entry_mode is None:
        entry_mode = MICRO_ALPHA_SWEEP.get("entry_mode", "market")
    if limit_offset_pct is None:
        limit_offset_pct = MICRO_ALPHA_SWEEP.get("limit_offset_pct", 0.0)
    if limit_ttl_bars is None:
        limit_ttl_bars = MICRO_ALPHA_SWEEP.get("limit_ttl_bars", 0)
    if limit_fill_strict is None:
        limit_fill_strict = MICRO_ALPHA_SWEEP.get("limit_fill_strict", False)
    np.random.seed(seed)

    data = _get_cached_data()
    oil_d = data["oil_d"]
    oil_h1 = data["oil_h1"]
    oil_m3 = data["oil_m3"]

    # Pre-filter data to date range
    filter_start = pd.Timestamp(start_date, tz="UTC") - pd.Timedelta(days=60)
    filter_end = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=30)
    oil_h1_filtered = oil_h1[(oil_h1.index >= filter_start) & (oil_h1.index <= filter_end)]
    oil_m3_filtered = oil_m3[(oil_m3.index >= filter_start) & (oil_m3.index <= filter_end)]

    # Daily bias — Combined V1+V2
    daily_bias = {}
    for i in range(1, len(oil_d)):
        # OANDA dailyAlignment=21: bar at T 21:00 represents (T → T+1) session,
        # so trade-date = bar.date() + 1day; oil_d[i-1] = true yesterday's bar. See parity audit
        # 2026-06-12 (drift bug #6).
        d = (oil_d.index[i] + pd.Timedelta(days=1)).date()
        prev_range = oil_d["mid_high"].iat[i - 1] - oil_d["mid_low"].iat[i - 1]
        if prev_range > 0:
            body_pct = abs(oil_d["mid_close"].iat[i - 1] - oil_d["mid_open"].iat[i - 1]) / prev_range
            v1_bias = "neutral"
            if body_pct >= 0.4:
                v1_bias = "bullish" if oil_d["mid_close"].iat[i - 1] > oil_d["mid_open"].iat[i - 1] else "bearish"
            close_position = (oil_d["mid_close"].iat[i - 1] - oil_d["mid_low"].iat[i - 1]) / prev_range
            v2_bias = "neutral"
            if close_position >= 0.8:
                v2_bias = "bullish"
            elif close_position <= 0.2:
                v2_bias = "bearish"
            if v1_bias == "bearish" or v2_bias == "bearish":
                daily_bias[d] = "bearish"
            elif v1_bias == "bullish" or v2_bias == "bullish":
                daily_bias[d] = "bullish"
            else:
                daily_bias[d] = "neutral"
        else:
            daily_bias[d] = "neutral"

    # Generate signals
    np.random.seed(seed)
    all_signals = generate_signals(oil_h1_filtered, oil_m3_filtered, daily_bias)
    all_signals.sort(key=lambda x: x.date)

    # Filter by date range
    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC")
    all_signals = [s for s in all_signals if start_ts <= s.date <= end_ts]

    # Execute with DD protection
    DAILY_MAX_LOSS = 400
    COOLDOWN_SECONDS = 300

    np.random.seed(seed)
    equity = capital
    peak_equity = capital
    consecutive_losses = 0
    pause_counter = 0
    equity_history = []
    trades: list[BacktestTrade] = []
    current_year = None
    current_date = None
    daily_pnl = 0.0
    last_signal_time = None
    position_exit_time = None
    # Filter #27 accumulators (micro_alpha_sweep_oil; Oil Micro is single-strategy)
    _filter27_missed_local = 0
    _filter27_wwl_local = 0
    _filter27_total_local = 0
    _filter27_filled_local = 0

    for signal in all_signals:
        trade_date = signal.date.date()
        trade_year = trade_date.year

        if trade_year != current_year:
            equity = capital
            peak_equity = capital
            consecutive_losses = 0
            pause_counter = 0
            equity_history = []
            current_year = trade_year
            daily_pnl = 0.0
            current_date = None

        if trade_date != current_date:
            daily_pnl = 0.0
            current_date = trade_date

        if last_signal_time and (signal.date - last_signal_time).total_seconds() < COOLDOWN_SECONDS:
            continue

        if position_exit_time and signal.date < position_exit_time:
            continue

        if daily_pnl <= -DAILY_MAX_LOSS:
            continue

        if equity < 100:
            continue

        if pause_counter > 0:
            pause_counter -= 1
            continue

        risk_mult = 1.0
        if consecutive_losses >= 3:
            risk_mult = 0.5
        if len(equity_history) >= 20:
            eq_ma = np.mean(equity_history[-20:])
            if equity < eq_ma:
                risk_mult *= 0.5

        strat_risk = STRATEGY_RISK.get("micro_alpha_sweep_oil", risk_pct)
        risk_dollar = equity * (strat_risk / 100) * risk_mult
        if signal.risk <= 0:
            continue
        units = min(risk_dollar / signal.risk, MAX_UNITS)

        try:
            bar_idx = oil_m3.index.get_loc(signal.date)
        except KeyError:
            continue

        # Filter #27 — compute limit_price per variant (Oil Micro = always micro_alpha_sweep_oil).
        # Uses the shared helper for live↔BT parity. See backend/execution/limit_price.py.
        use_limit = (entry_mode == "limit" and limit_ttl_bars > 0)
        limit_price = None
        if use_limit:
            limit_price = compute_limit_price(
                direction=signal.direction,
                signal_entry=signal.entry,
                signal_risk=signal.risk,
                engulf_close_ask=oil_m3["ask_close"].iat[bar_idx],
                engulf_close_bid=oil_m3["bid_close"].iat[bar_idx],
                limit_offset_pct=limit_offset_pct,
            )

        # Filter #27: count signals reaching execute_trade
        _filter27_total_local += 1

        result = _execute_trade(
            df=oil_m3,
            bar_start=bar_idx,
            entry=signal.entry,
            sl=signal.sl,
            tp=signal.tp,
            direction=signal.direction,
            max_bars=signal.max_bars,
            use_break_even=True,
            be_trigger_pct=be_trigger_pct,
            trail_after_be_pct=trail_after_be_pct,
            partial_tp_at_pct=partial_tp_at_pct,
            partial_tp_size=partial_tp_size,
            partial_arms_be=partial_arms_be,
            entry_mode="limit" if use_limit else "market",
            limit_price=limit_price,
            limit_ttl_bars=limit_ttl_bars if use_limit else 0,
            limit_fill_strict=limit_fill_strict if use_limit else False,
        )

        if result is None:
            continue

        # Filter #27: missed limit order — count, do NOT advance cooldown/position_exit_time
        if not result.get("filled", True):
            _filter27_missed_local += 1
            if result.get("would_have_won"):
                _filter27_wwl_local += 1
            continue

        # Filter #27: filled
        _filter27_filled_local += 1

        pnl_dollar = result["pnl_per_unit"] * units
        equity += pnl_dollar
        equity = max(equity, 0)
        daily_pnl += pnl_dollar
        last_signal_time = signal.date

        position_exit_time = signal.date + timedelta(seconds=result["bars_held"] * 180)

        if pnl_dollar > 0:
            consecutive_losses = 0
        else:
            consecutive_losses += 1
            if consecutive_losses >= 5:
                pause_counter = 2

        equity_history.append(equity)
        if equity > peak_equity:
            peak_equity = equity

        hold_str = f"{result['bars_held'] * 3}min" if result["bars_held"] < 20 else f"{result['bars_held'] * 3 / 60:.1f}hrs"

        trades.append(BacktestTrade(
            date=signal.date.isoformat(), year=trade_year, month=trade_date.month,
            strategy="micro_alpha_sweep_oil", direction=signal.direction.upper(),
            entry=round(signal.entry, 4), sl=round(signal.sl, 4), tp=round(signal.tp, 4),
            exit_price=round(result["exit_price"], 4),
            pnl_unit=round(result["pnl_per_unit"], 4), pnl_sized=round(pnl_dollar, 2),
            units=round(units, 2), status=result["exit_reason"], bars_held=result["bars_held"],
            hold_human=hold_str, risk=round(signal.risk, 4),
            r_mult=round(result["pnl_per_unit"] / signal.risk, 2) if signal.risk > 0 else 0,
            equity_after=round(equity, 2),
        ))

    # Stats
    result_obj = BacktestResult(trades=trades)
    if trades:
        pnls = [t.pnl_sized for t in trades]
        result_obj.total_trades = len(trades)
        result_obj.wins = sum(1 for p in pnls if p > 0)
        result_obj.losses = result_obj.total_trades - result_obj.wins
        result_obj.win_rate = result_obj.wins / result_obj.total_trades
        result_obj.total_pnl = sum(pnls)
        gross_wins = sum(p for p in pnls if p > 0)
        gross_losses = abs(sum(p for p in pnls if p <= 0))
        result_obj.profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0

        worst_dd = 0.0
        for year in set(t.year for t in trades):
            year_eq = np.array([t.equity_after for t in trades if t.year == year])
            if len(year_eq) < 2:
                continue
            year_peak = np.maximum.accumulate(year_eq)
            year_dd = ((year_eq - year_peak) / year_peak).min()
            if year_dd < worst_dd:
                worst_dd = year_dd
        result_obj.max_drawdown_pct = float(worst_dd * 100)

    # Filter #27 stats
    result_obj.missed_signals = _filter27_missed_local
    result_obj.would_have_won_count = _filter27_wwl_local
    result_obj.total_signals = _filter27_total_local
    result_obj.filled_signals = _filter27_filled_local

    return result_obj
