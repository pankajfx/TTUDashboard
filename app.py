from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import requests
from collections import defaultdict
from datetime import datetime
import json
import os
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from email_service import send_course_assignment_email, send_deadline_reminder_email, send_course_removal_email

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-to-something-random-and-secure-12345'  # Change this!

API_URL = "https://www3.tcsion.com/iONBizServices/iONWebService?servicekey=WaJkcnPwTLXzm%2FQICFcn3w%3D%3D&s=4CnZ%2FgPXtzK8efa1RmpmLg%3D%3D&u=TIX8NflllNXow1Ic/ZoBmze/jwyVQjfsnDydzQqFPGDD79kH58CkQVDgHATBFfbr"
USE_LOCAL_DATA = False  # Set to False to use live API (URL confirmed working in test_api_connection.py)

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
    
    # Send email notifications to all assigned users
    email_results = {'success': 0, 'failed': 0, 'failed_emails': []}
    users_data = load_json_file(USERS_FILE, {'users': []})
    users = users_data.get('users', [])
    
    # Create a mapping of email to name for quick lookup
    email_to_name = {user['email']: user['name'] for user in users}
    
    for user_email in user_emails:
        # Get user name from users data
        user_name = email_to_name.get(user_email, user_email.split('@')[0])
        
        # Send course assignment notification
        try:
            success = send_course_assignment_email(
                user_email=user_email,
                user_name=user_name,
                course_name=course_name,
                deadline=deadline
            )
            
            if success:
                email_results['success'] += 1
                logger.info(f"Successfully sent email to {user_email}")
            else:
                email_results['failed'] += 1
                email_results['failed_emails'].append(user_email)
                logger.warning(f"Failed to send email to {user_email}")
        except Exception as e:
            email_results['failed'] += 1
            email_results['failed_emails'].append(user_email)
            logger.error(f"Error sending email to {user_email}: {e}")
    
    return jsonify({
        'message': 'Assignment created successfully',
        'assignment': assignment,
        'emails_sent': email_results['success'],
        'emails_failed': email_results['failed'],
        'failed_emails': email_results['failed_emails']
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
        
        # Get users data for names
        users_data = load_json_file(USERS_FILE, {'users': []})
        email_to_name = {user['email']: user['name'] for user in users_data.get('users', [])}
        
        # Send notifications to added users
        added_results = {'success': 0, 'failed': 0, 'failed_emails': []}
        for user_email in added_users:
            user_name = email_to_name.get(user_email, user_email.split('@')[0])
            try:
                success = send_course_assignment_email(
                    user_email=user_email,
                    user_name=user_name,
                    course_name=assignment['course_name'],
                    deadline=assignment['deadline']
                )
                if success:
                    added_results['success'] += 1
                else:
                    added_results['failed'] += 1
                    added_results['failed_emails'].append(user_email)
            except Exception as e:
                added_results['failed'] += 1
                added_results['failed_emails'].append(user_email)
                logger.error(f"Error notifying added user {user_email}: {e}")
        
        # Send notifications to removed users
        removed_results = {'success': 0, 'failed': 0, 'failed_emails': []}
        for user_email in removed_users:
            user_name = email_to_name.get(user_email, user_email.split('@')[0])
            try:
                success = send_course_removal_email(
                    user_email=user_email,
                    user_name=user_name,
                    course_name=assignment['course_name']
                )
                if success:
                    removed_results['success'] += 1
                else:
                    removed_results['failed'] += 1
                    removed_results['failed_emails'].append(user_email)
            except Exception as e:
                removed_results['failed'] += 1
                removed_results['failed_emails'].append(user_email)
                logger.error(f"Error notifying removed user {user_email}: {e}")
        
        # Update assignment
        assignment['user_emails'] = new_user_emails
        assignment['last_modified'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Save
        if save_json_file(ASSIGNMENTS_FILE, assignments_data):
            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': assignment,
                'users_added': len(added_users),
                'users_removed': len(removed_users),
                'notifications_sent': added_results['success'] + removed_results['success'],
                'notifications_failed': added_results['failed'] + removed_results['failed']
            })
        else:
            return jsonify({'error': 'Failed to save assignment'}), 500
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

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=session.get('username'))

@app.route('/api/status')
@login_required
def get_status():
    return jsonify({
        'using_local_data': USE_LOCAL_DATA,
        'data_source': 'Local JSON File' if USE_LOCAL_DATA else 'TCS iON API'
    })

def load_data():
    """Load data from API or local file"""
    if USE_LOCAL_DATA:
        # Load from local JSON file
        json_path = os.path.join(os.path.dirname(__file__), 'Response Sample.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        # Load from API
        response = requests.get(API_URL, timeout=30)
        response.raise_for_status()
        return response.json()

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
    app.run(debug=True, port=5000)
