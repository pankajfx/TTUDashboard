"""
SQLite data-access layer — the app's single source of truth.

Replaces the old data/*.json files (users, course assignments, and the API cache).
There is no server to install: SQLite is a single file (``data/app.db`` by default,
override with the ``APP_DB_PATH`` env var) accessed through Python's stdlib
``sqlite3`` — no extra dependency.

Design notes
------------
* The app manipulates whole collections in Python (load-all -> mutate -> save-all),
  so each store exposes read_*/write_* that round-trip the exact dict shapes the app
  already uses. A write replaces the whole table inside one transaction, mirroring
  the previous "rewrite the whole JSON file" semantics (last-write-wins) — so no
  call site had to change its logic.
* Meaningful fields are real columns (the DB stays queryable/readable); any other
  key is preserved losslessly in an ``extra`` JSON column, so nothing is silently
  dropped and the schema never drifts.
* Insertion order is preserved (ORDER BY rowid) so collections come back in the same
  order the JSON arrays had them.
* One short-lived connection per call — simple and thread-safe for this app's load.
* On a brand-new DB file, the tables are bootstrapped once from the existing JSON
  files; afterwards those files are ignored (keep them as backups).
"""
import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get('APP_DB_PATH', os.path.join('data', 'app.db'))

# Default JSON locations used for the one-time bootstrap / the migration script.
USERS_JSON = os.path.join('data', 'users.json')
ASSIGNMENTS_JSON = os.path.join('data', 'course_assignments.json')
CACHE_JSON = os.path.join('data', 'api_cache.json')

# Fields kept as real columns; every other key rides along in the `extra` JSON blob.
_USER_COLS = ('email', 'name', 'source', 'added_date')
_ASSIGN_COLS = ('id', 'course_name', 'user_emails', 'deadline', 'effective_from',
                'effective_to', 'created_date', 'created_by', 'title', 'source',
                'last_modified')


# ── connection ──────────────────────────────────────────────────────────────
def _connect():
    os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def _create_tables(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            email      TEXT PRIMARY KEY,
            name       TEXT,
            source     TEXT,
            added_date TEXT,
            extra      TEXT
        );
        CREATE TABLE IF NOT EXISTS assignments (
            id             INTEGER PRIMARY KEY,
            course_name    TEXT,
            user_emails    TEXT,   -- JSON array
            deadline       TEXT,
            effective_from TEXT,
            effective_to   TEXT,
            created_date   TEXT,
            created_by     TEXT,
            title          TEXT,
            source         TEXT,
            last_modified  TEXT,
            extra          TEXT
        );
        CREATE TABLE IF NOT EXISTS api_cache (
            id                 INTEGER PRIMARY KEY CHECK (id = 1),
            data               TEXT,   -- JSON array of API records
            timestamp          TEXT,   -- ISO 8601
            cached_at_readable TEXT
        );
    ''')


def init_db():
    """Create tables if needed and, on a brand-new DB file, bootstrap the data
    once from the existing JSON files. Idempotent — safe to call on every start."""
    is_new = not os.path.exists(DB_PATH)
    conn = _connect()
    try:
        _create_tables(conn)
        conn.commit()
    finally:
        conn.close()
    if is_new:
        migrate_from_json(force=False)


# ── users ───────────────────────────────────────────────────────────────────
def _row_to_user(r):
    d = {'email': r['email'], 'name': r['name'], 'source': r['source'],
         'added_date': r['added_date']}
    if r['extra']:
        d.update(json.loads(r['extra']))
    return d


def read_users():
    conn = _connect()
    try:
        rows = conn.execute('SELECT * FROM users ORDER BY rowid').fetchall()
    finally:
        conn.close()
    return {'users': [_row_to_user(r) for r in rows]}


def write_users(data):
    users = data.get('users', []) if isinstance(data, dict) else (data or [])
    conn = _connect()
    try:
        conn.execute('DELETE FROM users')
        for u in users:
            u = dict(u or {})
            extra = {k: v for k, v in u.items() if k not in _USER_COLS}
            conn.execute(
                'INSERT OR REPLACE INTO users (email, name, source, added_date, extra) '
                'VALUES (?, ?, ?, ?, ?)',
                ((u.get('email') or '').strip(), u.get('name'), u.get('source'),
                 u.get('added_date'), json.dumps(extra) if extra else None))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f'db.write_users error: {e}')
        return False
    finally:
        conn.close()


# ── assignments ─────────────────────────────────────────────────────────────
def _row_to_assignment(r):
    d = {
        'id': r['id'],
        'course_name': r['course_name'],
        'user_emails': json.loads(r['user_emails']) if r['user_emails'] else [],
        'deadline': r['deadline'],
        'effective_from': r['effective_from'],
        'effective_to': r['effective_to'],
        'created_date': r['created_date'],
        'created_by': r['created_by'],
        'title': r['title'],
        'source': r['source'],
        'last_modified': r['last_modified'],
    }
    if r['extra']:
        d.update(json.loads(r['extra']))
    # Drop columns that are absent (NULL) so we don't inject keys the JSON lacked.
    return {k: v for k, v in d.items()
            if v is not None or k in ('id', 'course_name', 'user_emails')}


def read_assignments():
    conn = _connect()
    try:
        rows = conn.execute('SELECT * FROM assignments ORDER BY rowid').fetchall()
    finally:
        conn.close()
    return {'assignments': [_row_to_assignment(r) for r in rows]}


def write_assignments(data):
    items = data.get('assignments', []) if isinstance(data, dict) else (data or [])
    conn = _connect()
    try:
        conn.execute('DELETE FROM assignments')
        for a in items:
            a = dict(a or {})
            extra = {k: v for k, v in a.items() if k not in _ASSIGN_COLS}
            conn.execute(
                'INSERT OR REPLACE INTO assignments '
                '(id, course_name, user_emails, deadline, effective_from, effective_to, '
                ' created_date, created_by, title, source, last_modified, extra) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (a.get('id'), a.get('course_name'),
                 json.dumps(a.get('user_emails') or []),
                 a.get('deadline'), a.get('effective_from'), a.get('effective_to'),
                 a.get('created_date'), a.get('created_by'), a.get('title'),
                 a.get('source'), a.get('last_modified'),
                 json.dumps(extra) if extra else None))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f'db.write_assignments error: {e}')
        return False
    finally:
        conn.close()


# ── API cache ───────────────────────────────────────────────────────────────
def read_cache():
    """Return (data_list, timestamp_datetime) or (None, None)."""
    conn = _connect()
    try:
        row = conn.execute(
            'SELECT data, timestamp FROM api_cache WHERE id = 1').fetchone()
    finally:
        conn.close()
    if not row or not row['data']:
        return None, None
    try:
        return json.loads(row['data']), datetime.fromisoformat(row['timestamp'])
    except Exception as e:
        print(f'db.read_cache error: {e}')
        return None, None


def write_cache(data, timestamp):
    conn = _connect()
    try:
        conn.execute(
            'INSERT OR REPLACE INTO api_cache (id, data, timestamp, cached_at_readable) '
            'VALUES (1, ?, ?, ?)',
            (json.dumps(data, ensure_ascii=False), timestamp.isoformat(),
             timestamp.strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f'db.write_cache error: {e}')
        return False


# ── migration / bootstrap ───────────────────────────────────────────────────
def _load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f'db migrate: could not read {path}: {e}')
    return default


def migrate_from_json(force=False, users_path=USERS_JSON,
                      assignments_path=ASSIGNMENTS_JSON, cache_path=CACHE_JSON):
    """Import the existing JSON files into SQLite.

    force=False (bootstrap): only fills a table that is currently empty, so it
    never clobbers live data. force=True: wipes the three tables first and
    re-imports — used by the standalone migration script.
    Returns a dict of how many rows landed in each store."""
    conn = _connect()
    try:
        _create_tables(conn)
        if force:
            conn.executescript(
                'DELETE FROM users; DELETE FROM assignments; DELETE FROM api_cache;')
            conn.commit()
        counts = {
            'users': conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],
            'assignments': conn.execute('SELECT COUNT(*) FROM assignments').fetchone()[0],
            'api_cache': conn.execute('SELECT COUNT(*) FROM api_cache').fetchone()[0],
        }
    finally:
        conn.close()

    result = {'users': 0, 'assignments': 0, 'api_cache': 0}

    if counts['users'] == 0:
        users = _load_json(users_path, {'users': []})
        if users.get('users'):
            write_users(users)
            result['users'] = len(users['users'])

    if counts['assignments'] == 0:
        assignments = _load_json(assignments_path, {'assignments': []})
        if assignments.get('assignments'):
            write_assignments(assignments)
            result['assignments'] = len(assignments['assignments'])

    if counts['api_cache'] == 0:
        cache = _load_json(cache_path, None)
        if cache and cache.get('data') and cache.get('timestamp'):
            try:
                write_cache(cache['data'], datetime.fromisoformat(cache['timestamp']))
                result['api_cache'] = 1
            except Exception as e:
                print(f'db migrate: cache import skipped: {e}')

    return result
