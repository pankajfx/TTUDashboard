"""
Seed / reconcile course assignments from the TCS iON API data.

WHY
---
The FY / Assignment dashboard needs assignments to analyse. This script
reverse-engineers realistic, back-dated assignments from the API response so the
dashboard is populated immediately and so completion %s are measured against a
real assigned population. It is also safe to run in production to bootstrap the
assignments file.

WHAT IT DOES
------------
Groups API records by course (Activity_Name) and, enrolling ONLY the users that
appear in the API for that course, creates:

  1. A primary assignment per course, back-dated to just before that course's
     earliest completion  -> all completions count as valid (clean baseline).
  2. For courses nobody has completed yet, an assignment dated ~30 days ago
     (current FY) -> 0% completion ("assigned, nobody finished").

Each assignment gets a descriptive title (course + date + user count).

NOTE: a previous version also generated later "refresher" assignments that
postdated real completions to demo the staleness rule. Those are no longer
created: a completion before the assignment date is now simply Not Started, and
the synthetic refreshers only made genuinely-completed users look non-compliant.

USAGE
-----
  python scripts/seed_assignments_from_api.py --dry-run     # preview only
  python scripts/seed_assignments_from_api.py               # write if file empty
  python scripts/seed_assignments_from_api.py --reset       # overwrite existing
  python scripts/seed_assignments_from_api.py --input data/api_cache.json

Always backs up an existing assignments file before writing.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

# Make the sibling module importable no matter the CWD, and keep console output
# from crashing on Windows code pages when it prints the '·' in titles.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import assignment_analytics as aa
import db  # SQLite store (the source of truth; replaces the JSON files)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT = os.path.join(ROOT, "data", "course_assignments.json")


def load_api_data(input_path):
    """Return the list of API records. With no --input, prefer the live SQLite
    cache (the source of truth), then fall back to the JSON files (kept as
    backups). An explicit --input path is always read as a JSON file."""
    if not input_path:
        try:
            data, _ = db.read_cache()
            if data:
                print(f"Loaded {len(data)} API records from SQLite cache")
                return data
        except Exception as e:
            print(f"(SQLite cache unavailable: {e}; falling back to files)")
    candidates = [input_path] if input_path else [
        os.path.join(ROOT, "data", "api_cache.json"),
        os.path.join(ROOT, "Response Sample.json"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            data = raw.get("data", raw) if isinstance(raw, dict) else raw
            print(f"Loaded {len(data)} API records from {os.path.relpath(path, ROOT)}")
            return data
    raise FileNotFoundError("No API data found (looked in SQLite cache, data/api_cache.json, Response Sample.json)")


def group_by_course(api_data):
    """course -> {'emails': [...ordered unique...], 'completion_dates': [datetime...]}"""
    courses = defaultdict(lambda: {"emails": [], "seen": set(), "completion_dates": []})
    for r in api_data:
        c = aa.course_key(r)
        e = (r.get("User_Mail_ID") or "").strip()
        if not c or not e:
            continue
        entry = courses[c]
        if e not in entry["seen"]:
            entry["seen"].add(e)
            entry["emails"].append(e)
        if (r.get("Course_Completion_Status") or "").strip() == "Completed":
            d = aa.parse_completion(r.get("Course_Completion_Date_(YYYY-MM-DD)"))
            if d:
                entry["completion_dates"].append(d)
    return courses


def make_assignment(next_id, course, emails, created_dt, deadline_days=30):
    created_str = created_dt.strftime("%Y-%m-%d %H:%M:%S")
    deadline = (created_dt + timedelta(days=deadline_days)).strftime("%Y-%m-%d")
    a = {
        "id": next_id,
        "course_name": course,
        "user_emails": list(emails),
        "deadline": deadline,
        "created_date": created_str,
        "created_by": "seed-script",
        "source": "seed",
    }
    a["title"] = aa.assignment_title(a)
    return a


def build_assignments(api_data):
    courses = group_by_course(api_data)
    now = datetime.now()
    no_completion_dt = (now - timedelta(days=30)).replace(hour=9, minute=0, second=0, microsecond=0)

    assignments = []
    next_id = 1
    for course, info in sorted(courses.items()):
        emails = info["emails"]
        if not emails:
            continue
        dates = sorted(info["completion_dates"])
        if dates:
            created_dt = (dates[0] - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        else:
            created_dt = no_completion_dt
        assignments.append(make_assignment(next_id, course, emails, created_dt))
        next_id += 1

    return assignments


def print_summary(assignments, api_data):
    index = aa.build_api_index(api_data)
    try:
        history = aa.build_history_index(db.read_completion_history())
    except Exception:
        history = {}
    by_fy = defaultdict(int)
    print("\n{:>3}  {:<12} {:>6} {:>5} {:>5} {:>5}  {}".format(
        "id", "created", "users", "done", "stale", "rate%", "title"))
    print("-" * 100)
    for a in assignments:
        p = aa.compute_assignment_progress(a, index, history)
        by_fy[p["fy_label"]] += 1
        print("{:>3}  {:<12} {:>6} {:>5} {:>5} {:>5}  {}".format(
            a["id"], a["created_date"][:10], p["total"], p["completed"],
            p["stale"], p["completion_rate"], a["title"]))
    print("-" * 100)
    print("Total assignments:", len(assignments))
    for fy, n in sorted(by_fy.items()):
        print(f"  FY {fy}: {n} assignments")


def main():
    ap = argparse.ArgumentParser(description="Seed course assignments from API data.")
    ap.add_argument("--dry-run", action="store_true", help="Preview only; write nothing.")
    ap.add_argument("--reset", action="store_true", help="Overwrite existing assignments.")
    ap.add_argument("--input", help="Path to API data (default: data/api_cache.json).")
    ap.add_argument("--output", default=DEFAULT_OUTPUT, help="Assignments file to write.")
    args = ap.parse_args()

    api_data = load_api_data(args.input)
    assignments = build_assignments(api_data)
    print_summary(assignments, api_data)

    if args.dry_run:
        print("\n[dry-run] No files written.")
        return

    # Guard against clobbering real data (now the SQLite store, not the JSON file).
    db.init_db()
    existing = db.read_assignments().get("assignments", [])
    if existing and not args.reset:
        print(f"\nRefusing to overwrite {len(existing)} existing assignment(s) in the "
              f"SQLite store. Re-run with --reset to replace.")
        sys.exit(1)

    # Back up whatever is there before writing (timestamped JSON snapshot).
    if existing:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = args.output.replace(".json", f".backup.{ts}.json")
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        with open(backup, "w", encoding="utf-8") as f:
            json.dump({"assignments": existing}, f, indent=2, ensure_ascii=False)
        print(f"\nBacked up existing assignments -> {os.path.relpath(backup, ROOT)}")

    if db.write_assignments({"assignments": assignments}):
        print(f"Wrote {len(assignments)} assignments to the SQLite store")
    else:
        print("Failed to write assignments to the SQLite store")
        sys.exit(1)


if __name__ == "__main__":
    main()
