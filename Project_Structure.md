# TTU Summary — Course Analytics Dashboard
## Project Structure, Workflow & Business Logic

> **Maintenance note:** Update this file whenever core business logic, data flow, API contracts, or major UI/UX behaviour changes.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack & File Structure](#2-tech-stack--file-structure)
3. [Authentication & Security](#3-authentication--security)
4. [Data Layer & Cache System](#4-data-layer--cache-system)
5. [Business Logic — Dashboard & Analytics](#5-business-logic--dashboard--analytics)
6. [Business Logic — User Management](#6-business-logic--user-management)
7. [Business Logic — Course Assignments](#7-business-logic--course-assignments)
8. [Email Notification System](#8-email-notification-system)
9. [API Reference](#9-api-reference)
10. [UI/UX Design](#10-uiux-design)
11. [Deployment](#11-deployment)
12. [Configuration Reference](#12-configuration-reference)
13. [Troubleshooting & Monitoring](#13-troubleshooting--monitoring)
14. [Security Hardening — Status & Backlog](#14-security-hardening--status--backlog)

---

## 1. Project Overview

A Flask-based internal dashboard for tracking **Tata Tomorrow University (TTU)** course progress and user engagement. It pulls enrollment/completion data from the **TCS iON API**, caches it locally, and exposes it through an interactive UI with charts, tables, and an admin panel.

**Core capabilities:**
- Real-time KPI cards and interactive ECharts visualisations
- Per-course and per-user drill-down modals
- FY / quarter analytics, sliceable by **department, location and role** — one population narrows every figure on the page ([§7](#population-controls-top-of-the-page))
- Admin panel: user registry management, course assignments with deadlines
- Email notifications (assignment, reminder, removal) via Office 365 SMTP
- Background auto-refresh cache that keeps data ≤ 5 minutes stale without blocking users

---

## 2. Tech Stack & File Structure

### Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 / Flask |
| Frontend | Vanilla JS + hand-written `static/css/modern.css` + local Oswald font + ECharts (local) |
| Data store | **SQLite** (`data/app.db`, stdlib `sqlite3`) — source of truth via `db.py`. JSON files are migration seed/backup only |
| Email | smtplib → Office 365 SMTP (TLS, port 587) |
| Excel parsing | openpyxl |
| Password hashing | Werkzeug PBKDF2-SHA256 |
| Secrets | `python-dotenv` → `.env` (gitignored) |
| Concurrency | Python `threading` + `concurrent.futures.ThreadPoolExecutor` |

> **Storage note:** As of v1.3 the app reads/writes users, course assignments, and the API cache through `db.py` (SQLite at `data/app.db`). `db.init_db()` runs at import time in `app.py`, creating the DB + tables on first boot and, only when the DB file is brand-new, bootstrapping it once from the legacy `data/*.json` files. After that the JSON files are ignored. Styling is served entirely from committed files in `static/css/` — the compiled `tailwind.min.css` plus the hand-written `modern.css`. There is no CSS build step in deployment; only the Node tooling that *regenerates* `tailwind.min.css` is legacy.

### SQLite Schema (`data/app.db`)

| Table | Purpose |
|-------|---------|
| `users` | The user registry. Email + name + **department, location, job_role** + a **`tracked`** flag ([§6](#6-business-logic--user-management)) |
| `assignments` | Course assignments (users, deadline, validity window) |
| `api_cache` | The warm API snapshot (single row) |
| `completion_history` | Append-only ledger of every completion date ever observed — the API overwrites its single latest date per (course, user), so prior cycles survive only here |
| `completion_notifications` | One row per (assignment, user) congratulations email. PK `(assignment_id, email)` doubles as the claim lock that makes sending **exactly-once** ([§8](#automatic-completion-notifications)) |
| `notification_baseline` | Marks an assignment as "being watched" — completions predating the baseline are suppressed, so enabling the feature never blasts old completions |

**Schema migrations are automatic and idempotent.** `db._migrate_schema()` runs on every
boot: it reads `PRAGMA table_info(users)` and `ALTER TABLE`s in any column added since the
table first shipped (`CREATE TABLE IF NOT EXISTS` is a no-op on an existing DB, so new
columns must be added explicitly). On an existing `app.db`, `tracked` is backfilled as
`source = 'api' → 0, else 1` — i.e. anything the admin put there is roster, anything that
only ever came from the API sync is untracked. **No manual migration command; just deploy
the new code over the existing `app.db`.**

### File Structure

```
.
├── app.py                          # Flask app — all routes & business logic; calls db.init_db() at import
├── db.py                           # SQLite data-access layer (source of truth) — users, assignments, cache
├── assignment_analytics.py         # Assignment progress/analytics helpers
├── email_service.py                # SMTP email module (templates + sending)
├── requirements.txt                # Python dependencies
├── .env                            # Secrets (gitignored) — keys, passwords, API URL
├── .env.example                    # Sanitised template of required env vars (incl. SUPERADMIN_PASSWORD)
├── deploy_setup.ps1                # PowerShell deployment helper (venv + waitress + icacls)
├── deploy_simple.bat               # One-click Windows batch launcher (edit hardcoded paths!)
├── Response Sample.json            # Local data fixture (USE_LOCAL_DATA=true)
├── scripts/
│   └── seed_assignments_from_api.py  # Optional: pre-seed assignments from API on an empty setup
├── data/
│   ├── app.db                      # ★ SQLite DB — SOURCE OF TRUTH (auto-created; carries all live data)
│   ├── api_cache.json              # Legacy migration seed/backup only (ignored once app.db exists)
│   ├── users.json                  # Legacy migration seed/backup only
│   └── course_assignments.json     # Legacy migration seed/backup only
├── logs/
│   └── app.log                     # Rotating audit/app log (auto-created, gitignored)
├── templates/
│   ├── index.html                  # Main dashboard (SPA-style)
│   ├── login.html                  # Login page
│   ├── settings.html               # Admin settings page
│   └── assignments.html            # Assignments management page
├── static/                         # ★ Copy this folder whole — every file below is served
│   ├── css/tailwind.min.css        # ★ Compiled Tailwind utilities — REQUIRED, all 4 templates link it
│   ├── css/modern.css              # ★ Hand-written design system (committed)
│   ├── css/login.css               # ★ Per-page stylesheet
│   ├── css/settings.css            # ★ Per-page stylesheet
│   ├── css/assignments.css         # ★ Per-page stylesheet
│   ├── css/input.css               # Tailwind *source* — build-time only, unused at runtime
│   ├── fonts/Oswald/               # ★ Local Oswald font (self-hosted, satisfies CSP)
│   └── js/echarts.min.js           # ★ Charting library (self-hosted)
└── Project_Structure.md            # This file
```

> **★ marks what production actually uses.** `data/app.db` is the live store; the `data/*.json` files are only the one-time migration seed.
>
> **On Tailwind:** `tailwind.min.css` is **compiled output and is required at runtime** — every template links it (see SEC-09 in [§15](#15-security-audit), which was *resolved* by shipping this file instead of the CDN). What is legacy is the **build tooling** that regenerates it: `package.json`, `package-lock.json`, `tailwind.config.js`, `static/css/input.css`, `node_modules/`. Never deploy the tooling; always deploy the compiled CSS. Deployment needs only Python 3.11 + the `requirements.txt` deps + a WSGI server (gunicorn on Linux, waitress on Windows).

---

## 3. Authentication & Security

> Hardened on **2026-05-22**. All secrets now load from `.env` via `python-dotenv`; nothing sensitive remains in source. See [§14](#14-security-hardening--status--backlog) for the full per-item status.

### Login Flow

```
POST /login
  ├── Per-IP rate-limit: max 10 attempts / 60 s → 429 if exceeded
  ├── Read username + password from form
  ├── Per-username lockout: 5 consecutive failures → 429 for 15 min cooldown
  ├── Lookup username in USERS dict (hashes built at startup from .env)
  ├── check_password_hash() via Werkzeug
  ├── On success:
  │     _reset_failed_login(username)     # clear lockout counter
  │     session.clear()                  # prevent fixation
  │     session.permanent = True
  │     session['logged_in'] = True
  │     session['username'] = username
  │     session['role'] = USER_ROLES[username]
  │     session['_last_active'] = now
  └── On failure:
        _record_failed_login(username)    # increment, may trigger lockout
        logger.warning("Failed login attempt for '<user>' from <ip>")   # audit → logs/app.log
        re-render login.html with error
```

### Route Guards (Decorators)

| Decorator | Behaviour |
|-----------|-----------|
| `@login_required` | Redirects to `/login` if no active session |
| `@admin_required` | Redirects to `/login` OR returns 403 JSON unless `session['role'] == 'admin'` |
| `@csrf_required` | Returns 403 unless request carries a valid CSRF token (header or form field) |

### Credentials

Passwords are supplied as **plaintext in `.env`** (`ADMIN_PASSWORD`, `USER_PASSWORD`) and hashed in memory at startup with Werkzeug PBKDF2-SHA256 — no hashes or plaintext live in source. Accounts:

```
admin / <ADMIN_PASSWORD>   role=admin   (full access including /settings)
user  / <USER_PASSWORD>    role=user    (dashboard only)
```

To change a password, edit the value in `.env` and restart the app.

### Session Security

| Setting | Value | Purpose |
|---------|-------|---------|
| `SESSION_COOKIE_HTTPONLY` | `True` | Blocks JS access to the cookie (XSS theft) |
| `SESSION_COOKIE_SAMESITE` | `'Lax'` | Mitigates cross-site request use |
| `SESSION_COOKIE_SECURE` | `HTTPS_ONLY` env (`False` in dev) | HTTPS-only cookie when enabled |
| `PERMANENT_SESSION_LIFETIME` | `8 hours` | Absolute session expiry |
| Idle timeout | `30 min` | `@app.before_request` clears session after inactivity (tracked via `session['_last_active']`) |
| `MAX_CONTENT_LENGTH` | `5 MB` | Caps upload size (auto HTTP 413) |

### CSRF Protection

- A per-session token is generated (`secrets.token_hex(32)`) and exposed two ways: a `csrf_token` Jinja context variable and a `<meta name="csrf-token">` tag in every template `<head>`.
- The frontend patches `window.fetch` to auto-attach an `X-CSRF-Token` header on every `POST`/`PUT`/`DELETE`/`PATCH`.
- `@csrf_required` guards all 9 state-mutating endpoints; the token is validated against the session copy.

### HTTP Security Headers (`@app.after_request`)

Applied to every response:

```
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline';
                         style-src 'self' 'unsafe-inline'; img-src 'self' data:;
                         font-src 'self'; connect-src 'self'
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

> `script-src 'unsafe-inline'` is required because the templates rely on inline `<script>` blocks. Tailwind is served from a local compiled file (no CDN), satisfying `'self'`.

### XSS Prevention (frontend)

- An `h()` HTML-escape helper (escapes `& < > " '`) wraps **every** dynamic value inserted via `innerHTML` in `index.html` and `settings.html`.
- All previous `onclick="fn('${value}')"` patterns were replaced with `data-*` attributes plus delegated event listeners, eliminating attribute-based JS injection.

### Other Hardening
- Error responses return generic messages; full tracebacks are logged server-side only (no stack traces leaked to the browser).
- Assignment `user_emails` lists are capped at 500 entries to bound email-job size.
- **Upload validation:** Excel uploads are checked by magic bytes (`_is_valid_excel`) — `.xlsx` ZIP signature `PK\x03\x04` or `.xls` OLE2 signature — not just the filename extension.
- **Content-Type enforcement:** JSON endpoints carry `@json_required`, returning HTTP 415 unless the request is `application/json`.
- **Audit trail:** all auth events (failed logins, rate-limit trips, lockouts) are written to a rotating `logs/app.log` as well as the console — see [§13](#how-to-check-the-login-audit-trail-sec-18).
- No database — auth state lives in the signed session cookie; the signing key is `SECRET_KEY` from `.env`.

---

## 4. Data Layer & Cache System

### Data Sources

| Mode | Setting | Description |
|------|---------|-------------|
| Live API | `USE_LOCAL_DATA = False` | Fetches from TCS iON API URL |
| Local fixture | `USE_LOCAL_DATA = True` | Reads `Response Sample.json` |

### API Record Schema (from TCS iON)

Each record in the API response array contains:

```
User_Mail_ID                        — user email
Participant_Name                    — user display name
Activity_Name                       — course name
Course_Completion_Status            — "Completed" | "Current"
Activity_Status                     — "Not Attempted" | (other)
Course_Completion_Percentage        — "0"–"100"
Course_Completion_Date_(YYYY-MM-DD) — completion date or empty
```

### Background Cache Architecture

The API takes **3+ minutes** to respond. A background scheduler keeps a warm in-memory + on-disk cache so all user requests are served instantly.

#### Cache State Variables (`app.py` globals)

```python
_data_cache             # list[dict] — current API records in memory
_cache_timestamp        # datetime   — when cache was last populated
_cache_lock             # threading.Lock — guards reads/writes
_refresh_in_progress    # bool — prevents concurrent refreshes
AUTO_REFRESH_INTERVAL_MINUTES = 5
CACHE_FILE = 'data/api_cache.json'
API_TIMEOUT = 360  # seconds (API can take 3–5 min; gives headroom)
```

> **Reloader caveat:** the app runs `app.run(..., use_reloader=False)`. With the default reloader, Flask spawns a watcher + child process and `initialize_cache()` would run only in the watcher — leaving the request-serving child with no scheduler and permanently stale data. The scheduler also dispatches each refresh in its own thread so the slow API call never shifts the 5-minute interval.

#### Startup Initialisation (`initialize_cache`)

```
Server starts → initialize_cache()
  ├── USE_LOCAL_DATA=True → skip cache (reads file on every request)
  └── USE_LOCAL_DATA=False
        ├── load_cache_from_file()
        │     ├── Cache exists & fresh (< 5 min) → use it
        │     └── Cache missing or stale → spawn refresh thread
        └── Start cache_refresh_scheduler() daemon thread
```

#### Background Refresh Loop (`cache_refresh_scheduler`)

```
Every 5 minutes:
  └── refresh_cache_background()
        ├── Check _refresh_in_progress → skip if already running
        ├── Set _refresh_in_progress = True
        ├── fetch_fresh_data_from_api()  [blocks 3+ min]
        ├── Update _data_cache + _cache_timestamp (under lock)
        ├── save_cache_to_file()  → data/api_cache.json
        └── Set _refresh_in_progress = False
```

#### Manual Refresh Flow (UI "Get Latest Data" button)

```
User clicks button
  → POST /api/refresh-cache
      ├── If already refreshing → 202 "already in progress"
      └── Spawn refresh thread → 202 "started"

UI polls GET /api/status every 3 seconds
  └── When refresh_in_progress = false
        → loadDashboardData()  (no page reload)
        → showNotification("Data updated successfully!")
```

#### Cache File Format (`data/api_cache.json`)

```json
{
  "data": [ { ...record... }, ... ],
  "timestamp": "2026-02-15T14:30:00.123456",
  "cached_at_readable": "2026-02-15 14:30:00"
}
```

#### `load_data()` — The Single Entry Point

All routes call `load_data()` to get records. It never blocks after initialisation:
1. `USE_LOCAL_DATA=True` → read `Response Sample.json`
2. Cache in memory → return immediately
3. Cache missing → try file → else fetch synchronously (only on cold start with no cache file)

---

## 5. Business Logic — Dashboard & Analytics

### `/api/summary` — Core Aggregation

Iterates every API record and builds two aggregated structures:

**Course aggregation** (`courses` dict keyed by course name):
- `users` — unique user emails enrolled
- `completed` — users with `Course_Completion_Status == "Completed"`
- `in_progress` — users with status `"Current"` AND `Activity_Status != "Not Attempted"`
- `not_started` — users with status `"Current"` AND `Activity_Status == "Not Attempted"`
- `completion_rate` — `completed / total_users * 100`

**User aggregation** (`users` dict keyed by email):
- `courses` — all course names for this user
- `completed_courses` — subset where status is `"Completed"`
- `completion_rate` — `completed / total * 100`

**KPIs returned:**
```json
{
  "kpis": {
    "total_courses": <int>,
    "total_users": <int>,
    "total_enrollments": <sum of per-course user counts>,
    "overall_completion_rate": <float %>
  },
  "courses": [ ...sorted by total_users desc... ],
  "users":   [ ...sorted by total_courses desc... ]
}
```

### `/api/course/<name>` — Course Drill-Down

Returns per-user progress for a single course:
- Groups all matching records by `User_Mail_ID`
- Returns: name, email, completion %, status, activity status, completion date

### `/api/user/<email>` — User Drill-Down

Returns all courses for a single user:
- Sorted by `completion_date` ascending (uncompleted sorted last with `9999-99-99`)
- Used to render the timeline chart in the user detail modal

### Dashboard UI Components

| Component | Data source | Chart type |
|-----------|------------|-----------|
| KPI tiles (5 total) | `/api/summary` kpis | Stat cards |
| 5th tile | `/api/status` | Cache status + refresh button |
| Top Courses by Enrollment | courses list | Horizontal bar (ECharts) |
| Overall Completion Status | courses list | 3D donut (ECharts) |
| User Progress Overview | users list | Dual bar (ECharts) |
| Course Overview Table | courses list | Sortable table + CSV export |
| User Overview Table | users list | Sortable table + CSV export |
| Course Detail Modal | `/api/course/<name>` | User list table |
| User Detail Modal | `/api/user/<email>` | Timeline bar chart + table |

#### KPI Tile Grid Layout

```
xl (≥1280px): 5 columns  — [Courses] [Users] [Enrollments] [Completion%] [Cache+Refresh]
lg (1024–1279px): 3 cols
md (768–1023px): 2 cols
sm (<768px): 1 col
```

---

## 6. Business Logic — User Management

Users live in the `users` table (SQLite, via `db.py`). Each row is an email plus an
optional **profile** and a **tracked** flag:

```json
{
  "email": "user@example.com",
  "name": "John Doe",
  "source": "api | manual | upload",
  "added_date": "2025-12-05 14:30:00",
  "department": "Safety",
  "location": "Mumbai",
  "job_role": "Engineer",
  "tracked": true,
  "updated_date": "2026-07-12 11:02:00"
}
```

> The TCS iON API only ever supplies **email + name**. Department, location and role
> exist nowhere upstream — they come exclusively from the roster the admin uploads.

### Tracked vs Untracked — the authentic roster

| | Tracked (`tracked = 1`) | Untracked (`tracked = 0`) |
|---|---|---|
| **Who** | Uploaded on a roster, added by hand, or explicitly assigned a course | Seen in the API and never uploaded |
| **Profile** | Department / location / role (as supplied) | None — the API has no such fields |
| **Analytics** | Always counted | Counted only while *Include untracked users* is ticked |
| **Dimension bucket** | Their department / location / role, or `Unspecified` if the roster left the cell blank | The `Untracked` bucket |
| **Roster filter bucket** | Their department / location / role, or **`NA`** if the roster left the cell blank | **`NA`** — same bucket |
| **Table cells** (Users table, assignment drill-down modal) | Their department / location / role, or **`NA`** if the roster left the cell blank | **`NA`** on all three — there is no profile to read |

The uploaded roster is the **authentic source of users**. Anyone the API reports who
was never uploaded is classified untracked **automatically**, matched on email
(case-insensitive). No manual step marks them.

> **Two vocabularies, deliberately.** The *dimension breakdown* keeps `Unspecified` and
> `Untracked` apart, because the difference is informative there ("we have them on the
> roster but nobody filled in the cell" vs "we have never heard of them"). The *roster
> filter dropdowns* collapse both into a single **`NA`** — from a "show me this
> department" standpoint, both mean *nothing on record*, and offering two near-identical
> empty options would be noise. One helper, `_profile_value()` in
> `assignment_analytics.py` (reached via `profile_field()`), is the single definition of
> "nothing on record" that the table cells, the assignment drill-down modal, the dropdown
> option and the filter matcher all share — so a cell reading `NA` and a user landing in
> the `NA` filter bucket can never disagree.

### API Sync (`sync_users_from_api`)

Called automatically on every `GET /api/settings/users` request. It only ever *adds*:
1. Load current API data via `load_data()`
2. Extract unique `User_Mail_ID` + `Participant_Name` pairs
3. Compare against the registry **case-insensitively** (so `A@x.com` and `a@x.com` never become two rows)
4. Append only **new** users with `source: "api"`, `tracked: false`, and an empty profile
5. **Existing users are never touched** — a roster-supplied profile survives every sync

### Roster Upload (`POST /api/settings/users/bulk-upload`)

The upload *augments*, it does not replace. Column order is free; only `Email` is required.

```
| Email | Name | Department | Location | Role |
```

Accepted headings (case-insensitive) include `Email`/`E-Mail`/`Email Address`,
`Department`/`Dept`, `Location`/`Site`/`City`, `Role`/`Designation`/`Job Title`.
A sheet with **no** recognisable header row falls back to the legacy positional
layout: `A=Email, B=Name, C=Department, D=Location, E=Role`.

Per email in the sheet:
- **Already in the registry** (including an API-synced user) → augmented in place with
  the supplied fields, promoted to `tracked = 1`, `source = 'upload'`. A **blank cell
  never wipes** a value already stored (`COALESCE(NULLIF(?, ''), col)`).
- **Unknown** → inserted as a new tracked user.
- **Absent from the sheet** → left exactly as it was. An API-only user stays untracked
  with no profile. *This is what makes untracked users a real category rather than an
  accident.*

Duplicate rows within one sheet: last row wins.

### Duplicate Validation

Server and client check for duplicate emails (case-insensitive) — but an **untracked**
match is **not** a duplicate. It is the same person, synced in from the API and waiting
for a profile, so adding them **promotes** the existing row onto the roster
(`{"promoted": true}`) instead of returning 409. A *tracked* match still returns
**HTTP 409**.

### User Addition Methods

| Method | Route | Notes |
|--------|-------|-------|
| Manual entry | `POST /api/settings/users` | Email + optional name/department/location/role → tracked |
| Excel roster upload | `POST /api/settings/users/bulk-upload` | Augments existing users, inserts new ones → tracked |
| Bulk assignment upload | `POST /api/settings/assignments/bulk-upload` | Auto-creates any unknown assignee → tracked, empty profile |
| API auto-sync | (via `sync_users_from_api`) | Runs on settings page load → **untracked** |

### Real-Time Search & Filter (Settings Page)

- Client-side JS filters the rendered user list on every keystroke
- Substring match across email, name, **department, location and role** (case-insensitive)
- A **Tracked / Untracked / All** dropdown narrows the list further; both constraints apply together
- Each row shows a `Tracked` or `Untracked` badge plus chips for whatever profile values exist
- Header line reports `N tracked (M with profile), K untracked`

---

## 7. Business Logic — Course Assignments

Assignment records live in `data/course_assignments.json`:

```json
{
  "assignments": [
    {
      "id": 1,
      "course_name": "Understanding Hazards and Risks",
      "user_emails": ["a@example.com", "b@example.com"],
      "deadline": "2025-12-31",
      "created_date": "2025-12-05 14:30:00",
      "created_by": "admin"
    }
  ]
}
```

### Creating an Assignment (`POST /api/settings/assignments`)

```
Request body: { course_name, user_emails[], deadline?, effective_from?, effective_to?, notify_email }

1. Validate required fields (course_name + user_emails; deadline is OPTIONAL)
2. deadline omitted/blank → default to creation date + DEFAULT_DEADLINE_DAYS (15 days)
3. Append assignment record (id = max(existing ids) + 1)
4. Baseline it for completion notifications (see §8) — users already complete
   right now are recorded, NOT emailed
5. If notify_email=true:
     Build email_to_name map from the users table
     _dispatch_assignment_emails() → background ThreadPoolExecutor job
     Returns job_id for polling
6. Return 201 with assignment + email_job_id + deadline_defaulted flag
```

### Default Deadline (15 days)

`DEFAULT_DEADLINE_DAYS = 15` in `app.py`. If the admin leaves the deadline field
blank — on the manual form **or** the bulk-upload form — the server sets it to
**15 days from the assignment's creation date** (`YYYY-MM-DD`, the same shape used
everywhere else). The response carries `deadline_defaulted: true` and the UI reports
the date it landed on. The form shows the resolved date as a hint before submission.

### Assignment Detail View (`GET /api/settings/assignments/<id>`)

Returns **two views** of progress:

| View | Scope |
|------|-------|
| **Course View** | All users in API data for this course |
| **Assignment View** | Only the explicitly assigned users |

For each user: completion %, status (`Completed` / `Current` / `Not Started`), completion date.
Users not found in API data are shown as `{ untouched: true, completion_status: "Not Started" }`.

**Stats calculated:** completed, in_progress, not_started counts + completion_rate for both views.

### Updating an Assignment (`PUT /api/settings/assignments/<id>`)

1. Diff old vs new `user_emails`
2. `added_users` = new − old → send assignment emails (background)
3. `removed_users` = old − new → send removal emails (background)
4. Save immediately; emails fire in background threads
5. Reconcile the completion-notification ledger (`sync_assignment_notifications`):
   - an **added** user who has *already* completed the course inside the window is
     recorded as `pre_existing` — they finished before they were assigned it, so there
     is no completion *event* to congratulate (same rule as the creation baseline)
   - a **removed** user's ledger row is dropped, so if they are re-added later and then
     complete, that genuinely new completion is still announced

### Sending Reminders (`POST /api/settings/assignments/<id>/remind`)

1. Load assignment + API data
2. Calculate `days_remaining` from deadline
3. Determine completed users from API
4. Send `send_deadline_reminder_email()` **only** to incomplete users (synchronous, not threaded)
5. Returns counts: `reminders_sent`, `reminders_failed`, `already_completed`

### Follow-up Assignment — the Re-assign button (`GET /api/settings/assignments/<id>/reassign-preview`)

Every card in **Settings → Active Assignments** carries a fourth icon beside *Send Reminders*,
*Edit* and *Delete*. It answers the question you ask the moment an assignment ends: *these
people didn't finish — assign it to them again.*

Clicking it jumps to the **Course Assignments** tab with the Create Assignment form **seeded**:
the same course preselected, and preselected users = everyone from the original assignment who
did **not** complete it. A banner says where the selection came from. The seed is only a seed —
the course can be swapped, users added or removed, and the dates are chosen fresh. The
assignment is then created through the ordinary `POST /api/settings/assignments`, so a follow-up
is an ordinary assignment in every respect (its own validity window, deadline, baseline and
notifications). **Nothing is created by the preview endpoint itself.**

| Concern | Behaviour |
|---------|-----------|
| **When it unlocks (admin)** | Only once the assignment has **ended** — "who didn't finish" is not a question you can answer while it is still running. |
| **When it unlocks (superadmin)** | **Always**, irrespective of the dates. Superadmins run the remediation cycles and must not be blocked by a window they set themselves. |
| **What "ended" means** | Its **`effective_to`** when one was given (completions after it don't count anyway) — **otherwise the end of the `deadline` day**. `effective_to` is optional; the deadline never is (it defaults to 15 days), so every assignment has an end. An assignment due *today* is still running today. |
| **Who is carried over** | Every status **other than `completed`**: in-progress, never-started, and **stale** users (whose only completion falls outside the window, so they must redo the course). Users who completed it are left out. |
| **Where that comes from** | The same `compute_assignment_progress()` that produces the card's ✓/⟳/✗ counts and the details modal — so the carried-over set can never disagree with the numbers the admin is looking at. |
| **Deleted users** | A carried-over user since removed from the registry is **skipped** (with a toast), not silently selected-but-invisible. |
| **Where the rule lives** | **Server-side, once.** `GET /api/settings/assignments` returns a derived `expired` + `can_reassign` per record (computed per request against the caller's role, never stored); the UI only renders what the server decided, and the preview endpoint **403s** an admin whose assignment is still running. Disabling the button in the DOM is an affordance, not the guard. |

### Bulk Assignment Upload (`POST /api/settings/assignments/bulk-upload`)

1. Parse Excel file (Column A = emails)
2. Validate email format via regex
3. Auto-create any new users in `users.json`
4. Create assignment record
5. Optionally dispatch assignment emails in background

### Background Email Job Tracking

Parallel email dispatch uses `ThreadPoolExecutor` with 8 workers:

```python
_email_jobs: dict  # { job_id: { total, sent, failed, status } }
_EMAIL_WORKERS = 8
_JOB_TTL = 600     # seconds until job entry is cleaned up
```

Poll job progress with `GET /api/email-job/<job_id>`. Returns:
```json
{ "total": 50, "sent": 32, "failed": 2, "status": "running | completed" }
```

---

### FY / Quarter / Dimension Analytics (`/assignments-dashboard`)

Powered by `assignment_analytics.build_summary()`. All figures measure progress against
**everyone assigned**, applying the validity-window staleness rule (§7).

**Scope selection — top view:**

| Scope | `periods` strip shows | `quarter` param |
|-------|----------------------|-----------------|
| One financial year | **Q1 Apr–Jun · Q2 Jul–Sep · Q3 Oct–Dec · Q4 Jan–Mar** + a *Full Year* card | `1`–`4` narrows every figure to that quarter |
| All financial years | One card per FY | ignored |

Each period card shows its completion %, assignment count and `done/enrolled`. The cards sit
in a **single row** (they share the width evenly and shrink together; a narrow screen scrolls
the row sideways rather than wrapping, so the quarters stay side-by-side and comparable at a
glance). Clicking a quarter narrows the whole page to it; clicking it again returns to the
full year. The strip is rendered **outside** the dashboard container, so an empty quarter
still leaves you something to click back out of. The *Full Year* card is computed from the
period rows, not from the KPIs — the KPIs describe the *selected* quarter.

**Dimension breakdown** — a tabbed card (**By Department / By Location / By Role**) with a
stacked status bar chart and a sortable, CSV-exportable table. One enrollment (a user in an
assignment) contributes to one bucket in each dimension:

- a value from the roster (`Safety`, `Mumbai`, `Engineer`, …)
- `Unspecified` — tracked, but the roster left that cell blank
- `Untracked` — never uploaded at all (only present while untracked users are included)

### Population controls (top of the page)

Four controls sit together on the period strip, above the quarters, because they all answer
the same question — *which users are we counting?* All four narrow the **whole page**.

**Include-untracked switch** (`?include_untracked=`). When off, every enrollment belonging
to an untracked user is dropped **up front**, before any aggregation.

**Department / Location / Role dropdowns** (`?department=` `?location=` `?job_role=`).
Each defaults to **All**. A selection narrows the population to the users matching **every**
named dimension (they AND together), applied at exactly the same point and by exactly the
same mechanism as the untracked switch — so the KPIs, all three charts, the dimension
breakdown and all three tabbed tables are computed from one population and **cannot
disagree**. An active dropdown is tinted, a one-line note explains why the figures shrank,
and a *Clear filters* button appears.

| Concern | Behaviour |
|---------|-----------|
| **Where the options come from** | The **roster** — whatever *Add user* and the bulk upload have put there — not from whichever users happen to fall in the current FY scope. The lists therefore stay put as you move between years and quarters instead of shifting under you. |
| **`NA` option** | Offered only when somebody actually being counted has nothing on record: an untracked user (no profile at all), or a tracked user whose roster cell was left blank. |
| **Empty assignments** | An assignment nobody in the filtered population is enrolled in is **dropped**, not listed as a `0 enrolled` row — otherwise *Total Assignments* would answer a question nobody asked. |
| **Self-healing selection** | A selection whose option no longer exists is **silently dropped** rather than honoured. (Pick `NA`, then untick *Include untracked users*, and `NA` may cease to exist — without this the page would filter down to nothing the user could not then undo.) The server echoes back the selection it *actually applied* in `filters`, and the dropdowns mirror that rather than tracking it independently. |
| **Untrusted input** | A value that is not among the server-built options is ignored, so a hand-crafted query string cannot inject a filter. |

> **Before any roster is uploaded, every user is untracked.** Two consequences, both
> expected rather than bugs:
> - Unticking *Include untracked users* zeroes the page. The dashboard detects this
>   (`tracked_users == 0`) and shows an explanatory banner rather than a wall of zeros.
> - Every dropdown degenerates to **All + NA** only, and every row in the Users table reads
>   `NA` — there are simply no departments, locations or roles on record yet. The lists
>   populate themselves as soon as a roster is uploaded; no code change is needed.

**Engine internals** (`assignment_analytics.py`): `filter_options()` builds the dropdown
lists, `normalize_filters()` validates a request against them (this is what makes a stale
selection self-heal), `matches_filters()` decides one user, and `apply_filters()` rebuilds an
assignment's counts from the surviving enrollees via the same `_recount()` that
`drop_untracked()` uses. The `NA` bucket travels on the wire as the sentinel
`__na__` (`NA_FILTER_VALUE`), **not** the literal string `NA`, so a department genuinely
*named* "NA" can never collide with the empty bucket.

---

## 8. Email Notification System

**Module:** `email_service.py`  
**SMTP:** `smtp.office365.com:587` (STARTTLS)  
**Sender:** `SMTP_USERNAME` from `.env` (currently `noc.mis@nelco.in`)  
**Credentials:** `SMTP_USERNAME` / `SMTP_PASSWORD` loaded from `.env` via `python-dotenv` — not in source.

### Email Types

| Function | Trigger | Subject |
|----------|---------|---------|
| `send_course_assignment_email` | New assignment or user added to assignment | `📚 New Course Assignment: {course}` |
| `send_deadline_reminder_email` | Admin clicks "Send Reminders" | `⏰ REMINDER: Course Deadline - {course}` |
| `send_course_removal_email` | User removed from assignment | `Course Assignment Removed: {course}` |
| `send_course_completion_email` | **Automatic** — an API sync detects a new completion | `✅ Course Completed: {course}` |
| `send_bulk_emails` | Generic bulk send utility | Custom |

### Automatic Completion Notifications

**Every cache refresh** asks: *has anyone completed a course an assignment requires of
them, and have we told them yet?* If not, they get a congratulations email — once, ever.

```
refresh_cache_background()
  ├── fetch_fresh_data_from_api()
  ├── record_completion_history()            # append-only completion ledger
  └── dispatch_completion_notifications()    # ← this
        ├── For each assignment:
        │     compute_assignment_progress()  # same staleness/validity-window engine
        │     └── users with status == 'completed'  (i.e. finished INSIDE the window)
        ├── Assignment has no baseline yet? → set_notification_baseline()
        │     records everyone currently complete as 'pre_existing' and emails NOBODY
        ├── db.claim_completion_notifications(candidates)
        │     INSERT OR IGNORE on PK (assignment_id, email) → returns only rows
        │     THIS call inserted, so a concurrent sync claims nothing
        ├── Send claimed emails in parallel (ThreadPoolExecutor, 8 workers)
        └── db.settle_notification(...) per email:
              sent  → status 'sent'   (never sent again)
              failed→ claim DELETED   (retried on the next sync)
```

**Why the baseline exists.** Without it, the first sync after this feature shipped would
blast a congratulations email at every user who had *already* completed a course months
ago — and creating an assignment with a backdated `effective_from` (which deliberately
credits older completions) would do the same. An assignment is baselined the moment it
starts being watched: at creation, or on the first sync for assignments that predate the
feature. Everyone already complete at that instant is recorded as `pre_existing` and
permanently suppressed. **Only a completion that appears *after* the baseline is an event
worth announcing.**

**Exactly-once guarantee.** The `completion_notifications` table's primary key
`(assignment_id, email)` *is* the lock. The dispatcher claims before it sends, so:
re-observing the same completion on every 30-minute sync sends nothing; two concurrent
refreshes cannot both claim the same pair; and a send that fails releases its claim so
the next sync retries it. A `_notify_lock` additionally makes an overlapping pass a no-op.

Deleting an assignment drops its notification rows **and** its baseline.

Set `NOTIFY_ON_COMPLETION=false` in `.env` to switch the whole mechanism off.

### Assignment Email Template

- Blue-purple gradient header (`#667eea → #764ba2`)
- `text-shadow` on header h1 for Outlook visibility
- Course name + deadline details table
- "Access Course Portal" CTA button
- Plain text fallback included

### Reminder Email Template

- Urgency-adaptive: red (`#ef4444`) if ≤ 3 days, amber (`#f59e0b`) if > 3 days
- Displays days remaining prominently
- `URGENT` or `Important` badge in header

### Removal Email Template

- Grey gradient header (`#6b7280 → #4b5563`)
- States course name removed from assignment

### Error Handling

`send_email()` catches and logs (never raises):
- `SMTPAuthenticationError` → log + return `False`
- `SMTPException` → log + return `False`
- Generic `Exception` → log + return `False`

Email failures never block assignment creation/update — they are logged and counted.

---

## 9. API Reference

### Public

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/login` | Login page |
| POST | `/login` | Authenticate, set session |
| GET | `/logout` | Clear session, redirect to login |
| GET | `/favicon.ico` | Returns **204 No Content**. The app ships no icon; this exists only so the browser's automatic request stops 404-ing in the log |

### Authenticated (any logged-in user)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Main dashboard |
| GET | `/api/status` | Cache state + system config |
| POST | `/api/refresh-cache` | Trigger manual background refresh |
| GET | `/api/data` | Raw API records |
| GET | `/api/raw-data` | Raw records wrapped in `{ data: [] }` |
| GET | `/api/summary` | Aggregated KPIs, course list, user list |
| GET | `/api/course/<name>` | Per-user progress for one course |
| GET | `/api/user/<email>` | Per-course progress for one user |

### Admin Only

🔒 = requires a valid `X-CSRF-Token` header (auto-attached by the frontend `fetch` wrapper).

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/settings` | Admin settings page |
| GET | `/api/settings/users` | List users (triggers API sync) |
| POST 🔒 | `/api/settings/users` | Add user (duplicate-checked) |
| DELETE 🔒 | `/api/settings/users/<email>` | Delete user |
| POST 🔒 | `/api/settings/users/bulk-upload` | Bulk user import from Excel |
| GET | `/api/settings/courses` | Available courses from API data |
| GET | `/api/settings/assignments` | All assignments — each with a derived `expired` + `can_reassign` ([§7](#follow-up-assignment--the-re-assign-button-get-apisettingsassignmentsidreassign-preview)) |
| POST 🔒 | `/api/settings/assignments` | Create assignment |
| GET | `/api/settings/assignments/<id>` | Assignment detail + progress |
| PUT 🔒 | `/api/settings/assignments/<id>` | Update assignment user list |
| DELETE 🔒 | `/api/settings/assignments/<id>` | Delete assignment |
| GET | `/api/settings/assignments/<id>/reassign-preview` | Course + the users who did **not** complete it — seeds a follow-up assignment. **403** for an admin whose assignment is still running; a superadmin is never blocked. Creates nothing |
| POST 🔒 | `/api/settings/assignments/<id>/remind` | Send deadline reminders |
| POST 🔒 | `/api/settings/assignments/bulk-upload` | Bulk assignment from Excel |
| GET | `/api/email-job/<job_id>` | Poll background email job progress |

### FY / Assignment Analytics (any logged-in user)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/assignments-dashboard` | FY / quarter / dimension analytics page |
| GET | `/api/assignments-summary` | Full dashboard payload — see params below |
| GET | `/api/assignment-progress/<id>` | Per-user progress for one assignment (drill-down). Each row carries its roster `department`, `location`, `job_role` and `tracked` flag — empty means nothing on record, which the modal renders as **NA** |
| GET | `/api/fy-user/<email>` | One user's assignment-by-assignment breakdown |

**Query parameters:**

| Param | Values | Applies to | Meaning |
|-------|--------|-----------|---------|
| `fy` | `current` \| `all` \| `<start_year>` | summary, fy-user | Financial-year scope |
| `quarter` | `1`–`4` \| `all` | summary, fy-user | Narrow an FY scope to one quarter (ignored when `fy=all`) |
| `include_untracked` | `true` (default) \| `false` | summary, assignment-progress | Count users who are in the API but not on the uploaded roster |
| `department` | `all` (default) \| `<value>` \| `__na__` | summary | Narrow to one roster department; `__na__` = nothing on record ([§7](#population-controls-top-of-the-page)) |
| `location` | `all` (default) \| `<value>` \| `__na__` | summary | Narrow to one roster location |
| `job_role` | `all` (default) \| `<value>` \| `__na__` | summary | Narrow to one roster role |

An unrecognised value for the three roster filters is **ignored, not honoured** — the server
validates each against the options it just built. `/api/assignments-summary` echoes back what
it actually applied:

```json
{
  "filters":         { "department": "Safety", "location": "all", "job_role": "all" },
  "filter_options":  { "department": [ { "value": "Safety", "label": "Safety" },
                                       { "value": "__na__", "label": "NA" } ], ... },
  "filters_active":  true
}
```

> `POST /api/refresh-cache` (authenticated, [§9](#authenticated-any-logged-in-user)) is also CSRF-protected.

---

## 10. UI/UX Design

### Visual Style

- **Background:** animated multi-colour gradient (15s loop): purple → violet → pink → blue → cyan
- **Cards:** 3D glass-morphism with frosted glass effect and depth shadow
- **Icons:** gradient-coloured SVGs for KPI tiles
- **Transitions:** hover lift on cards, smooth chart animations

### Colour Palette

| Use | Value |
|-----|-------|
| Primary gradient | `#667eea → #764ba2` |
| Accent gradient | `#f093fb → #4facfe → #00f2fe` |
| Completed (green) | `#10b981` |
| In Progress (amber) | `#f59e0b` |
| Not Started (slate) | `#64748b` |
| Cache tile button | `#6366f1 → #9333ea` |

### Seamless Data Refresh (no page reload)

After manual refresh completes:
1. `loadDashboardData()` re-fetches `/api/summary` and updates all KPI DOM elements, tables, and re-renders all ECharts instances in place
2. `loadCacheStatus()` updates the 5th tile
3. `showNotification("Data updated successfully!")` — green toast, top-right, auto-dismisses after 3 s with fade animation
4. Scroll position, open modals, and filter states are preserved

---

## 11. Deployment

The app needs **only Python 3.11** — no database server, no Node, no build step. SQLite is stdlib; all CSS/JS/fonts are committed and served locally.

### What to copy, and what to leave behind

#### ✅ Copy — the app will not run without these

| Path | Why |
|------|-----|
| `app.py`, `db.py`, `email_service.py`, `assignment_analytics.py` | The application |
| `requirements.txt` | Dependency list |
| `templates/` | **All** of it — Jinja templates |
| `static/` | **All** of it — see the CSS warning below |
| `scripts/` | Optional; one-off seeding utilities |
| `Response Sample.json` | **Only** if you might set `USE_LOCAL_DATA=true` |
| `.env.example` | Convenient starting point for the real `.env` |

> ⚠️ **Copy the whole `static/` folder.** Every template links **`css/tailwind.min.css`** *and* `css/modern.css`, plus a page-specific sheet (`login.css`, `settings.css`, `assignments.css`), the Oswald fonts, and `js/echarts.min.js`. `tailwind.min.css` is **not** legacy — dropping it renders the app completely unstyled. (`css/input.css` is the Tailwind *source*; harmless to include, unused at runtime.)

#### ❌ Do NOT copy

| Path | Why |
|------|-----|
| `.env` | Secrets. **Recreate on the server** — see Step 3 |
| `venv/` | Rebuild on the server; a venv is not portable across machines/OSes |
| `__pycache__/` | Stale bytecode |
| `package.json`, `package-lock.json`, `tailwind.config.js`, `node_modules/` | Tailwind **build** tooling. Only needed to *regenerate* `tailwind.min.css`. Never needed at runtime |
| `logs/` | **Auto-created** — see below |
| `data/` | **Auto-created** — see the data section below. Copy contents only deliberately |
| `data/app.db-wal`, `data/app.db-shm` | Transient SQLite sidecars. **Copying these corrupts the database** |
| `data/*.backup*.json` | Old migration backups |
| `.kiro/`, `.vscode/` | Editor/dev config |
| `deploy_setup.ps1`, `deploy_simple.bat` | Windows-only launchers with hardcoded paths; useless on Linux |

#### Folders you never create by hand

Both are created at import time, so a completely empty deployment directory is fine:

* **`logs/`** — `app.py` calls `os.makedirs('logs', exist_ok=True)`, then a `RotatingFileHandler` writes `logs/app.log` (1 MB × 5 files).
* **`data/`** — `app.py` calls `os.makedirs('data', exist_ok=True)`, and `db._connect()` does the same for the DB's parent directory.

### Data: choose one of three, deliberately

`data/app.db` (SQLite) is the **single source of truth**. The JSON files are only a one-time bootstrap seed.

| Goal | Put in `data/` | Result |
|------|----------------|--------|
| **Truly fresh start** | **Nothing.** Leave `data/` empty or absent | New empty `app.db`. First boot has no cache, so it fetches from the API (**can take 3+ minutes**); users then populate as *untracked* on the first Settings → Sync. **Assignments start empty.** |
| **Carry everything over** | **`app.db` only** | Users, assignments, cache, and completion history preserved as-is |
| **Seed from JSON** | `users.json`, `course_assignments.json`, `api_cache.json` — and **no `app.db`** | First boot imports them into a new `app.db`, then ignores the JSONs forever |

> ⚠️ **`db.init_db()` only bootstraps when `app.db` does not exist** (`is_new = not os.path.exists(DB_PATH)`). If the file is present — *even if it is corrupt* — it is reused and the JSONs are ignored entirely. To force a rebuild you must **delete `app.db` from disk**; restarting the service is not enough.

> ⚠️ **Gotcha: `data/*.json` are tracked in git.** They were committed before `.gitignore` listed them, and `.gitignore` does not untrack existing files. So `git clone` on a new server **brings stale `users.json` / `course_assignments.json` / `api_cache.json` with it** and you silently get the "Seed from JSON" behaviour. If you want a truly fresh start, `rm data/*.json` after cloning.

#### Carrying `app.db` to a new server — safely

**Never `cp`/`scp` a live `app.db`.** SQLite runs in WAL mode (`PRAGMA journal_mode=WAL`), so a plain copy of a database being written to is a torn file, and copying the `-wal`/`-shm` sidecars alongside a mismatched `app.db` makes SQLite replay a foreign write-ahead log — both produce `database disk image is malformed`. Use SQLite's own consistent snapshot, which is safe on a running database:

```bash
sqlite3 data/app.db ".backup /tmp/app-snapshot.db"
scp /tmp/app-snapshot.db newserver:/path/to/Project/data/app.db   # no -wal, no -shm
```

#### Backups

Same rule. A cron entry is strongly recommended, since `app.db` is now the only copy of your assignments and completion history:

```bash
0 2 * * * sqlite3 /home/pankaj/Project_6/data/app.db ".backup /home/pankaj/db_backup/app-$(date +\%F).db"
```

### Step 1 — Install Python 3.11. (Nothing else.)

### Step 2 — Copy the app across, per the tables above.

### Step 3 — Create `.env` on the server (the main thing you change)
```bash
cp .env.example .env    # then fill in real values
```
Required (the app `KeyError`s and refuses to boot without them): `SECRET_KEY`, `SUPERADMIN_PASSWORD`, `ADMIN_PASSWORD`, `USER_PASSWORD`, `TCS_ION_API_URL`. Set `USE_LOCAL_DATA=false` and (behind TLS) `HTTPS_ONLY=true`. See [§12](#12-configuration-reference) for the full list.

### Step 4 — Install deps and run

No migration command exists or is needed — `app.py` calls `db.init_db()` at import, which creates `data/app.db` and its tables (or opens the one you copied).

**Linux (systemd + gunicorn) — the production setup:**
```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install gunicorn
venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5006 app:app
```

> ⚠️ **File ownership.** Run the first launch (and any `db.init_db()` by hand) as the **same user the service runs as** — the `User=` in the unit file. If `app.db` or `data/` ends up root-owned while gunicorn runs as an unprivileged user, every write fails with `attempt to write a readonly database`. SQLite needs write permission on the **directory** too, not just the file, because it creates the `-wal`/`-shm` sidecars there.

**Windows (Waitress, port 8888):**
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install waitress
python -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=8888, threads=4)"
```

### Step 5 — Optional hardening / seeding
- On Windows, run `deploy_setup.ps1` **as Administrator** to apply `icacls` ACLs on `data/` and `.env` (SEC-22).
- `scripts/seed_assignments_from_api.py` pre-populates assignments from the API on an empty setup (optional).

### Step 6 — Verify
1. Open `/login` and log in.
2. Confirm pages render **styled** — this proves `static/` (including `tailwind.min.css`) copied correctly.
3. Confirm `data/app.db` and `logs/app.log` exist, and that `app.db` is owned by the service user.
4. On a fresh DB, the first API fetch takes minutes. Until it lands, the dashboard is empty and Settings → Sync finds no users — **this is expected**. Reload the page once the fetch completes; nothing pushes to an already-open page.
5. Sanity-check the database:
   ```bash
   venv/bin/python -c "import sqlite3, db; print(sqlite3.connect(db.DB_PATH).execute('PRAGMA integrity_check').fetchone())"
   ```
   Anything other than `('ok',)` means a corrupt `app.db` — delete `app.db`, `app.db-wal`, `app.db-shm` and let it rebuild.

### Quick Start (Development)

```bash
pip install -r requirements.txt      # includes python-dotenv
cp .env.example .env                 # then fill in real values (incl. SUPERADMIN_PASSWORD)
python app.py
# → http://localhost:5000
```

The app **will not start** if required env vars are missing — `SECRET_KEY`, `SUPERADMIN_PASSWORD`, `ADMIN_PASSWORD`, `USER_PASSWORD`, and `TCS_ION_API_URL` are read with `os.environ[...]` and raise `KeyError` if absent. `python app.py` binds port **5000** (dev); the Waitress production launchers use **8888**.

### Styling (no build step)

There is **no CSS build step** and **no Node dependency in deployment**. The stylesheets are committed and served from `static/css/`: `tailwind.min.css` (utility classes — **required**, every template links it), `modern.css` (the hand-written design system), and the per-page `login.css` / `settings.css` / `assignments.css`.

The Node tooling (`package.json`, `package-lock.json`, `tailwind.config.js`, `static/css/input.css`, `node_modules/`) exists **only to regenerate `tailwind.min.css`** during development. Never copy it to a server — but do not confuse it with the generated `tailwind.min.css`, which is required at runtime.

### Windows (Production)

**Option A — Batch file:**
```
Double-click deploy_simple.bat
```

**Option B — PowerShell:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\deploy_setup.ps1
```

> **Both `deploy_simple.bat` and `deploy_setup.ps1` have hardcoded paths** (`PYTHON_PATH`, project dir `C:\Users\8527\PYTHON\ttu_dash`). **Edit those to match the new server** before running. Both launch Waitress on **port 8888** with `threads=4`, binding `0.0.0.0`.

**Manual steps:**
```batch
set PYTHON_PATH=C:\path\to\python_3_11\python.exe
"%PYTHON_PATH%" -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
pip install waitress
"%PYTHON_PATH%" -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=8888, threads=4)"
```

### Production Checklist

Already handled by the 2026-05-22 hardening:
- [x] `SECRET_KEY` randomised and loaded from `.env`
- [x] Login passwords moved to `.env` (`ADMIN_PASSWORD` / `USER_PASSWORD`)
- [x] SMTP credentials moved to `.env`
- [x] API URL/tokens moved to `.env`
- [x] Session cookie flags, 8 h lifetime + 30 min idle timeout
- [x] CSRF protection, security headers, login rate limiting
- [x] Tailwind served from local compiled file (no CDN)

Still required for production:
- [ ] Set a **strong** `ADMIN_PASSWORD` / `USER_PASSWORD` in `.env` (defaults are demo values)
- [ ] Set `USE_LOCAL_DATA=false` in `.env`
- [ ] Configure HTTPS / reverse proxy, then set `HTTPS_ONLY=true` in `.env` (enables `Secure` cookie + lets you add HSTS)
- [ ] Rotate the SMTP and TCS iON credentials (they were previously committed in source history)
- [ ] Set up periodic backup of `data/` folder; verify it is writable
- [ ] Restrict `data/` directory ACLs (SEC-22)
- [ ] Address remaining backlog items: SEC-13, SEC-15, SEC-22, SEC-23, SEC-24 ([§14](#14-security-hardening--status--backlog))

---

## 12. Configuration Reference

### Environment variables (`.env`)

Loaded by `python-dotenv` at startup in both `app.py` and `email_service.py`. A sanitised template lives in `.env.example`.

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | **yes** | Flask session signing key. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SUPERADMIN_PASSWORD` | **yes** | Plaintext superadmin password (hashed in memory at startup) |
| `ADMIN_PASSWORD` | **yes** | Plaintext admin password (hashed in memory at startup) |
| `USER_PASSWORD` | **yes** | Plaintext standard-user password (hashed at startup) |
| `TCS_ION_API_URL` | **yes** | Full TCS iON API URL incl. auth params |
| `USE_LOCAL_DATA` | no (`false`) | `true` = read `Response Sample.json` instead of API |
| `SMTP_USERNAME` | no | Office 365 sender account |
| `SMTP_PASSWORD` | no | Office 365 app password |
| `HTTPS_ONLY` | no (`false`) | `true` sets `SESSION_COOKIE_SECURE=True` (HTTPS deployments) |
| `APP_DB_PATH` | no (`data/app.db`) | Override the SQLite DB file location (read by `db.py`) |
| `NOTIFY_ON_COMPLETION` | no (`true`) | `false` disables the automatic completion congratulations email ([§8](#8-email-notification-system)) |

Missing any **required** variable raises `KeyError` and the app refuses to start (fail-fast). The three role passwords map to accounts `superadmin` / `admin` / `user`.

### Constants in `app.py`

| Variable | Default | Description |
|----------|---------|-------------|
| `API_TIMEOUT` | `360` | Seconds before API request times out |
| `AUTO_REFRESH_INTERVAL_MINUTES` | `5` | Background cache refresh cadence |
| `DEFAULT_DEADLINE_DAYS` | `15` | Deadline applied when an assignment is created without one ([§7](#default-deadline-15-days)) |
| `CACHE_FILE` | `'data/api_cache.json'` | Persistent cache path |
| `_LOGIN_MAX` / `_LOGIN_WINDOW` | `10` / `60` | Per-IP login rate limit: attempts per seconds |
| `_LOCKOUT_THRESHOLD` / `_LOCKOUT_SECONDS` | `5` / `900` | Per-username soft lockout: failures before a 15 min cooldown |
| `PERMANENT_SESSION_LIFETIME` | `8 h` | Absolute session expiry |
| Idle timeout | `30 min` | Inactivity window before session is cleared |
| `MAX_CONTENT_LENGTH` | `5 MB` | Upload size cap |

### Constants in `email_service.py`

| Variable | Value | Description |
|----------|-------|-------------|
| `SMTP_SERVER` | `smtp.office365.com` | SMTP host |
| `SMTP_PORT` | `587` | SMTP port (STARTTLS) |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | from `.env` | Sender credentials (env, not source) |

---

## 13. Troubleshooting & Monitoring

### Key Log Messages

| Message | Meaning |
|---------|---------|
| `Cache system initialized successfully` | Normal startup |
| `Cache is X minutes old, still valid` | Fresh cache loaded from file |
| `Background cache refresh completed` | Scheduled or manual refresh done |
| `Cache refresh already in progress, skipping` | Normal guard, not an error |
| `No cache available, fetching synchronously` | Cold start with no cache file (blocks) |
| `Error in background cache refresh: ...` | API unreachable; old cache remains |
| `Error loading cache from file: ...` | Corrupt or missing cache file |
| `Email sent successfully to ...` | Email delivered |
| `SMTP authentication failed` | Check SMTP credentials |
| `Failed login attempt for user '<x>' from <ip>` | Audit: incorrect credentials submitted (SEC-18) |
| `Rate limit exceeded for login from <ip>` | >10 login attempts in 60 s from one IP (SEC-08) |
| `Login blocked: account '<x>' temporarily locked (from <ip>)` | 5 consecutive failures → 15 min lockout (SEC-08) |

### How to Check the Login Audit Trail (SEC-18)

All authentication events are logged to **both the console and a persistent file** at `logs/app.log` (rotating: 1 MB per file, 5 backups, gitignored). Each line is timestamped:

```
2026-05-22 15:44:44,598 WARNING app: Failed login attempt for user 'attacker' from 127.0.0.1
2026-05-22 15:44:44,613 WARNING app: Login blocked: account 'attacker' temporarily locked (from 127.0.0.1)
```

**Ways to inspect it:**

| Goal | Command (PowerShell) |
|------|----------------------|
| See the whole log | `Get-Content logs\app.log` |
| Live-tail as events happen | `Get-Content logs\app.log -Wait -Tail 20` |
| Only failed logins | `Select-String -Path logs\app.log -Pattern 'Failed login'` |
| Lockouts / rate-limit trips | `Select-String -Path logs\app.log -Pattern 'locked|Rate limit'` |
| Count failures per IP | `Select-String logs\app.log -Pattern "from (\S+)" \| % { $_.Matches.Groups[1].Value } \| Group-Object \| Sort-Object Count -Descending` |

**To verify it yourself quickly:** open the login page, enter a wrong password 5–6 times, then check `logs/app.log` — you'll see the failed-attempt lines followed by a "temporarily locked" line, and the 6th attempt returns HTTP 429 even with the correct password until the 15-minute cooldown elapses (or the app restarts, since the counters are in-memory).

> If you ran the app before this change, `logs/` is created on the next startup. In a multi-process/Waitress setup every worker writes to the same file via the rotating handler.

### `/api/status` Response

```json
{
  "using_local_data": false,
  "data_source": "TCS iON API",
  "api_timeout_seconds": 360,
  "auto_refresh_interval_minutes": 5,
  "cache": {
    "cached": true,
    "cache_timestamp": "2026-02-15 14:30:00",
    "cache_age_seconds": 180,
    "cache_age_readable": "3 minutes",
    "cached_at_formatted": "15 February 2026 at 02:30 PM",
    "refresh_in_progress": false
  }
}
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Dashboard slow on first load | No cache file exists | Wait for initial fetch; subsequent loads instant |
| "Updating Data..." stuck > 5 min | API slow or unreachable | Check network; logs will show error |
| Cache not refreshing | `USE_LOCAL_DATA=true` in `.env` | Set to `false` |
| Email not delivered | Wrong SMTP credentials | Check `SMTP_*` values in `.env` |
| Login fails | Wrong password in `.env` | Fix `ADMIN_PASSWORD` / `USER_PASSWORD`, restart |
| App won't start (`KeyError`) | Missing required env var | Ensure `.env` exists with all required keys ([§12](#12-configuration-reference)) |
| `403 CSRF validation failed` on actions | Stale page / missing token | Hard-refresh the page so a fresh `csrf_token` loads |
| `Refused to execute script … MIME type ('text/plain') is not executable` + `echarts is not defined` | **Windows registry has `HKCR\.js` set to `text/plain`** — see below | Already fixed in code; if it recurs, confirm the `mimetypes.add_type(...)` block still runs at import in `app.py` |
| UI unstyled / charts missing | **`static/` not copied in full** (most common on a new server — `tailwind.min.css` is required, not legacy), the MIME-type cause above (CSS refused under `style-src 'self'`), or a stale cache | Confirm every file under `static/css/` and `static/fonts/` is on the server; check the browser Network tab for 404s; hard-refresh (Ctrl+F5). *Not* a Tailwind build problem — there is no CSS build step ([§11](#styling-no-build-step)) |
| `database disk image is malformed` on boot or on Sync | Corrupt `data/app.db` — usually a `cp`/`scp` of a live DB, or stale `app.db-wal`/`app.db-shm` sidecars copied alongside a different `app.db` | Stop the service, **delete `app.db`, `app.db-wal`, `app.db-shm`** (restarting alone does nothing — `init_db()` reuses any existing file), let it rebuild. Always snapshot with `sqlite3 … ".backup"`, never `cp` ([§11](#11-deployment)) |
| Sync from API says it worked but no users appear | Almost always a failing DB write — often `app.db` owned by root while the service runs as an unprivileged user | Check `ls -l data/app.db` against the unit's `User=`; `chown` the whole `data/` directory. The UI now surfaces the real error in red |
| Port already in use | Another process on 5000 | Use `netstat -ano \| findstr :5000` to identify |
| Permission error on data/ | Missing write permission | Run as Administrator or fix folder ACL |

### Static-file MIME types on Windows (why `echarts.min.js` refused to load)

Flask sets a static file's `Content-Type` from Python's `mimetypes.guess_type()`, and on
Windows that module **seeds itself from the registry** (`HKCR\.js` → *Content Type*). Various
installers (Visual Studio, older Java/Adobe packages) clobber that key to `text/plain`. The
file then serves at HTTP 200 with the wrong type, Chrome's strict MIME checking refuses to
execute it, and the page dies with `echarts is not defined` — even though nothing is actually
missing.

`app.py` therefore **pins the types explicitly at import time**, before Flask can build any
response, so the host machine's registry never gets a vote:

```python
mimetypes.add_type('text/javascript', '.js')
mimetypes.add_type('text/css',        '.css')
mimetypes.add_type('image/svg+xml',   '.svg')
mimetypes.add_type('application/json', '.json')
```

`.css` matters as much as `.js`: the CSP is strict (`style-src 'self'`), so a mis-typed
stylesheet is refused exactly the same way and the UI renders unstyled. This travels with the
app rather than patching one machine's registry, so **every** Windows box it deploys to is
covered.

---

## 14. Security Hardening — Status & Backlog

Audit performed **2026-05-22**; remediation implemented the **same day** (two rounds). Of 24 items: **23 resolved**, **1 partial** (SEC-24 — version-pinned, hash-lock pending a networked CI run).

### Status Overview

| ID | Item | Status |
|----|------|--------|
| SEC-01 | Hardcoded Flask secret key | ✅ Resolved — `SECRET_KEY` from `.env` |
| SEC-02 | Hardcoded SMTP password | ✅ Resolved — `SMTP_PASSWORD` from `.env` |
| SEC-03 | Hardcoded API URL/tokens | ✅ Resolved — `TCS_ION_API_URL` from `.env` |
| SEC-04 | No HTTP security headers | ✅ Resolved — `@app.after_request` headers + CSP |
| SEC-05 | No session cookie flags | ✅ Resolved — HttpOnly/SameSite/Secure |
| SEC-06 | Sessions never expire | ✅ Resolved — 8 h lifetime + 30 min idle |
| SEC-07 | No CSRF protection | ✅ Resolved — token + `@csrf_required` on all mutations |
| SEC-08 | No login rate limiting | ✅ Resolved — per-IP (10/60 s) + per-user soft lockout (5 fails → 15 min) |
| SEC-09 | CDN-loaded Tailwind | ✅ Resolved — compiled local `tailwind.min.css` |
| SEC-10 | XSS via `innerHTML` | ✅ Resolved — `h()` escape + `data-*` listeners |
| SEC-11 | Stack traces in responses | ✅ Resolved — generic messages, log server-side |
| SEC-12 | No upload size limit | ✅ Resolved — `MAX_CONTENT_LENGTH = 5 MB` |
| SEC-13 | Upload MIME not verified | ✅ Resolved — magic-byte check (`_is_valid_excel`) |
| SEC-14 | Credentials in source | ✅ Resolved — passwords from `.env` |
| SEC-15 | No Content-Type enforcement | ✅ Resolved — `@json_required` (415) on JSON endpoints |
| SEC-16 | No input size cap on user list | ✅ Resolved — capped at 500 |
| SEC-17 | Admin role hardcoded to username | ✅ Resolved — `session['role'] == 'admin'` |
| SEC-18 | No failed-login audit logging | ✅ Resolved — IP + username logged to `logs/app.log` |
| SEC-19 | `searchTerm` unescaped | ✅ Resolved — wrapped in `h()` |
| SEC-20 | `Secure` flag in dev | ✅ Resolved — gated on `HTTPS_ONLY` env |
| SEC-21 | No `.env` / secrets management | ✅ Resolved — `python-dotenv` + `.env`/`.env.example` |
| SEC-22 | `data/` has no ACL restrictions | ✅ Resolved — `icacls` hardening in `deploy_setup.ps1` |
| SEC-23 | `Response Sample.json` may hold real PII | ✅ Resolved — anonymised (synthetic users + domain) |
| SEC-24 | No dependency hash pinning | ⚠️ Partial — versions pinned; hash-lock command documented (run in CI) |

> The detailed entries below are retained as the audit record. **For resolved items the “Fix” describes what was implemented**; the one partial item remains actionable as written.

---

### CRITICAL — ✅ all resolved (was: must fix before any production exposure)

#### SEC-01 · Hardcoded Flask secret key
- **File:** [app.py:25](app.py#L25)
- **Current:** `app.secret_key = 'your-secret-key-change-this-to-something-random-and-secure-12345'`
- **Risk:** Anyone who reads the source can forge signed session cookies, impersonate any user including admin.
- **Fix:** Load from environment variable: `app.secret_key = os.environ['SECRET_KEY']`. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. Store in a `.env` file (gitignored) loaded via `python-dotenv`.

#### SEC-02 · Hardcoded SMTP password in source code
- **File:** [email_service.py:20](email_service.py#L20)
- **Current:** `SMTP_PASSWORD = "rvhgdskxyqgzsqrr"` — plaintext credential committed to repo.
- **Risk:** Full takeover of the sender email account; credential visible to anyone with repo access.
- **Fix:** `SMTP_PASSWORD = os.environ['SMTP_PASSWORD']`. Add to `.env`. Rotate the credential immediately after moving it out.

#### SEC-03 · Hardcoded API URL with authentication tokens
- **File:** [app.py:27](app.py#L27)
- **Current:** Full API URL with `servicekey`, `s`, and `u` auth parameters hardcoded in source.
- **Risk:** API credentials embedded in code; exposed in logs, version history, and anyone reading the file.
- **Fix:** `API_URL = os.environ['TCS_ION_API_URL']`. Store in `.env`.

#### SEC-04 · No HTTP security headers
- **File:** [app.py](app.py) — no headers middleware present.
- **Risk:** Browsers have no protection against clickjacking, MIME sniffing, XSS, or data injection. CSP is especially critical because templates currently pull Tailwind from `cdn.tailwindcss.com`.
- **Fix:** Add `flask-talisman` (one-liner) or set headers manually in an `@app.after_request` hook. Required headers:
  ```
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  X-XSS-Protection: 1; mode=block
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: geolocation=(), microphone=(), camera=()
  Strict-Transport-Security: max-age=31536000; includeSubDomains  (HTTPS only)
  ```
  Note: CSP `script-src 'self'` requires fixing SEC-09 first (remove CDN Tailwind).

#### SEC-05 · No session cookie security flags
- **File:** [app.py](app.py) — no session config present.
- **Risk:** Session cookie can be stolen via XSS (`HttpOnly` missing), sent over plain HTTP (`Secure` missing), or used in cross-site requests (`SameSite` missing).
- **Fix:** Add to app config:
  ```python
  app.config['SESSION_COOKIE_HTTPONLY'] = True
  app.config['SESSION_COOKIE_SECURE'] = True      # HTTPS only
  app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
  ```

#### SEC-06 · Sessions never expire (no timeout)
- **File:** [app.py](app.py) — no `PERMANENT_SESSION_LIFETIME` set.
- **Risk:** An unattended browser tab or stolen cookie grants perpetual access with no expiry.
- **Fix:**
  ```python
  from datetime import timedelta
  app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

  # In login route, after setting session:
  session.permanent = True
  ```
  Also add a `@app.before_request` check that reads `session['_last_active']` and clears the session if idle > N minutes (e.g. 30 min inactivity timeout separate from the absolute 8 h limit).

---

### HIGH — mostly resolved (SEC-08 partial, SEC-13 outstanding)

#### SEC-07 · No CSRF protection on state-changing endpoints — ✅ RESOLVED
- **Files:** All `POST`, `PUT`, `DELETE` routes in [app.py](app.py).
- **Risk:** A malicious page can silently issue requests on behalf of a logged-in user (cross-site request forgery). This affects assignment creation/deletion, user management, and cache refresh.
- **Implemented:** Per-session token (`secrets.token_hex(32)`) exposed via a `csrf_token` context processor and a `<meta name="csrf-token">` tag. The frontend patches `window.fetch` to attach an `X-CSRF-Token` header on all mutating verbs; a `@csrf_required` decorator validates it on all 9 state-mutating endpoints (returns 403 on mismatch).

#### SEC-08 · No login rate limiting (brute force) — ✅ RESOLVED
- **File:** [app.py](app.py) — `login()` route + `_is_rate_limited()` / `_is_locked_out()`.
- **Risk:** Unlimited login attempts allow automated password guessing.
- **Implemented (two layers):**
  1. Per-IP limiter — max **10 attempts / 60 s** (`_LOGIN_MAX` / `_LOGIN_WINDOW`); HTTP 429 when exceeded.
  2. Per-username soft lockout — **5 consecutive failures** (`_LOCKOUT_THRESHOLD`) trigger a **15-minute cooldown** (`_LOCKOUT_SECONDS`); a successful login resets the counter. Lockout trips are logged.
- **Note:** Both counters are in-memory — they reset on restart and are not shared across multiple worker processes (fine for the single-process Waitress deployment; back with Redis if scaling out).

#### SEC-09 · CDN-loaded Tailwind CSS (supply-chain risk) — ✅ RESOLVED
- **Files:** [templates/login.html](templates/login.html), [templates/index.html](templates/index.html), [templates/settings.html](templates/settings.html)
- **Risk:** CDN compromise or MITM delivers malicious script to every user. Also violates a strict CSP.
- **Implemented:** The CDN `<script>` was removed and replaced with a **compiled** static stylesheet `<link rel="stylesheet" href="{{ url_for('static', filename='css/tailwind.min.css') }}">`. Note the old `tailwind.min.css` was actually the Tailwind *Play CDN JS bundle* (broke when loaded as CSS); it was rebuilt into real ~21 KB CSS via Tailwind CLI 3.4.17 (`npm run build:css`, config scans `templates/**`). See [§11](#11-deployment).

#### SEC-10 · XSS via `innerHTML` with unsanitised API data — ✅ RESOLVED
- **Implemented:** An `h()` escape helper is defined at the top of the script block in both `index.html` and `settings.html` and now wraps every dynamic value inserted into `innerHTML`. All `onclick="fn('${value}')"` patterns were converted to `data-*` attributes + delegated listeners. Original audit locations:
  - [templates/index.html:901](templates/index.html#L901) — `${course.course_name}` injected directly into `<td>`
  - [templates/index.html:918-920](templates/index.html#L918) — `${user.user_name}`, `${user.user_email}` in `<td>`
  - [templates/index.html:809](templates/index.html#L809) — `${error.message}` injected into `innerHTML`
  - [templates/settings.html:860](templates/settings.html#L860) — `${searchTerm}` injected into no-results message
  - [templates/settings.html:869-872](templates/settings.html#L869) — `${user.email}`, `${user.name}` in user list
  - [templates/settings.html:875](templates/settings.html#L875) — `${user.email}` in `onclick` attribute (JS injection)
  - [templates/settings.html:1005-1006](templates/settings.html#L1005) — course names injected into `<select>` options
  - All other `innerHTML = data.map(...)` call sites.
- **Risk:** If any API record or user-supplied value contains `<script>`, `<img onerror=...>`, or similar, it executes in the user's browser context. The `onclick="deleteUser('${user.email}')"` pattern is directly exploitable with an email like `'); alert(1);//`.
- **Fix:** Add a `sanitize(str)` helper that escapes `& < > " ' /` to HTML entities, and wrap every variable inserted into `innerHTML` with it:
  ```javascript
  function h(str) {
      return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                              .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
                              .replace(/'/g,'&#x27;');
  }
  // Usage: `<td>${h(course.course_name)}</td>`
  ```
  For `onclick` attributes with dynamic values, use `data-*` attributes and a delegated event listener instead.

#### SEC-11 · Stack traces returned to browser in error responses — ✅ RESOLVED
- **Files:** error handlers throughout [app.py](app.py).
- **Risk:** Full Python stack trace (file paths, line numbers, variable names) is sent to the client. This directly aids an attacker in understanding the application internals.
- **Implemented:** Every handler now logs the full trace server-side with `logger.error(...)` and returns only a generic message (e.g. `{"error": "Failed to load summary"}`) — no `traceback`/`str(e)` leaks to the client.

#### SEC-12 · No file upload size limit — ✅ RESOLVED
- **Risk:** An attacker can upload a gigabyte-size Excel file, exhausting server memory (DoS).
- **Implemented:** `app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024` — Flask auto-returns HTTP 413 for oversized uploads.

#### SEC-13 · File upload MIME type not verified (extension-only check) — ✅ RESOLVED
- **File:** [app.py](app.py) — `bulk_upload_users` / `bulk_upload_assignment`.
- **Implemented:** `_is_valid_excel(file_bytes)` checks the file's magic bytes after the extension check — `.xlsx` must start with the ZIP signature `PK\x03\x04`, `.xls` with the OLE2 signature `\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1`. Content failing both is rejected with HTTP 400 before openpyxl ever parses it. No external dependency (`python-magic`) required.
- **Original audit note:** previously only checked `file.filename.endswith(('.xlsx', '.xls'))`, which a renamed file (e.g. HTML with JS) trivially bypassed. The magic-byte approach was chosen over `python-magic` to avoid the `libmagic` native dependency on Windows.

---

### MEDIUM — resolved except SEC-15

#### SEC-14 · Application credentials stored in source code — ✅ RESOLVED
- **Risk:** Password hashes in source code. A future developer adding a weaker hash algorithm exposes all accounts.
- **Implemented:** The `USERS` dict is built at startup by hashing `ADMIN_PASSWORD` / `USER_PASSWORD` read from `.env` — no plaintext or hashes in source. A parallel `USER_ROLES` map drives admin checks (see SEC-17).

#### SEC-15 · No Content-Type enforcement on JSON endpoints — ✅ RESOLVED
- **File:** [app.py](app.py) — `add_user`, `create_assignment`, `update_assignment`.
- **Risk:** Flask's `request.get_json()` returns `None` silently if the `Content-Type` is wrong, leading to `AttributeError` or bypassed validation.
- **Implemented:** A reusable `@json_required` decorator returns **HTTP 415** unless `request.is_json`. Applied to the three JSON-body endpoints (after `@admin_required`/`@csrf_required`). The multipart bulk-upload endpoints are intentionally excluded (they use `multipart/form-data`). Verified the frontend already sends `Content-Type: application/json` on these calls, so the workflow is unaffected.

#### SEC-16 · No input size limits on assignment user list — ✅ RESOLVED
- **Risk:** A crafted request with tens of thousands of emails can cause a slow email job that exhausts threads and memory.
- **Implemented:** `user_emails` is capped with `[:500]` in both `create_assignment` and `update_assignment`.

#### SEC-17 · Admin role hardcoded to the literal username `'admin'` — ✅ RESOLVED
- **Risk:** Fragile; renaming the admin account breaks all admin protection silently.
- **Implemented:** Login sets `session['role']` from `USER_ROLES`; `@admin_required` now checks `session.get('role') == 'admin'` rather than the username literal.

#### SEC-18 · No failed-login audit logging — ✅ RESOLVED
- **Risk:** No record of repeated failed attempts; impossible to detect or respond to attacks.
- **Implemented:** Every failed attempt logs `Failed login attempt for user '<username>' from <ip>`; rate-limit and lockout trips are logged too. Logging now also writes to a **persistent rotating file** `logs/app.log` (1 MB × 5 backups) in addition to the console, so the audit trail survives restarts. See [§13](#how-to-check-the-login-audit-trail-sec-18) for how to read it.

#### SEC-19 · `searchTerm` inserted into `innerHTML` without escaping — ✅ RESOLVED
- **Risk:** A user typing `<img src=x onerror=alert(1)>` in the search box triggers XSS.
- **Implemented:** Both no-results messages (user list and assignment-user list) now wrap `searchTerm` in `h()`.

---

### LOW — Good practice / defence in depth

#### SEC-20 · `Secure` flag on session cookie during development — ✅ RESOLVED
- **Implemented:** `SESSION_COOKIE_SECURE` is gated on the `HTTPS_ONLY` env var (`false` in dev, set `true` behind HTTPS) rather than always-on, so dev cookies still work over plain HTTP.

#### SEC-21 · No `.env` / secrets management setup — ✅ RESOLVED
- **Implemented:** `python-dotenv` added to `requirements.txt`; `.env` (gitignored) holds real values, `.env.example` (committed) documents the required keys. Both `app.py` and `email_service.py` call `load_dotenv()`.

#### SEC-22 · `data/` directory and cache file have no access restrictions — ✅ RESOLVED
- **Implemented:** `deploy_setup.ps1` now runs `icacls` to disable inheritance and grant access only to `SYSTEM`, `BUILTIN\Administrators`, and the service account (`$env:USERNAME`) on both `data/` and `.env`. `data/` is not registered as a Flask static route. (Ops step — applied at deployment time.)

#### SEC-23 · `Response Sample.json` may contain real personal data — ✅ RESOLVED
- **Implemented:** The fixture was anonymised in place — all 34 unique users mapped to synthetic identities (`User N` / `userN@example.com` / `userN`) consistently across the 133 records, and the `Domain` field scrubbed from `nelco` to `example`. Course names, statuses, percentages and dates are retained so the local-data demo stays realistic. No real `@nelco.in` addresses remain.

#### SEC-24 · No dependency pinning / integrity checking — ⚠️ PARTIAL
- **Done:** `requirements.txt` pins exact versions of all direct dependencies.
- **Outstanding:** SHA-256 hash verification. Generate a lock file in an environment with reliable PyPI access and a `pip-tools` build compatible with the local pip:
  ```bash
  pip install pip-tools
  pip-compile --generate-hashes --output-file requirements.lock requirements.txt
  # production install:
  pip install --require-hashes -r requirements.lock
  ```
  Not generated in this session: the local pip (26.x) is newer than the installed `pip-tools` (7.5.2) and PyPI was unreachable. This is best run in CI where the toolchain is controlled. Keep `requirements.txt` as the human-edited source and regenerate `requirements.lock` whenever it changes.

---

### Remaining Work

| Item | Type | Notes |
|------|------|-------|
| SEC-24 | Build | Generate `requirements.lock` with `--generate-hashes` in CI (versions already pinned) |

**Operational follow-ups (not code):**
- **Rotate credentials** — the SMTP password and TCS iON API tokens were previously committed in source/history; `.gitignore` only prevents *future* exposure, so rotate both.
- **Run `deploy_setup.ps1` as Administrator** so the SEC-22 `icacls` hardening on `data/` and `.env` actually applies.
- **Set strong `.env` passwords** and `HTTPS_ONLY=true` behind TLS before go-live.
