# Bulk Upload Feature Guide

## Overview
The bulk upload feature allows you to add multiple users and create course assignments using Excel files (.xlsx or .xls).

## Features

### 1. Bulk User Upload
Upload multiple users at once from an Excel file.

**Location:** Settings > User Management > Add New User > Upload Excel File

**How it works:**
- Upload an Excel file with email addresses in the first column
- System validates each email address
- Duplicate emails are automatically ignored
- Invalid emails are reported but don't stop the process
- All valid, non-duplicate users are added to the system

**Excel File Format:**
```
Column A: Email addresses
-----------------------
user1@example.com
user2@example.com
user3@example.com
```

**Response includes:**
- Number of users added
- Number of duplicates found
- Number of invalid emails
- List of invalid emails (for correction)

### 2. Bulk Course Assignment
Assign a course to multiple users via Excel file upload.

**Location:** Settings > Course Assignments > Create Course Assignment > Upload & Assign

**How it works:**
- Select a course from the dropdown
- Set the deadline
- Upload an Excel file with email addresses
- System automatically:
  - Validates all email addresses
  - Adds new users if they don't exist (flexible user management)
  - Assigns the course to all valid users
  - Sends email notifications to assigned users
  - Reports invalid emails

**Excel File Format:**
```
Column A: Email addresses
-----------------------
user1@example.com
user2@example.com
user3@example.com
```

**Response includes:**
- Number of users assigned to course
- Number of new users added to system
- Number of invalid emails ignored
- Email notification statistics

## Email Validation
The system uses strict email validation:
- Must contain @ symbol
- Must have valid domain
- Must follow standard email format: `username@domain.extension`

**Valid examples:**
- john.doe@company.com
- user123@example.org
- test.user+tag@domain.co.uk

**Invalid examples:**
- notanemail
- @domain.com
- user@
- user @domain.com (space)

## Key Benefits

1. **Time Saving:** Add hundreds of users in seconds instead of one-by-one
2. **Flexible:** New users are automatically created when assigning courses
3. **Safe:** Duplicate detection prevents redundant entries
4. **Informative:** Detailed feedback on what was processed
5. **Validated:** Invalid emails are caught and reported
6. **Integrated:** Email notifications sent automatically

## Best Practices

1. **Prepare your Excel file:**
   - Put email addresses in the first column (Column A)
   - One email per row
   - Remove any headers or extra data
   - Save as .xlsx or .xls format

2. **Check for duplicates:**
   - System handles duplicates automatically
   - But cleaning your file first is faster

3. **Validate emails beforehand:**
   - Use Excel formulas to check email format
   - Remove any obvious errors

4. **Test with small batches first:**
   - Upload 5-10 users first to verify format
   - Then upload the full list

## Example Workflow

### Adding Multiple Users:
1. Create Excel file with emails in Column A
2. Go to Settings > User Management
3. Scroll to "Upload Excel File" section
4. Click "Choose File" and select your Excel
5. Click "📤 Upload Users"
6. Review the success message showing counts
7. Check the users list to verify

### Assigning Course to Multiple Users:
1. Create Excel file with emails in Column A
2. Go to Settings > Course Assignments
3. Scroll to "Upload & Assign" section
4. Select course from dropdown
5. Set deadline date
6. Click "Choose File" and select your Excel
7. Click "📤 Upload & Assign"
8. Review success message with statistics
9. Check Active Assignments to verify

## Troubleshooting

**Problem:** "No valid email addresses found"
- **Solution:** Check that emails are in Column A and properly formatted

**Problem:** "Invalid file format"
- **Solution:** Ensure file is saved as .xlsx or .xls (not .csv)

**Problem:** "Some emails marked as invalid"
- **Solution:** Check the console log or notification for list of invalid emails, correct them, and re-upload

**Problem:** "Users already existed"
- **Solution:** This is normal - system prevents duplicates automatically

## Technical Details

- **Supported formats:** .xlsx, .xls
- **Email column:** First column (Column A)
- **Validation:** RFC-compliant email regex
- **Duplicate handling:** Case-insensitive email comparison
- **Auto-user creation:** New users added automatically during course assignment
- **Notifications:** Email sent to all successfully assigned users
