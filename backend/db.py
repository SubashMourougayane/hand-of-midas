"""Database connection and helpers for GoldDigger."""
import os
import json
import decimal
from datetime import datetime, date
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.config import DB_URL

# Parse DB_URL into components for psycopg2
# Format: postgresql://user@host:port/dbname or postgresql://user:pass@host:port/dbname
_url = DB_URL.replace("postgresql://", "")
if "@" in _url:
    _user_part, _host_part = _url.rsplit("@", 1)
    _user = _user_part.split(":")[0]
    _password = _user_part.split(":")[1] if ":" in _user_part else ""
else:
    _user = "subash"
    _password = ""
    _host_part = _url

if "/" in _host_part:
    _host_port, _dbname = _host_part.rsplit("/", 1)
else:
    _host_port = _host_part
    _dbname = "golddigger"

_host = _host_port.split(":")[0] if ":" in _host_port else _host_port
_port = int(_host_port.split(":")[1]) if ":" in _host_port else 5432


def get_conn():
    """Get a new database connection."""
    return psycopg2.connect(
        host=_host,
        port=_port,
        dbname=_dbname,
        user=_user,
        password=_password or None,
    )


def execute(sql: str, params=None, fetch=False):
    """Execute SQL and optionally fetch results."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetch:
                result = cur.fetchall()
            else:
                result = None
            conn.commit()
            return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def execute_many(sql: str, params_list: list):
    """Execute SQL for multiple rows."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, params_list)
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def insert_returning(sql: str, params=None):
    """Insert and return the generated ID."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchone()
            conn.commit()
            return result[0] if result else None
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# =============================================================================
# JSON serialization helpers
# =============================================================================
# Why these exist: psycopg2 returns Decimal for NUMERIC columns and numpy floats
# leak in from strategy code. json.dumps() crashes silently on both. When that
# happened inside _log_journal in execute_signal, the exception propagated up
# through unprotected callers, skipping Telegram + skipping the sweep blacklist
# update — causing the orphan-trade cascade on June 10 (see
# docs/JUNE10_OIL_4ORPHANS_INVESTIGATION.md).
# =============================================================================

def safe_json_value(v):
    """Convert a single value to a JSON-serializable form.

    Handles: None, str, bool, int, float, Decimal, datetime, date,
    numpy scalars (any platform/version), lists, dicts. Anything else
    falls through to str() so we never crash the journal write.
    """
    if v is None:
        return None
    if isinstance(v, bool):  # bool BEFORE int (bool is subclass of int)
        return v
    if isinstance(v, (str, int, float)):
        # Catch numpy scalars that subclass int/float — coerce to native
        # so json.dumps works regardless of numpy version
        if type(v) is int or type(v) is float or type(v) is str:
            return v
        # numpy.float64 / numpy.int64 etc — force native type
        if isinstance(v, float):
            return float(v)
        if isinstance(v, int):
            return int(v)
        return v
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    # numpy scalars (legacy path for older numpy versions)
    if hasattr(v, "item") and callable(getattr(v, "item")):
        try:
            extracted = v.item()
            # extracted should now be a native Python type
            if isinstance(extracted, (str, int, float, bool)) and type(extracted) in (str, int, float, bool):
                return extracted
            return float(extracted) if isinstance(extracted, (int, float)) else str(extracted)
        except (TypeError, ValueError):
            pass
    if isinstance(v, (list, tuple)):
        return [safe_json_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): safe_json_value(x) for k, x in v.items()}
    # Fallback: stringify anything else (e.g., custom objects)
    return str(v)


def safe_json_dumps(ctx):
    """Serialize a dict to JSON safely. Returns None if input is None/empty."""
    if not ctx:
        return None
    try:
        return json.dumps(safe_json_value(ctx))
    except (TypeError, ValueError) as e:
        # Last-resort fallback so journal write never crashes the caller
        return json.dumps({"_serialize_error": str(e), "_repr": repr(ctx)[:500]})


# =============================================================================
# Daily reconciliation report builder
# =============================================================================

def daily_recon_stats(trade_ref_pattern: str, strategy_pattern: str, target_date,
                       strategies: list = None):
    """Build daily reconciliation stats for a single system.

    trade_ref_pattern: SQL LIKE pattern (e.g., 'OIL-MI-%')
    strategy_pattern: SQL = match (e.g., 'micro_alpha_sweep_oil') for journal events
    target_date: date object — typically yesterday
    strategies: optional list of strategy values to scope the trades query.
        When provided, restricts gd_trades count/pnl to rows whose `strategy`
        column is in this list (in ADDITION to the trade_ref LIKE).
        Issue #3 fix 2026-06-15: Gold Macro previously called with "GD-%"
        which matched Gold Micro (GD-MI-). Pass strategies=['alpha_sweep',
        'mean_rev', 'cross_market'] to scope correctly.

    Returns dict with: total_trades, orphans_adopted, db_insert_failed,
    journal_errors, net_pnl. Used by the 00:00 UTC daily recon notify call.

    Uses BETWEEN range queries (not ::date) so the gd_trades_entry_time and
    gd_journal_event_type_ts indexes get used. Postgres rejects index
    expressions on (entry_time::date) because the cast depends on session
    timezone (not IMMUTABLE).
    """
    from datetime import datetime, time, timedelta, timezone as _tz
    day_start = datetime.combine(target_date, time.min, tzinfo=_tz.utc)
    day_end = day_start + timedelta(days=1)

    if strategies:
        placeholders = ",".join(["%s"] * len(strategies))
        rows = execute(
            f"""SELECT COUNT(*)::int AS cnt, COALESCE(SUM(pnl_usd), 0)::float AS pnl
               FROM gd_trades
               WHERE trade_ref LIKE %s
                 AND strategy IN ({placeholders})
                 AND entry_time >= %s AND entry_time < %s""",
            (trade_ref_pattern, *strategies, day_start, day_end), fetch=True
        )
    else:
        rows = execute(
            """SELECT COUNT(*)::int AS cnt, COALESCE(SUM(pnl_usd), 0)::float AS pnl
               FROM gd_trades
               WHERE trade_ref LIKE %s
                 AND entry_time >= %s AND entry_time < %s""",
            (trade_ref_pattern, day_start, day_end), fetch=True
        )
    total = rows[0]["cnt"] if rows else 0
    pnl = float(rows[0]["pnl"] or 0) if rows else 0.0

    def count_event(event_type):
        r = execute(
            """SELECT COUNT(*)::int AS cnt FROM gd_journal
               WHERE strategy = %s AND event_type = %s
                 AND timestamp >= %s AND timestamp < %s""",
            (strategy_pattern, event_type, day_start, day_end), fetch=True
        )
        return r[0]["cnt"] if r else 0

    return {
        "total_trades": total,
        "orphans_adopted": count_event("ORPHAN_ADOPTED"),
        "db_insert_failed": count_event("DB_INSERT_FAILED"),
        "journal_errors": count_event("ORPHAN_ADOPT_FAILED") + count_event("EXECUTE_SIGNAL_RAISED"),
        "exit_ambiguous": count_event("EXIT_AMBIGUOUS"),
        "net_pnl": pnl,
    }



def is_sweep_consumed(system: str, target_date, sweep_key: str) -> bool:
    """Issue #9: persistent sweep blacklist (replaces in-memory _traded_sweeps_*).

    Returns True if the sweep_key was already consumed by `system` on `target_date`.
    `system` is one of 'gold-macro' / 'gold-micro' / 'oil-macro' / 'oil-micro'.
    """
    rows = execute(
        "SELECT 1 FROM gd_traded_sweeps WHERE system = %s AND date = %s AND sweep_key = %s LIMIT 1",
        (system, target_date, sweep_key), fetch=True
    )
    return bool(rows)


def mark_sweep_consumed(system: str, target_date, sweep_key: str) -> None:
    """Insert sweep_key into the blacklist. Idempotent via UNIQUE constraint."""
    execute(
        """INSERT INTO gd_traded_sweeps (system, date, sweep_key)
           VALUES (%s, %s, %s)
           ON CONFLICT (system, date, sweep_key) DO NOTHING""",
        (system, target_date, sweep_key)
    )
