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
_USER_COLS = ('email', 'name', 'source', 'added_date', 'department', 'location',
              'job_role', 'tracked', 'updated_date')
_ASSIGN_COLS = ('id', 'course_name', 'user_emails', 'deadline', 'effective_from',
                'effective_to', 'created_date', 'created_by', 'title', 'source',
                'last_modified')

# Columns added to `users` after the table first shipped. CREATE TABLE IF NOT EXISTS
# will not add them to an existing app.db, so _migrate_schema ALTERs them in.
_USER_ADDED_COLS = (
    ('department', 'TEXT'),
    ('location', 'TEXT'),
    ('job_role', 'TEXT'),
    ('tracked', 'INTEGER'),   # 1 = admin-supplied (roster), 0 = API-only (untracked)
    ('updated_date', 'TEXT'),
)


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
            email        TEXT PRIMARY KEY,
            name         TEXT,
            source       TEXT,
            added_date   TEXT,
            department   TEXT,
            location     TEXT,
            job_role     TEXT,
            tracked      INTEGER,
            updated_date TEXT,
            extra        TEXT
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
        -- Append-only ledger of every distinct completion date ever observed.
        -- The TCS iON API returns only ONE (latest) completion date per
        -- (course, user) and overwrites it in place when a user re-does a
        -- recurring course, so prior-cycle dates survive only if we capture them
        -- here across snapshots. Dedup is by the (course, email, date) key; each
        -- assignment is then judged against this whole bucket, not the API's
        -- single moving value.
        CREATE TABLE IF NOT EXISTS completion_history (
            course          TEXT NOT NULL,
            email           TEXT NOT NULL,
            completion_date TEXT NOT NULL,   -- 'YYYY-MM-DD'
            first_seen      TEXT,            -- ISO 8601, when first observed
            last_seen       TEXT,            -- ISO 8601, when most recently observed
            PRIMARY KEY (course, email, completion_date)
        );
        -- One row per (assignment, user) congratulations email. Doubles as the
        -- claim ledger: the dispatcher INSERTs 'pending' rows first, so a second
        -- sync running concurrently claims nothing and cannot double-send. A row
        -- that fails to send is deleted, so the next sync retries it.
        CREATE TABLE IF NOT EXISTS completion_notifications (
            assignment_id   INTEGER NOT NULL,
            email           TEXT NOT NULL,
            course          TEXT,
            completion_date TEXT,
            status          TEXT,            -- 'pending' | 'sent' | 'pre_existing'
            claimed_at      TEXT,
            sent_at         TEXT,
            PRIMARY KEY (assignment_id, email)
        );
        -- An assignment gets a baseline row the moment it starts being watched for
        -- completions. Users already Completed at that moment are recorded as
        -- 'pre_existing' and never emailed — only completions detected *after* the
        -- baseline are congratulated. Without this, the first sync after an
        -- assignment is created with a backdated window (or the first sync after this
        -- feature shipped) would blast a congratulations mail at everyone who had
        -- already finished long ago.
        CREATE TABLE IF NOT EXISTS notification_baseline (
            assignment_id INTEGER PRIMARY KEY,
            created_at    TEXT
        );
    ''')


def _migrate_schema(conn):
    """Add columns introduced after a table first shipped. CREATE TABLE IF NOT
    EXISTS is a no-op on an existing app.db, so new columns must be ALTERed in.
    Idempotent: checks PRAGMA table_info first."""
    have = {r['name'] for r in conn.execute('PRAGMA table_info(users)')}
    added = False
    for col, coltype in _USER_ADDED_COLS:
        if col not in have:
            conn.execute(f'ALTER TABLE users ADD COLUMN {col} {coltype}')
            added = True
    if added or 'tracked' not in have:
        # Backfill the tracked flag for rows that predate it: anything the admin
        # put there (manual add / upload) is part of the authentic roster; users
        # that only ever came from the API sync are untracked.
        conn.execute(
            "UPDATE users SET tracked = CASE WHEN source = 'api' THEN 0 ELSE 1 END "
            "WHERE tracked IS NULL")


def init_db():
    """Create tables if needed and, on a brand-new DB file, bootstrap the data
    once from the existing JSON files. Idempotent — safe to call on every start."""
    is_new = not os.path.exists(DB_PATH)
    conn = _connect()
    try:
        _create_tables(conn)
        _migrate_schema(conn)
        conn.commit()
    finally:
        conn.close()
    if is_new:
        migrate_from_json(force=False)


# ── users ───────────────────────────────────────────────────────────────────
# A user row carries an optional profile (department / location / job_role) plus a
# `tracked` flag. Tracked users are the authentic roster the admin uploaded or added
# by hand; users that only ever appeared in the API sync are untracked — they still
# show up in analytics, but can be excluded with one switch on the dashboard.
def _row_to_user(r):
    d = {'email': r['email'], 'name': r['name'], 'source': r['source'],
         'added_date': r['added_date'],
         'department': r['department'] or '',
         'location': r['location'] or '',
         'job_role': r['job_role'] or '',
         'tracked': bool(r['tracked']),
         'updated_date': r['updated_date'] or ''}
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
                'INSERT OR REPLACE INTO users (email, name, source, added_date, '
                ' department, location, job_role, tracked, updated_date, extra) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                ((u.get('email') or '').strip(), u.get('name'), u.get('source'),
                 u.get('added_date'), u.get('department') or '', u.get('location') or '',
                 u.get('job_role') or '', 1 if u.get('tracked') else 0,
                 u.get('updated_date') or '',
                 json.dumps(extra) if extra else None))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f'db.write_users error: {e}')
        return False
    finally:
        conn.close()


def upsert_user_profiles(profiles, timestamp=None):
    """Apply an uploaded roster to the users table, matching on email (case-insensitive).

    ``profiles`` is an iterable of dicts with an ``email`` plus any of ``name``,
    ``department``, ``location``, ``job_role``. An existing user — including one the
    API sync created — is *augmented* in place: supplied fields overwrite, blank
    fields leave the stored value alone, and the row is promoted to tracked=1. An
    unknown email is inserted as a new tracked user. Users absent from the upload
    are untouched, so they keep whatever they had (untracked, no profile).

    Returns {'added': n, 'updated': n} — 'updated' counts rows that already existed.
    """
    ts = timestamp or datetime.now()
    ts = ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, 'strftime') else str(ts)
    conn = _connect()
    added = updated = 0
    try:
        _create_tables(conn)
        _migrate_schema(conn)
        existing = {(r['email'] or '').strip().lower(): r['email']
                    for r in conn.execute('SELECT email FROM users')}
        for p in profiles or []:
            email = (p.get('email') or '').strip()
            if not email:
                continue
            key = email.lower()
            stored = existing.get(key)
            if stored is None:
                conn.execute(
                    'INSERT INTO users (email, name, source, added_date, department, '
                    ' location, job_role, tracked, updated_date) '
                    "VALUES (?, ?, 'upload', ?, ?, ?, ?, 1, ?)",
                    (email, (p.get('name') or '').strip(), ts,
                     (p.get('department') or '').strip(), (p.get('location') or '').strip(),
                     (p.get('job_role') or '').strip(), ts))
                existing[key] = email
                added += 1
            else:
                # COALESCE(NULLIF(?, ''), col) — an omitted/blank cell in the upload
                # must not wipe a value the row already carries.
                conn.execute(
                    'UPDATE users SET '
                    "  name        = COALESCE(NULLIF(?, ''), name), "
                    "  department  = COALESCE(NULLIF(?, ''), department), "
                    "  location    = COALESCE(NULLIF(?, ''), location), "
                    "  job_role    = COALESCE(NULLIF(?, ''), job_role), "
                    "  source      = 'upload', "
                    '  tracked     = 1, '
                    '  updated_date = ? '
                    'WHERE email = ?',
                    ((p.get('name') or '').strip(), (p.get('department') or '').strip(),
                     (p.get('location') or '').strip(), (p.get('job_role') or '').strip(),
                     ts, stored))
                updated += 1
        conn.commit()
        return {'added': added, 'updated': updated}
    except Exception as e:
        conn.rollback()
        print(f'db.upsert_user_profiles error: {e}')
        return {'added': 0, 'updated': 0}
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
    finally:
        conn.close()


# ── completion-history ledger ───────────────────────────────────────────────
def record_completions(rows, timestamp=None):
    """Fold observed completions into the append-only completion_history ledger.

    ``rows`` is an iterable of ``(course, email, completion_date_str)`` tuples —
    typically ``assignment_analytics.extract_completions(api_data)``. Each distinct
    (course, email, date) is inserted once (INSERT OR IGNORE on the primary key);
    a repeat sighting just refreshes ``last_seen``. This is how prior-cycle dates
    survive the API overwriting its single latest value per (course, user).

    Returns the count of NEW (previously unseen) completion dates recorded."""
    ts = timestamp or datetime.now()
    ts = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
    conn = _connect()
    new = 0
    try:
        _create_tables(conn)  # tolerate an older DB that predates this table
        for row in rows or []:
            try:
                course, email, date_str = row
            except (ValueError, TypeError):
                continue
            course = (course or '').strip()
            email = (email or '').strip()
            date_str = (date_str or '').strip()
            if not (course and email and date_str):
                continue
            cur = conn.execute(
                'INSERT OR IGNORE INTO completion_history '
                '(course, email, completion_date, first_seen, last_seen) '
                'VALUES (?, ?, ?, ?, ?)',
                (course, email, date_str, ts, ts))
            if cur.rowcount:
                new += 1
            else:
                conn.execute(
                    'UPDATE completion_history SET last_seen = ? '
                    'WHERE course = ? AND email = ? AND completion_date = ?',
                    (ts, course, email, date_str))
        conn.commit()
        return new
    except Exception as e:
        conn.rollback()
        print(f'db.record_completions error: {e}')
        return 0
    finally:
        conn.close()


def read_completion_history():
    """Return every ledger row as a list of ``(course, email, completion_date)``
    tuples, for building the (course, email) -> [dates] index the analytics engine
    unions with the live snapshot."""
    conn = _connect()
    try:
        _create_tables(conn)  # tolerate an older DB that predates this table
        rows = conn.execute(
            'SELECT course, email, completion_date FROM completion_history').fetchall()
    finally:
        conn.close()
    return [(r['course'], r['email'], r['completion_date']) for r in rows]


# ── completion-notification ledger ──────────────────────────────────────────
def baselined_assignment_ids():
    """Ids of assignments already being watched for new completions."""
    conn = _connect()
    try:
        _create_tables(conn)
        rows = conn.execute('SELECT assignment_id FROM notification_baseline').fetchall()
    finally:
        conn.close()
    return {r['assignment_id'] for r in rows}


def set_notification_baseline(assignment_id, already_completed, timestamp=None):
    """Start watching an assignment for completions.

    ``already_completed`` is the iterable of candidate dicts (same shape as
    ``claim_completion_notifications``) for users who are *already* Completed inside
    the assignment's window right now. They are written to the ledger as
    'pre_existing', which permanently suppresses their congratulations email — they
    finished before anyone was watching, so there is no completion *event* to
    announce. Everyone who completes from here on is emailed exactly once.

    Idempotent: an assignment that already has a baseline is left alone."""
    ts = timestamp or datetime.now()
    ts = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
    conn = _connect()
    try:
        _create_tables(conn)
        cur = conn.execute(
            'INSERT OR IGNORE INTO notification_baseline (assignment_id, created_at) '
            'VALUES (?, ?)', (assignment_id, ts))
        if not cur.rowcount:
            conn.rollback()
            return 0   # already baselined; do not re-suppress anything
        seeded = 0
        for c in already_completed or []:
            email = (c.get('email') or '').strip()
            if not email:
                continue
            cur = conn.execute(
                'INSERT OR IGNORE INTO completion_notifications '
                '(assignment_id, email, course, completion_date, status, claimed_at) '
                "VALUES (?, ?, ?, ?, 'pre_existing', ?)",
                (assignment_id, email, c.get('course') or '',
                 c.get('completion_date') or '', ts))
            seeded += cur.rowcount
        conn.commit()
        return seeded
    except Exception as e:
        conn.rollback()
        print(f'db.set_notification_baseline error: {e}')
        return 0
    finally:
        conn.close()


def suppress_completion_notifications(candidates, timestamp=None):
    """Record (assignment, user) pairs as 'pre_existing' — already complete when they
    came under the assignment, so there is no completion *event* to congratulate.

    Used when users are added to an assignment that is already being watched: a person
    who finished the course before they were assigned it should not be emailed as if
    they had just completed it. Pairs already in the ledger are left alone."""
    ts = timestamp or datetime.now()
    ts = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
    conn = _connect()
    n = 0
    try:
        _create_tables(conn)
        for c in candidates or []:
            aid = c.get('assignment_id')
            email = (c.get('email') or '').strip()
            if aid is None or not email:
                continue
            cur = conn.execute(
                'INSERT OR IGNORE INTO completion_notifications '
                '(assignment_id, email, course, completion_date, status, claimed_at) '
                "VALUES (?, ?, ?, ?, 'pre_existing', ?)",
                (aid, email, c.get('course') or '', c.get('completion_date') or '', ts))
            n += cur.rowcount
        conn.commit()
        return n
    except Exception as e:
        conn.rollback()
        print(f'db.suppress_completion_notifications error: {e}')
        return 0
    finally:
        conn.close()


def claim_completion_notifications(candidates, timestamp=None):
    """Reserve the (assignment, user) pairs this process is about to congratulate.

    ``candidates`` is an iterable of dicts with ``assignment_id``, ``email`` and
    optionally ``course`` / ``completion_date``. Each pair is INSERTed with status
    'pending'; the (assignment_id, email) primary key means a pair already recorded
    — whether sent earlier or being sent right now by a concurrent refresh — is
    silently skipped. Only the rows this call actually inserted come back, so the
    caller can send exactly those and nothing is emailed twice.

    Call ``settle_notification`` for each claim afterwards: success marks it 'sent',
    failure deletes the claim so the next sync retries it."""
    ts = timestamp or datetime.now()
    ts = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
    conn = _connect()
    claimed = []
    try:
        _create_tables(conn)
        for c in candidates or []:
            aid = c.get('assignment_id')
            email = (c.get('email') or '').strip()
            if aid is None or not email:
                continue
            cur = conn.execute(
                'INSERT OR IGNORE INTO completion_notifications '
                '(assignment_id, email, course, completion_date, status, claimed_at) '
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (aid, email, c.get('course') or '', c.get('completion_date') or '', ts))
            if cur.rowcount:
                claimed.append(c)
        conn.commit()
        return claimed
    except Exception as e:
        conn.rollback()
        print(f'db.claim_completion_notifications error: {e}')
        return []
    finally:
        conn.close()


def settle_notification(assignment_id, email, sent, timestamp=None):
    """Close out a claim: ``sent=True`` marks it 'sent' (never emailed again),
    ``sent=False`` deletes the claim so the next API sync retries it."""
    ts = timestamp or datetime.now()
    ts = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
    conn = _connect()
    try:
        if sent:
            conn.execute(
                "UPDATE completion_notifications SET status = 'sent', sent_at = ? "
                'WHERE assignment_id = ? AND email = ?', (ts, assignment_id, email))
        else:
            conn.execute(
                'DELETE FROM completion_notifications '
                'WHERE assignment_id = ? AND email = ?', (assignment_id, email))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f'db.settle_notification error: {e}')
        return False
    finally:
        conn.close()


def read_completion_notifications(assignment_id=None):
    """Notification rows, optionally for one assignment. Used by the UI to show who
    has already been congratulated."""
    conn = _connect()
    try:
        _create_tables(conn)
        if assignment_id is None:
            rows = conn.execute(
                'SELECT * FROM completion_notifications').fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM completion_notifications WHERE assignment_id = ?',
                (assignment_id,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def delete_notifications_for_assignment(assignment_id):
    """Drop an assignment's notification rows when the assignment itself is deleted,
    so a later assignment that reuses the id can't inherit a 'already notified' state."""
    conn = _connect()
    try:
        _create_tables(conn)
        conn.execute('DELETE FROM completion_notifications WHERE assignment_id = ?',
                     (assignment_id,))
        conn.execute('DELETE FROM notification_baseline WHERE assignment_id = ?',
                     (assignment_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f'db.delete_notifications_for_assignment error: {e}')
        return False
    finally:
        conn.close()


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
        _migrate_schema(conn)
        conn.commit()
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
