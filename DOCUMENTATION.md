# Course Analytics Dashboard - Complete Documentation

## 📊 Project Overview

A modern Flask-based dashboard for tracking course progress and user engagement with real-time data visualization, user management, and course assignment capabilities.

### Key Features
- **Real-time Data**: Fetches data from TCS iON API or local JSON
- **Interactive Dashboards**: KPI cards, charts, and sortable tables
- **User Management**: Add, sync, and manage users with bulk upload
- **Course Assignments**: Assign courses with deadlines and email notifications
- **Admin Settings**: Secure admin panel for system management
- **Modern UI**: 3D styling, glass-morphism effects, and animated gradients

---

## 🚀 Quick Start Guide

### Installation & Setup

1. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

2. **Start the Flask server:**
```bash
python app.py
```

3. **Access the application:**
```
http://localhost:5000
```

### Default Login Credentials
**⚠️ CHANGE THESE IMMEDIATELY! ⚠️**

```
========================================
  DEFAULT CREDENTIALS - CHANGE NOW!
========================================

Username: admin
Password: admin123

Username: user  
Password: user123

Access URL: http://localhost:5000
========================================
```

**Security Notes:**
- ✓ Passwords are hashed (secure)
- ✓ Sessions are encrypted  
- ✓ All routes are protected
- ✓ No database needed
- ⚠️ Change default credentials NOW!
- ⚠️ Change the secret key!
- ⚠️ Use HTTPS in production!

---

## 🏗️ Project Structure

```
.
├── app.py                      # Main Flask application
├── email_service.py            # Email notification service
├── requirements.txt            # Python dependencies
├── deploy_setup.ps1           # PowerShell deployment script
├── deploy_simple.bat          # Simple batch deployment
├── data/                      # Data storage directory
│   ├── users.json            # User registry
│   └── course_assignments.json # Course assignments
├── templates/                 # HTML templates
│   ├── index.html           # Main dashboard
│   ├── login.html           # Login page
│   └── settings.html        # Admin settings
├── static/                   # Static assets
│   ├── css/
│   │   └── tailwind.min.css # Tailwind CSS framework
│   └── js/
│       └── echarts.min.js   # ECharts visualization library
└── DOCUMENTATION.md          # This file
```

---

## 🔐 Authentication & Security

### Security Features
- **Password Hashing**: Uses Werkzeug's PBKDF2 with SHA-256
- **Session Management**: Flask sessions with secure secret key
- **Protected Routes**: All endpoints require authentication
- **Admin Access Control**: Settings restricted to admin users
- **CSRF Protection**: Built-in Flask session protection

### Changing Credentials

**Method 1: Using Python Shell**
```python
from werkzeug.security import generate_password_hash
print(generate_password_hash('your_new_password'))
```

**Method 2: Edit app.py directly**
```python
USERS = {
    'admin': generate_password_hash('your_new_password'),
    'manager': generate_password_hash('manager_password'),
}
```

### Security Best Practices
- ✅ Change default credentials immediately
- ✅ Update secret key to random value
- ✅ Use HTTPS in production
- ✅ Regularly update passwords
- ✅ Keep secret key confidential

---

## 👥 User Management

### Features
- **User Registry**: Centralized user management
- **API Sync**: Automatic synchronization with API data
- **Bulk Upload**: Excel file import for multiple users
- **Duplicate Prevention**: Automatic deduplication
- **Source Tracking**: Distinguish between API and manual users

### User Data Structure
```json
{
  "users": [
    {
      "email": "user@example.com",
      "name": "John Doe",
      "source": "api",
      "added_date": "2025-12-05 14:30:00"
    }
  ]
}
```

### Adding Users

**Manual Addition:**
1. Go to Settings > User Management
2. Enter email address
3. Click "Add User"

**Bulk Upload:**
1. Prepare Excel file with emails in Column A
2. Go to Settings > User Management
3. Click "Upload Excel File"
4. Select file and upload

**API Sync:**
- Automatic sync when accessing Settings
- Manual sync with "Sync from API" button
- Extracts users from API response data

---

## 📚 Course Assignment System

### Features
- **Course Selection**: Choose from available courses
- **User Assignment**: Assign multiple users to courses
- **Deadline Management**: Set completion deadlines
- **Email Notifications**: Automatic assignment notifications
- **Progress Tracking**: Monitor completion status
- **Bulk Operations**: Excel-based bulk assignments

### Assignment Data Structure
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

### Creating Assignments

**Standard Assignment:**
1. Go to Settings > Course Assignments
2. Select course from dropdown
3. Select users (use Select All/Deselect All for bulk)
4. Set deadline date
5. Click "Create Assignment"

**Bulk Assignment:**
1. Select course and set deadline
2. Click "Upload & Assign"
3. Upload Excel file with user emails
4. System automatically creates users if needed
5. Sends notifications to all assigned users

### Assignment Management
- **View Details**: Click assignment to see progress statistics
- **Send Reminders**: Email incomplete users
- **Update Users**: Add/remove users from assignments
- **Delete Assignments**: Remove assignments entirely

---

## 📊 Dashboard Features

### KPI Cards
- **Total Courses**: Number of available courses
- **Total Users**: Registered user count
- **Total Enrollments**: Sum of all course enrollments
- **Overall Completion Rate**: Percentage of completed enrollments

### Interactive Charts

**1. Top Courses by Enrollment**
- Horizontal bar chart
- Toggle: Top 10 / Show All
- Zoom functionality
- Click bars for course details

**2. Overall Completion Status**
- 3D donut chart with gradients
- Shows Completed, In Progress, Not Started
- Interactive hover effects
- Zoom functionality

**3. User Progress Overview**
- Dual bar chart (Total vs Completed courses)
- Toggle: Top 10 / Show All
- User performance comparison
- Zoom functionality

### Data Tables

**Course Overview Table:**
- Sortable columns
- Course name, users, completion stats
- Click rows for detailed view
- CSV export functionality

**User Overview Table:**
- User performance metrics
- Email, courses, completion rates
- Click rows for user timeline
- CSV export functionality

### Modal Views

**Course Detail Modal:**
- All users assigned to course
- Completion status and dates
- Scrollable with fixed headers
- Progress statistics

**User Detail Modal:**
- Timeline chart of course completions
- All assigned courses
- Completion status and dates
- Progress overview

---

## 🎨 UI/UX Design

### Visual Features
- **Animated Gradient Background**: Multi-color shifting gradient
- **3D Glass-Morphism Cards**: Frosted glass effects with depth
- **Gradient Icons**: Color-coded KPI indicators
- **Interactive Elements**: Hover effects and smooth transitions
- **Professional Typography**: Clean, readable fonts
- **Responsive Design**: Works on all screen sizes

### Color Palette
- **Primary Gradient**: Purple (#667eea) → Violet (#764ba2) → Pink (#f093fb) → Blue (#4facfe) → Cyan (#00f2fe)
- **Accent Colors**: Green (#10b981), Purple (#8b5cf6), Yellow (#f59e0b)
- **Status Colors**: Green (Completed), Amber (In Progress), Slate (Not Started)

### Animations
- **Background**: 15-second gradient animation
- **Cards**: Lift effects on hover
- **Charts**: Smooth transitions and scaling
- **Modals**: Fade in/out with backdrop blur

---

## 📧 Email Notification System

### Features
- **Assignment Notifications**: Welcome emails for new assignments
- **Deadline Reminders**: Automated reminder emails
- **Removal Notifications**: Course removal confirmations
- **Bulk Operations**: Mass email sending
- **Error Handling**: Failed email tracking

### Email Types

**Course Assignment Email:**
- Sent when user is assigned to course
- Includes course name and deadline
- Professional HTML formatting

**Deadline Reminder Email:**
- Sent to incomplete users
- Shows days remaining
- Encourages completion

**Course Removal Email:**
- Sent when user is removed from assignment
- Confirmation of removal
- Professional closure

### Configuration
Email service configuration is handled in `email_service.py`. Update SMTP settings for your email provider.

---

## 🚀 Deployment Guide

### Windows Server Deployment

**Option 1: Quick Deployment (Recommended)**
```batch
# Double-click deploy_simple.bat
# Automatically sets up virtual environment and starts server
```

**Option 2: PowerShell Deployment**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\deploy_setup.ps1
```

**Option 3: Windows Service (Production)**
```powershell
# After running deploy_setup.ps1
.\install_service.ps1
```

### Manual Setup
```batch
# Set Python path
set PYTHON_PATH=C:\Users\8527\PYTHON\python_3_11_4\python.exe

# Create virtual environment
"%PYTHON_PATH%" -m venv venv
venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt
pip install waitress

# Run application
python app.py
```

### Production Configuration
- Change `SECRET_KEY` to secure random value
- Set `USE_LOCAL_DATA = False` for live API
- Configure firewall rules for port access
- Set up HTTPS with SSL certificates
- Configure automatic backups for data folder

---

## 🔧 API Endpoints

### Public Endpoints
- `GET /login` - Login page
- `POST /login` - Authentication
- `GET /logout` - Logout

### Protected Endpoints (Login Required)
- `GET /` - Main dashboard
- `GET /api/status` - System status
- `GET /api/data` - Raw API data
- `GET /api/summary` - Dashboard summary
- `GET /api/course/<name>` - Course details
- `GET /api/user/<email>` - User details

### Admin Endpoints (Admin Only)
- `GET /settings` - Settings page
- `GET /api/settings/users` - User list
- `POST /api/settings/users` - Add user
- `DELETE /api/settings/users/<email>` - Delete user
- `POST /api/settings/users/bulk-upload` - Bulk user upload
- `GET /api/settings/courses` - Available courses
- `GET /api/settings/assignments` - Assignment list
- `POST /api/settings/assignments` - Create assignment
- `GET /api/settings/assignments/<id>` - Assignment details
- `PUT /api/settings/assignments/<id>` - Update assignment
- `DELETE /api/settings/assignments/<id>` - Delete assignment
- `POST /api/settings/assignments/<id>/remind` - Send reminders
- `POST /api/settings/assignments/bulk-upload` - Bulk assignment

---

## 📁 Data Management

### Data Storage
All data is stored in local JSON files in the `data/` directory:
- `users.json` - User registry
- `course_assignments.json` - Course assignments

### Data Sources
- **API Mode**: Fetches from TCS iON API (production)
- **Local Mode**: Uses `Response Sample.json` (development)
- Toggle with `USE_LOCAL_DATA` setting in `app.py`

### Backup Strategy
- Regular backups of `data/` folder
- Version control for configuration files
- Export functionality for data portability

---

## 🛠️ Troubleshooting

### Common Issues

**Login Problems:**
- Verify credentials in `USERS` dictionary
- Check password hash generation
- Clear browser cookies and restart server

**Data Loading Issues:**
- Check API URL and connectivity
- Verify `Response Sample.json` format
- Review server logs for errors

**Permission Errors:**
- Run as Administrator on Windows
- Check folder permissions for data directory
- Verify Python path in deployment scripts

**Port Conflicts:**
- Change port in deployment scripts
- Check for other services using port 5000/8888
- Use `netstat -ano | findstr :PORT` to identify conflicts

### Performance Optimization
- Monitor server resources
- Adjust thread count in Waitress configuration
- Implement caching for frequently accessed data
- Optimize database queries and API calls

---

## 🔄 Maintenance

### Regular Tasks
- **Update Dependencies**: Keep Python packages current
- **Monitor Logs**: Check for errors and performance issues
- **Backup Data**: Regular backups of user and assignment data
- **Security Updates**: Update credentials and security settings
- **Performance Review**: Monitor response times and resource usage

### Monitoring
- Check application logs for errors
- Monitor API response times
- Track user activity and engagement
- Review email delivery success rates

---

## 📈 Future Enhancements

### Planned Features
- **Advanced Analytics**: More detailed reporting and insights
- **Role-Based Access**: Multiple user roles and permissions
- **API Integration**: Enhanced API connectivity and error handling
- **Mobile App**: Native mobile application
- **Advanced Notifications**: SMS and push notifications
- **Reporting**: Automated report generation and scheduling

### Scalability Considerations
- Database migration for larger datasets
- Load balancing for high traffic
- Caching layer for improved performance
- Microservices architecture for complex deployments

---

## 📞 Support & Maintenance

### Getting Help
1. Check application logs for error messages
2. Review this documentation for common solutions
3. Verify configuration settings
4. Test with minimal data set
5. Check network connectivity and API access

### Best Practices
- Regular backups of critical data
- Monitor system performance
- Keep dependencies updated
- Follow security guidelines
- Document any customizations

---

## ✅ Summary

The Course Analytics Dashboard provides:
- ✅ Comprehensive user and course management
- ✅ Real-time data visualization and analytics
- ✅ Secure authentication and admin controls
- ✅ Email notification system
- ✅ Modern, responsive UI with 3D effects
- ✅ Bulk operations and Excel integration
- ✅ Production-ready deployment options
- ✅ Extensive documentation and support

**Ready for production use with proper security configuration!**