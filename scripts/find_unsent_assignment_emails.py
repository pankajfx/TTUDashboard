"""Recover the list of recipients an assignment's email job failed to reach.

For dispatches made from the current build this is a straight lookup: every job is
written to the email_jobs table with one entry per undelivered recipient AND the
server's reason, and the same data is on the Email delivery log screen. Use --db.

For dispatches made BEFORE that table existed there is no stored record -- the job
counters were in-memory only and dropped after 10 minutes -- so the list has to be
reconstructed from logs/app.log. That is what --logs mode does, and it is the mode
to use for the historical 197-recipient run.

Log mode uses set-difference, not error-scraping, on purpose: the old send_email()
logged the recipient on success but, on an SMTPAuthenticationError, logged only the
exception with no address. Treating "not confirmed sent" as unsent is the safe
direction -- it can over-report, never under-report.

Usage:
    python scripts/find_unsent_assignment_emails.py --list
    python scripts/find_unsent_assignment_emails.py --db                # recorded jobs
    python scripts/find_unsent_assignment_emails.py --id 12             # reconstruct
    python scripts/find_unsent_assignment_emails.py --id 12 --out data/resend.txt

Run it on the machine that hosts the app -- it needs that machine's data/ and logs/.
"""
import argparse
import glob
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import read_assignments, read_email_jobs  # noqa: E402

# '%(asctime)s %(levelname)s %(name)s: %(message)s' -> '2026-07-27 11:26:33,123 INFO ...'
TS = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+'
SENT_RE = re.compile(TS + r'.*Email sent successfully to (\S+)')
FAIL_RE = re.compile(TS + r'.*(?:SMTP error|Unexpected error) sending email to ([^:\s]+)')
AUTH_RE = re.compile(TS + r'.*SMTP authentication failed: (.*)')


def log_files(logs_dir):
    """Rotation order: app.log is newest, app.log.5 the oldest kept."""
    files = sorted(glob.glob(os.path.join(logs_dir, 'app.log.*')), reverse=True)
    newest = os.path.join(logs_dir, 'app.log')
    if os.path.exists(newest):
        files.append(newest)
    return files


def scan(logs_dir, window_start, window_end):
    """Collect sent/failed addresses logged inside [window_start, window_end]."""
    sent, failed, auth_errors, earliest = set(), {}, [], None

    for path in log_files(logs_dir):
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                m = SENT_RE.match(line) or FAIL_RE.match(line) or AUTH_RE.match(line)
                if not m:
                    continue
                ts = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
                if earliest is None or ts < earliest:
                    earliest = ts
                if not (window_start <= ts <= window_end):
                    continue
                if SENT_RE.match(line):
                    sent.add(m.group(2).lower())
                elif FAIL_RE.match(line):
                    failed[m.group(2).lower()] = line.strip()
                else:
                    auth_errors.append(line.strip())

    return sent, failed, auth_errors, earliest


def report_recorded_jobs(out_path=None):
    """Recorded dispatches -- exact, no reconstruction needed."""
    jobs = read_email_jobs(limit=200, only_failed=True)
    if not jobs:
        print('No recorded dispatch has any undelivered recipients.')
        print('(Jobs sent before the email_jobs table existed are not here -- '
              'use --id <n> to reconstruct those from the logs.)')
        return 0

    everyone = []
    for job in jobs:
        print(f"\n{job.get('started_at', '?')}  {job.get('kind')}  "
              f"{job.get('course_name') or '(no course)'}  "
              f"[assignment {job.get('assignment_id')}]  job {job['job_id']}")
        print(f"  {job.get('sent', 0)} sent, {job.get('failed', 0)} undelivered "
              f"of {job.get('total', 0)} ({job.get('status')})")
        for f in job.get('failures', []):
            kind = 'permanent' if f.get('permanent') else 'transient'
            print(f"    {f.get('email'):<40} {kind:<10} {f.get('reason')}")
            everyone.append(f.get('email'))

    if out_path:
        with open(out_path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(dict.fromkeys(filter(None, everyone))) + '\n')
        print(f'\nWrote {len(set(filter(None, everyone)))} unique address(es) to {out_path}')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', type=int, help='assignment id to audit (reconstruct from logs)')
    ap.add_argument('--db', action='store_true',
                    help='report recorded dispatches from the email_jobs table')
    ap.add_argument('--list', action='store_true', help='list assignments and exit')
    ap.add_argument('--logs', default='logs', help='log directory (default: logs)')
    ap.add_argument('--hours', type=float, default=6.0,
                    help='hours after creation to scan (default: 6)')
    ap.add_argument('--out', help='write the unconfirmed addresses to this file')
    args = ap.parse_args()

    if args.db:
        return report_recorded_jobs(args.out)

    assignments = read_assignments().get('assignments', [])

    if args.list or not args.id:
        for a in assignments:
            print(f"{a['id']:>4}  {a.get('created_date', '?'):<20} "
                  f"{len(a.get('user_emails', [])):>4} users  {a.get('course_name', '')}")
        return 0

    assignment = next((a for a in assignments if a['id'] == args.id), None)
    if not assignment:
        print(f'No assignment with id {args.id}.')
        return 1

    created = assignment.get('created_date')
    if not created:
        print(f'Assignment {args.id} has no created_date; cannot bound the log scan.')
        return 1
    start = datetime.strptime(created[:19], '%Y-%m-%d %H:%M:%S') - timedelta(minutes=1)
    end = start + timedelta(hours=args.hours)

    recipients = [e.lower() for e in assignment.get('user_emails', [])]
    sent, failed, auth_errors, earliest = scan(args.logs, start, end)

    unconfirmed = [e for e in recipients if e not in sent]

    print(f"Assignment {args.id}: {assignment.get('course_name')}")
    print(f"Created      : {created}")
    print(f"Log window   : {start:%Y-%m-%d %H:%M:%S} .. {end:%Y-%m-%d %H:%M:%S}")
    print(f"Recipients   : {len(recipients)}")
    print(f"Confirmed sent: {len(recipients) - len(unconfirmed)}")
    print(f"NOT confirmed : {len(unconfirmed)}")
    print(f"  of which logged an explicit SMTP error: "
          f"{sum(1 for e in unconfirmed if e in failed)}")
    if auth_errors:
        print(f"  {len(auth_errors)} SMTP auth failure(s) in window "
              f"(recipient not logged for these) e.g. {auth_errors[0][:160]}")

    if earliest and earliest > start:
        print(f"\nWARNING: oldest email line in {args.logs} is {earliest:%Y-%m-%d %H:%M:%S}, "
              f"after this assignment was created. Logs have rotated away -- the list "
              f"below is over-inclusive (some of these were probably delivered).")

    print('\n--- not confirmed delivered ---')
    for e in unconfirmed:
        reason = failed.get(e, '')
        print(f'{e}\t{reason.split(": ", 2)[-1] if reason else "no send attempt logged"}')

    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(unconfirmed) + '\n')
        print(f'\nWrote {len(unconfirmed)} address(es) to {args.out}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
