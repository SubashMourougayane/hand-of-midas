"""Replay today's two Gold Micro signals through the live core fn (dry_run)
with runtime-only gates bypassed (max_trades_per_day, startup_cooldown,
_traded_sweeps deduper). This isolates the strategy logic from runtime
state to answer: would the strategy have fired these same signals on a
fresh process given today's market data?"""
import scanner.scheduler as sched
from datetime import datetime, timezone

orig_state = dict(sched._daily_state)
orig_cooldown = sched._startup_cooldown_until
sched._daily_state["trades"] = 0
sched._startup_cooldown_until = None
_real_execute = sched.execute

def fake_execute(sql, params=None, fetch=False):
    if fetch and "COUNT(*) as cnt" in sql:
        return [{"cnt": 0}]
    if fetch:
        return []
    return None
sched.execute = fake_execute

import scanner._log as logmod
calls = []
orig_debug = logmod.debug; orig_info = logmod.info; orig_warn = logmod.warn
logmod.debug = lambda cat, msg, **kw: calls.append(("DEBUG", cat, msg, kw))
logmod.info  = lambda cat, msg, **kw: calls.append(("INFO",  cat, msg, kw))
logmod.warn  = lambda cat, msg, **kw: calls.append(("WARN",  cat, msg, kw))

from scanner.scheduler import _run_micro_sweep_core, _get_active_windows
from backend.execution import get_candles

try:
    for entry_iso, label in [
        ("2026-06-12T13:36:01", "da28460d (R:R 1.13)"),
        ("2026-06-12T14:18:01", "0b973d80 (R:R 2.26)"),
    ]:
        calls.clear()
        try:
            sched._traded_sweeps.clear()
        except Exception:
            pass
        now = datetime.fromisoformat(entry_iso).replace(tzinfo=timezone.utc)
        h1 = [c for c in get_candles(instrument="XAU_USD", granularity="H1", count=200) if c["timestamp"] <= entry_iso + "Z"]
        m3 = [c for c in get_candles(instrument="XAU_USD", granularity="M3", count=500) if c["timestamp"] <= entry_iso + "Z"]
        daily = [c for c in get_candles(instrument="XAU_USD", granularity="D", count=10) if c["timestamp"] <= entry_iso + "Z"]
        active = _get_active_windows(now)
        sigs = _run_micro_sweep_core(now=now, active_windows=active,
                                      h1_candles=h1, daily_candles=daily,
                                      m3_candles=m3, dry_run=True)
        print(f"\n=== {label} @ {entry_iso} UTC ===")
        print(f"  bars: h1={len(h1)} m3={len(m3)} daily={len(daily)}")
        print(f"  active_windows={active}")
        print(f"  signals_returned: {len(sigs) if sigs else 0}")
        for s in sigs or []:
            print("    SIGNAL:", s)
        print("  log trace (last 25):")
        for lvl, cat, msg, kw in calls[-25:]:
            print(f"    {lvl:5} {cat:8} {msg}: {kw}")
finally:
    sched._daily_state.update(orig_state)
    sched._startup_cooldown_until = orig_cooldown
    sched.execute = _real_execute
    logmod.debug = orig_debug; logmod.info = orig_info; logmod.warn = orig_warn
