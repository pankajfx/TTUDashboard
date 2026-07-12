"""
Assignment / Financial-Year analytics engine.

Pure functions (no Flask, no I/O) shared by app.py (the FY dashboard endpoints)
and scripts/seed_assignments_from_api.py (the seed / production reconciler).

Why this module exists
----------------------
The raw TCS iON API only returns users who actually opened the training portal.
So course completion % computed from the API alone is misleading: if 100 users
are assigned a course but only 2 ever logged in and both finished, the API shows
2 users @ 100%. This engine instead measures progress against *everyone assigned*
in an assignment, bucketed by the Financial Year the assignment was created in,
and discounts "stale" completions (finished outside the assignment's validity
window — its effective_from..effective_to range, which defaults to "from the
creation date, open-ended").
"""

from datetime import datetime, timedelta
from collections import defaultdict

# India Financial Year runs 1 April -> 31 March.
FY_START_MONTH = 4


# ── Financial Year helpers ──────────────────────────────────────────────────
def fy_start_year(dt: datetime) -> int:
    """Return the calendar year in which the FY containing `dt` starts.
    e.g. 2025-07-06 -> 2025 (FY 2025-26); 2025-02-15 -> 2024 (FY 2024-25)."""
    return dt.year if dt.month >= FY_START_MONTH else dt.year - 1


def fy_label(start_year: int) -> str:
    """2025 -> '2025-26'."""
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def fy_bounds(start_year: int):
    """(inclusive start, inclusive end) datetimes for the FY starting `start_year`."""
    start = datetime(start_year, FY_START_MONTH, 1, 0, 0, 0)
    end = datetime(start_year + 1, FY_START_MONTH, 1, 0, 0, 0) - timedelta(seconds=1)
    return start, end


def fy_of_datetime(dt: datetime):
    """datetime -> (start_year, label)."""
    sy = fy_start_year(dt)
    return sy, fy_label(sy)


def current_fy_start_year(now: datetime = None) -> int:
    return fy_start_year(now or datetime.now())


# ── Date / value parsing (tolerant of the messy API strings) ────────────────
def parse_created(value: str):
    """Parse an assignment created_date / effective_from / effective_to. Accepts
    'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DD HH:MM', 'YYYY-MM-DD', and the ISO 'T'
    separator variants that HTML <input type="datetime-local"> emits
    ('YYYY-MM-DDTHH:MM'). Returns a datetime or None."""
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_completion(value: str):
    """Parse a course completion date. The API returns date-only strings, often
    with a trailing space ('2024-12-19 ') or empty. Returns a datetime (at
    midnight) or None."""
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_percentage(value) -> float:
    try:
        return float(str(value).strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def course_key(record: dict) -> str:
    """The course identity used throughout the app: Activity_Name, falling back
    to Course_Name (this is what assignments store as course_name)."""
    return (record.get("Activity_Name") or record.get("Course_Name") or "").strip()


# ── Assignment title (nomenclature) ─────────────────────────────────────────
def assignment_title(assignment: dict) -> str:
    """Return the stored title, or derive a unique one so a glance tells you the
    course, the exact date and time it was created, and how many users are
    enrolled:
        'Understanding Hazards and Risks · 06 Jul 2025 · 14:23:07 · 23 users'
    """
    existing = assignment.get("title")
    if existing:
        return existing
    course = assignment.get("course_name", "Course")
    n = len(assignment.get("user_emails", []))
    dt = parse_created(assignment.get("created_date", ""))
    when = dt.strftime("%d %b %Y · %H:%M:%S") if dt else "undated"
    return f"{course} · {when} · {n} user{'s' if n != 1 else ''}"


# ── API index ───────────────────────────────────────────────────────────────
def build_api_index(api_data):
    """Index API records by (course, email) -> [records] for O(1) lookup."""
    index = defaultdict(list)
    for record in api_data or []:
        c = course_key(record)
        e = (record.get("User_Mail_ID") or "").strip()
        if c and e:
            index[(c, e)].append(record)
    return index


def extract_completions(api_data):
    """Yield ``(course, email, 'YYYY-MM-DD')`` for every record that is Completed
    with a parseable date. Feeds the persistent completion-history ledger
    (``db.record_completions``): the API overwrites its single date per
    (course, user), so we harvest each snapshot's completions to preserve them."""
    for record in api_data or []:
        if (record.get("Course_Completion_Status") or "").strip() != "Completed":
            continue
        c = course_key(record)
        e = (record.get("User_Mail_ID") or "").strip()
        d = parse_completion(record.get("Course_Completion_Date_(YYYY-MM-DD)"))
        if c and e and d is not None:
            yield c, e, d.strftime("%Y-%m-%d")


def build_history_index(history_rows):
    """Index persistent completion-history rows by (course, email) -> [datetimes].

    ``history_rows`` is an iterable of ``(course, email, completion_date_str)`` as
    returned by ``db.read_completion_history()``. Blank/unparseable dates are
    skipped. This bucket of prior-cycle completion dates is unioned with the live
    snapshot in ``_classify_user`` so each assignment is judged against every date
    ever observed, not just the API's latest (overwriting) value."""
    index = defaultdict(list)
    for row in history_rows or []:
        try:
            course, email, date_str = row
        except (ValueError, TypeError):
            continue
        c = (course or "").strip()
        e = (email or "").strip()
        d = parse_completion(date_str)
        if c and e and d is not None:
            index[(c, e)].append(d)
    return index


def _completion_in_window(d, window_start, window_end) -> bool:
    """Does a completion datetime `d` fall inside the assignment's validity window?

    Day-granular (the API returns date-only completions). Either bound may be None
    meaning "open" on that side. A None `d` (Completed but the API gave no date) is
    unverifiable, so it gets the benefit of the doubt and counts."""
    if d is None:
        return True
    day = d.date()
    if window_start is not None and day < window_start.date():
        return False
    if window_end is not None and day > window_end.date():
        return False
    return True


def _classify_live(records, window_start, window_end):
    """Classify one (course, user) from the LIVE API snapshot only (no ledger).

    Returns (status, percentage, completion_date_str, stale_bool).
    status ∈ {'completed', 'in_progress', 'not_started'}.
    A completion counts only if it falls within [window_start, window_end]
    (inclusive, day granularity; either bound may be None = open on that side).
    A completion *outside* the window — finished before it opened OR after it
    closed — is "stale": it does NOT count for this assignment, so the user is
    classified 'not_started' (they must (re)do it inside the window) with the
    stale flag set so callers can annotate the row."""
    if not records:
        # user is assigned but never appeared in the API → never opened portal
        return "not_started", 0.0, "", False

    completed_dates = []          # datetimes of Completed records (None = no date)
    has_completed = False
    max_pct = 0.0
    attempted = False

    for r in records:
        status = (r.get("Course_Completion_Status") or "").strip()
        activity = (r.get("Activity_Status") or "").strip().upper()
        pct = parse_percentage(r.get("Course_Completion_Percentage"))
        max_pct = max(max_pct, pct)
        if activity and activity != "NOT ATTEMPTED":
            attempted = True
        if status == "Completed":
            has_completed = True
            completed_dates.append(parse_completion(r.get("Course_Completion_Date_(YYYY-MM-DD)")))

    if has_completed:
        valid = [d for d in completed_dates
                 if _completion_in_window(d, window_start, window_end)]
        if valid:
            dated = [d for d in valid if d is not None]
            latest = max(dated) if dated else None
            return "completed", 100.0, (latest.strftime("%Y-%m-%d") if latest else ""), False
        # every completion falls outside the window → the prior completion is
        # "stale": it does not count here, so treat the user as Not Started
        # (must redo). Keep the flag + date so the row can note the prior finish.
        stale_dates = [d for d in completed_dates if d is not None]
        latest_stale = max(stale_dates).strftime("%Y-%m-%d") if stale_dates else ""
        return "not_started", 0.0, latest_stale, True

    # no completion on record
    if attempted or max_pct > 0:
        return "in_progress", max_pct, "", False
    return "not_started", 0.0, "", False


def _classify_user(records, window_start, window_end, history_dates=None):
    """Classify one (course, user) against an assignment window, unioning the live
    API snapshot with the persistent completion-history ledger.

    ``history_dates`` is the list of prior-cycle completion datetimes for this
    (course, user) from the ledger (the API overwrites its single latest date, so
    earlier cycles survive only there). The ledger can only ever *upgrade* a user's
    standing toward Completed — it supplies extra completion DATES, never
    in-progress or negative signal — so it never downgrades a live in_progress /
    completed result. Returns (status, percentage, completion_date_str, stale_bool).

    Precedence:
      1. Any in-window completion (live OR ledger)        -> completed
      2. Live snapshot shows a current attempt            -> in_progress
      3. Only out-of-window completions (live or ledger)  -> not_started + stale
      4. Nothing                                          -> not_started
    """
    status, pct, cdate, is_stale = _classify_live(records, window_start, window_end)

    hist = [d for d in (history_dates or []) if d is not None]
    if not hist or status == "completed":
        # No ledger to add, or the live snapshot already counts an in-window
        # completion — nothing the ledger could improve.
        return status, pct, cdate, is_stale

    # A ledger date inside this window proves completion for this cycle even after
    # the API overwrote it away → upgrade to Completed.
    in_window = [d for d in hist if _completion_in_window(d, window_start, window_end)]
    if in_window:
        latest = max(in_window)
        return "completed", 100.0, latest.strftime("%Y-%m-%d"), False

    # No in-window ledger date. Keep an active live re-attempt as in_progress
    # (it outranks a stale prior finish).
    if status == "in_progress":
        return status, pct, cdate, is_stale

    # Otherwise the user finished before, but outside this window → Not Started,
    # flagged stale, annotated with the most recent prior finish (live or ledger).
    stale_candidates = list(hist)
    live_stale = parse_completion(cdate) if cdate else None
    if live_stale is not None:
        stale_candidates.append(live_stale)
    latest_stale = max(stale_candidates).strftime("%Y-%m-%d") if stale_candidates else ""
    return "not_started", 0.0, latest_stale, True


def compute_assignment_progress(assignment: dict, api_index, history_index=None) -> dict:
    """Compute per-user progress + bucket totals for a single assignment,
    applying the staleness rule. `api_index` from build_api_index()."""
    course = (assignment.get("course_name") or "").strip()
    emails = assignment.get("user_emails", []) or []
    created_dt = parse_created(assignment.get("created_date", ""))
    # Validity window: a completion must fall within [effective_from, effective_to]
    # to count. effective_from defaults to the creation datetime (back-compat with
    # assignments that predate this feature); effective_to is optional (None = open
    # ended). FY bucketing stays on the creation date — the FY is about when the
    # assignment was created, not the window it validates.
    window_start = parse_created(assignment.get("effective_from", "")) or created_dt
    window_end = parse_created(assignment.get("effective_to", ""))
    sy, label = (fy_of_datetime(created_dt) if created_dt else (None, "Unknown"))

    users = []
    completed = in_progress = stale = not_started = untouched = 0
    for email in emails:
        email = (email or "").strip()
        records = api_index.get((course, email), [])
        hist = history_index.get((course, email), []) if history_index else []
        status, pct, cdate, is_stale = _classify_user(records, window_start, window_end, hist)
        # "Untouched" = never seen at all: not in the live snapshot AND no prior
        # completion on record in the ledger.
        is_untouched = not records and not hist
        name = ""
        if records:
            name = (records[0].get("Participant_Name") or "").strip()
        users.append({
            "email": email,
            "name": name,
            "status": status,
            "percentage": round(pct, 2),
            "completion_date": cdate,
            "stale": is_stale,
            "untouched": is_untouched,
        })
        if status == "completed":
            completed += 1
        elif status == "in_progress":
            in_progress += 1
        else:
            # not_started — this includes "stale" prior completions. `stale` is
            # tracked as a subset of not_started purely for reference; those users
            # still need to redo the course, so they are Not Started here.
            not_started += 1
            if is_stale:
                stale += 1
            elif is_untouched:
                untouched += 1

    total = len(emails)
    rate = (completed / total * 100) if total else 0.0
    return {
        "id": assignment.get("id"),
        "title": assignment_title(assignment),
        "course_name": course,
        "created_date": assignment.get("created_date", ""),
        "effective_from": window_start.strftime("%Y-%m-%d %H:%M:%S") if window_start else "",
        "effective_to": window_end.strftime("%Y-%m-%d %H:%M:%S") if window_end else "",
        "deadline": assignment.get("deadline", ""),
        "fy_start_year": sy,
        "fy_label": label,
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "not_started": not_started,
        "stale": stale,
        "untouched": untouched,
        "completion_rate": round(rate, 2),
        "users": users,
    }


# ── FY resolution + full dashboard summary ──────────────────────────────────
def available_financial_years(assignments):
    """Sorted (desc) list of {start_year, label, count} present in assignments."""
    counts = defaultdict(int)
    for a in assignments:
        dt = parse_created(a.get("created_date", ""))
        if dt:
            counts[fy_start_year(dt)] += 1
    return [
        {"start_year": sy, "label": fy_label(sy), "count": counts[sy]}
        for sy in sorted(counts, reverse=True)
    ]


def resolve_selected_fy(selected, assignments, now: datetime = None):
    """Turn a requested scope ('current' | 'all' | '<start_year>') into a concrete
    selection. 'current' falls back to the most recent FY that actually has
    assignments when the current FY is empty, so the page never opens blank.
    Returns 'all' or an int start_year."""
    fys = {f["start_year"] for f in available_financial_years(assignments)}
    if selected == "all":
        return "all"
    if selected in (None, "", "current"):
        cur = current_fy_start_year(now)
        if cur in fys:
            return cur
        return max(fys) if fys else cur
    try:
        return int(selected)
    except (ValueError, TypeError):
        return "all"


def build_summary(assignments, api_data, selected="current", now: datetime = None,
                  history_index=None) -> dict:
    """Full payload for the FY dashboard for the given scope.

    ``history_index`` (from ``build_history_index(db.read_completion_history())``)
    supplies prior-cycle completion dates the live API has overwritten, so each
    assignment is classified against the full bucket of dates ever observed."""
    index = build_api_index(api_data)
    resolved = resolve_selected_fy(selected, assignments, now)

    # progress for every assignment (needed to filter + aggregate)
    progressed = [compute_assignment_progress(a, index, history_index) for a in assignments]
    if resolved == "all":
        scoped = progressed
    else:
        scoped = [p for p in progressed if p["fy_start_year"] == resolved]

    # ── per-assignment rows (drop the heavy per-user list for the table) ──
    assignment_rows = [{k: v for k, v in p.items() if k != "users"} for p in scoped]
    assignment_rows.sort(key=lambda r: r["created_date"], reverse=True)

    # ── course aggregation ──
    courses = defaultdict(lambda: {
        "course_name": "", "assignment_count": 0, "total_enrollments": 0,
        "completed": 0, "in_progress": 0, "not_started": 0, "stale": 0,
        "latest_assignment_date": "",
    })
    for p in scoped:
        c = courses[p["course_name"]]
        c["course_name"] = p["course_name"]
        c["assignment_count"] += 1
        c["total_enrollments"] += p["total"]
        c["completed"] += p["completed"]
        c["in_progress"] += p["in_progress"]
        c["not_started"] += p["not_started"]
        c["stale"] += p["stale"]
        if p["created_date"] > c["latest_assignment_date"]:
            c["latest_assignment_date"] = p["created_date"]
    course_rows = []
    for c in courses.values():
        te = c["total_enrollments"]
        c["completion_rate"] = round(c["completed"] / te * 100, 2) if te else 0.0
        course_rows.append(c)
    course_rows.sort(key=lambda r: (r["assignment_count"], r["total_enrollments"]), reverse=True)

    # ── user aggregation ──
    users = defaultdict(lambda: {
        "email": "", "name": "", "assignments_count": 0, "courses": set(),
        "completed": 0, "in_progress": 0, "not_started": 0, "stale": 0,
    })
    for p in scoped:
        for u in p["users"]:
            row = users[u["email"]]
            row["email"] = u["email"]
            if u["name"] and not row["name"]:
                row["name"] = u["name"]
            row["assignments_count"] += 1
            row["courses"].add(p["course_name"])
            row[u["status"]] = row.get(u["status"], 0) + 1
    user_rows = []
    for r in users.values():
        ac = r["assignments_count"]
        r["courses_count"] = len(r.pop("courses"))
        r["completion_rate"] = round(r["completed"] / ac * 100, 2) if ac else 0.0
        user_rows.append(r)
    user_rows.sort(key=lambda r: (r["assignments_count"], r["completion_rate"]), reverse=True)

    # ── KPIs ──
    total_assignments = len(scoped)
    total_enrollments = sum(p["total"] for p in scoped)
    total_completed = sum(p["completed"] for p in scoped)
    total_stale = sum(p["stale"] for p in scoped)
    most_assigned = max(course_rows, key=lambda r: r["assignment_count"], default=None)

    kpis = {
        "total_assignments": total_assignments,
        "total_enrollments": total_enrollments,
        "avg_enrollment": round(total_enrollments / total_assignments, 1) if total_assignments else 0,
        "courses_covered": len(course_rows),
        "unique_users": len(user_rows),
        "overall_completion_rate": round(total_completed / total_enrollments * 100, 2) if total_enrollments else 0.0,
        "stale_completions": total_stale,
        "most_assigned_course": (
            {"course_name": most_assigned["course_name"], "count": most_assigned["assignment_count"]}
            if most_assigned else None
        ),
    }

    # Always expose the current FY as a selectable option — even on a clean
    # instance with zero assignments — so the dropdown is never blank and the
    # page opens on the current FY (0 assignments) by default.
    fys = available_financial_years(assignments)
    cur = current_fy_start_year(now)
    if not any(f["start_year"] == cur for f in fys):
        fys.append({"start_year": cur, "label": fy_label(cur), "count": 0})
        fys.sort(key=lambda f: f["start_year"], reverse=True)
    return {
        "financial_years": fys,
        "current_fy": current_fy_start_year(now),
        "selected": ("all" if resolved == "all" else resolved),
        "selected_label": ("All Financial Years" if resolved == "all" else fy_label(resolved)),
        "kpis": kpis,
        "assignments": assignment_rows,
        "courses": course_rows,
        "users": user_rows,
    }
