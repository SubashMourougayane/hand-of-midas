"""Live↔BT purity check.

Reads the SAME DWX M15 bars the live runner consumed, replays them through
FibV2IntradayA + FibV2IntradayD (identical code the live process runs), and
compares emitted gate events against what's persisted in bt_signals for the
current live runs.

If the strategy code is deterministic and mode-invariant (as parity claims),
counts + statuses + close-values should match exactly. Any drift = latent bug.

Usage:
    python3 -m bt_engine.scripts.live_bt_parity
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bt_engine.core.bar import Bar
from bt_engine.core.engine import EngineDeps, run_engine
from bt_engine.core.signal import StrategyEvent
from bt_engine.db.engine import make_engine
from bt_engine.db.models import BtRun, BtSignal
from bt_engine.execution.simulator import BTExecutionModel
from bt_engine.strategies.fib_v2_intraday import FibV2IntradayA, FibV2IntradayD

from tests.parity._fib_v2_helper import InMemoryClock, InMemoryProvider


DB_URL = os.environ.get(
    "BT_ENGINE_DB_URL",
    "postgresql+psycopg2://subash@localhost:5432/golddigger_bt",
)
DWX_DIR = Path("/Users/subash/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX")


def load_dwx_m15() -> pd.DataFrame:
    """Read DWX bars_XAUUSD_ecn_M15.json → UTC-labeled DataFrame."""
    p = DWX_DIR / "bars_XAUUSD_ecn_M15.json"
    raw = json.loads(p.read_text())
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
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    return df


def replay_leg(StrategyCls, m15: pd.DataFrame, cutoff_start: pd.Timestamp,
               max_bars_held: int, label: str) -> dict:
    """Replay full history to warm state, then continue capturing events
    only for bars >= cutoff_start. Mirrors live runner's warmup + live loop."""
    provider = InMemoryProvider(m15, symbol="XAUUSD.ecn", timeframe="M15")
    clock = InMemoryClock(provider)
    strat = StrategyCls(symbol="XAUUSD.ecn")

    captured: list[StrategyEvent] = []

    def _on_event(ev: StrategyEvent) -> None:
        # Only capture events tied to bars >= cutoff_start
        bar_ts_str = ev.detail.get("bar_ts")
        if bar_ts_str is None:
            return
        try:
            bar_ts = pd.Timestamp(bar_ts_str)
            if bar_ts.tzinfo is None:
                bar_ts = bar_ts.tz_localize("UTC")
        except Exception:
            return
        if bar_ts < cutoff_start:
            return
        captured.append(ev)

    deps = EngineDeps(
        clock=clock, data_provider=provider, strategy=strat,
        execution=BTExecutionModel(),
        broker=None, recorder=None, journal=None,
        on_strategy_event=_on_event,
        max_bars_held=max_bars_held,
    )
    import uuid
    run_engine(run_id=uuid.uuid4(), deps=deps, mode="bt")

    # Aggregate
    types = {}
    detail_by_bar = {}  # (bar_ts_iso, status, leg) -> full detail
    for ev in captured:
        types[ev.type] = types.get(ev.type, 0) + 1
        bar_ts = ev.detail.get("bar_ts", "")
        leg = ev.detail.get("leg", "")
        key = (bar_ts, ev.type, leg)
        detail_by_bar[key] = ev.detail

    print(f"[REPLAY {label}] total events post-cutoff: {len(captured)}")
    for t in sorted(types.keys()):
        print(f"  {t}: {types[t]}")

    return {"types": types, "detail_by_bar": detail_by_bar, "events": captured}


def load_live_signals(run_id: str) -> dict:
    """Pull all bt_signals for a live run, group same way as replay."""
    engine_db = make_engine(DB_URL)
    Session = sessionmaker(bind=engine_db, expire_on_commit=False)
    with Session() as s:
        rows = s.execute(
            select(BtSignal).where(BtSignal.run_id == run_id)
                .order_by(BtSignal.ts.asc())
        ).scalars().all()
    types = {}
    detail_by_bar = {}
    for r in rows:
        types[r.status] = types.get(r.status, 0) + 1
        detail = r.detail or {}
        bar_ts = detail.get("bar_ts", "")
        leg = detail.get("leg", "")
        key = (bar_ts, r.status, leg)
        detail_by_bar[key] = detail
    return {"types": types, "detail_by_bar": detail_by_bar, "rows": rows}


def diff_events(live: dict, replay: dict, label: str) -> None:
    print(f"\n=== DIFF {label} ===")
    print(f"live total events:   {sum(live['types'].values())}")
    print(f"replay total events: {sum(replay['types'].values())}")
    print()
    all_types = sorted(set(live["types"].keys()) | set(replay["types"].keys()))
    print(f"{'event_type':<40s} {'live':>8s} {'replay':>8s} {'diff':>6s}")
    for t in all_types:
        l = live["types"].get(t, 0)
        r = replay["types"].get(t, 0)
        d = r - l
        marker = "  ⚠" if d != 0 else ""
        print(f"{t:<40s} {l:>8d} {r:>8d} {d:>+6d}{marker}")

    # Bar-level check: any (bar_ts, type, leg) in one but not other?
    live_keys = set(live["detail_by_bar"].keys())
    replay_keys = set(replay["detail_by_bar"].keys())
    only_live = live_keys - replay_keys
    only_replay = replay_keys - live_keys
    print(f"\nkeys only in live:   {len(only_live)}")
    for k in list(only_live)[:10]:
        print(f"  {k}")
    print(f"keys only in replay: {len(only_replay)}")
    for k in list(only_replay)[:10]:
        print(f"  {k}")

    # Numeric drift on close prices in shared keys
    shared = live_keys & replay_keys
    close_mismatches = 0
    for k in shared:
        ld = live["detail_by_bar"][k]
        rd = replay["detail_by_bar"][k]
        for fld in ("bar_close", "fib_L", "fib_H", "fib_382", "fib_786", "sl_price"):
            lv = ld.get(fld)
            rv = rd.get(fld)
            if lv is None or rv is None:
                continue
            try:
                if abs(float(lv) - float(rv)) > 1e-6:
                    close_mismatches += 1
                    if close_mismatches <= 5:
                        print(f"  drift @ {k[0]} {k[1]}: {fld}  live={lv}  replay={rv}")
            except Exception:
                pass
    print(f"numeric drifts in shared keys: {close_mismatches}")


def main():
    print("Loading DWX M15 bars...")
    m15 = load_dwx_m15()
    print(f"  bars: {len(m15)}  range: {m15.timestamp.min()} → {m15.timestamp.max()}")

    # Cutoff = when live launched (skip pre-launch backlog).
    engine_db = make_engine(DB_URL)
    Session = sessionmaker(bind=engine_db, expire_on_commit=False)
    with Session() as s:
        a_run = s.execute(
            select(BtRun).where(BtRun.strategy_id == "fib_v2_intraday_a")
                .where(BtRun.mode == "live").where(BtRun.end_ts.is_(None))
                .order_by(BtRun.start_ts.desc()).limit(1)
        ).scalar_one()
        d_run = s.execute(
            select(BtRun).where(BtRun.strategy_id == "fib_v2_intraday_d")
                .where(BtRun.mode == "live").where(BtRun.end_ts.is_(None))
                .order_by(BtRun.start_ts.desc()).limit(1)
        ).scalar_one()

    # Live runner skipped bars <= latest_closed_ts at launch.
    # Approximate cutoff = start_ts - 30min (be inclusive).
    cutoff = pd.Timestamp(a_run.start_ts).tz_convert("UTC") - pd.Timedelta(minutes=30)
    print(f"live launched: A={a_run.start_ts}  D={d_run.start_ts}")
    print(f"cutoff for event capture: {cutoff}")

    # Replay both legs
    a_replay = replay_leg(FibV2IntradayA, m15, cutoff, max_bars_held=96, label="A")
    d_replay = replay_leg(FibV2IntradayD, m15, cutoff, max_bars_held=192, label="D")

    # Load live persisted events
    a_live = load_live_signals(a_run.run_id)
    d_live = load_live_signals(d_run.run_id)

    diff_events(a_live, a_replay, "A LEG")
    diff_events(d_live, d_replay, "D LEG")


if __name__ == "__main__":
    main()
