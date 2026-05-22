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
- Admin panel: user registry management, course assignments with deadlines
- Email notifications (assignment, reminder, removal) via Office 365 SMTP
- Background auto-refresh cache that keeps data ≤ 5 minutes stale without blocking users

---

## 2. Tech Stack & File Structure

### Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 / Flask |
| Frontend | Vanilla JS + Tailwind CSS (compiled static build) + ECharts (local) |
| Data store | JSON flat files (`data/`) |
| Email | smtplib → Office 365 SMTP (TLS, port 587) |
| Excel parsing | openpyxl |
| Password hashing | Werkzeug PBKDF2-SHA256 |
| Secrets | `python-dotenv` → `.env` (gitignored) |
| CSS build | Tailwind CLI v3.4.17 (Node/npx) → static `tailwind.min.css` |
| Concurrency | Python `threading` + `concurrent.futures.ThreadPoolExecutor` |

### File Structure

```
.
├── app.py                          # Flask app — all routes & business logic
├── email_service.py                # SMTP email module (templates + sending)
├── requirements.txt                # Python dependencies
├── .env                            # Secrets (gitignored) — keys, passwords, API URL
├── .env.example                    # Sanitised template of required env vars
├── package.json                    # Tailwind build scripts + pinned devDependency
├── tailwind.config.js              # Tailwind content scan config (templates/**)
├── deploy_setup.ps1                # PowerShell deployment helper
├── deploy_simple.bat               # One-click Windows batch launcher
├── Response Sample.json            # Local data fixture (USE_LOCAL_DATA=True)
├── data/
│   ├── api_cache.json              # Persistent API response cache (auto-created)
│   ├── users.json                  # User registry
│   └── course_assignments.json     # Course assignment records
├── logs/
│   └── app.log                     # Rotating audit/app log (auto-created, gitignored)
├── templates/
│   ├── index.html                  # Main dashboard (SPA-style)
│   ├── login.html                  # Login page
│   └── settings.html               # Admin settings page
├── static/
│   ├── css/input.css               # Tailwind directives (build source)
│   ├── css/tailwind.min.css        # Compiled static CSS (build output, committed)
│   └── js/echarts.min.js
└── Project_Structure.md            # This file
```

> **Build artifact note:** `static/css/tailwind.min.css` is generated from `input.css` by the Tailwind CLI and is committed so deployment needs only Python. `node_modules/` is gitignored; Node is required only when rebuilding CSS (see [§11](#11-deployment)).

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

All user data lives in `data/users.json`:

```json
{
  "users": [
    {
      "email": "user@example.com",
      "name": "John Doe",
      "source": "api | manual",
      "added_date": "2025-12-05 14:30:00"
    }
  ]
}
```

### API Sync (`sync_users_from_api`)

Called automatically on every `GET /api/settings/users` request:
1. Load current API data via `load_data()`
2. Extract unique `User_Mail_ID` + `Participant_Name` pairs
3. Compare against existing `users.json` (set of lowercase emails)
4. Append only **new** users with `source: "api"`
5. Save if any additions were made

### Duplicate Validation

Both client-side (JS) and server-side (Flask) check for duplicate emails (case-insensitive):
- Server returns **HTTP 409** with `{ "error": "User with email X already exists" }`
- Client highlights the email field in red and blocks submission

### User Addition Methods

| Method | Route | Notes |
|--------|-------|-------|
| Manual entry | `POST /api/settings/users` | Single email, duplicate-checked |
| Excel bulk upload | `POST /api/settings/users/bulk-upload` | Column A = emails; skips duplicates, reports invalid |
| API auto-sync | (via `sync_users_from_api`) | Runs on settings page load |

### Real-Time Search (Settings Page)

- Client-side JS filters the rendered user list on every keystroke
- Substring match against both email and name (case-insensitive)
- Shows "Showing X of Y users" count; empty result shows "No users found" message
- Clearing the field restores the full list

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
Request body: { course_name, user_emails[], deadline, notify_email }

1. Validate required fields
2. Append assignment record (id = len + 1) to assignments.json
3. If notify_email=true:
     Build email_to_name map from users.json
     _dispatch_assignment_emails() → background ThreadPoolExecutor job
     Returns job_id for polling
4. Return 201 with assignment + email_job_id
```

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

### Sending Reminders (`POST /api/settings/assignments/<id>/remind`)

1. Load assignment + API data
2. Calculate `days_remaining` from deadline
3. Determine completed users from API
4. Send `send_deadline_reminder_email()` **only** to incomplete users (synchronous, not threaded)
5. Returns counts: `reminders_sent`, `reminders_failed`, `already_completed`

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
| `send_bulk_emails` | Generic bulk send utility | Custom |

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
| GET | `/api/settings/assignments` | All assignments |
| POST 🔒 | `/api/settings/assignments` | Create assignment |
| GET | `/api/settings/assignments/<id>` | Assignment detail + progress |
| PUT 🔒 | `/api/settings/assignments/<id>` | Update assignment user list |
| DELETE 🔒 | `/api/settings/assignments/<id>` | Delete assignment |
| POST 🔒 | `/api/settings/assignments/<id>/remind` | Send deadline reminders |
| POST 🔒 | `/api/settings/assignments/bulk-upload` | Bulk assignment from Excel |
| GET | `/api/email-job/<job_id>` | Poll background email job progress |

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

### Quick Start (Development)

```bash
pip install -r requirements.txt      # includes python-dotenv
cp .env.example .env                 # then fill in real values
python app.py
# → http://localhost:5000
```

The app **will not start** if required env vars are missing — `SECRET_KEY`, `ADMIN_PASSWORD`, `USER_PASSWORD`, and `TCS_ION_API_URL` are read with `os.environ[...]` and raise `KeyError` if absent.

### Rebuilding Tailwind CSS

The compiled `static/css/tailwind.min.css` is committed, so normal deployment needs **no Node**. Rebuild only when you add/remove Tailwind utility classes in a template:

```bash
npm install            # one-time, installs pinned tailwindcss 3.4.17
npm run build:css      # regenerates static/css/tailwind.min.css (minified)
npm run watch:css      # optional: auto-rebuild while editing templates
```

`tailwind.config.js` scans `templates/**/*.html` (including class names inside inline `<script>` template literals), so all dynamically-applied classes are captured.

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

**Manual steps:**
```batch
set PYTHON_PATH=C:\Users\8527\PYTHON\python_3_11_4\python.exe
"%PYTHON_PATH%" -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
pip install waitress
python app.py
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
| `ADMIN_PASSWORD` | **yes** | Plaintext admin password (hashed in memory at startup) |
| `USER_PASSWORD` | **yes** | Plaintext standard-user password (hashed at startup) |
| `TCS_ION_API_URL` | **yes** | Full TCS iON API URL incl. auth params |
| `USE_LOCAL_DATA` | no (`false`) | `true` = read `Response Sample.json` instead of API |
| `SMTP_USERNAME` | no | Office 365 sender account |
| `SMTP_PASSWORD` | no | Office 365 app password |
| `HTTPS_ONLY` | no (`false`) | `true` sets `SESSION_COOKIE_SECURE=True` (HTTPS deployments) |

Missing any **required** variable raises `KeyError` and the app refuses to start (fail-fast).

### Constants in `app.py`

| Variable | Default | Description |
|----------|---------|-------------|
| `API_TIMEOUT` | `360` | Seconds before API request times out |
| `AUTO_REFRESH_INTERVAL_MINUTES` | `5` | Background cache refresh cadence |
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
| UI unstyled / "totally disturbed" | Stale or broken `tailwind.min.css` | Hard-refresh (Ctrl+F5); if persists run `npm run build:css` |
| Port already in use | Another process on 5000 | Use `netstat -ano \| findstr :5000` to identify |
| Permission error on data/ | Missing write permission | Run as Administrator or fix folder ACL |

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
