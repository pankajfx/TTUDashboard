## 🔐 Authentication System Documentation

## Overview

A secure authentication system has been implemented to protect the Course Analytics Dashboard. No database is required - credentials are stored securely in the code using industry-standard password hashing.

---

## 🛡️ Security Features

### 1. **Password Hashing**
- Uses Werkzeug's `generate_password_hash` and `check_password_hash`
- Passwords are never stored in plain text
- Uses PBKDF2 with SHA-256 by default
- Salted hashes prevent rainbow table attacks

### 2. **Session Management**
- Flask sessions with secure secret key
- Session data stored server-side
- Automatic session expiration
- CSRF protection built-in

### 3. **Protected Routes**
- All dashboard pages require authentication
- All API endpoints require authentication
- Automatic redirect to login if not authenticated
- No data accessible without valid session

---

## 👥 Default Credentials

**⚠️ IMPORTANT: Change these immediately!**

```
Username: admin
Password: admin123

Username: user
Password: user123
```

---

## 🔧 How to Change/Add Users

### Method 1: Using Python Shell

1. Open Python shell:
```bash
python
```

2. Generate password hash:
```python
from werkzeug.security import generate_password_hash
print(generate_password_hash('your_new_password'))
```

3. Copy the output hash

4. Edit `app.py` and update the USERS dictionary:
```python
USERS = {
    'admin': 'pbkdf2:sha256:...',  # Paste your hash here
    'newuser': 'pbkdf2:sha256:...',  # Add new users
}
```

### Method 2: Direct Edit (Less Secure)

Edit `app.py`:
```python
USERS = {
    'admin': generate_password_hash('your_new_password'),
    'manager': generate_password_hash('manager_password'),
    'viewer': generate_password_hash('viewer_password'),
}
```

---

## 🔑 Changing the Secret Key

**CRITICAL**: Change the secret key in `app.py`:

```python
app.secret_key = 'your-secret-key-change-this-to-something-random-and-secure-12345'
```

Generate a secure random key:
```python
import secrets
print(secrets.token_hex(32))
```

Use the output as your secret key.

---

## 📋 Features

### Login Page
- Beautiful gradient design matching dashboard theme
- Responsive layout
- Error messages for invalid credentials
- Auto-focus on username field
- Secure form submission

### Dashboard
- Logout button in header
- Session-based authentication
- Automatic redirect if session expires
- Username display (optional)

### Security
- All routes protected with `@login_required` decorator
- Sessions expire on browser close
- No credentials in URLs or client-side code
- Secure password comparison

---

## 🚀 Usage

### For Users:

1. Navigate to `http://localhost:5000`
2. You'll be redirected to login page
3. Enter username and password
4. Click "Sign In"
5. Access the dashboard
6. Click "Logout" when done

### For Administrators:

1. Change default credentials immediately
2. Update secret key
3. Add/remove users as needed
4. Monitor access (add logging if needed)

---

## 🔒 Best Practices

### DO:
- ✅ Change default credentials immediately
- ✅ Use strong, unique passwords
- ✅ Change the secret key to something random
- ✅ Keep the secret key confidential
- ✅ Use HTTPS in production
- ✅ Regularly update passwords

### DON'T:
- ❌ Use default credentials in production
- ❌ Share credentials
- ❌ Store passwords in plain text
- ❌ Use the same secret key across applications
- ❌ Commit secret keys to version control

---

## 🔐 Production Deployment

For production use, consider:

1. **HTTPS**: Always use HTTPS
2. **Environment Variables**: Store secret key in environment variable
3. **Session Security**: Configure secure session cookies
4. **Rate Limiting**: Add login attempt rate limiting
5. **Logging**: Log authentication attempts
6. **Password Policy**: Enforce strong password requirements

### Example Production Config:

```python
import os

app.secret_key = os.environ.get('SECRET_KEY')
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True  # No JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour timeout
```

---

## 🛠️ Troubleshooting

### "Invalid username or password"
- Check credentials are correct
- Verify USERS dictionary in app.py
- Ensure password hash was generated correctly

### Session expires immediately
- Check secret key is set
- Verify browser accepts cookies
- Check session configuration

### Can't access after login
- Clear browser cookies
- Restart Flask server
- Check @login_required decorators are in place

---

## 📝 Code Structure

```
app.py
├── Imports (Flask, security modules)
├── App configuration (secret key)
├── USERS dictionary (hashed passwords)
├── login_required decorator
├── /login route (GET/POST)
├── /logout route
├── / route (protected)
└── /api/* routes (all protected)

templates/
├── login.html (login page)
└── index.html (dashboard with logout)
```

---

## 🔄 Session Flow

```
1. User visits dashboard → Not logged in
2. Redirect to /login
3. User enters credentials
4. Server validates against USERS dict
5. If valid: Create session, redirect to dashboard
6. If invalid: Show error, stay on login
7. User accesses dashboard (session valid)
8. User clicks logout → Clear session → Redirect to login
```

---

## ⚡ Quick Start

1. **Change credentials** in `app.py`:
```python
USERS = {
    'yourusername': generate_password_hash('yourpassword'),
}
```

2. **Change secret key** in `app.py`:
```python
app.secret_key = 'your-random-secret-key-here'
```

3. **Restart server**:
```bash
python app.py
```

4. **Login** at `http://localhost:5000`

---

## 🎯 Summary

- ✅ Secure authentication implemented
- ✅ No database required
- ✅ Industry-standard password hashing
- ✅ Session-based security
- ✅ All routes protected
- ✅ Beautiful login page
- ✅ Easy to manage users
- ✅ Production-ready with proper configuration

**Remember**: Change default credentials and secret key immediately!
