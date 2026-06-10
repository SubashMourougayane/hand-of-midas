"""Apply a SQL file to the GoldDigger Postgres DB using DATABASE_URL from .env.

Usage:
    python scripts/run_sql.py <path_to_sql_file>

Why this exists: the Windows VPS's psql.exe doesn't pick up the right
credentials by default, but the trading services already have working
DATABASE_URL credentials in .env. This script uses the same connection
string so we never have to fight psql's auth prompts.
"""
import sys
import os
import psycopg2
from dotenv import load_dotenv


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_sql.py <path_to_sql_file>")
        sys.exit(1)

    sql_path = sys.argv[1]
    if not os.path.exists(sql_path):
        print(f"ERROR: file not found: {sql_path}")
        sys.exit(1)

    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    print(f"Connecting to: {db_url.split('@')[-1] if '@' in db_url else 'localhost'}")
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            sql = open(sql_path).read()
            print(f"Applying {sql_path} ({len(sql)} chars)...")
            cur.execute(sql)
            conn.commit()
            print(f"✓ {sql_path} applied successfully")
    except Exception as e:
        conn.rollback()
        print(f"✗ FAILED: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
