from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import requests
from collections import defaultdict
from datetime import datetime
import json
import os
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from email_service import send_course_assignment_email, send_deadline_reminder_email, send_course_removal_email
import openpyxl
from io import BytesIO
import threading
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-to-something-random-and-secure-12345'  # Change this!

API_URL = "https://www3.tcsion.com/iONBizServices/iONWebService?servicekey=WaJkcnPwTLXzm%2FQICFcn3w%3D%3D&s=4CnZ%2FgPXtzK8efa1RmpmLg%3D%3D&u=TIX8NflllNXow1Ic/ZoBmze/jwyVQjfsnDydzQqFPGDD79kH58CkQVDgHATBFfbr"
USE_LOCAL_DATA = False  # Set to False to use live API (URL confirmed working in test_api_connection.py)

# API timeout configuration (in seconds)
# The API typically takes 3+ minutes to respond, so set timeout accordingly
API_TIMEOUT = 200  # 200 seconds = 3 minutes 20 seconds

# Cache configuration
AUTO_REFRESH_INTERVAL_MINUTES = 5  # Auto-refresh cache every 15 minutes
CACHE_FILE = 'data/api_cache.json'  # Persistent cache file
_data_cache = None
_cache_timestamp = None
_cache_lock = threading.Lock()
_refresh_in_progress = False

# Secure password storage (hashed)
# To add users: generate_password_hash('your_password')
USERS = {
    'admin': generate_password_hash('admin123'),  # Change these credentials!
    'user': generate_password_hash('user123')     # Add more users as needed
}

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        if session.get('username') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
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
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username in USERS and check_password_hash(USERS[username], password):
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/settings')
@admin_required
def settings():
    return render_template('settings.html', username=session.get('username'))

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
def bulk_upload_users():
    """Bulk upload users from Excel file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'Invalid file format. Please upload an Excel file (.xlsx or .xls)'}), 400
    
    try:
        # Read Excel file
        workbook = openpyxl.load_workbook(BytesIO(file.read()))
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
        logger.error(f"Error processing Excel file: {str(e)}")
        return jsonify({'error': f'Error processing file: {str(e)}'}), 500

@app.route('/api/settings/users/<email>', methods=['DELETE'])
@admin_required
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
        return jsonify({'error': str(e)}), 500

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
def create_assignment():
    """Create a new course assignment"""
    data = request.get_json()
    course_name = data.get('course_name')
    user_emails = data.get('user_emails', [])
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
        assigned_users = assignment['user_emails']
        
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
        
        # Assignment View: Only assigned users
        assignment_users = []
        for email in assigned_users:
            if email in course_users:
                # User exists in API - has attempted course
                assignment_users.append(course_users[email])
            else:
                # User doesn't exist in API - hasn't touched course
                assignment_users.append({
                    'email': email,
                    'name': '',
                    'completion_percentage': '0',
                    'completion_status': 'Not Started',
                    'activity_status': 'Not Attempted',
                    'completion_date': '',
                    'untouched': True
                })
        
        # Calculate Course View stats
        course_completed = sum(1 for u in course_users.values() if u['completion_status'] == 'Completed')
        course_in_progress = sum(1 for u in course_users.values() if u['completion_status'] == 'Current')
        course_not_started = len(course_users) - course_completed - course_in_progress
        course_completion_rate = (course_completed / len(course_users) * 100) if len(course_users) > 0 else 0
        
        # Calculate Assignment View stats
        assignment_completed = sum(1 for u in assignment_users if u['completion_status'] == 'Completed')
        assignment_in_progress = sum(1 for u in assignment_users if u['completion_status'] == 'Current')
        assignment_not_started = sum(1 for u in assignment_users if u.get('untouched') or u['completion_status'] == 'Not Started')
        assignment_completion_rate = (assignment_completed / len(assigned_users) * 100) if len(assigned_users) > 0 else 0
        
        return jsonify({
            'assignment': assignment,
            'course_view': {
                'total_users': len(course_users),
                'completed': course_completed,
                'in_progress': course_in_progress,
                'not_started': course_not_started,
                'completion_rate': round(course_completion_rate, 2),
                'users': list(course_users.values())
            },
            'assignment_view': {
                'total_users': len(assigned_users),
                'completed': assignment_completed,
                'in_progress': assignment_in_progress,
                'not_started': assignment_not_started,
                'completion_rate': round(assignment_completion_rate, 2),
                'users': assignment_users
            }
        })
    except Exception as e:
        logger.error(f"Error getting assignment details: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/assignments/<int:assignment_id>/remind', methods=['POST'])
@admin_required
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
        
        # Get completed users from API
        course_records = [r for r in api_data if r.get('Activity_Name', r.get('Course_Name')) == course_name]
        completed_users = set()
        for record in course_records:
            email = record.get('User_Mail_ID', '')
            if record.get('Course_Completion_Status') == 'Completed':
                completed_users.add(email)
        
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
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/assignments/<int:assignment_id>', methods=['PUT'])
@admin_required
def update_assignment(assignment_id):
    """Update assignment (add/remove users)"""
    try:
        from email_service import send_course_assignment_email, send_course_removal_email
        
        data = request.get_json()
        new_user_emails = data.get('user_emails', [])
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
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/assignments/<int:assignment_id>', methods=['DELETE'])
@admin_required
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
    
    try:
        # Read Excel file
        workbook = openpyxl.load_workbook(BytesIO(file.read()))
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
        logger.error(f"Error processing Excel file: {str(e)}")
        return jsonify({'error': f'Error processing file: {str(e)}'}), 500

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=session.get('username'))

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
    data = response.json()
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
    """Background thread that refreshes cache every N minutes"""
    logger.info(f"Cache refresh scheduler started (interval: {AUTO_REFRESH_INTERVAL_MINUTES} minutes)")
    
    while True:
        try:
            time.sleep(AUTO_REFRESH_INTERVAL_MINUTES * 60)
            if not USE_LOCAL_DATA:
                refresh_cache_background()
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
@login_required
def get_data():
    try:
        data = load_data()
        return jsonify(data)
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in get_data: {error_details}")
        return jsonify({"error": str(e), "details": error_details}), 500

@app.route('/api/raw-data')
@login_required
def get_raw_data():
    """Return raw data for detailed analysis"""
    try:
        data = load_data()
        return jsonify({'data': data})
    except Exception as e:
        logger.error(f"Error loading raw data: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/summary')
@login_required
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
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in get_summary: {error_details}")
        return jsonify({"error": str(e), "details": error_details}), 500

@app.route('/api/course/<path:course_name>')
@login_required
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
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in get_course_details: {error_details}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/user/<path:user_email>')
@login_required
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
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in get_user_details: {error_details}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Initialize cache system on startup
    initialize_cache()
    app.run(debug=True, port=5000)
