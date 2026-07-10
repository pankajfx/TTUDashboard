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
and discounts "stale" completions (finished before the assignment was created).
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
    """Parse an assignment created_date. Accepts 'YYYY-MM-DD HH:MM:SS' or
    'YYYY-MM-DD'. Returns a datetime or None."""
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
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


def _classify_user(records, created_dt):
    """Given all API records for one (course, user) and the assignment creation
    datetime, return (status, percentage, completion_date_str, stale_bool).

    status ∈ {'completed', 'in_progress', 'stale', 'not_started'}.
    A completion counts only if it is dated on/after the assignment was created;
    completions strictly before creation are 'stale' (must be redone)."""
    if not records:
        # user is assigned but never appeared in the API → never opened portal
        return "not_started", 0.0, "", False

    created_day = created_dt.date() if created_dt else None
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
        # valid if any completion has no date (unverifiable → benefit of doubt)
        # or is dated on/after the assignment creation day.
        valid = [d for d in completed_dates
                 if d is None or created_day is None or d.date() >= created_day]
        if valid:
            dated = [d for d in valid if d is not None]
            latest = max(dated) if dated else None
            return "completed", 100.0, (latest.strftime("%Y-%m-%d") if latest else ""), False
        # every completion predates the assignment → stale, must redo
        stale_dates = [d for d in completed_dates if d is not None]
        latest_stale = max(stale_dates).strftime("%Y-%m-%d") if stale_dates else ""
        return "stale", max_pct, latest_stale, True

    # no completion on record
    if attempted or max_pct > 0:
        return "in_progress", max_pct, "", False
    return "not_started", 0.0, "", False


def compute_assignment_progress(assignment: dict, api_index) -> dict:
    """Compute per-user progress + bucket totals for a single assignment,
    applying the staleness rule. `api_index` from build_api_index()."""
    course = (assignment.get("course_name") or "").strip()
    emails = assignment.get("user_emails", []) or []
    created_dt = parse_created(assignment.get("created_date", ""))
    sy, label = (fy_of_datetime(created_dt) if created_dt else (None, "Unknown"))

    users = []
    completed = in_progress = stale = not_started = untouched = 0
    for email in emails:
        email = (email or "").strip()
        records = api_index.get((course, email), [])
        status, pct, cdate, is_stale = _classify_user(records, created_dt)
        is_untouched = not records
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
        elif status == "stale":
            stale += 1
        else:
            not_started += 1
            if is_untouched:
                untouched += 1

    total = len(emails)
    rate = (completed / total * 100) if total else 0.0
    return {
        "id": assignment.get("id"),
        "title": assignment_title(assignment),
        "course_name": course,
        "created_date": assignment.get("created_date", ""),
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


def build_summary(assignments, api_data, selected="current", now: datetime = None) -> dict:
    """Full payload for the FY dashboard for the given scope."""
    index = build_api_index(api_data)
    resolved = resolve_selected_fy(selected, assignments, now)

    # progress for every assignment (needed to filter + aggregate)
    progressed = [compute_assignment_progress(a, index) for a in assignments]
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

    fys = available_financial_years(assignments)
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
