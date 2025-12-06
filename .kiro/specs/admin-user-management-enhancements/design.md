# Design Document

## Overview

This design enhances the admin user management system with three key features:
1. **Real-time Search**: A substring-based search filter that updates the user list as the admin types
2. **Duplicate Validation**: Client and server-side validation to prevent adding users that already exist
3. **Email Service Module**: A reusable SMTP-based email notification system for course assignments and reminders

The design integrates seamlessly with the existing Flask backend and JavaScript frontend, maintaining the current architecture patterns.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Admin Settings UI                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Search Input │  │ User List    │  │ Add User     │      │
│  │ (Real-time)  │  │ (Filtered)   │  │ Form         │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Flask Backend (app.py)                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  User Management Endpoints                           │   │
│  │  - GET /api/settings/users (with duplicate check)    │   │
│  │  - POST /api/settings/users (with validation)        │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Email Integration                                    │   │
│  │  - Import email_service module                        │   │
│  │  - Trigger emails on assignment creation              │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Email Service Module (email_service.py)         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  SMTP Connection Management                           │   │
│  │  - Office365 SMTP (smtp.office365.com:587)           │   │
│  │  - TLS encryption                                     │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Email Templates & Sending                            │   │
│  │  - send_email() - Core sending function               │   │
│  │  - send_course_assignment_email()                     │   │
│  │  - send_deadline_reminder_email()                     │   │
│  │  - send_bulk_emails()                                 │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

**Search Flow:**
1. User types in search input
2. JavaScript event listener captures input
3. Filter function runs on client-side user array
4. Filtered results re-render immediately

**Duplicate Validation Flow:**
1. User submits add user form
2. Client-side validation checks existing users array
3. If duplicate found, show error and prevent submission
4. If unique, send POST request to server
5. Server validates again against database
6. Return success or error response

**Email Notification Flow:**
1. Admin creates course assignment
2. Backend receives assignment data
3. Backend calls email_service module
4. Email service sends notification to each assigned user
5. Return success/failure status

## Components and Interfaces

### 1. Search Component (Frontend)

**Location:** `templates/settings.html`

**HTML Structure:**
```html
<div class="search-container mb-4">
    <input 
        type="text" 
        id="userSearchInput" 
        placeholder="Search users by email or name..."
        class="input-field w-full px-4 py-2 rounded-lg"
    />
    <div id="searchResultsCount" class="text-sm text-gray-600 mt-1">
        <!-- Shows: "Showing X of Y users" -->
    </div>
</div>
```

**JavaScript Interface:**
```javascript
// State
let allUsers = [];        // Full user list from API
let filteredUsers = [];   // Filtered results

// Functions
function filterUsers(searchTerm)
  Input: searchTerm (string)
  Output: void
  Side-effects: Updates filteredUsers array, re-renders user list

function renderUsers()
  Input: void (uses filteredUsers array)
  Output: void
  Side-effects: Updates DOM with filtered user list

// Event Listener
userSearchInput.addEventListener('input', (e) => {
    filterUsers(e.target.value);
});
```

### 2. Duplicate Validation Component

**Client-Side Validation (JavaScript):**
```javascript
function validateUserEmail(email)
  Input: email (string)
  Output: { valid: boolean, error: string }
  Logic:
    - Check if email exists in allUsers array
    - Return validation result

function showValidationError(message)
  Input: message (string)
  Output: void
  Side-effects: Display error message in UI
```

**Server-Side Validation (Python):**
```python
@app.route('/api/settings/users', methods=['POST'])
def add_user():
    Input: JSON { email: string }
    Output: JSON { message/error: string }
    Logic:
      1. Load existing users from data/users.json
      2. Check if email exists (case-insensitive)
      3. If duplicate: return 400 error
      4. If unique: add user and return 200 success
```

### 3. Email Service Module

**Module:** `email_service.py`

**Core Functions:**

```python
def send_email(to_address, subject, body_html, body_text=None)
  Input:
    - to_address: str (recipient email)
    - subject: str (email subject)
    - body_html: str (HTML content)
    - body_text: str (optional plain text)
  Output: bool (True if sent successfully)
  Logic:
    1. Create MIME multipart message
    2. Connect to SMTP server with TLS
    3. Authenticate with credentials
    4. Send message
    5. Handle exceptions and return status

def send_course_assignment_email(user_email, user_name, course_name, deadline)
  Input:
    - user_email: str
    - user_name: str
    - course_name: str
    - deadline: str (YYYY-MM-DD)
  Output: bool
  Logic:
    1. Generate email subject: "New Course Assignment: {course_name}"
    2. Generate HTML email body with:
       - Greeting with user name
       - Main message: "A new course - {course_name} has been assigned"
       - Course details table (Course Name, Due Date)
       - Call-to-action or next steps
    3. Call send_email()
    4. Return result
  
  Email Template:
    Subject: "New Course Assignment: {course_name}"
    Body:
      Dear {user_name},
      
      A new course - {course_name} has been assigned to you.
      
      Course Details:
      - Course Name: {course_name}
      - Due Date: {deadline}
      
      Please log in to the Tata Tommorrow University portal to access your course materials.
      
      Best regards,
      Course Management System

def send_deadline_reminder_email(user_email, user_name, course_name, deadline, days_remaining)
  Input:
    - user_email: str
    - user_name: str
    - course_name: str
    - deadline: str
    - days_remaining: int
  Output: bool
  Logic:
    1. Generate reminder email with urgency styling
    2. Call send_email()
    3. Return result

def send_bulk_emails(recipients, subject, body_html, body_text=None)
  Input:
    - recipients: list[str] (email addresses)
    - subject: str
    - body_html: str
    - body_text: str (optional)
  Output: dict { success: int, failed: int, failed_emails: list }
  Logic:
    1. Iterate through recipients
    2. Call send_email() for each
    3. Track success/failure counts
    4. Return results summary
```

**Integration with Flask Backend:**

```python
# In app.py
from email_service import send_course_assignment_email, send_bulk_emails

@app.route('/api/settings/assignments', methods=['POST'])
def create_assignment():
    """
    Triggered when: Admin creates a new course assignment
    Email trigger: Immediately after assignment is saved to database
    """
    data = request.get_json()
    course_name = data.get('course_name')
    deadline = data.get('deadline')
    user_emails = data.get('user_emails', [])
    
    # Save assignment to database
    assignment_id = save_assignment(course_name, deadline, user_emails)
    
    # Send email notifications to all assigned users
    email_results = {'success': 0, 'failed': 0}
    for user_email in user_emails:
        # Get user name from users data
        user_name = get_user_name_by_email(user_email)
        
        # Send course assignment notification
        success = send_course_assignment_email(
            user_email=user_email,
            user_name=user_name,
            course_name=course_name,
            deadline=deadline
        )
        
        if success:
            email_results['success'] += 1
        else:
            email_results['failed'] += 1
            logger.warning(f"Failed to send email to {user_email}")
    
    return jsonify({
        'message': 'Assignment created successfully',
        'assignment_id': assignment_id,
        'emails_sent': email_results['success'],
        'emails_failed': email_results['failed']
    }), 201
```

**Email Notification Trigger Points:**

1. **Course Assignment Creation** (Primary Use Case)
   - Trigger: When admin clicks "Assign Course" button and assignment is saved
   - Recipients: All users selected for the course
   - Email Type: Course assignment notification
   - Content: Course name, due date, welcome message

2. **Future Use Cases** (Infrastructure Ready)
   - Deadline reminders (e.g., 3 days before due date)
   - Course completion confirmations
   - Assignment updates or changes
   - Bulk announcements to all users

## Data Models

### User Model (Existing - No Changes)
```json
{
  "email": "user@example.com",
  "name": "User Name",
  "source": "api|manual",
  "added_date": "2024-12-06 10:30:00"
}
```

### Email Configuration
```python
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USERNAME = "noc.mis@nelco.in"
SMTP_PASSWORD = "rvhgdskxyqgzsqrr"
SENDER_ADDRESS = SMTP_USERNAME
```

### Email Template Structure

**Course Assignment Email HTML Template:**
```html
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                  color: white; padding: 20px; border-radius: 8px 8px 0 0; }
        .content { background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }
        .details-table { width: 100%; margin: 20px 0; background: white; 
                         border-radius: 8px; padding: 15px; }
        .details-table td { padding: 10px; border-bottom: 1px solid #eee; }
        .label { font-weight: bold; color: #667eea; }
        .cta-button { background: #667eea; color: white; padding: 12px 30px; 
                      text-decoration: none; border-radius: 5px; display: inline-block; 
                      margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>New Course Assignment</h2>
        </div>
        <div class="content">
            <p>Dear {user_name},</p>
            
            <p>A new course - <strong>{course_name}</strong> has been assigned to you.</p>
            
            <table class="details-table">
                <tr>
                    <td class="label">Course Name:</td>
                    <td>{course_name}</td>
                </tr>
                <tr>
                    <td class="label">Due Date:</td>
                    <td>{deadline}</td>
                </tr>
            </table>
            
            <p>Please log in to the Tata Tommorrow University portal to access your course materials and begin your learning journey.</p>
            
            <a href="{login_url}" class="cta-button">Access Course</a>
            
            <p style="margin-top: 30px; color: #666; font-size: 14px;">
                Best regards,<br>
                Course Management System
            </p>
        </div>
    </div>
</body>
</html>
```

**Plain Text Fallback:**
```
Dear {user_name},

A new course - {course_name} has been assigned to you.

Course Details:
- Course Name: {course_name}
- Due Date: {deadline}

Please log in to the Tata Tommorrow University portal to access your course materials.

Best regards,
Course Management System
```

### Email Result Model
```python
{
    'success': int,           # Number of successfully sent emails
    'failed': int,            # Number of failed emails
    'failed_emails': list     # List of email addresses that failed
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Search filter matches substring
*For any* user list and any search term, all users returned by the filter function should contain the search term as a substring (case-insensitive) in their email or name.
**Validates: Requirements 1.2, 1.3**

### Property 2: Clear search restores full list
*For any* user list, applying a search filter and then clearing the search should result in the original full user list being displayed.
**Validates: Requirements 1.5**

### Property 3: Duplicate detection identifies existing emails
*For any* user list and any email address, the duplicate validation function should return true if and only if that email already exists in the list (case-insensitive comparison).
**Validates: Requirements 2.1**

### Property 4: Duplicate addition preserves list invariant
*For any* user list, attempting to add a user with a duplicate email should not change the length or contents of the user list.
**Validates: Requirements 2.2, 2.4**

### Property 5: Duplicate error message contains email reference
*For any* duplicate email validation error, the error message should contain either the word "email" or the actual email address that caused the conflict.
**Validates: Requirements 2.3**

### Property 6: Unique email addition succeeds
*For any* user list and any email that doesn't exist in the list, adding a user with that email should increase the list length by one and include the new user.
**Validates: Requirements 2.5**

### Property 7: Email send returns status
*For any* valid email parameters (recipient, subject, body), the send_email function should return a boolean status indicating success or failure, never raising an unhandled exception.
**Validates: Requirements 3.3, 3.4**

### Property 8: Email service accepts both text formats
*For any* recipient and subject, the send_email function should successfully accept and process both plain text and HTML body content without errors.
**Validates: Requirements 3.6**

### Property 9: Batch send processes all recipients
*For any* list of recipient email addresses, the send_bulk_emails function should attempt to send to each recipient and return a results dictionary with success and failure counts that sum to the total number of recipients.
**Validates: Requirements 3.7**

## Error Handling

### Frontend Error Handling

**Search Functionality:**
- Empty search terms: Display full user list (no error)
- No matching results: Display "No users found matching '[search term]'" message
- Invalid characters: Accept all input, filter will naturally return no results if no matches

**Duplicate Validation:**
- Duplicate email detected: 
  - Display error message: "User with email '[email]' already exists"
  - Highlight the email input field in red
  - Prevent form submission
  - Keep form data so user can correct
- Network error during validation:
  - Display: "Unable to verify user. Please try again."
  - Allow retry

### Backend Error Handling

**User Addition Endpoint:**
```python
try:
    # Validate email format
    if not is_valid_email(email):
        return jsonify({'error': 'Invalid email format'}), 400
    
    # Check for duplicates
    if email_exists(email):
        return jsonify({'error': f'User with email {email} already exists'}), 409
    
    # Add user
    add_user_to_database(user_data)
    return jsonify({'message': 'User added successfully'}), 201
    
except Exception as e:
    logger.error(f"Error adding user: {str(e)}")
    return jsonify({'error': 'Internal server error'}), 500
```

**Email Service Error Handling:**
```python
def send_email(to_address, subject, body_html, body_text=None):
    try:
        # Validate email address format
        if not is_valid_email(to_address):
            logger.error(f"Invalid email address: {to_address}")
            return False
        
        # Create and send message
        msg = create_mime_message(to_address, subject, body_html, body_text)
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"Email sent successfully to {to_address}")
        return True
        
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed - check credentials")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email: {str(e)}")
        return False
```

**Error Logging:**
- All errors should be logged with appropriate severity levels
- Include timestamps, user context, and error details
- Email failures should be logged but not block the main operation

## Testing Strategy

### Unit Testing

**Search Functionality Tests:**
- Test search with exact matches
- Test search with partial matches
- Test search with no matches
- Test case-insensitive matching
- Test clearing search

**Duplicate Validation Tests:**
- Test duplicate detection with exact email match
- Test duplicate detection with different case
- Test unique email passes validation
- Test error message format

**Email Service Tests:**
- Test successful email send with valid parameters
- Test email send with invalid recipient
- Test email send with SMTP connection failure
- Test HTML and plain text body handling
- Test batch send with mixed success/failure

### Property-Based Testing

We will use **Hypothesis** (Python) for property-based testing of the backend and **fast-check** (JavaScript) for frontend testing.

**Configuration:**
- Minimum 100 iterations per property test
- Each test must reference the correctness property it validates using the format: `**Feature: admin-user-management-enhancements, Property X: [property text]**`

**Property Test Examples:**

```python
# Property 3: Duplicate detection
@given(st.lists(st.emails()), st.emails())
def test_duplicate_detection_property(user_emails, test_email):
    """Feature: admin-user-management-enhancements, Property 3: Duplicate detection identifies existing emails"""
    users = [{'email': email} for email in user_emails]
    result = is_duplicate_email(test_email, users)
    expected = test_email.lower() in [e.lower() for e in user_emails]
    assert result == expected

# Property 9: Batch send processes all recipients
@given(st.lists(st.emails(), min_size=1, max_size=10))
def test_batch_send_property(recipients):
    """Feature: admin-user-management-enhancements, Property 9: Batch send processes all recipients"""
    result = send_bulk_emails(recipients, "Test", "<p>Test</p>")
    assert result['success'] + result['failed'] == len(recipients)
```

**JavaScript Property Tests:**
```javascript
// Property 1: Search filter matches substring
fc.assert(
  fc.property(
    fc.array(fc.record({ email: fc.emailAddress(), name: fc.string() })),
    fc.string(),
    (users, searchTerm) => {
      // Feature: admin-user-management-enhancements, Property 1: Search filter matches substring
      const filtered = filterUsers(users, searchTerm);
      return filtered.every(user => 
        user.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
        user.name.toLowerCase().includes(searchTerm.toLowerCase())
      );
    }
  ),
  { numRuns: 100 }
);
```

### Integration Testing

- Test complete flow: search → select users → add to course → send emails
- Test duplicate validation across client and server
- Test email service integration with Flask endpoints
- Verify error handling across the full stack

### Manual Testing Checklist

- Verify search UI appears correctly on page load
- Test search with various inputs and verify real-time filtering
- Attempt to add duplicate user and verify error message
- Add unique user and verify success
- Verify email notifications are received (use test email addresses)
- Test with large user lists (100+ users) for performance

## Implementation Notes

### Frontend Implementation Priority
1. Add search input UI component
2. Implement real-time filter function
3. Add duplicate validation to add user form
4. Display validation errors in UI

### Backend Implementation Priority
1. Create email_service.py module with core functions
2. Add duplicate validation to user addition endpoint
3. Integrate email service with assignment creation
4. Add logging for email operations

### Security Considerations
- Store SMTP credentials in environment variables (not hardcoded)
- Validate and sanitize all email addresses
- Implement rate limiting for email sending to prevent abuse
- Use TLS for SMTP connections
- Log email operations for audit trail

### Performance Considerations
- Client-side search filtering for lists under 1000 users
- Consider server-side pagination for larger user lists
- Implement email queue for batch operations
- Add timeout handling for SMTP connections
- Cache user list to reduce API calls

