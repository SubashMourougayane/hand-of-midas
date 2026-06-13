"""Hand of Midas — single-line text logger for week-long observability.

Design (see docs/OBSERVABILITY_PLAN.md):
- Thin wrapper around print() — relies on start-win.bat's existing stdout
  redirect to logs/<svc>.log. NO stdlib `logging` (would clash with shell
  redirect on the same file).
- Every public function wraps the work in try/except so a logging bug
  NEVER crashes the scheduler. Failure is silent (best-effort observability).
- Single-line format: timestamp | LEVEL | CATEGORY | service | msg | k=v k=v
- Env-gated threshold via HOM_LOG_LEVEL (default DEBUG).
- Categories used in this codebase: SCAN, SIGNAL, GATE, POSITION, EXIT,
  BROKER, DB, SYSTEM. Tags are free-form strings; pick what helps grep.

Service identity is set per copy of this file (one per backend dir).
"""
import os
import sys
import traceback
from datetime import datetime, timezone


SERVICE_NAME = "oil-macro"


_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40, "CRIT": 50}
_THRESHOLD = _LEVELS.get(os.environ.get("HOM_LOG_LEVEL", "DEBUG").upper(), 10)


def _fmt_value(v):
    """Render a field value compactly for grep-friendly single-line output."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        # Avoid trailing zero noise on round numbers
        return f"{v:.4f}".rstrip("0").rstrip(".")
    s = str(v)
    # Newlines must not break our single-line invariant (matters for tracebacks)
    if "\n" in s or "\r" in s:
        s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    # Quote values with spaces so key=value parsing stays unambiguous
    if " " in s or "|" in s:
        s = '"' + s.replace('"', '\\"') + '"'
    return s


def _emit(level: str, category: str, msg: str, fields: dict) -> None:
    """Internal: format and print one line. Never raises."""
    try:
        if _LEVELS.get(level, 0) < _THRESHOLD:
            return
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        # Column-aligned for human-scan; widths chosen so the longest level
        # (DEBUG, 5 chars) and longest category (POSITION, 8 chars) fit.
        head = f"{ts} | {level:<5} | {category:<8} | {SERVICE_NAME} | {msg}"
        if fields:
            tail = " ".join(f"{k}={_fmt_value(v)}" for k, v in fields.items())
            line = f"{head} | {tail}"
        else:
            line = head
        print(line, flush=True)
    except Exception:
        # Last resort: don't crash the caller. Try to write to stderr; if even
        # that fails, swallow silently.
        try:
            sys.__stderr__.write(f"_log emit failed for level={level} cat={category}\n")
        except Exception:
            pass


def debug(category: str, msg: str, **fields) -> None:
    _emit("DEBUG", category, msg, fields)


def info(category: str, msg: str, **fields) -> None:
    _emit("INFO", category, msg, fields)


def warn(category: str, msg: str, **fields) -> None:
    _emit("WARN", category, msg, fields)


def error(category: str, msg: str, **fields) -> None:
    _emit("ERROR", category, msg, fields)


def exception(category: str, msg: str, **fields) -> None:
    """Like error() but auto-captures the current exception traceback into tb=...

    Call ONLY from inside an `except` block.
    """
    try:
        tb = traceback.format_exc()
    except Exception:
        tb = "tb-capture-failed"
    fields["tb"] = tb
    _emit("ERROR", category, msg, fields)
