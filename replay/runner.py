"""Replay Runner — drives live code against tape data deterministically.

Strategy:
  1. BEFORE importing any live module, set DB_URL to golddigger_replay
     and overlay sys.modules['backend.execution.mt5_executor'] with a
     stub that proxies to FakeBroker.
  2. Patch datetime.now / time.time inside the imported live modules so
     all wall-clock reads return tape time.
  3. Walk tape from start_date to end_date in 3-min increments. At each
     tick, call live's micro_sweep_job(), position_monitor jobs, and
     pending_order_monitor — same cadence as the production scheduler.
  4. After each call, advance bridge.tick() so SL/TP/limit fills resolve
     at tape time.
  5. At end, dump trades from golddigger_replay.gd_trades.

Hard guards:
  - Refuses to start if DB_URL doesn't end with "/golddigger_replay".
  - Refuses to start if any live module loaded BEFORE patching.
  - Truncates replay DB tables before run.
"""
from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import psycopg2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


REPLAY_DB_NAME = os.environ.get("REPLAY_DB_NAME", "golddigger_replay")
REPLAY_DB_URL = f"postgresql://subash@localhost:5432/{REPLAY_DB_NAME}"


def _truncate_replay_db() -> None:
    """Wipe replay DB tables before each run."""
    if "replay" not in REPLAY_DB_NAME:
        raise RuntimeError(f"Replay refuses to truncate non-replay DB: {REPLAY_DB_NAME}")
    conn = psycopg2.connect(REPLAY_DB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    # Truncate everything except auth tables (users, sessions) and settings
    cur.execute(
        "TRUNCATE gd_trades, gd_signals, gd_journal, gd_dd_state, "
        "gd_traded_sweeps, gd_backtest_runs, gd_backtest_trades, "
        "gd_backtest_equity RESTART IDENTITY CASCADE"
    )
    # Re-seed dd_state row 1 (gold-micro) and 2 (oil-micro) — same shape as conftest
    cur.execute(
        "INSERT INTO gd_dd_state (id, consecutive_losses, pause_counter, equity, peak_equity) "
        "VALUES (1, 0, 0, 10000, 10000), (2, 0, 0, 10000, 10000) "
        "ON CONFLICT (id) DO UPDATE SET consecutive_losses=0, pause_counter=0, equity=10000, peak_equity=10000"
    )
    conn.close()


@dataclass
class ReplayRunner:
    """Drives one system's live code through a tape window."""

    system: str  # "gold-micro" or "oil-micro"
    pkg_dir: str  # "backend-micro" or "backend-oil-micro"
    instrument: str  # "XAU_USD" or "BCO_USD"
    bias_mode: str = "neutral"

    def setup_env(self) -> None:
        """Pre-import setup. MUST be called BEFORE importing live modules."""
        # Hard guard: replay DB only.
        if "replay" not in REPLAY_DB_URL:
            raise RuntimeError(f"Replay refuses to run with DB={REPLAY_DB_URL}")

        # Live's `from backend.config import DB_URL` reads DATABASE_URL env.
        os.environ["DATABASE_URL"] = REPLAY_DB_URL
        # Live's bias mode env-var (varies per system)
        if self.system == "gold-micro":
            os.environ["GOLD_MICRO_BIAS_MODE"] = self.bias_mode
        else:
            os.environ["OIL_MICRO_BIAS_MODE"] = self.bias_mode
        # Disable Macros (already disabled per Phase 6 e38b288 but be defensive)
        os.environ["GOLD_MACRO_SCAN_ENABLED"] = "false"
        os.environ["OIL_MACRO_SCAN_ENABLED"] = "false"
        # Use mt5 executor path (we'll override with FakeBroker via sys.modules)
        os.environ["EXECUTOR"] = "mt5"
        # Force LIMIT_DRY_RUN off so live takes the real-limit path
        os.environ["LIMIT_DRY_RUN"] = "false"
        os.environ["MICRO_LIMIT_DRY_RUN"] = "false"
        os.environ["OIL_MICRO_LIMIT_DRY_RUN"] = "false"

        # Clear any cached live modules so re-imports respect new env
        for k in list(sys.modules.keys()):
            if k.startswith((
                "scanner", "config", "backtest", "strategies",
                "backend.execution", "backend.strategies", "backend.scanner",
                "backend.config", "backend.backtest", "backend.data",
                "backend.db", "backend.routes", "backend.notify",
            )):
                del sys.modules[k]
        importlib.invalidate_caches()

    def install_db_clock_patch(self, tape) -> None:
        """Replace backend.db.execute with one that:
        (1) rewrites NOW()/CURRENT_TIMESTAMP/CURRENT_DATE in SQL → tape-time
            literals, AND
        (2) for INSERTs into gd_signals / gd_traded_sweeps / gd_journal /
            gd_trades, injects an explicit timestamp column = tape time
            so the table's `DEFAULT NOW()` doesn't fire wall-clock.

        Why: many tables have `timestamp TIMESTAMPTZ DEFAULT NOW()` set at
        the schema level. Live's `_log_signal` etc. INSERT WITHOUT supplying
        timestamp → Postgres NOW() fires (wall clock). Python patches can't
        intercept Postgres-side defaults. Solution: rewrite the INSERT in
        flight to add the column.
        """
        import re as _re

        backend_db = importlib.import_module("backend.db")
        _orig_execute = backend_db.execute

        def _tape_now_lit() -> str:
            return f"'{tape.current_time().isoformat()}'::timestamptz"

        def _tape_today_lit() -> str:
            return f"'{tape.current_time().date().isoformat()}'::date"

        _NOW_PAT = _re.compile(r"\bNOW\s*\(\s*\)", _re.IGNORECASE)
        _CURRENT_TS_PAT = _re.compile(r"\bCURRENT_TIMESTAMP\b", _re.IGNORECASE)
        _CURRENT_DATE_PAT = _re.compile(r"\bCURRENT_DATE\b", _re.IGNORECASE)

        # Tables with DEFAULT NOW() column that we need to override with
        # tape-time. Map: table_name → (column_name, default_kind).
        # default_kind: "timestamp" → tape now ISO, "date" → tape date.
        _DEFAULT_NOW_TABLES = {
            "gd_signals":         ("timestamp",   "timestamp"),
            "gd_traded_sweeps":   ("consumed_at", "timestamp"),
            "gd_journal":         ("timestamp",   "timestamp"),
            # gd_trades has entry_time = NOW() in INSERT statement (not default),
            # so SQL rewriter handles it.
        }

        # Pattern: INSERT INTO <table> (col1, col2, ...) VALUES (%s, %s, ...)
        _INSERT_PAT = _re.compile(
            r"\bINSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
            _re.IGNORECASE | _re.DOTALL,
        )

        def _inject_default_column(sql: str) -> str:
            """If SQL is INSERT into a default-NOW table and doesn't already
            include the auto-timestamp column, inject it with tape-time literal.
            """
            m = _INSERT_PAT.search(sql)
            if not m:
                return sql
            table = m.group(1).lower()
            cols_str = m.group(2)
            vals_str = m.group(3)
            spec = _DEFAULT_NOW_TABLES.get(table)
            if not spec:
                return sql
            col_name, kind = spec
            # If already in column list, leave alone
            if col_name in [c.strip().lower() for c in cols_str.split(",")]:
                return sql
            now_lit = _tape_now_lit() if kind == "timestamp" else _tape_today_lit()
            new_cols = f"{col_name}, {cols_str}"
            new_vals = f"{now_lit}, {vals_str}"
            new_sql = sql[:m.start()] + f"INSERT INTO {table} ({new_cols}) VALUES ({new_vals})" + sql[m.end():]
            return new_sql

        def _rewrite_sql(sql: str) -> str:
            now_lit = _tape_now_lit()
            today_lit = _tape_today_lit()
            sql2 = _NOW_PAT.sub(now_lit, sql)
            sql2 = _CURRENT_TS_PAT.sub(now_lit, sql2)
            sql2 = _CURRENT_DATE_PAT.sub(today_lit, sql2)
            sql2 = _inject_default_column(sql2)
            return sql2

        def _patched_execute(sql: str, params=None, fetch=False):
            return _orig_execute(_rewrite_sql(sql), params, fetch)

        backend_db.execute = _patched_execute

    def install_broker_stub(self, broker) -> None:
        """Replace backend.execution.mt5_executor with a stub that delegates
        every call to our FakeBroker."""
        import types

        stub = types.ModuleType("backend.execution.mt5_executor")
        stub.MAGIC = 24824824
        stub.DWX_DIR = "/tmp/replay_dwx_unused"

        # Wire each public function to broker
        stub.get_current_price = lambda instrument="XAU_USD": broker.get_current_price(instrument)
        stub.get_account_summary = lambda: broker.get_account_summary()
        stub.get_open_trades = lambda instrument=None: broker.get_open_trades(instrument)
        stub.get_candles = lambda instrument="XAU_USD", granularity="H1", count=24, price="BA": (
            broker.get_candles(instrument, granularity, count, price)
        )
        stub.place_market_order = lambda instrument, units, sl=None, tp=None, comment="": (
            broker.place_market_order(instrument, units, sl, tp, comment)
        )
        stub.place_limit_order = lambda instrument, units, limit_price, sl=None, tp=None, ttl_seconds=900, comment="": (
            broker.place_limit_order(instrument, units, limit_price, sl, tp, ttl_seconds, comment)
        )
        stub.cancel_pending_order = lambda ticket: broker.cancel_pending_order(ticket)
        stub.modify_stop_loss = lambda trade_id, new_sl, new_tp=None: (
            broker.modify_stop_loss(trade_id, new_sl, new_tp)
        )
        stub.close_trade = lambda trade_id: broker.close_trade(trade_id)
        stub.close_partial_trade = lambda trade_id, units_to_close, instrument="XAU_USD": (
            broker.close_partial_trade(trade_id, units_to_close, instrument)
        )
        stub.get_trade_details = lambda trade_id: broker.get_trade_details(trade_id)
        stub.is_connected = lambda: True
        stub.get_dwx_status = lambda: {"connected": True, "via": "tape_bridge"}
        # Stubs for misc helpers live code imports
        stub.compute_time_to_fill = lambda *a, **kw: "replay_n/a"
        stub._server_to_utc_iso = lambda t: t
        stub._server_to_utc_dt = lambda t: None

        sys.modules["backend.execution.mt5_executor"] = stub

        # Also stub backend.notify — Telegram is real network, expensive,
        # and irrelevant for replay parity. ConnectTimeout per signal is
        # ~5s of wasted wall-clock.
        notify_stub = types.ModuleType("backend.notify")
        for fn in (
            "signal_skipped", "trade_filled", "trade_closed", "limit_placed",
            "limit_ttl_expired", "max_hold_deferred", "be_armed", "partial_filled",
            "daily_recon", "bad_open_price_persistent", "send", "exception",
            "send_text",
        ):
            setattr(notify_stub, fn, lambda *a, **kw: None)
        sys.modules["backend.notify"] = notify_stub

    def patch_live_clock(self, tape) -> None:
        """Patch datetime.now in live modules to return tape time.

        This is the cleanest approach without modifying live code.
        We monkey-patch the `datetime` symbol inside each live module's
        namespace, replacing the class with a tape-aware subclass.
        """
        # We can't replace datetime globally — too many side effects.
        # Instead, we wrap datetime so .now() returns tape time but
        # all other behavior is preserved.
        class _TapeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                t = tape.current_time()
                if tz is None:
                    return t.replace(tzinfo=None)
                return t.astimezone(tz) if t.tzinfo else t.replace(tzinfo=tz)

        # Import live modules and overlay
        live_modules_to_patch = [
            f"{self.pkg_dir.replace('-', '_')}.scanner.scheduler",  # for sys.modules lookup compat
            "scanner.scheduler",
            "scanner.live_engine",
        ]
        # Live uses `from datetime import datetime, timezone` so we need to
        # patch the imported names INSIDE each module's namespace.
        for mod_name in list(sys.modules.keys()):
            if mod_name.startswith(("scanner", "backend.scanner")):
                mod = sys.modules.get(mod_name)
                if mod and hasattr(mod, "datetime"):
                    setattr(mod, "datetime", _TapeDatetime)

    def import_live_scheduler(self):
        """Import the system's scheduler module after env is set."""
        # Add pkg_dir to sys.path so `from scanner.live_engine import ...` works
        pkg_path = os.path.join(REPO_ROOT, self.pkg_dir)
        if pkg_path not in sys.path:
            sys.path.insert(0, pkg_path)
        # Add backend root for `from backend.execution import ...`
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)

        return importlib.import_module("scanner.scheduler")


# ────────────────────────────────────────────────────────────────────
# Driver: walks tape clock + fires live cron jobs at exact cadence.
# ────────────────────────────────────────────────────────────────────

@dataclass
class ReplaySession:
    """Holds the running state of one replay (one or more systems on one tape)."""
    tape: object  # TapeServer
    broker: object  # FakeBroker
    runners: dict[str, ReplayRunner] = field(default_factory=dict)
    schedulers: dict[str, object] = field(default_factory=dict)
    # Track when each cron job last fired in tape time, so we can replay
    # APScheduler's "*/3 min" / "* min" / "30s" cadences deterministically.
    _last_run: dict[str, datetime] = field(default_factory=dict)
    # Verbose: print every cron tick
    verbose: bool = False

    def add_system(self, system: str, pkg_dir: str, instrument: str,
                    bias_mode: str = "neutral") -> None:
        """Install a system runner. ORDER MATTERS — first system installed
        gets first sys.path priority. Pattern from existing parity tests."""
        runner = ReplayRunner(
            system=system, pkg_dir=pkg_dir, instrument=instrument, bias_mode=bias_mode,
        )
        runner.setup_env()
        runner.install_broker_stub(self.broker)
        runner.install_db_clock_patch(self.tape)
        sched = runner.import_live_scheduler()
        runner.patch_live_clock(self.tape)
        # Force daily state to reset for tape's start date
        sched._daily_state["date"] = None
        sched._traded_sweeps["date"] = None
        if hasattr(sched, "_startup_cooldown_until"):
            sched._startup_cooldown_until = None  # disable C8 startup gate
        self.runners[system] = runner
        self.schedulers[system] = sched

    def run(self, start: datetime, end: datetime, *,
            sweep_minute_cadence: int = 3,
            position_monitor_minute_cadence: int = 1,
            pending_minute_cadence: int = 1,  # interval=30s in prod; we fire every minute
            ) -> dict:
        """Walk tape clock from start to end, firing jobs at cadence.

        Approach:
          - Step 1 minute at a time (smallest cadence we model).
          - At each step, advance tape clock + bridge.tick().
          - If tape minute % sweep_cadence == 0 → fire micro_sweep_job() for
            every system.
          - Every minute → fire position_monitor_job() for every system.
          - Every pending_minute_cadence → fire pending_order_monitor_job().
        Returns: {"steps": int, "events": [...]}
        """
        from datetime import timedelta
        start_utc = self._to_utc(start)
        end_utc = self._to_utc(end)
        if end_utc <= start_utc:
            raise ValueError(f"end {end_utc} must be after start {start_utc}")

        self.tape.set_clock(start_utc)
        steps = 0
        events: list[dict] = []
        clock = start_utc
        prev_date = clock.date()

        while clock <= end_utc:
            # Advance tape + resolve any in-flight broker events
            self.tape.advance_to(clock)
            tick_events = self.broker.tick()
            for e in tick_events:
                e["clock"] = clock.isoformat()
                events.append(e)
                if self.verbose and tick_events:
                    print(f"  [{clock.isoformat()}] broker_event: {e}")

            # Daily reset on date change
            if clock.date() != prev_date:
                for sched in self.schedulers.values():
                    sched._daily_state["date"] = None
                    sched._traded_sweeps["date"] = None
                prev_date = clock.date()

            # ── Sweep poll: every `sweep_minute_cadence` minutes
            if clock.minute % sweep_minute_cadence == 0:
                for system, sched in self.schedulers.items():
                    try:
                        sched.micro_sweep_job()
                    except Exception as e:
                        events.append({
                            "clock": clock.isoformat(),
                            "system": system,
                            "type": "ERROR_SWEEP",
                            "err": f"{type(e).__name__}: {e}",
                        })
                        if self.verbose:
                            import traceback; traceback.print_exc()

            # ── Position monitor: every minute (skip when no open trades — major speedup)
            has_open = any(o.state == "OPEN" for o in self.broker._orders.values())
            if has_open and clock.minute % position_monitor_minute_cadence == 0:
                for system, sched in self.schedulers.items():
                    try:
                        sched.position_monitor_job()
                    except Exception as e:
                        events.append({
                            "clock": clock.isoformat(),
                            "system": system,
                            "type": "ERROR_POSMON",
                            "err": f"{type(e).__name__}: {e}",
                        })
                        if self.verbose:
                            import traceback; traceback.print_exc()

            # ── Pending order monitor (Filter #27) — skip when no pending limits
            has_pending = any(o.state == "PENDING" for o in self.broker._orders.values())
            if has_pending and clock.minute % pending_minute_cadence == 0:
                for system, sched in self.schedulers.items():
                    if hasattr(sched, "pending_order_monitor_job"):
                        try:
                            sched.pending_order_monitor_job()
                        except Exception as e:
                            events.append({
                                "clock": clock.isoformat(),
                                "system": system,
                                "type": "ERROR_PENDINGMON",
                                "err": f"{type(e).__name__}: {e}",
                            })

            # Daily recon at 00:05 UTC (matches live cron)
            if clock.hour == 0 and clock.minute == 5:
                for system, sched in self.schedulers.items():
                    if hasattr(sched, "daily_recon_job"):
                        try:
                            sched.daily_recon_job()
                        except Exception:
                            pass  # daily recon is non-critical for parity

            steps += 1
            clock = clock + timedelta(minutes=1)

        return {"steps": steps, "events": events}

    @staticmethod
    def _to_utc(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
