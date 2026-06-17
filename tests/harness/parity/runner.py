"""High-level entry point: run_parity_check(system_key, days=N) → ParityScore.

This module ties the extractor, diff, and score modules together, and
handles the file I/O for input CSVs.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pandas as pd

from .config import SYSTEMS, SystemConfig, DEFAULT_DAYS
from .extractor import extract_backtest_signals, extract_live_signals
from .diff import diff_signals
from .score import score_parity, ParityScore


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))


def _ensure_paths():
    """Make sure backend/ is importable. Mirrors test_12_replay.py."""
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    backend_dir = os.path.join(PROJECT_ROOT, "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


def _load_data(cfg: SystemConfig):
    """Load H1, M3, D CSVs.

    Two CSV column shapes exist in this repo:

    1. Bid/ask shape: bid_open, bid_high, ..., ask_close. Used by gold files.
       backend.data.cache.load_candles() handles this and synthesizes mid_*.

    2. Plain OHLC shape: open, high, low, close, volume. Used by some oil
       files (BCO_USD_D.csv has this shape). backend.data.cache.load_candles
       leaves the DataFrame WITHOUT mid_* columns in this case, which the
       per-system backtest engines then fail on with KeyError 'mid_high'.

    We use load_candles() for shape (1) and post-process to add mid_*
    columns for shape (2). This keeps us out of production-code edits.
    """
    _ensure_paths()
    from backend.data.cache import load_candles
    h1_df = _ensure_mid_columns(load_candles(cfg.h1_csv))
    m3_df = _ensure_mid_columns(load_candles(cfg.m3_csv))
    d_df = _ensure_mid_columns(load_candles(cfg.daily_csv))
    return h1_df, m3_df, d_df


def _ensure_mid_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add mid_* and bid_*/ask_* columns when the CSV had only plain OHLC.

    Mirrors the fallback in backend-oil-micro/backtest/engine.py:_load_candles
    so a plain-OHLC daily file like BCO_USD_D.csv works with strategy code
    that expects mid_high / mid_low / mid_close / mid_open and the bid/ask
    pair columns.
    """
    if "mid_open" in df.columns:
        return df
    if "open" not in df.columns:
        # Unrecognized shape; let downstream raise its own error.
        return df
    df = df.copy()
    df["mid_open"] = df["open"]
    df["mid_high"] = df["high"]
    df["mid_low"] = df["low"]
    df["mid_close"] = df["close"]
    # The strategy code also peeks at bid_*/ask_* directly when computing
    # entry slippage. Synthesize them at zero spread.
    for side in ("bid", "ask"):
        for px in ("open", "high", "low", "close"):
            df[f"{side}_{px}"] = df[px]
    return df


def _build_daily_bias(d_df: pd.DataFrame) -> dict:
    """Reproduce conftest.py:daily_bias fixture. Combined V1+V2 like prod.

    Note (2026-06-12 drift-bug #6 fix): OANDA dailyAlignment=21 means a bar with
    timestamp T 21:00 represents the trading session (T 21:00 → (T+1) 21:00), so
    its `.date()` is one day BEFORE the session it represents. Strategy code looks
    up `daily_bias[trade_date]` expecting yesterday's bias. Therefore key by
    `bar.date() + 1day` so that the entry for trade-date D is computed from the
    bar representing (D-1) session = true yesterday.
    """
    bias = {}
    for i in range(1, len(d_df)):
        d = (d_df.index[i] + pd.Timedelta(days=1)).date()
        prev_range = d_df["mid_high"].iat[i - 1] - d_df["mid_low"].iat[i - 1]
        if prev_range <= 0:
            continue
        prev_close = d_df["mid_close"].iat[i - 1]
        prev_open = d_df["mid_open"].iat[i - 1]
        prev_low = d_df["mid_low"].iat[i - 1]
        # V1: body% > 40%
        body_pct = abs(prev_close - prev_open) / prev_range
        v1 = "neutral"
        if body_pct >= 0.4:
            v1 = "bullish" if prev_close > prev_open else "bearish"
        # V2: close in top/bottom 20%
        close_pos = (prev_close - prev_low) / prev_range
        v2 = "neutral"
        if close_pos >= 0.8:
            v2 = "bullish"
        elif close_pos <= 0.2:
            v2 = "bearish"
        if v1 == "bearish" or v2 == "bearish":
            bias[d] = "bearish"
        elif v1 == "bullish" or v2 == "bullish":
            bias[d] = "bullish"
        else:
            bias[d] = "neutral"
    return bias


def _resolve_system_bias_mode(cfg) -> str:
    """F28-H3: read this system's BIAS_MODE config to know whether to swap
    daily_bias for NeutralBiasDict in the parity comparison.

    Returns "production" or "neutral". Defaults to "production" if anything
    fails (config import error, attribute missing, etc.) — the harness must
    not break on F28 config issues; the parity check itself will surface
    drift if the live system is actually running with a flipped bias.
    """
    import importlib
    try:
        # cfg.config_module_path is e.g. "config" or "backend.config".
        # For service-relative configs (3 of 4), the system's sys.path has
        # been injected by extractor.py before this is called.
        mod = importlib.import_module(cfg.config_module_path)
        return getattr(mod, "BIAS_MODE", "production")
    except Exception:
        return "production"


def run_parity_check(
    system_key: str,
    days: int = DEFAULT_DAYS,
) -> ParityScore:
    """Run one full parity comparison for a system, return the ParityScore.

    Steps:
    1. Load CSV data (H1, M3, D).
    2. Build daily_bias dict.
    3. F28-H3: if this system's BIAS_MODE=="neutral", swap daily_bias for
       NeutralBiasDict so the BT comparison mirrors live behavior.
    4. Slice to last `days` days.
    5. Run BT signal-gen → list[SignalRecord].
    6. Replay live signal-gen → list[SignalRecord].
    7. Diff and score.

    The function does not write JSON itself (that's the caller's job, e.g.
    test_22_parity.py calls score.write_json()).
    """
    if system_key not in SYSTEMS:
        raise ValueError(f"Unknown system_key: {system_key}. Known: {sorted(SYSTEMS)}")
    cfg = SYSTEMS[system_key]

    h1_full, m3_full, d_full = _load_data(cfg)
    daily_bias = _build_daily_bias(d_full)

    # F28-H3 — bias-mode mirroring.
    # If this system has BIAS_MODE=neutral live, the live core fn will fire
    # signals that V1+V2 would block. Without this mirror, BT side keeps
    # blocking → harness shows drift on every run (false positive). Swap
    # the bias dict for NeutralBiasDict on BOTH sides so the comparison
    # measures genuine live↔BT drift, not the F28 setting itself.
    bias_mode = _resolve_system_bias_mode(cfg)
    if bias_mode == "neutral":
        # Late-import so the harness doesn't fail to load when running on
        # an older branch without neutral_bias.py. Swallow any ImportError
        # and fall back to V1+V2 (better signal than crash).
        try:
            from backend.backtest.neutral_bias import NeutralBiasDict
            daily_bias = NeutralBiasDict()
            print(f"  [parity] F28-aware: {system_key} BIAS_MODE=neutral → "
                  f"swapping daily_bias for NeutralBiasDict on both sides")
        except ImportError:
            print(f"  [parity] WARNING: {system_key} BIAS_MODE=neutral but "
                  f"NeutralBiasDict unavailable; falling back to V1+V2 — "
                  f"parity report may show false drift")

    # Window the data to last `days` days. Use the M3 file's last timestamp
    # as the reference (it's the freshest source).
    last_ts = m3_full.index[-1]
    cutoff = last_ts - pd.Timedelta(days=days)
    h1_df = h1_full[h1_full.index >= cutoff]
    m3_df = m3_full[m3_full.index >= cutoff]

    if len(h1_df) < 6 or len(m3_df) < 50:
        # Insufficient data for meaningful comparison. Return an empty score
        # with a clear marker rather than raising — the soft gate will treat
        # this as "warning level" since BT count = Live count = 0.
        return score_parity(
            system=system_key,
            date_range=(cutoff.date(), last_ts.date()),
            diffs=[],
            sweep_threshold=cfg.sweep_threshold,
            data_files=(cfg.h1_csv, cfg.m3_csv, cfg.daily_csv),
        )

    # 1) Backtest signals: pass the windowed slice so BT only emits signals
    #    within our parity window. BT walks bars internally; it doesn't need
    #    extra history beyond what's in the window.
    bt_records = extract_backtest_signals(
        system_key=system_key,
        backtest_module_path=cfg.backtest_module_path,
        backtest_fn_name=cfg.backtest_fn_name,
        h1_df=h1_df,
        m3_df=m3_df,
        daily_bias=daily_bias,
    )

    # 2) Live signals. Pass h1/m3 with one-day prefix so first-day lookback
    #    is realistic (24 h1 bars + 50 m3 bars need history older than the
    #    earliest evaluated bar). One-day prefix is enough; passing full
    #    history makes per-bar tail() calls 3x slower without changing
    #    parity output (verified empirically on May 2026 data).
    live_lookback_cutoff = cutoff - pd.Timedelta(days=2)
    h1_for_live = h1_full[h1_full.index >= live_lookback_cutoff]
    m3_for_live = m3_full[m3_full.index >= live_lookback_cutoff]
    live_records = extract_live_signals(
        system_key=system_key,
        live_module_path=cfg.live_module_path,
        live_core_fn_name=cfg.live_core_fn_name,
        h1_df=h1_for_live,
        m3_df=m3_for_live,
        d_df=d_full,
        daily_bias=daily_bias,
        date_range_start=cutoff.date(),
        date_range_end=last_ts.date(),
        architecture=cfg.architecture,
    )

    # 3) Diff
    diffs = diff_signals(bt_records, live_records)

    # 4) Score
    return score_parity(
        system=system_key,
        date_range=(cutoff.date(), last_ts.date()),
        diffs=diffs,
        sweep_threshold=cfg.sweep_threshold,
        data_files=(cfg.h1_csv, cfg.m3_csv, cfg.daily_csv),
    )
