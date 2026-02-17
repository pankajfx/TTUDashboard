# Background Cache System - Complete Implementation

## 🎯 Solution Overview

Implemented a **background auto-refresh cache system** that:
- ✅ Fetches API data every 15 minutes automatically (even when no users are active)
- ✅ Persists cache to disk (survives server restarts)
- ✅ Shows cache age in UI with manual refresh button
- ✅ Provides seamless UX with instant responses (slightly stale data)
- ✅ Non-blocking refresh (users can continue working during updates)

---

## 🏗️ Architecture

### Components

1. **Persistent Cache File**: `data/api_cache.json`
   - Stores API data and timestamp
   - Survives server restarts
   - Automatically created on first run

2. **Background Scheduler Thread**
   - Runs continuously in the background
   - Refreshes cache every 15 minutes
   - Independent of user activity

3. **Thread-Safe Operations**
   - Uses `threading.Lock()` for safe concurrent access
   - Prevents race conditions
   - Ensures data consistency

4. **UI Components**
   - Cache status display showing data age
   - Manual refresh button
   - Real-time status updates

---

## 📋 Configuration Variables

```python
# API timeout (in seconds)
API_TIMEOUT = 200  # 3 minutes 20 seconds

# Auto-refresh interval (in minutes)
AUTO_REFRESH_INTERVAL_MINUTES = 15  # Refresh every 15 minutes

# Cache file location
CACHE_FILE = 'data/api_cache.json'
```

### Adjusting Refresh Interval

Change `AUTO_REFRESH_INTERVAL_MINUTES` to control how often the cache refreshes:

```python
AUTO_REFRESH_INTERVAL_MINUTES = 5   # Every 5 minutes (more frequent)
AUTO_REFRESH_INTERVAL_MINUTES = 15  # Every 15 minutes (default)
AUTO_REFRESH_INTERVAL_MINUTES = 30  # Every 30 minutes (less frequent)
AUTO_REFRESH_INTERVAL_MINUTES = 60  # Every hour
```

---

## 🚀 How It Works

### Server Startup Sequence

1. **Server starts** → `initialize_cache()` is called
2. **Check for existing cache file**
   - If found: Load data and timestamp
   - If not found: Trigger immediate API fetch
3. **Validate cache age**
   - If older than 15 minutes: Trigger refresh
   - If fresh: Use existing cache
4. **Start background scheduler**
   - Runs in daemon thread
   - Refreshes every 15 minutes
   - Continues even when no users are active

### Background Refresh Process

```
Every 15 minutes:
├── Check if refresh already in progress → Skip if yes
├── Set refresh_in_progress flag
├── Fetch data from API (3+ minutes)
├── Update in-memory cache
├── Save to disk (api_cache.json)
├── Clear refresh_in_progress flag
└── Log completion
```

### User Request Flow

```
User opens dashboard:
├── Load cache status (instant)
├── Display: "Showing Data as on 15th February 2026 (2 hours 30 minutes ago)"
├── Load data from cache (instant)
└── Render dashboard (instant)

User clicks "Get Latest Data":
├── Trigger manual refresh (non-blocking)
├── Show "Updating Data..." with spinning icon
├── Poll status every 3 seconds
├── When complete: Reload page with fresh data
└── User sees updated dashboard
```

---

## 🎨 UI Features

### Cache Status Display

Shows in a card below the header:
```
🕐 Showing Data as on 15th February 2026
   (2 hours 30 minutes ago)
   [Get Latest Data] button
```

### Refresh Button States

**Normal State:**
- Blue gradient button
- Text: "Get Latest Data"
- Clickable

**Refreshing State:**
- Disabled (grayed out)
- Spinning refresh icon
- Text: "Updating Data..."
- Not clickable

### Auto-Update

- Cache status updates every 30 seconds
- Shows real-time age without page reload
- Button state reflects refresh progress

---

## 📁 Cache File Structure

`data/api_cache.json`:
```json
{
  "data": [
    {
      "User_Mail_ID": "user@example.com",
      "Participant_Name": "John Doe",
      "Activity_Name": "Course Name",
      ...
    }
  ],
  "timestamp": "2026-02-15T14:30:00.123456",
  "cached_at_readable": "2026-02-15 14:30:00"
}
```

---

## 🔧 API Endpoints

### GET `/api/status`

Returns cache information:

```json
{
  "using_local_data": false,
  "data_source": "TCS iON API",
  "api_timeout_seconds": 200,
  "auto_refresh_interval_minutes": 15,
  "cache": {
    "cached": true,
    "cache_timestamp": "2026-02-15 14:30:00",
    "cache_age_seconds": 9000,
    "cache_age_readable": "2 hours 30 minutes",
    "cached_at_formatted": "15 February 2026",
    "refresh_in_progress": false
  }
}
```

### POST `/api/refresh-cache`

Triggers manual cache refresh:

**Request:**
```bash
POST /api/refresh-cache
```

**Response (202 Accepted):**
```json
{
  "message": "Cache refresh started in background",
  "refresh_in_progress": true
}
```

**Response (if already refreshing):**
```json
{
  "message": "Cache refresh already in progress",
  "refresh_in_progress": true
}
```

---

## 🔄 Refresh Scenarios

### Scenario 1: Server Startup (No Cache)
```
1. Server starts
2. No cache file found
3. Immediately fetch from API (3+ minutes)
4. Save to cache file
5. Start background scheduler
6. Users get instant responses from cache
```

### Scenario 2: Server Startup (Stale Cache)
```
1. Server starts
2. Load cache from file (20 minutes old)
3. Cache is stale (> 15 minutes)
4. Trigger background refresh
5. Users get instant responses from old cache
6. After 3 minutes, cache updates automatically
7. Next page load shows fresh data
```

### Scenario 3: Server Startup (Fresh Cache)
```
1. Server starts
2. Load cache from file (5 minutes old)
3. Cache is fresh (< 15 minutes)
4. Use existing cache
5. Start background scheduler
6. Will refresh in 10 minutes (15 - 5)
```

### Scenario 4: Manual Refresh
```
1. User clicks "Get Latest Data"
2. Trigger background refresh
3. Button shows "Updating Data..." with spinner
4. UI polls status every 3 seconds
5. After 3+ minutes, refresh completes
6. Page reloads automatically
7. User sees fresh data
```

### Scenario 5: Background Auto-Refresh
```
1. 15 minutes pass since last refresh
2. Scheduler triggers refresh automatically
3. Happens in background (users unaffected)
4. Cache updates silently
5. Next page load shows fresh data
6. No user interaction needed
```

---

## 📊 Performance Comparison

### Before Implementation
```
User Journey:
├── Load dashboard     → 3 min wait (API call)
├── Click course       → 3 min wait (API call)
├── Click user         → 3 min wait (API call)
├── View assignment    → 3 min wait (API call)
└── Total: 12+ minutes of waiting
```

### After Implementation
```
User Journey:
├── Load dashboard     → INSTANT (cached)
├── Click course       → INSTANT (cached)
├── Click user         → INSTANT (cached)
├── View assignment    → INSTANT (cached)
└── Total: < 1 second

Data freshness: Max 15 minutes old
Background refresh: Every 15 minutes automatically
```

---

## 🛠️ Monitoring & Logs

### Log Messages

**Startup:**
```
INFO:__main__:Initializing cache system...
INFO:__main__:Cache loaded from file (cached at: 2026-02-15 14:30:00)
INFO:__main__:Cache is 5.2 minutes old, still valid
INFO:__main__:Cache refresh scheduler started (interval: 15 minutes)
INFO:__main__:Cache system initialized successfully
```

**Background Refresh:**
```
INFO:__main__:Background cache refresh started...
INFO:__main__:Fetching fresh data from API (this may take 3+ minutes)...
INFO:__main__:Successfully fetched 1250 records from API
INFO:__main__:Cache saved to file: data/api_cache.json
INFO:__main__:Background cache refresh completed at 2026-02-15 14:45:00
```

**Manual Refresh:**
```
INFO:__main__:Manual cache refresh triggered by admin
INFO:__main__:Background cache refresh started...
INFO:__main__:Successfully fetched 1250 records from API
INFO:__main__:Background cache refresh completed at 2026-02-15 15:00:00
```

**Skip Refresh (Already Running):**
```
INFO:__main__:Cache refresh already in progress, skipping...
```

---

## 🔒 Thread Safety

### Locking Mechanism

```python
_cache_lock = threading.Lock()

# Safe read
with _cache_lock:
    data = _data_cache

# Safe write
with _cache_lock:
    _data_cache = new_data
    _cache_timestamp = datetime.now()
```

### Race Condition Prevention

- Only one refresh can run at a time
- `_refresh_in_progress` flag prevents concurrent refreshes
- Lock ensures atomic read/write operations
- Daemon threads don't block server shutdown

---

## 🧪 Testing

### Test 1: Verify Background Refresh
```bash
1. Start server
2. Wait 16 minutes
3. Check logs for "Background cache refresh completed"
4. Verify cache file timestamp updated
```

### Test 2: Manual Refresh
```bash
1. Open dashboard
2. Note cache age
3. Click "Get Latest Data"
4. Wait for completion
5. Verify page reloads with fresh data
```

### Test 3: Server Restart
```bash
1. Stop server
2. Check data/api_cache.json exists
3. Start server
4. Verify cache loaded from file
5. Dashboard loads instantly
```

### Test 4: Concurrent Requests
```bash
1. Open dashboard in multiple tabs
2. All tabs load instantly (same cache)
3. Click refresh in one tab
4. Other tabs continue working
5. All tabs update after refresh
```

---

## 🚨 Error Handling

### API Fetch Failure
```python
try:
    data = fetch_fresh_data_from_api()
except Exception as e:
    logger.error(f"Error in background cache refresh: {e}")
    # Keep using old cache
    # Retry on next scheduled refresh
```

### Cache File Corruption
```python
try:
    cache_data = json.load(f)
except Exception as e:
    logger.error(f"Error loading cache from file: {e}")
    # Fetch fresh data from API
    # Create new cache file
```

### Thread Failure
```python
# Daemon threads don't block shutdown
# If scheduler crashes, server continues
# Next restart will reinitialize
```

---

## 📈 Scalability Considerations

### Current Implementation (Single Server)
- ✅ In-memory cache with file persistence
- ✅ Background thread scheduler
- ✅ Suitable for single-server deployments

### Future Enhancements (Multi-Server)

**Option 1: Redis Cache**
```python
import redis
r = redis.Redis(host='localhost', port=6379)

def load_data():
    cached = r.get('api_data')
    if cached:
        return json.loads(cached)
    # Fetch and cache
```

**Option 2: Distributed Lock**
```python
# Only one server refreshes at a time
# Others use cached data
# Prevents duplicate API calls
```

**Option 3: Message Queue**
```python
# Celery Beat for scheduled tasks
# RabbitMQ/Redis for task queue
# Separate worker for API fetching
```

---

## 🎯 Benefits Achieved

### User Experience
- ✅ Instant page loads (< 1 second)
- ✅ Seamless navigation
- ✅ No waiting for API calls
- ✅ Clear data freshness indicator
- ✅ Manual refresh option available

### System Performance
- ✅ Reduced API load (1 call per 15 min vs 100s per day)
- ✅ Predictable API usage
- ✅ Lower server resource usage
- ✅ Better error recovery

### Operational
- ✅ Survives server restarts
- ✅ Automatic background updates
- ✅ No manual intervention needed
- ✅ Comprehensive logging
- ✅ Easy to monitor

---

## 📝 Summary

The background cache system provides:

1. **Automatic refresh every 15 minutes** (configurable)
2. **Persistent cache** that survives restarts
3. **Instant user experience** with slightly stale data
4. **Manual refresh option** for immediate updates
5. **Thread-safe operations** for reliability
6. **Comprehensive logging** for monitoring
7. **Non-blocking architecture** for seamless UX

**Result**: Users get instant responses with data that's never more than 15 minutes old, while the system handles the slow API calls in the background automatically.
