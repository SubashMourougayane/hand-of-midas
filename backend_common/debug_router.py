"""Shared debug router — mounted by all 4 services under /api/{svc}/debug/*.

Read-only by convention but NOT enforced. /sql can DROP tables, /exec runs
arbitrary Python. NO auth, NO scrubbing — exposes secrets, full env, raw
tracebacks, file contents. By design — same risk as SSH access.

Each service builds its own DebugConfig and calls build_debug_router(cfg).
Cross-service aggregates live in build_aggregate_router() and are mounted
ONLY by Gold (port 5053) under /api/debug/*.
"""
from __future__ import annotations

import io
import os
import re
import sys
import time
import json
import socket
import platform
import threading
import traceback
import subprocess
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

try:
    import psutil
except ImportError:
    psutil = None
from fastapi import APIRouter, Query, HTTPException, Response
from pydantic import BaseModel


# ── Config ────────────────────────────────────────────────────────────────

class ExecPythonBody(BaseModel):
    code: str


class ExecScriptBody(BaseModel):
    path: str
    args: list[str] | None = None
    timeout: int | None = 60


class ExecShellBody(BaseModel):
    cmd: str
    timeout: int | None = 60


@dataclass
class DebugConfig:
    """Per-service config. Each service's main.py builds one of these and
    passes it to build_debug_router()."""
    service_name: str          # "gold" / "oil" / "micro" / "oil-micro"
    log_filename: str          # "gold.log" / "oil.log" / "micro.log" / "oil-micro.log"
    repo_root: str             # /path/to/GoldDigger (used for log dir + code reads)
    instrument: str            # "XAU_USD" / "BCO_USD"
    strategies: list[str]      # ["alpha_sweep","mean_reversion","cross_market"] etc.
    trade_ref_prefix: str      # "GD-AL-", "OIL-AS-", "GD-MI-", "OIL-MI-"
    db_execute: Callable       # service's `from <pkg>.db import execute`
    config_module: Any         # service's config module (introspected dynamically)
    scheduler_module: Any      # service's scanner.scheduler module (for jobs/state)
    dwx_dir_getter: Callable[[], str] | None = None  # returns DWX dir if MT5 mode


# ── Module-level: last-N exception buffer ─────────────────────────────────
# We do NOT have a global hook, but the logger module's exception() can
# append here. To avoid a hard dependency, we expose a class-level ring
# buffer that callers (live_engine, scheduler) can opt into via append().

_EXC_BUF: list[dict] = []
_EXC_LOCK = threading.Lock()
_EXC_MAX = 50


def record_exception(category: str, msg: str, **fields):
    """Public hook the logger can call to capture exceptions for /debug/exception.
    Idempotent — safe to call from try/except wrapped paths."""
    try:
        with _EXC_LOCK:
            _EXC_BUF.append({
                "ts": datetime.utcnow().isoformat() + "Z",
                "category": category,
                "msg": msg,
                "fields": dict(fields),
                "tb": fields.get("tb") or traceback.format_exc(),
            })
            if len(_EXC_BUF) > _EXC_MAX:
                del _EXC_BUF[0:len(_EXC_BUF) - _EXC_MAX]
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────

def _logs_dir(cfg: DebugConfig) -> str:
    return os.path.join(cfg.repo_root, "logs")


def _resolve_log_path(cfg: DebugConfig, filename: Optional[str]) -> str:
    """Resolve filename to full path under logs/. Reject path traversal."""
    name = filename or cfg.log_filename
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="invalid filename")
    return os.path.join(_logs_dir(cfg), name)


def _tail_lines(path: str, n: int) -> list[str]:
    """Return last n lines of file. Cheap implementation — reads from end."""
    if not os.path.exists(path):
        return []
    block = 64 * 1024
    out: list[bytes] = []
    seen = 0
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        pos = end
        chunks: list[bytes] = []
        while pos > 0 and seen <= n:
            read_size = min(block, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            chunks.append(chunk)
            seen += chunk.count(b"\n")
        data = b"".join(reversed(chunks))
    lines = data.splitlines()
    return [l.decode("utf-8", errors="replace") for l in lines[-n:]]


def _parse_since(since: Optional[str]) -> Optional[datetime]:
    """Parse '1h', '30m', '2d', or ISO-8601 → UTC datetime."""
    if not since:
        return None
    s = since.strip().lower()
    m = re.fullmatch(r"(\d+)\s*([smhd])", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[unit]
        return datetime.utcnow() - timedelta(**{delta: n})
    try:
        return datetime.fromisoformat(s.replace("z", "+00:00")).replace(tzinfo=None)
    except Exception:
        raise HTTPException(status_code=400, detail=f"bad since: {since}")


_TS_RX = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


def _line_ts(line: str) -> Optional[datetime]:
    m = _TS_RX.match(line)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1))
    except Exception:
        return None


def _filter_lines(
    lines: list[str],
    level: Optional[str],
    category: Optional[str],
    grep: Optional[str],
    since_dt: Optional[datetime],
) -> list[str]:
    out = []
    rx = re.compile(grep) if grep else None
    for line in lines:
        if level and f" {level.upper()} " not in line:
            continue
        if category and f" {category.upper()} " not in line:
            # Categories are space-padded too
            cat_padded = f" {category.upper():<8} "
            if cat_padded not in line:
                continue
        if since_dt:
            ts = _line_ts(line)
            if ts and ts < since_dt:
                continue
        if rx and not rx.search(line):
            continue
        out.append(line)
    return out


def _safe_dict(d: Any) -> Any:
    """Convert unhashable/non-JSON values to strings for dump."""
    if d is None or isinstance(d, (str, int, float, bool)):
        return d
    if isinstance(d, dict):
        return {str(k): _safe_dict(v) for k, v in d.items()}
    if isinstance(d, (list, tuple)):
        return [_safe_dict(x) for x in d]
    if isinstance(d, datetime):
        return d.isoformat()
    try:
        json.dumps(d)
        return d
    except Exception:
        return repr(d)


# ── Router builder ────────────────────────────────────────────────────────

def build_debug_router(cfg: DebugConfig) -> APIRouter:
    router = APIRouter()

    # ─ Logs ───────────────────────────────────────────────────────────────

    @router.get("/logs")
    def get_logs(
        lines: int = Query(500, le=50000),
        level: Optional[str] = Query(None, description="DEBUG/INFO/WARN/ERROR/CRIT"),
        category: Optional[str] = Query(None, description="SCAN/SIGNAL/GATE/POSITION/EXIT/BROKER/DB/SYSTEM"),
        grep: Optional[str] = Query(None, description="regex"),
        since: Optional[str] = Query(None, description="1h, 30m, 2d, or ISO-8601"),
        filename: Optional[str] = Query(None, description="rotated file (default: live)"),
    ):
        path = _resolve_log_path(cfg, filename)
        since_dt = _parse_since(since)
        # Tail more than we need so post-filter still has enough
        # if no filter: just return last `lines` lines
        if not (level or category or grep or since_dt):
            tailed = _tail_lines(path, lines)
            return {
                "service": cfg.service_name,
                "path": path,
                "exists": os.path.exists(path),
                "size_bytes": os.path.getsize(path) if os.path.exists(path) else 0,
                "lines": tailed,
                "count": len(tailed),
            }
        # Filtered: tail much more, then filter, then trim
        tail_n = max(lines * 20, 5000)
        tailed = _tail_lines(path, tail_n)
        filtered = _filter_lines(tailed, level, category, grep, since_dt)[-lines:]
        return {
            "service": cfg.service_name,
            "path": path,
            "exists": os.path.exists(path),
            "filters": {"level": level, "category": category, "grep": grep, "since": since},
            "scanned_lines": len(tailed),
            "matched_lines": len(filtered),
            "lines": filtered,
        }

    @router.get("/logs/files")
    def list_log_files():
        d = _logs_dir(cfg)
        if not os.path.exists(d):
            return {"dir": d, "exists": False, "files": []}
        out = []
        for fn in sorted(os.listdir(d)):
            full = os.path.join(d, fn)
            if not os.path.isfile(full):
                continue
            st = os.stat(full)
            out.append({
                "name": fn,
                "size_bytes": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
            })
        return {"dir": d, "files": out}

    @router.get("/logs/raw", response_class=Response)
    def get_logs_raw(
        filename: Optional[str] = Query(None),
        lines: int = Query(2000, le=100000),
    ):
        """Plain-text response, no JSON envelope. Useful for piping/grep."""
        path = _resolve_log_path(cfg, filename)
        body = "\n".join(_tail_lines(path, lines))
        return Response(content=body, media_type="text/plain")

    # ─ Journal & DB ───────────────────────────────────────────────────────

    @router.get("/journal")
    def get_journal(
        trade_ref: Optional[str] = Query(None),
        event_type: Optional[str] = Query(None),
        strategy: Optional[str] = Query(None),
        limit: int = Query(200, le=2000),
        since: Optional[str] = Query(None),
    ):
        sql = "SELECT * FROM gd_journal WHERE 1=1"
        params: list = []
        if trade_ref:
            sql += " AND trade_ref = %s"
            params.append(trade_ref)
        if event_type:
            sql += " AND event_type = %s"
            params.append(event_type)
        if strategy:
            sql += " AND strategy = %s"
            params.append(strategy)
        elif not trade_ref:
            placeholders = ",".join(["%s"] * len(cfg.strategies))
            sql += f" AND strategy IN ({placeholders})"
            params.extend(cfg.strategies)
        if since:
            since_dt = _parse_since(since)
            sql += " AND timestamp >= %s"
            params.append(since_dt)
        sql += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        rows = cfg.db_execute(sql, params, fetch=True) or []
        return {"count": len(rows), "events": [_safe_dict(dict(r)) for r in rows]}

    @router.get("/trade/{trade_ref}")
    def get_trade(trade_ref: str):
        trade_rows = cfg.db_execute(
            "SELECT * FROM gd_trades WHERE trade_ref = %s", (trade_ref,), fetch=True
        ) or []
        if not trade_rows:
            raise HTTPException(status_code=404, detail=f"trade_ref {trade_ref} not found")
        events = cfg.db_execute(
            "SELECT * FROM gd_journal WHERE trade_ref = %s ORDER BY timestamp ASC",
            (trade_ref,), fetch=True
        ) or []
        return {
            "trade": _safe_dict(dict(trade_rows[0])),
            "events": [_safe_dict(dict(r)) for r in events],
            "event_count": len(events),
        }

    @router.get("/trades")
    def list_trades(
        status: str = Query("all", description="open/closed/all"),
        since: Optional[str] = Query(None),
        limit: int = Query(50, le=1000),
        strategy: Optional[str] = Query(None),
    ):
        sql = "SELECT * FROM gd_trades WHERE 1=1"
        params: list = []
        if strategy:
            sql += " AND strategy = %s"
            params.append(strategy)
        else:
            placeholders = ",".join(["%s"] * len(cfg.strategies))
            sql += f" AND strategy IN ({placeholders})"
            params.extend(cfg.strategies)
        if status == "open":
            sql += " AND exit_time IS NULL"
        elif status == "closed":
            sql += " AND exit_time IS NOT NULL"
        if since:
            since_dt = _parse_since(since)
            sql += " AND entry_time >= %s"
            params.append(since_dt)
        sql += " ORDER BY entry_time DESC LIMIT %s"
        params.append(limit)
        rows = cfg.db_execute(sql, params, fetch=True) or []
        return {"count": len(rows), "trades": [_safe_dict(dict(r)) for r in rows]}

    @router.get("/signals")
    def list_signals(
        taken: Optional[bool] = Query(None),
        since: Optional[str] = Query(None),
        limit: int = Query(100, le=2000),
    ):
        sql = "SELECT * FROM gd_signals WHERE 1=1"
        params: list = []
        placeholders = ",".join(["%s"] * len(cfg.strategies))
        sql += f" AND strategy IN ({placeholders})"
        params.extend(cfg.strategies)
        if taken is not None:
            sql += " AND taken = %s"
            params.append(taken)
        if since:
            since_dt = _parse_since(since)
            sql += " AND timestamp >= %s"
            params.append(since_dt)
        sql += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        rows = cfg.db_execute(sql, params, fetch=True) or []
        return {"count": len(rows), "signals": [_safe_dict(dict(r)) for r in rows]}

    @router.get("/orphans")
    def find_orphans():
        """Broker-not-in-DB and DB-not-on-broker mismatches for THIS service."""
        try:
            from importlib import import_module
            # Each service has a different exec module path; import its open trades getter
            # via convention: service uses backend.execution or scanner.execution
            try:
                exec_mod = import_module("backend.execution")
            except Exception:
                exec_mod = None
            broker_positions = []
            if exec_mod and hasattr(exec_mod, "get_open_trades"):
                try:
                    broker_positions = exec_mod.get_open_trades(instrument=cfg.instrument) or []
                except Exception as e:
                    broker_positions = [{"error": str(e)}]
        except Exception as e:
            broker_positions = [{"error": str(e)}]

        placeholders = ",".join(["%s"] * len(cfg.strategies))
        db_open = cfg.db_execute(
            f"SELECT trade_ref, oanda_trade_id, strategy, side, entry_price, units "
            f"FROM gd_trades WHERE exit_time IS NULL AND strategy IN ({placeholders})",
            tuple(cfg.strategies), fetch=True
        ) or []
        db_open = [dict(r) for r in db_open]
        db_oanda_ids = {str(r.get("oanda_trade_id")) for r in db_open if r.get("oanda_trade_id")}
        broker_ids = {str(p.get("id") or p.get("trade_id") or p.get("ticket")) for p in broker_positions if isinstance(p, dict)}
        broker_only = [p for p in broker_positions if isinstance(p, dict) and str(p.get("id") or p.get("trade_id") or p.get("ticket")) not in db_oanda_ids]
        db_only = [r for r in db_open if str(r.get("oanda_trade_id")) not in broker_ids]
        return {
            "service": cfg.service_name,
            "broker_position_count": len(broker_positions),
            "db_open_count": len(db_open),
            "broker_only": [_safe_dict(p) for p in broker_only],
            "db_only": [_safe_dict(r) for r in db_only],
        }

    @router.get("/sql")
    def run_sql(q: str = Query(..., description="raw SELECT — read-only by discipline")):
        """Raw SQL passthrough. NO write protection — caller responsibility.
        Returns rows, runtime, row count."""
        t0 = time.time()
        rows = cfg.db_execute(q, None, fetch=True) or []
        runtime = time.time() - t0
        return {
            "query": q,
            "runtime_ms": round(runtime * 1000, 1),
            "count": len(rows),
            "rows": [_safe_dict(dict(r)) for r in rows[:1000]],  # cap response size
            "truncated": len(rows) > 1000,
        }

    # ─ Config & strategy state ────────────────────────────────────────────

    @router.get("/config")
    def get_config():
        """Dump current config module values. Includes secrets — by design."""
        out = {}
        for name in dir(cfg.config_module):
            if name.startswith("_"):
                continue
            val = getattr(cfg.config_module, name)
            if callable(val):
                continue
            if isinstance(val, type):
                continue
            out[name] = _safe_dict(val)
        return {"service": cfg.service_name, "config": out}

    @router.get("/scanner-state")
    def get_scanner_state():
        """Internal scheduler module state — _traded_sweeps, _seen_sweeps, etc."""
        sched = cfg.scheduler_module
        out = {}
        for name in dir(sched):
            if name.startswith("__"):
                continue
            val = getattr(sched, name, None)
            # Snapshot anything that smells like state: dicts, sets, lists, datetimes, basic types.
            if isinstance(val, (dict, set, list, tuple, str, int, float, bool, datetime)) or val is None:
                if isinstance(val, set):
                    val = sorted(val) if all(isinstance(x, (str, int, float)) for x in val) else list(val)
                out[name] = _safe_dict(val)
        # Try to introspect APScheduler if exposed
        try:
            scheduler_obj = getattr(sched, "scheduler", None)
            if scheduler_obj is not None and hasattr(scheduler_obj, "get_jobs"):
                jobs = []
                for j in scheduler_obj.get_jobs():
                    jobs.append({
                        "id": j.id,
                        "name": j.name,
                        "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                        "trigger": str(j.trigger),
                    })
                out["_apscheduler_jobs"] = jobs
                out["_apscheduler_running"] = scheduler_obj.running
        except Exception as e:
            out["_apscheduler_error"] = str(e)
        return {"service": cfg.service_name, "state": out}

    @router.get("/asia")
    def get_asia():
        """Today's asia/range computation if available on scheduler module."""
        sched = cfg.scheduler_module
        candidates = ["asia_high", "asia_low", "consol_high", "consol_low",
                      "consol_range", "_asia_range", "_consol_high", "_consol_low",
                      "active_windows", "_traded_sweeps", "_seen_sweeps"]
        out = {}
        for k in candidates:
            if hasattr(sched, k):
                v = getattr(sched, k)
                if isinstance(v, set):
                    v = sorted(v) if all(isinstance(x, (str, int, float)) for x in v) else list(v)
                out[k] = _safe_dict(v)
        return {"service": cfg.service_name, "asia_state": out}

    # ─ DWX / broker ───────────────────────────────────────────────────────

    @router.get("/dwx")
    def get_dwx():
        """DWX bridge directory dump — open_orders, closed_orders, last_response."""
        if cfg.dwx_dir_getter is None:
            return {"executor": "non-mt5", "dwx_dir": None}
        try:
            dwx_dir = cfg.dwx_dir_getter()
        except Exception as e:
            return {"error": f"dwx_dir resolution failed: {e}"}
        if not dwx_dir or not os.path.isdir(dwx_dir):
            return {"dwx_dir": dwx_dir, "exists": False}
        out: dict[str, Any] = {"dwx_dir": dwx_dir, "files": {}}
        # Auto-discover all .json files in DWX dir (bars_XAUUSD_ecn_M3.json etc.)
        try:
            present = [f for f in os.listdir(dwx_dir) if f.endswith(".json")]
        except Exception:
            present = []
        # Always-known files + anything else discovered
        well_known = ["open_orders.json", "closed_orders.json", "last_response.json",
                      "market_data.json", "messages.json", "historic_data.json",
                      "bar_data.json", "tick_data.json"]
        all_files = list(dict.fromkeys(well_known + sorted(present)))
        for fname in all_files:
            full = os.path.join(dwx_dir, fname)
            if not os.path.exists(full):
                out["files"][fname] = {"exists": False}
                continue
            st = os.stat(full)
            entry = {
                "exists": True,
                "size_bytes": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
                "stale_seconds": round(time.time() - st.st_mtime, 1),
            }
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read()
                try:
                    entry["content"] = json.loads(raw) if raw.strip() else None
                except Exception:
                    entry["content_raw"] = raw[:5000]
            except Exception as e:
                entry["read_error"] = str(e)
            out["files"][fname] = entry
        return out

    @router.get("/account")
    def get_account():
        """Live broker account snapshot."""
        try:
            from importlib import import_module
            try:
                exec_mod = import_module("backend.execution")
            except Exception:
                exec_mod = None
            if exec_mod and hasattr(exec_mod, "get_account_summary"):
                summary = exec_mod.get_account_summary()
                return {"service": cfg.service_name, "account": _safe_dict(summary)}
        except Exception as e:
            return {"error": str(e)}
        return {"error": "no execution module available"}

    @router.get("/price")
    def get_price():
        """Live broker price snapshot."""
        try:
            from importlib import import_module
            try:
                exec_mod = import_module("backend.execution")
            except Exception:
                exec_mod = None
            if exec_mod and hasattr(exec_mod, "get_current_price"):
                price = exec_mod.get_current_price()
                return {"service": cfg.service_name, "instrument": cfg.instrument, "price": _safe_dict(price)}
        except Exception as e:
            return {"error": str(e)}
        return {"error": "no execution module available"}

    @router.get("/bars")
    def get_bars(timeframe: str = Query("M3"), count: int = Query(50, le=1000)):
        """Last N bars from cached/live data the scanner sees."""
        try:
            from importlib import import_module
            try:
                exec_mod = import_module("backend.execution")
            except Exception:
                exec_mod = None
            if exec_mod and hasattr(exec_mod, "get_recent_bars"):
                bars = exec_mod.get_recent_bars(instrument=cfg.instrument, timeframe=timeframe, count=count)
                return {"timeframe": timeframe, "count": len(bars) if bars else 0, "bars": _safe_dict(bars)}
        except Exception as e:
            return {"error": str(e), "tb": traceback.format_exc()}
        return {"error": "get_recent_bars not available"}

    # ─ Health / exceptions / system ───────────────────────────────────────

    @router.get("/health")
    def health():
        mem_mb = None
        uptime = None
        disk: dict = {}
        if psutil is not None:
            try:
                proc = psutil.Process(os.getpid())
                mem_mb = round(proc.memory_info().rss / 1_000_000, 1)
                uptime = round(time.time() - proc.create_time(), 1)
                du = psutil.disk_usage(cfg.repo_root)
                disk = {"total_gb": round(du.total / 1e9, 1),
                        "free_gb": round(du.free / 1e9, 1),
                        "percent": du.percent}
            except Exception as e:
                disk = {"error": str(e)}
        else:
            disk = {"error": "psutil not installed"}
        # APScheduler state
        sched_status = "unknown"
        jobs = []
        try:
            sched = getattr(cfg.scheduler_module, "scheduler", None)
            if sched is not None and hasattr(sched, "get_jobs"):
                sched_status = "running" if sched.running else "stopped"
                for j in sched.get_jobs():
                    jobs.append({
                        "id": j.id,
                        "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                    })
        except Exception as e:
            sched_status = f"error: {e}"
        return {
            "service": cfg.service_name,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "uptime_seconds": uptime,
            "memory_mb": mem_mb,
            "disk": disk,
            "scheduler_status": sched_status,
            "scheduler_jobs": jobs,
            "log_path": os.path.join(_logs_dir(cfg), cfg.log_filename),
            "log_size_bytes": (os.path.getsize(os.path.join(_logs_dir(cfg), cfg.log_filename))
                               if os.path.exists(os.path.join(_logs_dir(cfg), cfg.log_filename)) else 0),
            "exception_buffer_size": len(_EXC_BUF),
        }

    @router.get("/exceptions")
    def get_exceptions(limit: int = Query(20, le=200)):
        with _EXC_LOCK:
            out = list(_EXC_BUF[-limit:])
        return {"service": cfg.service_name, "count": len(out), "exceptions": out}

    @router.get("/env")
    def get_env():
        """Full os.environ. Includes secrets — by design."""
        return {"service": cfg.service_name, "env": dict(os.environ)}

    @router.get("/threads")
    def get_threads():
        out = []
        for t in threading.enumerate():
            out.append({
                "name": t.name,
                "ident": t.ident,
                "daemon": t.daemon,
                "alive": t.is_alive(),
            })
        # Active stacks
        frames = sys._current_frames()
        stacks = {}
        for tid, frame in frames.items():
            stack = traceback.format_stack(frame)
            stacks[str(tid)] = stack[-15:]  # last 15 frames per thread
        return {"service": cfg.service_name, "threads": out, "stacks": stacks}

    # ─ Code / repo ────────────────────────────────────────────────────────

    @router.get("/code")
    def get_code(path: str = Query(..., description="path relative to repo_root")):
        """Read a file from the repo. No path traversal — must stay under repo_root."""
        full = os.path.normpath(os.path.join(cfg.repo_root, path))
        if not full.startswith(os.path.normpath(cfg.repo_root)):
            raise HTTPException(status_code=400, detail="path escapes repo_root")
        if not os.path.exists(full):
            raise HTTPException(status_code=404, detail=f"not found: {path}")
        if not os.path.isfile(full):
            raise HTTPException(status_code=400, detail=f"not a file: {path}")
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"read error: {e}")
        return {
            "path": path,
            "abs_path": full,
            "size_bytes": os.path.getsize(full),
            "lines": content.count("\n") + 1,
            "content": content,
        }

    @router.get("/code/grep")
    def grep_code(
        pattern: str = Query(...),
        path: str = Query("", description="dir under repo_root, default = whole repo"),
        max_results: int = Query(200, le=2000),
    ):
        rx = re.compile(pattern)
        root = os.path.normpath(os.path.join(cfg.repo_root, path))
        if not root.startswith(os.path.normpath(cfg.repo_root)):
            raise HTTPException(status_code=400, detail="path escapes repo_root")
        if not os.path.exists(root):
            raise HTTPException(status_code=404, detail=f"not found: {path}")
        results = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip noise
            dirnames[:] = [d for d in dirnames
                           if d not in (".git", "node_modules", "__pycache__", ".venv",
                                         "data", ".next", "models", "logs")]
            for fn in filenames:
                if not fn.endswith((".py", ".ts", ".tsx", ".js", ".jsx",
                                     ".sql", ".md", ".bat", ".sh", ".json")):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if rx.search(line):
                                rel = os.path.relpath(full, cfg.repo_root)
                                results.append({"file": rel, "line": i,
                                                "content": line.rstrip("\n")})
                                if len(results) >= max_results:
                                    return {"pattern": pattern, "count": len(results),
                                            "results": results, "truncated": True}
                except Exception:
                    continue
        return {"pattern": pattern, "count": len(results), "results": results,
                "truncated": False}

    @router.get("/git")
    def get_git():
        out = {}
        for label, cmd in [
            ("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
            ("commit", ["git", "rev-parse", "HEAD"]),
            ("commit_short", ["git", "rev-parse", "--short", "HEAD"]),
            ("status", ["git", "status", "--short"]),
            ("log_recent", ["git", "log", "--oneline", "-20"]),
        ]:
            try:
                out[label] = subprocess.check_output(cmd, cwd=cfg.repo_root,
                                                     stderr=subprocess.DEVNULL,
                                                     timeout=10).decode().strip()
            except Exception as e:
                out[label] = f"error: {e}"
        return {"service": cfg.service_name, "repo": cfg.repo_root, "git": out}

    # ─ Code execution ─────────────────────────────────────────────────────
    # NOT read-only. Lets the operator run arbitrary Python in-process or via
    # subprocess. Same risk class as /sql + /env + /code combined.

    @router.post("/exec/python")
    def exec_python(body: ExecPythonBody):
        """Run arbitrary Python code in-process. Returns stdout, stderr, and
        the value of `_result` if the code assigned to that name.

        Has access to the live process — same imports, same db connection,
        same scheduler, same DWX state. Useful for one-off introspection
        like:
            from backend.execution.mt5_executor import get_candles
            _result = get_candles('XAU_USD', 'M3', 50)

        Code runs in-process; errors are caught and returned, not propagated."""
        stdout, stderr = io.StringIO(), io.StringIO()
        local_ns: dict = {"cfg": cfg}
        result = None
        error = None
        tb = None
        t0 = time.time()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exec(compile(body.code, "<exec_python>", "exec"), local_ns, local_ns)
            result = local_ns.get("_result", None)
        except Exception as e:
            error = repr(e)
            tb = traceback.format_exc()
        runtime_ms = round((time.time() - t0) * 1000, 1)
        return {
            "runtime_ms": runtime_ms,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "result": _safe_dict(result),
            "error": error,
            "traceback": tb,
        }

    @router.get("/exec/python")
    def exec_python_get(code: str = Query(..., description="inline python")):
        """Same as POST /exec/python but with code in URL query — easier for curl."""
        return exec_python(ExecPythonBody(code=code))

    @router.post("/exec/script")
    def exec_script(body: ExecScriptBody):
        """Run a Python script from the repo as a subprocess. Path is relative
        to repo_root. Args are passed as argv. Output captured; timeout enforced.

        Use this for `scripts/print_today_h1_bars.py` style throwaway diagnostics
        without RDP'ing into the VPS."""
        full = os.path.normpath(os.path.join(cfg.repo_root, body.path))
        if not full.startswith(os.path.normpath(cfg.repo_root)):
            raise HTTPException(status_code=400, detail="path escapes repo_root")
        if not os.path.isfile(full):
            raise HTTPException(status_code=404, detail=f"not found: {body.path}")
        cmd = [sys.executable, full] + list(body.args or [])
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, cwd=cfg.repo_root, capture_output=True,
                                  text=True, timeout=body.timeout or 60)
            return {
                "cmd": cmd,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "runtime_ms": round((time.time() - t0) * 1000, 1),
            }
        except subprocess.TimeoutExpired as e:
            return {
                "cmd": cmd,
                "error": "timeout",
                "timeout_seconds": body.timeout or 60,
                "stdout_partial": (e.stdout or b"").decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""),
                "stderr_partial": (e.stderr or b"").decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""),
            }
        except Exception as e:
            return {"cmd": cmd, "error": repr(e), "traceback": traceback.format_exc()}

    @router.get("/exec/script")
    def exec_script_get(
        path: str = Query(..., description="relative to repo_root"),
        args: Optional[str] = Query(None, description="space-separated argv"),
        timeout: int = Query(60, le=600),
    ):
        """GET version: ?path=scripts/foo.py&args=arg1+arg2&timeout=60"""
        argv = args.split() if args else []
        return exec_script(ExecScriptBody(path=path, args=argv, timeout=timeout))

    @router.post("/exec/shell")
    def exec_shell(body: ExecShellBody):
        """Run a shell command. cwd defaults to repo_root.
        Examples: `dir logs\\`, `git pull`, `findstr ERROR logs\\gold.log`."""
        t0 = time.time()
        try:
            proc = subprocess.run(body.cmd, shell=True, cwd=cfg.repo_root,
                                  capture_output=True, text=True,
                                  timeout=body.timeout or 60)
            return {
                "cmd": body.cmd,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "runtime_ms": round((time.time() - t0) * 1000, 1),
            }
        except subprocess.TimeoutExpired:
            return {"cmd": body.cmd, "error": "timeout"}
        except Exception as e:
            return {"cmd": body.cmd, "error": repr(e), "traceback": traceback.format_exc()}

    @router.get("/exec/shell")
    def exec_shell_get(cmd: str = Query(...), timeout: int = Query(60, le=600)):
        return exec_shell(ExecShellBody(cmd=cmd, timeout=timeout))

    # ─ Notify (read-only inspection) ──────────────────────────────────────

    @router.get("/notify/recent")
    def get_recent_notifies(limit: int = Query(50, le=500)):
        """If notify history is in gd_journal, surface entries. Otherwise scrape log."""
        rows = cfg.db_execute(
            "SELECT * FROM gd_journal "
            "WHERE event_type IN ('TELEGRAM_SENT','TELEGRAM_FAILED','NOTIFY','TG_DEBUG') "
            "ORDER BY timestamp DESC LIMIT %s",
            (limit,), fetch=True
        ) or []
        return {"count": len(rows), "events": [_safe_dict(dict(r)) for r in rows]}

    return router


# ── Cross-service aggregator (mounted only by Gold @ 5053) ────────────────

def build_aggregate_router(service_urls: dict[str, str]) -> APIRouter:
    """service_urls: {"gold": "http://localhost:5053", ...}"""
    import urllib.request

    router = APIRouter()

    def _fetch(url: str, timeout: float = 5.0) -> Any:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            return {"error": str(e)}

    @router.get("/all-health")
    def all_health():
        out = {}
        for svc, base in service_urls.items():
            out[svc] = _fetch(f"{base}/api/{svc}/debug/health")
        return out

    @router.get("/all-orphans")
    def all_orphans():
        out = {}
        for svc, base in service_urls.items():
            out[svc] = _fetch(f"{base}/api/{svc}/debug/orphans")
        return out

    @router.get("/all-state")
    def all_state():
        out = {}
        for svc, base in service_urls.items():
            out[svc] = _fetch(f"{base}/api/{svc}/state")
        return out

    @router.get("/all-exceptions")
    def all_exceptions(limit: int = Query(20, le=200)):
        out = {}
        for svc, base in service_urls.items():
            out[svc] = _fetch(f"{base}/api/{svc}/debug/exceptions?limit={limit}")
        return out

    return router
