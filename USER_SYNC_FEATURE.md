# User Sync Feature Documentation

## 🔄 Automatic User Synchronization

The system now automatically syncs users from the API response with locally managed users, ensuring complete coverage without duplicates.

---

## 🎯 How It Works

### Automatic Sync:
1. **When accessing Settings**: Users are automatically synced from API
2. **On page load**: Latest user list is fetched
3. **Manual sync**: Click "Sync from API" button anytime

### Deduplication:
- System checks existing emails before adding
- No duplicate users are created
- Both API and manual users coexist

---

## 👥 User Sources

### Two Types of Users:

1. **API Users** (Blue badge)
   - Automatically extracted from API response
   - Based on `User_Mail_ID` field
   - Includes user name from `Participant_Name`
   - Marked with `source: 'api'`

2. **Manual Users** (Green badge)
   - Added manually by admin
   - Custom email addresses
   - Marked with `source: 'manual'`

---

## 📊 User Data Structure

```json
{
  "users": [
    {
      "email": "user@example.com",
      "name": "John Doe",
      "source": "api",
      "added_date": "2025-12-05 14:30:00"
    },
    {
      "email": "custom@example.com",
      "name": "",
      "source": "manual",
      "added_date": "2025-12-05 15:00:00"
    }
  ]
}
```

### Fields:
- **email**: User's email address (unique)
- **name**: User's name (from API or empty for manual)
- **source**: Either 'api' or 'manual'
- **added_date**: When user was added to system

---

## 🔄 Sync Process

### Step-by-Step:

1. **Load API Data**
   ```
   Load data from API or local JSON
   ```

2. **Extract Unique Users**
   ```
   Get all unique User_Mail_ID values
   Store with Participant_Name
   ```

3. **Load Existing Users**
   ```
   Read from data/users.json
   Create set of existing emails
   ```

4. **Merge Without Duplicates**
   ```
   For each API user:
     If email not in existing users:
       Add to users list
   ```

5. **Save Updated List**
   ```
   Write back to data/users.json
   ```

---

## 🎨 UI Features

### User List Display:

Each user shows:
- **Email address** (bold)
- **Badge**: Blue for API, Green for Manual
- **Name**: If available from API
- **Added date**: When user was added
- **Delete button**: Remove user

### Sync Button:
- Located in Users List header
- Shows sync status (Syncing... / Synced! / Error)
- Automatically updates user count
- Disabled during sync

### User Counter:
- Shows total users
- Breaks down by source (API vs Manual)
- Updates after each sync

---

## 💡 Use Cases

### Scenario 1: Initial Setup
```
1. Admin opens Settings
2. System auto-syncs all API users
3. Shows "50 users (50 from API, 0 manual)"
4. All course participants are now registered
```

### Scenario 2: Adding Custom User
```
1. Admin adds custom@example.com manually
2. User appears with green "Manual" badge
3. Shows "51 users (50 from API, 1 manual)"
4. Custom user can be assigned to courses
```

### Scenario 3: New API Users
```
1. New users appear in API data
2. Admin clicks "Sync from API"
3. New users are automatically added
4. Shows "55 users (55 from API, 0 manual)"
5. No duplicates created
```

---

## 🔒 Deduplication Logic

### How Duplicates Are Prevented:

```python
# Create set of existing emails
existing_emails = {user['email'] for user in existing_users}

# Only add if not exists
for email, name in api_users.items():
    if email not in existing_emails:
        # Add new user
```

### Rules:
- Email is the unique identifier
- Case-sensitive comparison
- Whitespace is trimmed
- Empty emails are ignored

---

## 📈 Benefits

### Complete Coverage:
- ✅ All API users automatically included
- ✅ Can add custom users manually
- ✅ No users missed

### No Duplicates:
- ✅ Email-based deduplication
- ✅ Safe to sync multiple times
- ✅ Manual users preserved

### Easy Management:
- ✅ Visual badges show source
- ✅ One-click sync
- ✅ Real-time counter
- ✅ Delete any user

---

## 🔧 Technical Details

### Sync Function:
```python
def sync_users_from_api():
    # Load API data
    data = load_data()
    
    # Extract unique users
    api_users = {}
    for record in data:
        email = record.get('User_Mail_ID', '').strip()
        name = record.get('Participant_Name', '').strip()
        if email and email not in api_users:
            api_users[email] = name
    
    # Merge with existing
    # ... deduplication logic ...
    
    # Save updated list
    save_json_file(USERS_FILE, users_data)
```

### When Sync Happens:
1. **Automatic**: When GET /api/settings/users is called
2. **Manual**: When "Sync from API" button is clicked
3. **On Load**: When Settings page loads

---

## 📊 Example Data Flow

### Before Sync:
```json
{
  "users": [
    {"email": "manual@example.com", "source": "manual"}
  ]
}
```

### API Has:
```
user1@example.com (John)
user2@example.com (Jane)
manual@example.com (Already exists)
```

### After Sync:
```json
{
  "users": [
    {"email": "manual@example.com", "source": "manual"},
    {"email": "user1@example.com", "name": "John", "source": "api"},
    {"email": "user2@example.com", "name": "Jane", "source": "api"}
  ]
}
```

**Result**: 3 users total, no duplicates!

---

## ⚠️ Important Notes

### Data Integrity:
- Sync is safe to run multiple times
- Existing users are never modified
- Only new users are added
- Manual users are preserved

### Performance:
- Sync happens in background
- Non-blocking operation
- Fast with large datasets
- Efficient deduplication

### Limitations:
- Email must be unique
- Cannot merge users with same email
- Name from API cannot be edited
- Manual users don't have names by default

---

## 🚀 Quick Start

### For Admins:

1. **Login as admin**
2. **Go to Settings**
3. **Click "User Management" tab**
4. **Users auto-sync on load**
5. **Click "Sync from API" to refresh**
6. **View user count and badges**

### Adding Manual User:

1. Enter email in form
2. Click "Add User"
3. User appears with green "Manual" badge
4. Can be assigned to courses

### Syncing:

1. Click "🔄 Sync from API" button
2. Wait for "✓ Synced!" message
3. View updated user count
4. New API users appear with blue badge

---

## ✅ Summary

The User Sync feature provides:
- ✅ Automatic sync from API
- ✅ Manual user addition
- ✅ No duplicate users
- ✅ Visual source badges
- ✅ Real-time counter
- ✅ One-click refresh
- ✅ Complete user coverage

**All users from API + Manual users = Complete registry without duplicates!**
