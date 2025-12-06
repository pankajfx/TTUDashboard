# Admin Settings Guide

## 🔧 Admin Settings Overview

The Admin Settings page allows administrators to manage users and assign courses with deadlines. This feature is **only accessible to users with the 'admin' username**.

---

## 🎯 Features

### 1. **User Management**
- Add users by email address
- View all registered users
- Delete users
- Track when users were added

### 2. **Course Assignments**
- Select from available courses
- Assign multiple users to a course
- Set completion deadlines
- View all active assignments
- Delete assignments

---

## 📁 Data Storage

All data is stored locally in JSON files:

### Files Created:
```
data/
├── users.json              # User registry
└── course_assignments.json # Course assignments with deadlines
```

### Data Structure:

**users.json**:
```json
{
  "users": [
    {
      "email": "user@example.com",
      "added_date": "2025-12-05 14:30:00"
    }
  ]
}
```

**course_assignments.json**:
```json
{
  "assignments": [
    {
      "id": 1,
      "course_name": "Understanding Hazards and Risks",
      "user_emails": ["user1@example.com", "user2@example.com"],
      "deadline": "2025-12-31",
      "created_date": "2025-12-05 14:30:00",
      "created_by": "admin"
    }
  ]
}
```

---

## 🚀 How to Use

### Accessing Settings:

1. **Login as admin**:
   - Username: `admin`
   - Password: `admin123` (change this!)

2. **Click Settings button** in the header (gear icon)
   - Only visible to admin users
   - Located next to the Logout button

3. **Navigate between tabs**:
   - User Management
   - Course Assignments

---

## 👥 User Management

### Adding a User:

1. Go to "User Management" tab
2. Enter user's email address
3. Click "Add User"
4. User appears in the list

### Deleting a User:

1. Find user in the list
2. Click the trash icon
3. Confirm deletion
4. User is removed from registry

**Note**: Deleting a user does NOT remove them from existing course assignments.

---

## 📚 Course Assignments

### Creating an Assignment:

1. Go to "Course Assignments" tab
2. **Select a course** from the dropdown
   - Courses are loaded from your data
   - Shows all available courses
3. **Select users** to assign
   - Check boxes for multiple users
   - Must select at least one user
4. **Set deadline** date
5. Click "Create Assignment"
6. Assignment appears in the list

### Viewing Assignments:

Each assignment shows:
- Course name
- Deadline date
- Number of users assigned
- List of user emails
- Creation date

### Deleting an Assignment:

1. Find assignment in the list
2. Click the trash icon
3. Confirm deletion
4. Assignment is removed

---

## 🔒 Security Features

### Admin-Only Access:

- Settings page requires admin login
- Non-admin users cannot access `/settings`
- All API endpoints are protected
- Returns 403 Forbidden for non-admin users

### Protected Endpoints:

```
GET  /settings                          # Settings page
GET  /api/settings/users                # List users
POST /api/settings/users                # Add user
DELETE /api/settings/users/<email>      # Delete user
GET  /api/settings/courses              # List courses
GET  /api/settings/assignments          # List assignments
POST /api/settings/assignments          # Create assignment
DELETE /api/settings/assignments/<id>   # Delete assignment
```

---

## 💡 Use Cases

### Scenario 1: Onboarding New Users
1. Admin adds user emails to the system
2. Admin assigns relevant courses
3. Admin sets completion deadlines
4. Users can now be tracked in the system

### Scenario 2: Course Rollout
1. Admin selects a course
2. Admin assigns to multiple users
3. Admin sets deadline (e.g., end of quarter)
4. Assignment is tracked

### Scenario 3: User Offboarding
1. Admin removes user from registry
2. User data is cleaned up
3. Historical assignments remain for records

---

## 🎨 UI Features

### Design:
- Matches dashboard gradient theme
- Glass-morphism cards
- Responsive layout
- Smooth animations
- Hover effects

### User Experience:
- Two-tab interface
- Real-time updates
- Confirmation dialogs
- Success/error messages
- Scrollable lists

---

## 📊 Data Flow

### Adding a User:
```
1. Admin enters email
2. Frontend sends POST to /api/settings/users
3. Backend validates email
4. Backend saves to users.json
5. Frontend refreshes user list
```

### Creating Assignment:
```
1. Admin selects course, users, deadline
2. Frontend sends POST to /api/settings/assignments
3. Backend validates data
4. Backend saves to course_assignments.json
5. Frontend refreshes assignment list
```

---

## 🔧 Technical Details

### Backend (Flask):
- `@admin_required` decorator protects routes
- JSON file operations with error handling
- Automatic data directory creation
- RESTful API design

### Frontend (JavaScript):
- Async/await for API calls
- Dynamic content rendering
- Form validation
- Error handling

---

## ⚠️ Important Notes

### Data Persistence:
- ✅ Data survives server restarts
- ✅ Stored in local JSON files
- ✅ Human-readable format
- ✅ Easy to backup

### Limitations:
- ⚠️ No user authentication for assigned users (yet)
- ⚠️ No email notifications (yet)
- ⚠️ No deadline reminders (yet)
- ⚠️ Single admin user only

### Best Practices:
- Regular backups of `data/` folder
- Validate email addresses
- Set realistic deadlines
- Review assignments periodically

---

## 🚀 Future Enhancements (Possible)

- Email notifications for assignments
- Deadline reminders
- Progress tracking per assignment
- Bulk user import (CSV)
- Assignment templates
- User roles (admin, manager, viewer)
- Assignment history/audit log

---

## 🐛 Troubleshooting

### Settings button not visible:
- Ensure you're logged in as 'admin'
- Check username in session
- Refresh the page

### Cannot add user:
- Check email format
- Ensure user doesn't already exist
- Check browser console for errors

### Courses not loading:
- Ensure data source is available
- Check API endpoint is working
- Verify data format

### Data not persisting:
- Check `data/` folder exists
- Verify file permissions
- Check server logs for errors

---

## 📝 Quick Reference

### Admin Credentials:
```
Username: admin
Password: admin123  (CHANGE THIS!)
```

### Access URLs:
```
Dashboard: http://localhost:5000/
Settings:  http://localhost:5000/settings
```

### Data Files:
```
data/users.json
data/course_assignments.json
```

---

## ✅ Summary

The Admin Settings feature provides:
- ✅ User management (add/delete)
- ✅ Course assignment with deadlines
- ✅ Local JSON storage
- ✅ Admin-only access
- ✅ Beautiful UI matching dashboard
- ✅ Real-time updates
- ✅ Easy to use interface

**Login as admin and click the Settings button to get started!**
