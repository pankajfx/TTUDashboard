"""
Backfill the completion-history ledger from every API snapshot on disk.

WHY
---
The TCS iON API returns only ONE (latest) completion date per (course, user) and
overwrites it in place when a user re-does a recurring course. So prior-cycle
dates survive only in snapshots we captured earlier. Going forward the app records
every refresh automatically (see app.record_completion_history), but that starts
empty — this one-time pass folds in the history that is *already* on disk before
those older dates are gone for good:

  * the live SQLite api_cache            (current snapshot)
  * data/api_cache.json                  (old JSON cache backup, if present)
  * Response Sample.json                 (an older captured snapshot)

Dedup is by the ledger's (course, email, completion_date) primary key, so this is
idempotent and safe to re-run. Add extra snapshots with --input (repeatable).

USAGE
-----
  python scripts/seed_completion_history.py            # backfill from the sources above
  python scripts/seed_completion_history.py --dry-run  # count only, write nothing
  python scripts/seed_completion_history.py --input path/to/snapshot.json
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import assignment_analytics as aa
import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _records(raw):
    """Normalise a loaded JSON blob to the list of API records."""
    if isinstance(raw, dict):
        return raw.get("data", []) or []
    return raw or []


def iter_sources(extra_inputs):
    """Yield (label, api_records) for every available snapshot."""
    # 1) live SQLite cache (source of truth for the current snapshot)
    try:
        data, _ = db.read_cache()
        if data:
            yield "SQLite api_cache", data
    except Exception as e:
        print(f"(SQLite cache unavailable: {e})")

    # 2) on-disk snapshots
    paths = [
        os.path.join(ROOT, "data", "api_cache.json"),
        os.path.join(ROOT, "Response Sample.json"),
    ] + list(extra_inputs or [])
    for path in paths:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    yield os.path.relpath(path, ROOT), _records(json.load(f))
            except Exception as e:
                print(f"(skipping {path}: {e})")


def main():
    ap = argparse.ArgumentParser(description="Backfill the completion-history ledger.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Count what would be recorded; write nothing.")
    ap.add_argument("--input", action="append", default=[],
                    help="Extra snapshot JSON to fold in (repeatable).")
    args = ap.parse_args()

    db.init_db()
    ts = datetime.now()
    total_new = 0
    total_seen = 0

    for label, records in iter_sources(args.input):
        completions = list(aa.extract_completions(records))
        total_seen += len(completions)
        if args.dry_run:
            distinct = len({(c, e, d) for c, e, d in completions})
            print(f"{label:<22} {len(records):>5} records  {distinct:>5} distinct completions")
            continue
        new = db.record_completions(completions, ts)
        total_new += new
        print(f"{label:<22} {len(records):>5} records  {new:>5} NEW completion date(s)")

    if args.dry_run:
        print(f"\n[dry-run] {total_seen} completion rows across sources. No writes.")
        return

    ledger = db.read_completion_history()
    print(f"\nRecorded {total_new} new date(s). Ledger now holds {len(ledger)} "
          f"(course, user, date) row(s).")


if __name__ == "__main__":
    main()
