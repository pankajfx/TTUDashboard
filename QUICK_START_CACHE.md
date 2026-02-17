# Quick Start Guide - Background Cache System

## 🚀 What Changed?

Your application now has a **smart background cache system** that:
- Automatically fetches API data every 15 minutes
- Stores data persistently (survives server restarts)
- Provides instant user experience
- Shows data age with manual refresh option

---

## ⚡ Quick Start

### 1. Start the Server

```bash
python app.py
```

**What happens:**
- Server initializes cache system
- Loads existing cache (if available) or fetches fresh data
- Starts background scheduler
- Ready to serve requests instantly!

### 2. Open Dashboard

Navigate to: `http://localhost:5000`

**You'll see:**
- Cache status banner: "Showing Data as on 15th February 2026 (5 minutes ago)"
- "Get Latest Data" button
- Instant dashboard load (no 3-minute wait!)

### 3. Manual Refresh (Optional)

Click **"Get Latest Data"** button when you want fresh data:
- Button shows "Updating Data..." with spinning icon
- Takes 3+ minutes (API call in background)
- Dashboard updates automatically when done (no page reload!)
- Shows success notification
- You can continue working during the update

---

## 📁 Files Created

### `data/api_cache.json`
- Automatically created on first run
- Stores API data and timestamp
- Updated every 15 minutes
- Survives server restarts

**Location:** `data/api_cache.json`

**Don't delete this file!** It contains your cached data.

---

## ⚙️ Configuration

### Change Refresh Interval

Edit `app.py` line ~28:

```python
AUTO_REFRESH_INTERVAL_MINUTES = 15  # Change this number
```

**Examples:**
- `5` = Refresh every 5 minutes (more frequent, more API calls)
- `15` = Refresh every 15 minutes (default, balanced)
- `30` = Refresh every 30 minutes (less frequent, fewer API calls)
- `60` = Refresh every hour

### Change API Timeout

Edit `app.py` line ~26:

```python
API_TIMEOUT = 200  # Seconds (3 min 20 sec)
```

---

## 🎯 User Experience

### Before (Old System)
```
Load dashboard → Wait 3 minutes → See data
Click course   → Wait 3 minutes → See details
Click user     → Wait 3 minutes → See timeline
Total: 9+ minutes of waiting!
```

### After (New System)
```
Load dashboard → INSTANT → See data (max 15 min old)
Click course   → INSTANT → See details
Click user     → INSTANT → See timeline
Total: < 1 second!
```

---

## 📊 Cache Status Display

The banner shows:

```
🕐 Showing Data as on 15th February 2026
   (2 hours 30 minutes ago)
   [Get Latest Data] button
```

**Updates automatically every 30 seconds** without page reload!

---

## 🔄 How Background Refresh Works

### Timeline Example

```
14:00 - Server starts, cache loaded (data from 13:45)
14:15 - Background refresh #1 (automatic)
14:30 - Background refresh #2 (automatic)
14:45 - Background refresh #3 (automatic)
15:00 - User clicks "Get Latest Data" (manual)
15:15 - Background refresh #4 (automatic)
...continues every 15 minutes...
```

**Key Points:**
- Happens automatically in background
- No user interaction needed
- Continues even when no users are active
- Data never more than 15 minutes old

---

## 🔍 Monitoring

### Check Logs

Look for these messages in console:

**Startup:**
```
INFO:__main__:Initializing cache system...
INFO:__main__:Cache system initialized successfully
```

**Background Refresh:**
```
INFO:__main__:Background cache refresh started...
INFO:__main__:Successfully fetched 1250 records from API
INFO:__main__:Background cache refresh completed
```

**Manual Refresh:**
```
INFO:__main__:Manual cache refresh triggered by admin
```

### Check Cache File

```bash
# View cache file
cat data/api_cache.json

# Check file timestamp
ls -l data/api_cache.json
```

---

## ❓ FAQ

### Q: What happens on first server start?
**A:** Server fetches data from API (takes 3+ minutes), saves to cache, then starts serving instantly.

### Q: What if server restarts?
**A:** Cache loads from file instantly. If cache is old (>15 min), triggers background refresh.

### Q: Can users work during refresh?
**A:** Yes! Refresh happens in background. Users continue with cached data.

### Q: How do I force immediate refresh?
**A:** Click "Get Latest Data" button in dashboard.

### Q: What if API call fails?
**A:** Server keeps using old cache. Retries on next scheduled refresh.

### Q: Can I disable background refresh?
**A:** Set `USE_LOCAL_DATA = True` in app.py to use local JSON file instead.

### Q: How much disk space does cache use?
**A:** Typically 1-5 MB depending on data size. Negligible.

### Q: Does cache work in settings page?
**A:** Yes! All pages use the same cache system.

---

## 🚨 Troubleshooting

### Problem: Dashboard still slow
**Solution:** Check if `USE_LOCAL_DATA = False` in app.py. Check logs for errors.

### Problem: Cache not updating
**Solution:** Check logs for refresh errors. Verify API_URL is correct. Check network connectivity.

### Problem: "Updating Data..." stuck
**Solution:** API call may be taking longer than expected. Check logs. Wait up to 5 minutes.

### Problem: Cache file missing
**Solution:** Normal on first run. Server will create it automatically.

### Problem: Old data showing
**Solution:** Click "Get Latest Data" to force refresh. Check AUTO_REFRESH_INTERVAL_MINUTES setting.

---

## 📞 Support

### Check These First:
1. Server logs (console output)
2. Cache file exists: `data/api_cache.json`
3. API_TIMEOUT setting (should be 200+)
4. AUTO_REFRESH_INTERVAL_MINUTES setting

### Log Files to Check:
- Console output (where you ran `python app.py`)
- Look for ERROR or WARNING messages

---

## ✅ Success Indicators

You'll know it's working when:

✅ Dashboard loads in < 1 second
✅ Cache status shows in banner
✅ "Get Latest Data" button visible
✅ Logs show "Background cache refresh completed"
✅ `data/api_cache.json` file exists
✅ No 3-minute waits when clicking around

---

## 🎉 Enjoy!

Your application now provides a seamless, instant user experience while keeping data fresh automatically in the background!

**No more waiting!** 🚀
