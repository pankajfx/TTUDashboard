from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import requests
from collections import defaultdict
from datetime import datetime, timedelta
import json
import os
import logging
import re
import uuid
import secrets
from concurrent.futures import ThreadPoolExecutor, as_completed
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from email_service import send_course_assignment_email, send_deadline_reminder_email, send_course_removal_email
import assignment_analytics as aa
import openpyxl
from io import BytesIO
import threading
import time
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

load_dotenv()

# Configure logging — console + persistent rotating file (audit trail).
# Attach handlers directly to the root logger and clear any pre-existing ones
# (e.g. email_service.py calls logging.basicConfig() at import time, which would
# otherwise make our basicConfig a no-op and silently drop the file handler).
os.makedirs('logs', exist_ok=True)
_log_format = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')

_file_handler = RotatingFileHandler('logs/app.log', maxBytes=1_000_000, backupCount=5, encoding='utf-8')
_file_handler.setFormatter(_log_format)
_file_handler.setLevel(logging.INFO)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_format)

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)
for _h in list(_root_logger.handlers):
    _root_logger.removeHandler(_h)
_root_logger.addHandler(_console_handler)
_root_logger.addHandler(_file_handler)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']

# Session security
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('HTTPS_ONLY', 'false').lower() == 'true'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB upload limit

API_URL = os.environ['TCS_ION_API_URL']
USE_LOCAL_DATA = os.environ.get('USE_LOCAL_DATA', 'false').lower() == 'true'

# API timeout configuration (in seconds)
# The API typically takes 3+ minutes to respond, so set timeout accordingly
API_TIMEOUT = 360  # 360 seconds = 6 minutes (API can take 3-5 min; give headroom)

# Cache configuration
AUTO_REFRESH_INTERVAL_MINUTES = 30  # Auto-refresh cache every 5 minutes
CACHE_FILE = 'data/api_cache.json'  # Persistent cache file
_data_cache = None
_cache_timestamp = None
_cache_lock = threading.Lock()
_refresh_in_progress = False

# Secure password storage (hashed, loaded from env)
USERS = {
    'superadmin': generate_password_hash(os.environ['SUPERADMIN_PASSWORD']),
    'admin': generate_password_hash(os.environ['ADMIN_PASSWORD']),
    'user': generate_password_hash(os.environ['USER_PASSWORD']),
}
USER_ROLES = {'superadmin': 'superadmin', 'admin': 'admin', 'user': 'user'}
# Access model:
#   superadmin -> Dashboard + FY Analytics + Settings
#   admin      -> FY Analytics + Settings (no Dashboard)
#   user       -> FY Analytics only

# Login rate limiting: max 10 attempts per 60 seconds per IP
_login_attempts: dict = {}
_login_attempts_lock = threading.Lock()
_LOGIN_MAX = 10
_LOGIN_WINDOW = 60  # seconds


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    with _login_attempts_lock:
        attempts = _login_attempts.get(ip, [])
        attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
        _login_attempts[ip] = attempts
        if len(attempts) >= _LOGIN_MAX:
            return True
        attempts.append(now)
        _login_attempts[ip] = attempts
        return False


# Per-username soft lockout: N consecutive failures → temporary cooldown
_failed_logins: dict = {}  # username -> {'count': int, 'locked_until': float}
_failed_logins_lock = threading.Lock()
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_SECONDS = 15 * 60  # 15-minute cooldown


def _is_locked_out(username: str) -> bool:
    if not username:
        return False
    with _failed_logins_lock:
        rec = _failed_logins.get(username)
        if not rec:
            return False
        if rec.get('locked_until', 0) > time.time():
            return True
        if rec.get('locked_until', 0):  # cooldown expired → clear
            _failed_logins.pop(username, None)
        return False


def _record_failed_login(username: str):
    if not username:
        return
    with _failed_logins_lock:
        rec = _failed_logins.setdefault(username, {'count': 0, 'locked_until': 0})
        rec['count'] += 1
        if rec['count'] >= _LOCKOUT_THRESHOLD:
            rec['locked_until'] = time.time() + _LOCKOUT_SECONDS
            rec['count'] = 0


def _reset_failed_login(username: str):
    with _failed_logins_lock:
        _failed_logins.pop(username, None)


def _is_valid_excel(file_bytes: bytes) -> bool:
    """Verify file content is a real Excel workbook by magic bytes,
    not just the filename extension. .xlsx = ZIP (PK..); .xls = OLE2."""
    return (
        file_bytes[:4] == b'PK\x03\x04'
        or file_bytes[:8] == b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'
    )


# CSRF helpers
def _get_csrf_token() -> str:
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


@app.context_processor
def inject_csrf_token():
    return {'csrf_token': _get_csrf_token()}


def csrf_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
        if not token or token != session.get('csrf_token'):
            return jsonify({'error': 'CSRF validation failed'}), 403
        return f(*args, **kwargs)
    return decorated


def json_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 415
        return f(*args, **kwargs)
    return decorated


# Security headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self';"
    )
    return response


# Session idle timeout (30 minutes of inactivity clears session)
@app.before_request
def check_session_idle():
    if 'logged_in' in session:
        last_active = session.get('_last_active')
        if last_active:
            idle_seconds = (datetime.now() - datetime.fromisoformat(last_active)).total_seconds()
            if idle_seconds > 1800:
                session.clear()
                return redirect(url_for('login'))
        session['_last_active'] = datetime.now().isoformat()


# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# Admin required decorator (admin and superadmin)
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        if session.get('role') not in ('admin', 'superadmin'):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


# Superadmin required decorator (dashboard APIs)
def superadmin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'superadmin':
            return jsonify({'error': 'Superadmin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# Helper functions for data persistence
def load_json_file(filename, default=None):
    """Load data from JSON file"""
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading {filename}: {e}")
    return default if default is not None else {}

def save_json_file(filename, data):
    """Save data to JSON file"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving {filename}: {e}")
        return False

# Data files
USERS_FILE = 'data/users.json'
ASSIGNMENTS_FILE = 'data/course_assignments.json'

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

def sync_users_from_api():
    """Sync users from API response with local users file (no duplicates)"""
    try:
        # Load API data
        data = load_data()
        
        # Extract unique user emails from API
        api_users = {}
        for record in data:
            email = record.get('User_Mail_ID', '').strip()
            name = record.get('Participant_Name', '').strip()
            if email and email not in api_users:
                api_users[email] = name
        
        # Load existing local users
        users_data = load_json_file(USERS_FILE, {'users': []})
        existing_users = users_data.get('users', [])
        
        # Create set of existing emails for quick lookup
        existing_emails = {user['email'] for user in existing_users}
        
        # Add new users from API that don't exist locally
        new_users_added = 0
        for email, name in api_users.items():
            if email not in existing_emails:
                existing_users.append({
                    'email': email,
                    'name': name,
                    'source': 'api',
                    'added_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                new_users_added += 1
        
        # Save updated users list
        if new_users_added > 0:
            users_data['users'] = existing_users
            save_json_file(USERS_FILE, users_data)
            print(f"Synced {new_users_added} new users from API")
        
        return new_users_added
    except Exception as e:
        print(f"Error syncing users from API: {e}")
        return 0

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        ip = request.remote_addr
        if _is_rate_limited(ip):
            logger.warning(f"Rate limit exceeded for login from {ip}")
            return render_template('login.html', error='Too many login attempts. Please wait a moment.'), 429

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if _is_locked_out(username):
            logger.warning(f"Login blocked: account '{username}' temporarily locked (from {ip})")
            return render_template('login.html', error='Account temporarily locked due to repeated failed attempts. Try again later.'), 429

        if username in USERS and check_password_hash(USERS[username], password):
            _reset_failed_login(username)
            session.clear()
            session.permanent = True
            session['logged_in'] = True
            session['username'] = username
            session['role'] = USER_ROLES.get(username, 'user')
            session['_last_active'] = datetime.now().isoformat()
            # Superadmin lands on the Dashboard; admin/user land on FY Analytics
            if session['role'] == 'superadmin':
                return redirect(url_for('index'))
            return redirect(url_for('assignments_dashboard'))
        else:
            _record_failed_login(username)
            logger.warning(f"Failed login attempt for user '{username}' from {ip}")
            return render_template('login.html', error='Invalid username or password')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/settings')
@login_required
def settings():
    # Settings page is for admin and superadmin; others go to FY Analytics
    if session.get('role') not in ('admin', 'superadmin'):
        return redirect(url_for('assignments_dashboard'))
    return render_template('settings.html', username=session.get('username'),
                           role=session.get('role'))

# API endpoints for settings
@app.route('/api/settings/users', methods=['GET'])
@admin_required
def get_users():
    """Get all users (synced with API data)"""
    # Sync users from API first
    sync_users_from_api()
    
    # Return all users
    users_data = load_json_file(USERS_FILE, {'users': []})
    return jsonify(users_data.get('users', []))

@app.route('/api/settings/users', methods=['POST'])
@admin_required
@csrf_required
@json_required
def add_user():
    """Add a new user"""
    data = request.get_json()
    email = data.get('email')
    
    if not email:
        return jsonify({'error': 'Email is required'}), 400
    
    users_data = load_json_file(USERS_FILE, {'users': []})
    users = users_data.get('users', [])
    
    # Check if user already exists (case-insensitive)
    email_lower = email.lower()
    if any(u['email'].lower() == email_lower for u in users):
        return jsonify({'error': f'User with email {email} already exists'}), 409
    
    # Add new user
    users.append({
        'email': email,
        'name': '',
        'source': 'manual',
        'added_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    
    users_data['users'] = users
    if save_json_file(USERS_FILE, users_data):
        return jsonify({'message': 'User added successfully', 'user': users[-1]})
    else:
        return jsonify({'error': 'Failed to save user'}), 500

@app.route('/api/settings/users/bulk-upload', methods=['POST'])
@admin_required
@csrf_required
def bulk_upload_users():
    """Bulk upload users from Excel file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'Invalid file format. Please upload an Excel file (.xlsx or .xls)'}), 400

    file_bytes = file.read()
    if not _is_valid_excel(file_bytes):
        return jsonify({'error': 'Invalid file content. File is not a valid Excel workbook.'}), 400

    try:
        # Read Excel file
        workbook = openpyxl.load_workbook(BytesIO(file_bytes))
        sheet = workbook.active

        # Email validation regex
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

        valid_emails = []
        invalid_emails = []

        # Parse rows for emails (check first column)
        for row in sheet.iter_rows(min_row=1, values_only=True):
            if row[0]:  # If first cell has value
                email = str(row[0]).strip()
                if email_pattern.match(email):
                    valid_emails.append(email)
                else:
                    invalid_emails.append(email)

        if not valid_emails:
            return jsonify({
                'error': 'No valid email addresses found in file',
                'invalid_emails': invalid_emails
            }), 400
        
        # Load existing users
        users_data = load_json_file(USERS_FILE, {'users': []})
        users = users_data.get('users', [])
        existing_emails = {u['email'].lower() for u in users}
        
        # Add new users (ignore duplicates)
        added_users = []
        duplicate_users = []
        
        for email in valid_emails:
            email_lower = email.lower()
            if email_lower not in existing_emails:
                new_user = {
                    'email': email,
                    'name': '',
                    'source': 'manual',
                    'added_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                users.append(new_user)
                added_users.append(email)
                existing_emails.add(email_lower)
            else:
                duplicate_users.append(email)
        
        # Save updated users
        users_data['users'] = users
        if save_json_file(USERS_FILE, users_data):
            return jsonify({
                'message': f'Successfully processed {len(valid_emails)} email(s)',
                'added_count': len(added_users),
                'added_users': added_users,
                'duplicate_count': len(duplicate_users),
                'duplicate_users': duplicate_users,
                'invalid_count': len(invalid_emails),
                'invalid_emails': invalid_emails
            })
        else:
            return jsonify({'error': 'Failed to save users'}), 500
            
    except Exception as e:
        logger.error(f"Error processing Excel file (users): {e}")
        return jsonify({'error': 'Failed to process file'}), 500

@app.route('/api/settings/users/<email>', methods=['DELETE'])
@admin_required
@csrf_required
def delete_user(email):
    """Delete a user"""
    users_data = load_json_file(USERS_FILE, {'users': []})
    users = users_data.get('users', [])
    
    # Remove user
    users = [u for u in users if u['email'] != email]
    users_data['users'] = users
    
    if save_json_file(USERS_FILE, users_data):
        return jsonify({'message': 'User deleted successfully'})
    else:
        return jsonify({'error': 'Failed to delete user'}), 500

@app.route('/api/settings/courses', methods=['GET'])
@admin_required
def get_available_courses():
    """Get list of available courses from the data"""
    try:
        data = load_data()
        # Get unique course names
        courses = list(set(record.get('Activity_Name', record.get('Course_Name', '')) for record in data))
        courses = [c for c in courses if c]  # Remove empty strings
        courses.sort()
        return jsonify({'courses': courses})
    except Exception as e:
        logger.error(f"Error loading courses: {e}")
        return jsonify({'error': 'Failed to load courses'}), 500

# ── Email Job Tracking ────────────────────────────────────────────────────────
# Each job: {total, sent, failed, status: 'running'|'completed'}
_email_jobs: dict = {}
_email_jobs_lock = threading.Lock()

_EMAIL_WORKERS = 8   # parallel SMTP connections per job
_JOB_TTL = 600       # seconds before a completed job is cleaned up


def _create_job(total: int) -> str:
    job_id = str(uuid.uuid4())
    with _email_jobs_lock:
        _email_jobs[job_id] = {'total': total, 'sent': 0, 'failed': 0, 'status': 'running'}
    return job_id


def _mark_job_done(job_id: str):
    with _email_jobs_lock:
        if job_id in _email_jobs:
            _email_jobs[job_id]['status'] = 'completed'
    def _cleanup():
        time.sleep(_JOB_TTL)
        with _email_jobs_lock:
            _email_jobs.pop(job_id, None)
    threading.Thread(target=_cleanup, daemon=True).start()


def _run_email_job(job_id, emails, send_fn):
    """Execute a list of (email, name, ...) send calls in parallel and track progress."""
    def _one(task):
        try:
            return send_fn(task)
        except Exception as e:
            logger.error(f"Email job {job_id}: error: {e}")
            return False

    with ThreadPoolExecutor(max_workers=_EMAIL_WORKERS) as pool:
        futures = {pool.submit(_one, task): task for task in emails}
        for future in as_completed(futures):
            ok = future.result()
            with _email_jobs_lock:
                if job_id in _email_jobs:
                    if ok:
                        _email_jobs[job_id]['sent'] += 1
                    else:
                        _email_jobs[job_id]['failed'] += 1
    _mark_job_done(job_id)


def _dispatch_assignment_emails(emails, course_name, deadline, email_to_name) -> str:
    """Start a background job to send assignment notification emails. Returns job_id."""
    tasks = [(email, email_to_name.get(email, email.split('@')[0])) for email in emails]
    job_id = _create_job(len(tasks))

    def _send(task):
        user_email, user_name = task
        return send_course_assignment_email(user_email, user_name, course_name, deadline)

    t = threading.Thread(target=_run_email_job, args=(job_id, tasks, _send), daemon=True)
    t.start()
    return job_id


def _dispatch_removal_emails(emails, course_name, email_to_name) -> str:
    """Start a background job to send removal notification emails. Returns job_id."""
    tasks = [(email, email_to_name.get(email, email.split('@')[0])) for email in emails]
    job_id = _create_job(len(tasks))

    def _send(task):
        user_email, user_name = task
        return send_course_removal_email(user_email, user_name, course_name)

    t = threading.Thread(target=_run_email_job, args=(job_id, tasks, _send), daemon=True)
    t.start()
    return job_id


@app.route('/api/email-job/<job_id>', methods=['GET'])
@admin_required
def get_email_job_status(job_id):
    """Return current progress of an email dispatch job."""
    with _email_jobs_lock:
        job = _email_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found or already expired'}), 404
    return jsonify(job)


@app.route('/api/settings/assignments', methods=['GET'])
@admin_required
def get_assignments():
    """Get all course assignments"""
    assignments = load_json_file(ASSIGNMENTS_FILE, {'assignments': []})
    return jsonify(assignments.get('assignments', []))

@app.route('/api/settings/assignments', methods=['POST'])
@admin_required
@csrf_required
@json_required
def create_assignment():
    """Create a new course assignment"""
    data = request.get_json()
    course_name = data.get('course_name')
    user_emails = data.get('user_emails', [])[:500]
    deadline = data.get('deadline')
    notify_email = data.get('notify_email', False)

    if not course_name or not user_emails or not deadline:
        return jsonify({'error': 'Course name, users, and deadline are required'}), 400

    assignments_data = load_json_file(ASSIGNMENTS_FILE, {'assignments': []})
    assignments = assignments_data.get('assignments', [])

    # Create new assignment
    assignment = {
        'id': len(assignments) + 1,
        'course_name': course_name,
        'user_emails': user_emails,
        'deadline': deadline,
        'created_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'created_by': session.get('username')
    }
    assignment['title'] = aa.assignment_title(assignment)

    assignments.append(assignment)
    assignments_data['assignments'] = assignments

    if not save_json_file(ASSIGNMENTS_FILE, assignments_data):
        return jsonify({'error': 'Failed to save assignment'}), 500

    # Dispatch email notifications in background if requested
    email_job_id = None
    if notify_email:
        users_data = load_json_file(USERS_FILE, {'users': []})
        email_to_name = {u['email']: u['name'] for u in users_data.get('users', [])}
        email_job_id = _dispatch_assignment_emails(user_emails, course_name, deadline, email_to_name)

    return jsonify({
        'message': 'Assignment created successfully',
        'assignment': assignment,
        'notify_email': notify_email,
        'email_job_id': email_job_id,
        'email_total': len(user_emails) if notify_email else 0
    }), 201

@app.route('/api/settings/assignments/<int:assignment_id>', methods=['GET'])
@admin_required
def get_assignment_details(assignment_id):
    """Get detailed assignment statistics with course data"""
    try:
        # Load assignment
        assignments_data = load_json_file(ASSIGNMENTS_FILE, {'assignments': []})
        assignment = next((a for a in assignments_data.get('assignments', []) if a.get('id') == assignment_id), None)
        
        if not assignment:
            return jsonify({'error': 'Assignment not found'}), 404
        
        # Load API data
        api_data = load_data()
        course_name = assignment['course_name']

        # Get all users from API for this course (Course View)
        course_records = [r for r in api_data if r.get('Activity_Name', r.get('Course_Name')) == course_name]
        
        # Course View: All users in API for this course
        course_users = {}
        for record in course_records:
            email = record.get('User_Mail_ID', '')
            if email and email not in course_users:
                course_users[email] = {
                    'email': email,
                    'name': record.get('Participant_Name', ''),
                    'completion_percentage': record.get('Course_Completion_Percentage', '0'),
                    'completion_status': record.get('Course_Completion_Status', ''),
                    'activity_status': record.get('Activity_Status', ''),
                    'completion_date': record.get('Course_Completion_Date_(YYYY-MM-DD)', '').strip()
                }
        
        # Assignment View: staleness-aware. A completion counts only if it is dated
        # on/after the assignment was created; completions that predate the assignment
        # are "stale" (the user must complete it again) and do NOT count as done.
        # Uses the same engine as the FY dashboard so both views agree.
        api_index = aa.build_api_index(api_data)
        prog = aa.compute_assignment_progress(assignment, api_index)
        status_display = {'completed': 'Completed', 'in_progress': 'Current',
                          'stale': 'Stale', 'not_started': 'Not Started'}
        assignment_users = []
        for u in prog['users']:
            assignment_users.append({
                'email': u['email'],
                'name': u['name'],
                # a stale completion contributes 0% toward this assignment
                'completion_percentage': '0' if u['stale'] else str(u['percentage']),
                'completion_status': status_display[u['status']],
                'activity_status': '',
                'completion_date': u['completion_date'],
                'untouched': u['untouched'],
                'stale': u['stale'],
            })

        # Course View stats (course-wide, raw API — no assignment-date staleness)
        course_completed = sum(1 for u in course_users.values() if u['completion_status'] == 'Completed')
        course_in_progress = sum(1 for u in course_users.values() if u['completion_status'] == 'Current')
        course_not_started = len(course_users) - course_completed - course_in_progress
        course_completion_rate = (course_completed / len(course_users) * 100) if len(course_users) > 0 else 0

        return jsonify({
            'assignment': assignment,
            'course_view': {
                'total_users': len(course_users),
                'completed': course_completed,
                'in_progress': course_in_progress,
                'not_started': course_not_started,
                'stale': 0,
                'completion_rate': round(course_completion_rate, 2),
                'users': list(course_users.values())
            },
            'assignment_view': {
                'total_users': prog['total'],
                'completed': prog['completed'],
                'in_progress': prog['in_progress'],
                'not_started': prog['not_started'],
                'stale': prog['stale'],
                'completion_rate': prog['completion_rate'],
                'users': assignment_users
            }
        })
    except Exception as e:
        logger.error(f"Error getting assignment details: {e}")
        return jsonify({'error': 'Failed to load assignment details'}), 500

@app.route('/api/settings/assignments/<int:assignment_id>/remind', methods=['POST'])
@admin_required
@csrf_required
def send_assignment_reminders(assignment_id):
    """Send reminder emails to incomplete users"""
    try:
        from datetime import datetime, timedelta
        from email_service import send_deadline_reminder_email
        
        # Load assignment
        assignments_data = load_json_file(ASSIGNMENTS_FILE, {'assignments': []})
        assignment = next((a for a in assignments_data.get('assignments', []) if a.get('id') == assignment_id), None)
        
        if not assignment:
            return jsonify({'error': 'Assignment not found'}), 404
        
        # Load API data to check completion status
        api_data = load_data()
        course_name = assignment['course_name']
        assigned_users = assignment['user_emails']
        deadline = assignment['deadline']
        
        # Calculate days remaining
        try:
            deadline_date = datetime.strptime(deadline, '%Y-%m-%d')
            today = datetime.now()
            days_remaining = (deadline_date - today).days
        except:
            days_remaining = 0
        
        # Only VALID completions (dated on/after the assignment) are skipped.
        # A stale completion means the user must redo the course, so they still
        # get a reminder — same staleness rule as the dashboards.
        _prog = aa.compute_assignment_progress(assignment, aa.build_api_index(api_data))
        completed_users = {u['email'] for u in _prog['users'] if u['status'] == 'completed'}
        
        # Get users data for names
        users_data = load_json_file(USERS_FILE, {'users': []})
        email_to_name = {user['email']: user['name'] for user in users_data.get('users', [])}
        
        # Send reminders to incomplete users only
        results = {'success': 0, 'failed': 0, 'skipped': 0, 'failed_emails': []}
        
        for user_email in assigned_users:
            if user_email in completed_users:
                results['skipped'] += 1
                continue
            
            user_name = email_to_name.get(user_email, user_email.split('@')[0])
            
            try:
                success = send_deadline_reminder_email(
                    user_email=user_email,
                    user_name=user_name,
                    course_name=course_name,
                    deadline=deadline,
                    days_remaining=days_remaining
                )
                
                if success:
                    results['success'] += 1
                    logger.info(f"Reminder sent to {user_email}")
                else:
                    results['failed'] += 1
                    results['failed_emails'].append(user_email)
                    logger.warning(f"Failed to send reminder to {user_email}")
            except Exception as e:
                results['failed'] += 1
                results['failed_emails'].append(user_email)
                logger.error(f"Error sending reminder to {user_email}: {e}")
        
        return jsonify({
            'message': 'Reminders sent',
            'reminders_sent': results['success'],
            'reminders_failed': results['failed'],
            'already_completed': results['skipped'],
            'failed_emails': results['failed_emails']
        })
    except Exception as e:
        logger.error(f"Error sending reminders: {e}")
        return jsonify({'error': 'Failed to send reminders'}), 500

@app.route('/api/settings/assignments/<int:assignment_id>', methods=['PUT'])
@admin_required
@csrf_required
@json_required
def update_assignment(assignment_id):
    """Update assignment (add/remove users)"""
    try:
        from email_service import send_course_assignment_email, send_course_removal_email
        
        data = request.get_json()
        new_user_emails = data.get('user_emails', [])[:500]
        notify_email = data.get('notify_email', False)

        # Load assignment
        assignments_data = load_json_file(ASSIGNMENTS_FILE, {'assignments': []})
        assignments = assignments_data.get('assignments', [])
        assignment = next((a for a in assignments if a.get('id') == assignment_id), None)

        if not assignment:
            return jsonify({'error': 'Assignment not found'}), 404

        old_user_emails = set(assignment['user_emails'])
        new_user_emails_set = set(new_user_emails)

        # Find added and removed users
        added_users = new_user_emails_set - old_user_emails
        removed_users = old_user_emails - new_user_emails_set

        # Update assignment
        assignment['user_emails'] = new_user_emails
        assignment['last_modified'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Save first so response is immediate
        if not save_json_file(ASSIGNMENTS_FILE, assignments_data):
            return jsonify({'error': 'Failed to save assignment'}), 500

        # Dispatch email notifications in background if requested
        email_job_id = None
        email_total = 0
        if notify_email:
            users_data = load_json_file(USERS_FILE, {'users': []})
            email_to_name = {u['email']: u['name'] for u in users_data.get('users', [])}
            recipients = list(added_users) + list(removed_users)
            email_total = len(recipients)
            if added_users:
                email_job_id = _dispatch_assignment_emails(
                    list(added_users), assignment['course_name'], assignment['deadline'], email_to_name)
            if removed_users:
                _dispatch_removal_emails(list(removed_users), assignment['course_name'], email_to_name)

        return jsonify({
            'message': 'Assignment updated successfully',
            'assignment': assignment,
            'users_added': len(added_users),
            'users_removed': len(removed_users),
            'notify_email': notify_email,
            'email_job_id': email_job_id,
            'email_total': email_total
        })
    except Exception as e:
        logger.error(f"Error updating assignment: {e}")
        return jsonify({'error': 'Failed to update assignment'}), 500

@app.route('/api/settings/assignments/<int:assignment_id>', methods=['DELETE'])
@admin_required
@csrf_required
def delete_assignment(assignment_id):
    """Delete a course assignment"""
    assignments_data = load_json_file(ASSIGNMENTS_FILE, {'assignments': []})
    assignments = assignments_data.get('assignments', [])
    
    # Remove assignment
    assignments = [a for a in assignments if a.get('id') != assignment_id]
    assignments_data['assignments'] = assignments
    
    if save_json_file(ASSIGNMENTS_FILE, assignments_data):
        return jsonify({'message': 'Assignment deleted successfully'})
    else:
        return jsonify({'error': 'Failed to delete assignment'}), 500

@app.route('/api/settings/assignments/bulk-upload', methods=['POST'])
@admin_required
@csrf_required
def bulk_upload_assignment():
    """Bulk upload users for course assignment from Excel file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    course_name = request.form.get('course_name')
    deadline = request.form.get('deadline')
    notify_email = request.form.get('notify_email', 'false').lower() == 'true'

    if not course_name or not deadline:
        return jsonify({'error': 'Course name and deadline are required'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'Invalid file format. Please upload an Excel file (.xlsx or .xls)'}), 400

    file_bytes = file.read()
    if not _is_valid_excel(file_bytes):
        return jsonify({'error': 'Invalid file content. File is not a valid Excel workbook.'}), 400

    try:
        # Read Excel file
        workbook = openpyxl.load_workbook(BytesIO(file_bytes))
        sheet = workbook.active

        # Email validation regex
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

        valid_emails = []
        invalid_emails = []

        # Parse rows for emails (check first column)
        for row in sheet.iter_rows(min_row=1, values_only=True):
            if row[0]:  # If first cell has value
                email = str(row[0]).strip()
                if email_pattern.match(email):
                    valid_emails.append(email)
                else:
                    invalid_emails.append(email)

        if not valid_emails:
            return jsonify({
                'error': 'No valid email addresses found in file',
                'invalid_emails': invalid_emails
            }), 400
        
        # Load existing users
        users_data = load_json_file(USERS_FILE, {'users': []})
        users = users_data.get('users', [])
        existing_emails = {u['email'].lower() for u in users}
        
        # Add new users if they don't exist
        new_users_added = []
        for email in valid_emails:
            email_lower = email.lower()
            if email_lower not in existing_emails:
                new_user = {
                    'email': email,
                    'name': '',
                    'source': 'manual',
                    'added_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                users.append(new_user)
                new_users_added.append(email)
                existing_emails.add(email_lower)
        
        # Save updated users if any new users were added
        if new_users_added:
            users_data['users'] = users
            save_json_file(USERS_FILE, users_data)
        
        # Create assignment with all valid emails
        assignments_data = load_json_file(ASSIGNMENTS_FILE, {'assignments': []})
        assignments = assignments_data.get('assignments', [])
        
        assignment = {
            'id': len(assignments) + 1,
            'course_name': course_name,
            'user_emails': valid_emails,
            'deadline': deadline,
            'created_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'created_by': session.get('username')
        }
        assignment['title'] = aa.assignment_title(assignment)

        assignments.append(assignment)
        assignments_data['assignments'] = assignments
        
        if not save_json_file(ASSIGNMENTS_FILE, assignments_data):
            return jsonify({'error': 'Failed to save assignment'}), 500

        # Dispatch email notifications in background if requested
        email_job_id = None
        if notify_email:
            email_to_name = {u['email']: u['name'] for u in users}
            email_job_id = _dispatch_assignment_emails(valid_emails, course_name, deadline, email_to_name)

        return jsonify({
            'message': 'Assignment created successfully',
            'assignment': assignment,
            'users_assigned': len(valid_emails),
            'new_users_added': len(new_users_added),
            'new_users_list': new_users_added,
            'invalid_count': len(invalid_emails),
            'invalid_emails': invalid_emails,
            'notify_email': notify_email,
            'email_job_id': email_job_id,
            'email_total': len(valid_emails) if notify_email else 0
        }), 201
            
    except Exception as e:
        logger.error(f"Error processing Excel file (assignments): {e}")
        return jsonify({'error': 'Failed to process file'}), 500

@app.route('/')
@login_required
def index():
    # Dashboard is superadmin-only; everyone else lands on FY Analytics
    if session.get('role') != 'superadmin':
        return redirect(url_for('assignments_dashboard'))
    return render_template('index.html', username=session.get('username'),
                           role=session.get('role'))

# Available to all logged-in users: the FY Analytics page shows cache
# freshness and offers the refresh button to every role.
@app.route('/api/status')
@login_required
def get_status():
    """Get system status including cache information"""
    cache_info = {
        'cached': _data_cache is not None,
        'cache_timestamp': None,
        'cache_age_seconds': None,
        'cache_age_readable': None,
        'refresh_in_progress': _refresh_in_progress
    }
    
    if _cache_timestamp is not None:
        now = datetime.now()
        cache_age = now - _cache_timestamp
        cache_age_seconds = int(cache_age.total_seconds())
        
        # Calculate readable age
        days = cache_age.days
        hours = cache_age.seconds // 3600
        minutes = (cache_age.seconds % 3600) // 60
        
        age_parts = []
        if days > 0:
            age_parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours > 0:
            age_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0 or len(age_parts) == 0:
            age_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        
        cache_info['cache_timestamp'] = _cache_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        cache_info['cache_age_seconds'] = cache_age_seconds
        cache_info['cache_age_readable'] = ' '.join(age_parts)
        cache_info['cached_at_formatted'] = _cache_timestamp.strftime('%d %B %Y at %I:%M %p')
    
    return jsonify({
        'using_local_data': USE_LOCAL_DATA,
        'data_source': 'Local JSON File' if USE_LOCAL_DATA else 'TCS iON API',
        'api_timeout_seconds': API_TIMEOUT,
        'auto_refresh_interval_minutes': AUTO_REFRESH_INTERVAL_MINUTES,
        'cache': cache_info
    })

@app.route('/api/refresh-cache', methods=['POST'])
@login_required
@csrf_required
def refresh_cache_endpoint():
    """Trigger manual cache refresh (non-blocking)"""
    global _refresh_in_progress
    
    if USE_LOCAL_DATA:
        return jsonify({'error': 'Cache refresh not available in local data mode'}), 400
    
    with _cache_lock:
        if _refresh_in_progress:
            return jsonify({
                'message': 'Cache refresh already in progress',
                'refresh_in_progress': True
            }), 202
    
    # Start refresh in background thread
    threading.Thread(target=refresh_cache_background, daemon=True).start()
    
    logger.info(f"Manual cache refresh triggered by {session.get('username')}")
    
    return jsonify({
        'message': 'Cache refresh started in background',
        'refresh_in_progress': True
    }), 202

def save_cache_to_file(data, timestamp):
    """Save cache data and timestamp to file"""
    try:
        cache_data = {
            'data': data,
            'timestamp': timestamp.isoformat(),
            'cached_at_readable': timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Cache saved to file: {CACHE_FILE}")
        return True
    except Exception as e:
        logger.error(f"Error saving cache to file: {e}")
        return False

def load_cache_from_file():
    """Load cache data and timestamp from file"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                timestamp = datetime.fromisoformat(cache_data['timestamp'])
                logger.info(f"Cache loaded from file (cached at: {cache_data['cached_at_readable']})")
                return cache_data['data'], timestamp
    except Exception as e:
        logger.error(f"Error loading cache from file: {e}")
    return None, None

def fetch_fresh_data_from_api():
    """Fetch fresh data from API (blocking call)"""
    logger.info("Fetching fresh data from API (this may take 3+ minutes)...")
    response = requests.get(API_URL, timeout=API_TIMEOUT)
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        # Body was empty or not JSON (e.g. an HTML login/error page returned
        # with a 200 status). Surface what we actually received so the real
        # problem (expired token, redirect, wrong URL) is diagnosable.
        body_preview = (response.text or '').strip()[:500]
        logger.error(
            "API did not return JSON. status=%s content-type=%s final_url=%s body[:500]=%r",
            response.status_code,
            response.headers.get('Content-Type'),
            response.url,
            body_preview,
        )
        raise
    logger.info(f"Successfully fetched {len(data)} records from API")
    return data

def refresh_cache_background():
    """Refresh cache in background (called by scheduler)"""
    global _data_cache, _cache_timestamp, _refresh_in_progress
    
    with _cache_lock:
        if _refresh_in_progress:
            logger.info("Cache refresh already in progress, skipping...")
            return
        _refresh_in_progress = True
    
    try:
        logger.info("Background cache refresh started...")
        data = fetch_fresh_data_from_api()
        now = datetime.now()
        
        with _cache_lock:
            _data_cache = data
            _cache_timestamp = now
            save_cache_to_file(data, now)
        
        logger.info(f"Background cache refresh completed at {now.strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        logger.error(f"Error in background cache refresh: {e}")
    finally:
        with _cache_lock:
            _refresh_in_progress = False

def cache_refresh_scheduler():
    """Background thread that refreshes cache every N minutes.
    The API fetch itself is dispatched into a separate thread so the sleep
    interval is never shifted by a slow API response.
    """
    logger.info(f"Cache refresh scheduler started (interval: {AUTO_REFRESH_INTERVAL_MINUTES} minutes)")

    while True:
        time.sleep(AUTO_REFRESH_INTERVAL_MINUTES * 60)
        if not USE_LOCAL_DATA:
            try:
                t = threading.Thread(target=refresh_cache_background, daemon=True)
                t.start()
            except Exception as e:
                logger.error(f"Error in cache scheduler: {e}")

def initialize_cache():
    """Initialize cache on server startup"""
    global _data_cache, _cache_timestamp
    
    logger.info("Initializing cache system...")
    
    if USE_LOCAL_DATA:
        logger.info("Using local data mode - cache system disabled")
        return
    
    # Try to load from file first
    data, timestamp = load_cache_from_file()
    
    if data and timestamp:
        with _cache_lock:
            _data_cache = data
            _cache_timestamp = timestamp
        
        # Check if cache is too old
        age_minutes = (datetime.now() - timestamp).total_seconds() / 60
        if age_minutes > AUTO_REFRESH_INTERVAL_MINUTES:
            logger.info(f"Cache is {age_minutes:.1f} minutes old, triggering refresh...")
            threading.Thread(target=refresh_cache_background, daemon=True).start()
        else:
            logger.info(f"Cache is {age_minutes:.1f} minutes old, still valid")
    else:
        logger.info("No valid cache found, fetching initial data...")
        threading.Thread(target=refresh_cache_background, daemon=True).start()
    
    # Start background scheduler
    scheduler_thread = threading.Thread(target=cache_refresh_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("Cache system initialized successfully")

def load_data():
    """Load data from cache (instant) or local file"""
    global _data_cache, _cache_timestamp
    
    if USE_LOCAL_DATA:
        # Load from local JSON file
        json_path = os.path.join(os.path.dirname(__file__), 'Response Sample.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        # Return cached data (should always be available after initialization)
        with _cache_lock:
            if _data_cache is None:
                # Fallback: try to load from file if cache not initialized
                data, timestamp = load_cache_from_file()
                if data:
                    _data_cache = data
                    _cache_timestamp = timestamp
                else:
                    # Last resort: fetch synchronously (will block)
                    logger.warning("No cache available, fetching synchronously...")
                    data = fetch_fresh_data_from_api()
                    now = datetime.now()
                    _data_cache = data
                    _cache_timestamp = now
                    save_cache_to_file(data, now)
            
            return _data_cache

@app.route('/api/data')
@superadmin_required
def get_data():
    try:
        data = load_data()
        return jsonify(data)
    except Exception:
        import traceback
        logger.error(f"Error in get_data: {traceback.format_exc()}")
        return jsonify({"error": "Failed to load data"}), 500

@app.route('/api/raw-data')
@superadmin_required
def get_raw_data():
    try:
        data = load_data()
        return jsonify({'data': data})
    except Exception as e:
        logger.error(f"Error loading raw data: {e}")
        return jsonify({'error': 'Failed to load data'}), 500

@app.route('/api/summary')
@superadmin_required
def get_summary():
    try:
        print(f"Loading data (USE_LOCAL_DATA={USE_LOCAL_DATA})")
        data = load_data()
        print(f"Data received: {len(data)} records")
        
        # Process data for summary
        courses = defaultdict(lambda: {
            'name': '',
            'users': set(),
            'completed': set(),
            'in_progress': set(),
            'not_started': set(),
            'completion_dates': []
        })
        
        users = defaultdict(lambda: {
            'name': '',
            'email': '',
            'courses': set(),
            'completed_courses': set()
        })
        
        for record in data:
            course_name = record.get('Activity_Name', record.get('Course_Name', ''))
            user_email = record.get('User_Mail_ID', '')
            user_name = record.get('Participant_Name', '')
            completion_status = record.get('Course_Completion_Status', '')
            completion_date = record.get('Course_Completion_Date_(YYYY-MM-DD)', '').strip()
            
            # Course aggregation
            courses[course_name]['name'] = course_name
            courses[course_name]['users'].add(user_email)
            
            if completion_status == 'Completed':
                courses[course_name]['completed'].add(user_email)
                if completion_date:
                    courses[course_name]['completion_dates'].append(completion_date)
            elif completion_status == 'Current':
                activity_status = record.get('Activity_Status', '')
                if activity_status == 'Not Attempted':
                    courses[course_name]['not_started'].add(user_email)
                else:
                    courses[course_name]['in_progress'].add(user_email)
            
            # User aggregation
            users[user_email]['name'] = user_name
            users[user_email]['email'] = user_email
            users[user_email]['courses'].add(course_name)
            if completion_status == 'Completed':
                users[user_email]['completed_courses'].add(course_name)
        
        # Convert to list format
        course_list = []
        for course_name, course_data in courses.items():
            total_users = len(course_data['users'])
            completed = len(course_data['completed'])
            in_progress = len(course_data['in_progress'])
            not_started = len(course_data['not_started'])
            completion_rate = (completed / total_users * 100) if total_users > 0 else 0
            
            # Get earliest date
            earliest_date = None
            if course_data['completion_dates']:
                dates = [d for d in course_data['completion_dates'] if d]
                if dates:
                    earliest_date = min(dates)
            
            course_list.append({
                'course_name': course_name,
                'total_users': total_users,
                'completed': completed,
                'in_progress': in_progress,
                'not_started': not_started,
                'completion_rate': round(completion_rate, 2),
                'earliest_date': earliest_date
            })
        
        # Sort by total users descending
        course_list.sort(key=lambda x: x['total_users'], reverse=True)
        
        # User list
        user_list = []
        for user_email, user_data in users.items():
            total_courses = len(user_data['courses'])
            completed_courses = len(user_data['completed_courses'])
            completion_rate = (completed_courses / total_courses * 100) if total_courses > 0 else 0
            
            user_list.append({
                'user_name': user_data['name'],
                'user_email': user_email,
                'total_courses': total_courses,
                'completed_courses': completed_courses,
                'in_progress': total_courses - completed_courses,
                'completion_rate': round(completion_rate, 2)
            })
        
        # Sort by total courses descending
        user_list.sort(key=lambda x: x['total_courses'], reverse=True)
        
        # Calculate KPIs
        total_courses = len(courses)
        total_users = len(users)
        total_enrollments = sum(c['total_users'] for c in course_list)
        total_completions = sum(c['completed'] for c in course_list)
        overall_completion_rate = (total_completions / total_enrollments * 100) if total_enrollments > 0 else 0
        
        return jsonify({
            'kpis': {
                'total_courses': total_courses,
                'total_users': total_users,
                'total_enrollments': total_enrollments,
                'overall_completion_rate': round(overall_completion_rate, 2)
            },
            'courses': course_list,
            'users': user_list
        })
    except Exception:
        import traceback
        logger.error(f"Error in get_summary: {traceback.format_exc()}")
        return jsonify({"error": "Failed to load summary"}), 500

@app.route('/api/course/<path:course_name>')
@superadmin_required
def get_course_details(course_name):
    try:
        data = load_data()
        
        # Filter records for this course (using Activity_Name)
        course_records = [r for r in data if r.get('Activity_Name', r.get('Course_Name')) == course_name]
        
        # Group by user
        user_progress = {}
        for record in course_records:
            user_email = record.get('User_Mail_ID', '')
            if user_email not in user_progress:
                user_progress[user_email] = {
                    'user_name': record.get('Participant_Name', ''),
                    'user_email': user_email,
                    'completion_percentage': record.get('Course_Completion_Percentage', '0'),
                    'completion_status': record.get('Course_Completion_Status', ''),
                    'activity_status': record.get('Activity_Status', ''),
                    'completion_date': record.get('Course_Completion_Date_(YYYY-MM-DD)', '').strip()
                }
        
        return jsonify({
            'course_name': course_name,
            'users': list(user_progress.values())
        })
    except Exception:
        import traceback
        logger.error(f"Error in get_course_details: {traceback.format_exc()}")
        return jsonify({"error": "Failed to load course details"}), 500

@app.route('/api/user/<path:user_email>')
@superadmin_required
def get_user_details(user_email):
    try:
        data = load_data()
        
        # Filter records for this user
        user_records = [r for r in data if r.get('User_Mail_ID') == user_email]
        
        # Group by course
        course_progress = {}
        user_name = ''
        for record in user_records:
            course_name = record.get('Activity_Name', record.get('Course_Name', ''))
            user_name = record.get('Participant_Name', '')
            completion_date = record.get('Course_Completion_Date_(YYYY-MM-DD)', '').strip()
            
            if course_name not in course_progress:
                course_progress[course_name] = {
                    'course_name': course_name,
                    'completion_percentage': record.get('Course_Completion_Percentage', '0'),
                    'completion_status': record.get('Course_Completion_Status', ''),
                    'activity_status': record.get('Activity_Status', ''),
                    'completion_date': completion_date
                }
        
        # Sort by completion date
        courses_list = list(course_progress.values())
        courses_list.sort(key=lambda x: x['completion_date'] if x['completion_date'] else '9999-99-99')
        
        return jsonify({
            'user_name': user_name,
            'user_email': user_email,
            'courses': courses_list
        })
    except Exception:
        import traceback
        logger.error(f"Error in get_user_details: {traceback.format_exc()}")
        return jsonify({"error": "Failed to load user details"}), 500

# ── FY / Assignment Analytics dashboard ─────────────────────────────────────
# A second dashboard that analyses progress by *assignment* and *financial year*
# (see assignment_analytics.py). Unlike /api/summary (raw API), completion % here
# is measured against everyone assigned, and completions predating the assignment
# are treated as stale. Read-only analytics — open to any logged-in user.

def _load_assignments():
    return load_json_file(ASSIGNMENTS_FILE, {'assignments': []}).get('assignments', [])


@app.route('/assignments-dashboard')
@login_required
def assignments_dashboard():
    return render_template('assignments.html', username=session.get('username'),
                           role=session.get('role'))


@app.route('/api/assignments-summary')
@login_required
def api_assignments_summary():
    """Full FY dashboard payload for a scope (?fy=current|all|<start_year>)."""
    try:
        fy = request.args.get('fy', 'current')
        summary = aa.build_summary(_load_assignments(), load_data(), selected=fy)
        return jsonify(summary)
    except Exception:
        import traceback
        logger.error(f"Error in api_assignments_summary: {traceback.format_exc()}")
        return jsonify({'error': 'Failed to build assignments summary'}), 500


@app.route('/api/assignment-progress/<int:assignment_id>')
@login_required
def api_assignment_progress(assignment_id):
    """Per-user progress for one assignment (drill-down modal), with stale flags."""
    try:
        assignment = next((a for a in _load_assignments() if a.get('id') == assignment_id), None)
        if not assignment:
            return jsonify({'error': 'Assignment not found'}), 404
        index = aa.build_api_index(load_data())
        return jsonify(aa.compute_assignment_progress(assignment, index))
    except Exception:
        import traceback
        logger.error(f"Error in api_assignment_progress: {traceback.format_exc()}")
        return jsonify({'error': 'Failed to load assignment progress'}), 500


@app.route('/api/fy-user/<path:user_email>')
@login_required
def api_fy_user(user_email):
    """A single user's assignment-by-assignment breakdown within an FY scope."""
    try:
        fy = request.args.get('fy', 'current')
        assignments = _load_assignments()
        index = aa.build_api_index(load_data())
        resolved = aa.resolve_selected_fy(fy, assignments)

        rows = []
        user_name = ''
        for a in assignments:
            p = aa.compute_assignment_progress(a, index)
            if resolved != 'all' and p['fy_start_year'] != resolved:
                continue
            u = next((x for x in p['users'] if x['email'] == user_email), None)
            if not u:
                continue
            if u['name'] and not user_name:
                user_name = u['name']
            rows.append({
                'assignment_id': a.get('id'),
                'title': p['title'],
                'course_name': p['course_name'],
                'created_date': p['created_date'],
                'fy_label': p['fy_label'],
                'deadline': p['deadline'],
                'status': u['status'],
                'percentage': u['percentage'],
                'completion_date': u['completion_date'],
                'stale': u['stale'],
                'untouched': u['untouched'],
            })
        rows.sort(key=lambda r: r['created_date'], reverse=True)
        return jsonify({'user_email': user_email, 'user_name': user_name, 'assignments': rows})
    except Exception:
        import traceback
        logger.error(f"Error in api_fy_user: {traceback.format_exc()}")
        return jsonify({'error': 'Failed to load user assignment details'}), 500


# Initialize cache when the module is imported (covers both direct run and
# Waitress/any WSGI server that imports app without running __main__).
initialize_cache()

if __name__ == '__main__':
    # use_reloader=False is required: with the default reloader Flask spawns a
    # child subprocess for requests and a parent watcher process. The scheduler
    # would start twice — once in the parent watcher and once in the child.
    app.run(debug=True, port=5000, use_reloader=False)
