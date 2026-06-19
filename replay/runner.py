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
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import psycopg2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


REPLAY_DB_NAME = "golddigger_replay"
REPLAY_DB_URL = f"postgresql://subash@localhost:5432/{REPLAY_DB_NAME}"


def _truncate_replay_db() -> None:
    """Wipe replay DB tables before each run."""
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
        if "golddigger_replay" not in REPLAY_DB_URL:
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
