"""Database connection and helpers for GoldDigger."""
import os
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
