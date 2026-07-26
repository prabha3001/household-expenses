# -*- coding: utf-8 -*-
"""
Database access layer. Two backends are supported behind one thin API:

- SQLite (default — used for local/dev, and works fine on any single-instance
  deployment where the disk is persistent). No extra dependency: sqlite3 is
  part of the Python standard library.
- PostgreSQL (used when DATABASE_URL is set to a postgres:// URL — e.g. a free
  Neon database) via psycopg2, for deployments where the app's own disk is
  NOT persistent (e.g. Render's free web service, whose filesystem resets on
  every redeploy) but the data must survive indefinitely.

NOTE: the Postgres path is written to the standard psycopg2 API and mirrors
the SQLite path query-for-query, but this build environment's outbound
network access is restricted to a small allowlist that does not include
installing psycopg2, so it could only be verified for syntax, not run
against a live Postgres server. Test it once after your first deploy (the
README has a smoke-test step) — flag anything odd and it's a quick fix.
"""
import os
import sqlite3
import datetime

DB_PATH = os.environ.get('SQLITE_PATH', os.path.join(os.path.dirname(__file__), 'data', 'app.db'))
DATABASE_URL = os.environ.get('DATABASE_URL')
IS_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith(('postgres://', 'postgresql://')))

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

_conn = None

def get_conn():
    global _conn
    if _conn is not None:
        try:
            if IS_POSTGRES:
                cur = _conn.cursor(); cur.execute('SELECT 1'); cur.close()
            else:
                _conn.execute('SELECT 1')
            return _conn
        except Exception:
            _conn = None
    if IS_POSTGRES:
        _conn = psycopg2.connect(DATABASE_URL)
        _conn.autocommit = False
    else:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute('PRAGMA foreign_keys = ON')
    return _conn

def _adapt(sql):
    if IS_POSTGRES:
        sql = sql.replace('?', '%s')
        sql = sql.replace('AUTOINCREMENT', '')
        sql = sql.replace('INTEGER PRIMARY KEY', 'SERIAL PRIMARY KEY')
    return sql

def run_many(sql, seq_of_params, commit=True):
    """Bulk-insert helper: one round-trip to the database for many rows,
    instead of one round-trip per row. This matters a lot on Postgres
    (Neon) where every query has real network latency — a 12-file batch
    upload with a few hundred transactions total was slow enough on
    Render's free instance to trip gunicorn's worker timeout when each
    transaction was inserted with its own separate query.
    """
    conn = get_conn()
    sql2 = _adapt(sql)
    cur = conn.cursor()
    cur.executemany(sql2, seq_of_params)
    if commit:
        conn.commit()
    cur.close()


def run(sql, params=(), fetch=None, commit=False, returning_id=False):
    """
    fetch: None | 'one' | 'all'
    returning_id: if True (Postgres only), appends RETURNING id and returns it
    """
    conn = get_conn()
    sql2 = _adapt(sql)
    if IS_POSTGRES and returning_id and 'RETURNING' not in sql2.upper():
        sql2 = sql2.rstrip().rstrip(';') + ' RETURNING id'
    if IS_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()
    cur.execute(sql2, params)
    result = None
    new_id = None
    if returning_id:
        if IS_POSTGRES:
            row = cur.fetchone()
            new_id = row['id'] if row else None
        else:
            new_id = cur.lastrowid
    if fetch == 'one':
        result = cur.fetchone()
    elif fetch == 'all':
        result = cur.fetchall()
    if commit:
        conn.commit()
    cur.close()
    return (result, new_id) if returning_id else result

def now_iso():
    return datetime.datetime.utcnow().isoformat()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    is_active INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Append-only upload log. Deliberately NOT unique on (account, period): two
-- real statements (e.g. adjacent credit-card billing cycles) can legitimately
-- both land in "mostly January" once bucketed by month, and both are real.
-- Duplicate protection is at the FILE level (file_hash, a SHA-256 of the
-- uploaded PDF's bytes) so re-uploading the exact same statement twice is a
-- harmless no-op, without risking two genuinely-separate same-day,
-- same-amount transactions (e.g. two identical top-ups) being mistaken for
-- duplicates of each other.
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    period TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_hash TEXT,
    uploaded_by INTEGER,
    uploaded_at TEXT NOT NULL,
    txn_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id INTEGER,
    account TEXT NOT NULL,
    date TEXT,
    month TEXT,
    txn_desc TEXT,
    amount REAL NOT NULL,
    dir TEXT NOT NULL,
    type TEXT,
    category TEXT,
    subcategory TEXT,
    shopping_subcategory TEXT,
    canonical_merchant TEXT,
    is_dd INTEGER NOT NULL DEFAULT 0,
    is_atm INTEGER NOT NULL DEFAULT 0,
    is_refund INTEGER NOT NULL DEFAULT 0
);
"""

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    for stmt in SCHEMA.strip().split(';'):
        stmt = stmt.strip()
        if stmt:
            cur.execute(_adapt(stmt))
    conn.commit()
    cur.close()
# -*- coding: utf-8 -*-
"""
Database access layer. Two backends are supported behind one thin API:

- SQLite (default — used for local/dev, and works fine on any single-instance
  deployment where the disk is persistent). No extra dependency: sqlite3 is
  part of the Python standard library.
- PostgreSQL (used when DATABASE_URL is set to a postgres:// URL — e.g. a free
  Neon database) via psycopg2, for deployments where the app's own disk is
  NOT persistent (e.g. Render's free web service, whose filesystem resets on
  every redeploy) but the data must survive indefinitely.

NOTE: the Postgres path is written to the standard psycopg2 API and mirrors
the SQLite path query-for-query, but this build environment's outbound
network access is restricted to a small allowlist that does not include
installing psycopg2, so it could only be verified for syntax, not run
against a live Postgres server. Test it once after your first deploy (the
README has a smoke-test step) — flag anything odd and it's a quick fix.
"""
import os
import sqlite3
import datetime

DB_PATH = os.environ.get('SQLITE_PATH', os.path.join(os.path.dirname(__file__), 'data', 'app.db'))
DATABASE_URL = os.environ.get('DATABASE_URL')
IS_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith(('postgres://', 'postgresql://')))

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

_conn = None

def get_conn():
    global _conn
    if _conn is not None:
        try:
            if IS_POSTGRES:
                cur = _conn.cursor(); cur.execute('SELECT 1'); cur.close()
            else:
                _conn.execute('SELECT 1')
            return _conn
        except Exception:
            _conn = None
    if IS_POSTGRES:
        _conn = psycopg2.connect(DATABASE_URL)
        _conn.autocommit = False
    else:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute('PRAGMA foreign_keys = ON')
    return _conn

def _adapt(sql):
    if IS_POSTGRES:
        sql = sql.replace('?', '%s')
        sql = sql.replace('AUTOINCREMENT', '')
        sql = sql.replace('INTEGER PRIMARY KEY', 'SERIAL PRIMARY KEY')
    return sql

def run(sql, params=(), fetch=None, commit=False, returning_id=False):
    """
    fetch: None | 'one' | 'all'
    returning_id: if True (Postgres only), appends RETURNING id and returns it
    """
    conn = get_conn()
    sql2 = _adapt(sql)
    if IS_POSTGRES and returning_id and 'RETURNING' not in sql2.upper():
        sql2 = sql2.rstrip().rstrip(';') + ' RETURNING id'
    if IS_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()
    cur.execute(sql2, params)
    result = None
    new_id = None
    if returning_id:
        if IS_POSTGRES:
            row = cur.fetchone()
            new_id = row['id'] if row else None
        else:
            new_id = cur.lastrowid
    if fetch == 'one':
        result = cur.fetchone()
    elif fetch == 'all':
        result = cur.fetchall()
    if commit:
        conn.commit()
    cur.close()
    return (result, new_id) if returning_id else result

def now_iso():
    return datetime.datetime.utcnow().isoformat()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    is_active INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Append-only upload log. Deliberately NOT unique on (account, period): two
-- real statements (e.g. adjacent credit-card billing cycles) can legitimately
-- both land in "mostly January" once bucketed by month, and both are real.
-- Duplicate protection is at the FILE level (file_hash, a SHA-256 of the
-- uploaded PDF's bytes) so re-uploading the exact same statement twice is a
-- harmless no-op, without risking two genuinely-separate same-day,
-- same-amount transactions (e.g. two identical top-ups) being mistaken for
-- duplicates of each other.
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    period TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_hash TEXT,
    uploaded_by INTEGER,
    uploaded_at TEXT NOT NULL,
    txn_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id INTEGER,
    account TEXT NOT NULL,
    date TEXT,
    month TEXT,
    txn_desc TEXT,
    amount REAL NOT NULL,
    dir TEXT NOT NULL,
    type TEXT,
    category TEXT,
    subcategory TEXT,
    shopping_subcategory TEXT,
    canonical_merchant TEXT,
    is_dd INTEGER NOT NULL DEFAULT 0,
    is_atm INTEGER NOT NULL DEFAULT 0,
    is_refund INTEGER NOT NULL DEFAULT 0
);
"""

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    for stmt in SCHEMA.strip().split(';'):
        stmt = stmt.strip()
        if stmt:
            cur.execute(_adapt(stmt))
    conn.commit()
    cur.close()
