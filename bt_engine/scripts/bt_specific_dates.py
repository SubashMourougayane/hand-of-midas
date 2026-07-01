"""Run A+D backtest for two specific dates: 2026-06-23 and 2026-06-30.

Jun 23 → OANDA parquet (M5 → resample M15)
Jun 30 → DWX live bars (M15 native, UTC-adjusted)

Uses IDENTICAL strategy code as live runner. Prints every event + trade with
full detail. Pure parity — no look-ahead, no execution shortcut.

To warm the pivot tracker / regime / prev-bar cache before the target day,
we load and replay a 5-day pre-window through on_bar, discard events, then
capture events + trades only on the target day.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bt_engine.core.bar import Bar
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.core.signal import StrategyEvent
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD

from tests.parity._fib_v2_helper import InMemoryClock, InMemoryProvider


DWX_PATH = Path("/Users/subash/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX/bars_XAUUSD_ecn_M15.json")
OANDA_M5 = Path("/tmp/oanda_xau_m5.parquet")


def load_dwx_m15() -> pd.DataFrame:
    """DWX bars → UTC-labeled M15."""
    raw = json.loads(DWX_PATH.read_text())
    rows = []
    for b in raw:
        ts = datetime.strptime(b["time"], "%Y.%m.%d %H:%M:%S") - timedelta(hours=3)
        rows.append({
            "timestamp": ts.replace(tzinfo=timezone.utc),
            "open": float(b["open"]),
            "high": float(b["high"]),
            "low": float(b["low"]),
            "close": float(b["close"]),
            "volume": float(b.get("volume", 0) or 0),
        })
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def load_oanda_m15() -> pd.DataFrame:
    """OANDA M5 parquet → resample M15."""
    m5 = pd.read_parquet(OANDA_M5)
    if m5["timestamp"].dt.tz is None:
        m5["timestamp"] = m5["timestamp"].dt.tz_localize("UTC")
    m5 = m5.sort_values("timestamp").reset_index(drop=True)
    idx = m5.set_index("timestamp")
    m15 = idx.resample("15min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    return m15


def run_leg(StrategyCls, m15: pd.DataFrame, day_start: pd.Timestamp,
            day_end: pd.Timestamp, max_bars_held: int, label: str) -> None:
    """Replay full history; only print/capture events + trades on the target day."""
    provider = InMemoryProvider(m15, symbol="XAUUSD.ecn", timeframe="M15")
    clock = InMemoryClock(provider)
    strat = StrategyCls(symbol="XAUUSD.ecn")

    day_events = []
    day_trades_open = []
    day_trades_close = []

    def _on_event(ev: StrategyEvent) -> None:
        bar_ts_str = ev.detail.get("bar_ts")
        if not bar_ts_str:
            return
        try:
            bar_ts = pd.Timestamp(bar_ts_str)
            if bar_ts.tzinfo is None:
                bar_ts = bar_ts.tz_localize("UTC")
        except Exception:
            return
        if day_start <= bar_ts < day_end:
            day_events.append(ev)

    def _on_open(trade) -> None:
        ts = pd.Timestamp(trade.entry_timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        if day_start <= ts < day_end:
            day_trades_open.append(trade)

    def _on_close(trade, outcome) -> None:
        ts = pd.Timestamp(trade.entry_timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        if day_start <= ts < day_end:
            day_trades_close.append((trade, outcome))

    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_trade_open=_on_open,
        on_trade_close=_on_close,
        on_strategy_event=_on_event,
        max_bars_held=max_bars_held,
    )
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")

    print(f"\n─── {label} · {day_start.date()} ───")
    types = {}
    for ev in day_events:
        types[ev.type] = types.get(ev.type, 0) + 1
    for t in sorted(types.keys()):
        print(f"  {t}: {types[t]}")
    print(f"  Total events on day: {len(day_events)}")
    print(f"  Trades opened on day: {len(day_trades_open)}")
    print(f"  Trades closed on day (entry within day): {len(day_trades_close)}")

    if day_trades_open:
        print("\n  ── Trades opened ──")
        for tr in day_trades_open:
            leg = tr.order.extra.get("leg")
            side_str = "LONG" if tr.side > 0 else "SHORT"
            print(f"    {tr.entry_timestamp} · {side_str} · {leg} · entry ${tr.entry_price:.2f} "
                  f"SL ${tr.stop_price:.2f} TP ${tr.take_profit:.2f} risk ${tr.risk_units:.2f}")

    if day_trades_close:
        print("\n  ── Trades closed (entered same day) ──")
        for tr, oc in day_trades_close:
            cost_r = tr.order.extra.get("cost_r", 0.0)
            net_r = oc.bracket_1r_outcome - cost_r
            side_str = "LONG" if tr.side > 0 else "SHORT"
            print(f"    entry {tr.entry_timestamp} → exit {oc.exit_timestamp} · {side_str} · "
                  f"{oc.reason} · gross_R {oc.bracket_1r_outcome:+.2f} net_R {net_r:+.3f}")

    if day_events:
        # Show the SIGNAL_PASSED ones if any
        passed = [ev for ev in day_events if ev.type == "GATE_SIGNAL_PASSED"]
        if passed:
            print(f"\n  ── {len(passed)} SIGNAL_PASSED events ──")
            for ev in passed:
                d = ev.detail
                print(f"    {d.get('bar_ts')} · {d.get('leg')} · pattern={d.get('pattern')}")


def run_day(m15: pd.DataFrame, target_date: str, source: str) -> None:
    day_start = pd.Timestamp(target_date, tz="UTC")
    day_end = day_start + pd.Timedelta(days=1)
    print(f"\n═══════ TARGET: {target_date}  (source={source}) ═══════")
    day_bars = m15[(m15["timestamp"] >= day_start) & (m15["timestamp"] < day_end)]
    print(f"M15 bars on {target_date}: {len(day_bars)}")
    if day_bars.empty:
        print("  no bars for this day, skipping")
        return
    print(f"  price range: ${day_bars['low'].min():.2f} → ${day_bars['high'].max():.2f}")
    print(f"  first bar: {day_bars['timestamp'].iloc[0]}  last: {day_bars['timestamp'].iloc[-1]}")

    run_leg(FibV2IntradayA, m15, day_start, day_end, max_bars_held=96, label="A LEG · LONG")
    run_leg(FibV2IntradayD, m15, day_start, day_end, max_bars_held=192, label="D LEG · SHORT")


def main():
    print("Loading OANDA M5 → M15…")
    oanda_m15 = load_oanda_m15()
    print(f"  OANDA M15 range: {oanda_m15['timestamp'].min()} → {oanda_m15['timestamp'].max()}")
    print(f"  OANDA M15 bars: {len(oanda_m15):,}")

    run_day(oanda_m15, "2026-06-23", "OANDA")
    run_day(oanda_m15, "2026-06-30", "OANDA")


if __name__ == "__main__":
    main()
