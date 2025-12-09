# TTU Dashboard - Windows Server Deployment Guide

## Prerequisites
- Windows Server with RDP access
- Python 3.11.4 installed at: `C:\Users\8527\PYTHON\python_3_11_4`
- Project files located at: `C:\Users\8527\PYTHON\ttu_dash`

## Deployment Options

### Option 1: Quick Deployment (Recommended for Testing)

**Using Batch File (Easiest):**
1. Copy all project files to `C:\Users\8527\PYTHON\ttu_dash`
2. Double-click `deploy_simple.bat`
3. The script will:
   - Create virtual environment
   - Install all dependencies
   - Install Waitress WSGI server
   - Start the application on port 8888

**Access the application:**
- Local: http://localhost:8888
- Network: http://YOUR_SERVER_IP:8888

### Option 2: PowerShell Deployment (More Control)

1. Open PowerShell as Administrator
2. Navigate to project directory:
   ```powershell
   cd C:\Users\8527\PYTHON\ttu_dash
   ```
3. Run the setup script:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   .\deploy_setup.ps1
   ```
4. After setup completes, run the application:
   ```powershell
   .\run_production.bat
   ```

### Option 3: Windows Service (Production - Auto-start on Boot)

**Install as Windows Service:**
1. Complete Option 2 first (run deploy_setup.ps1)
2. Open PowerShell as Administrator
3. Navigate to project directory:
   ```powershell
   cd C:\Users\8527\PYTHON\ttu_dash
   ```
4. Run the service installer:
   ```powershell
   .\install_service.ps1
   ```

**Service Management:**
```powershell
# Start service
nssm start TTUDashboard

# Stop service
nssm stop TTUDashboard

# Restart service
nssm restart TTUDashboard

# Check status
nssm status TTUDashboard

# Remove service
nssm remove TTUDashboard confirm
```

## Manual Setup (Step-by-Step)

If you prefer to set up manually:

```batch
# 1. Set Python path
set PYTHON_PATH=C:\Users\8527\PYTHON\python_3_11_4\python.exe

# 2. Navigate to project directory
cd C:\Users\8527\PYTHON\ttu_dash

# 3. Create virtual environment
"%PYTHON_PATH%" -m venv venv

# 4. Activate virtual environment
venv\Scripts\activate.bat

# 5. Upgrade pip
"%PYTHON_PATH%" -m pip install --upgrade pip

# 6. Install dependencies
pip install -r requirements.txt

# 7. Install Waitress (production WSGI server)
pip install waitress

# 8. Run the application
"%PYTHON_PATH%" -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=8888, threads=4)"
```

## Configuration

### Change Port Number
Edit the port number in the deployment scripts:
- `deploy_simple.bat`: Change `port=8888` to your desired port
- `run_production.ps1`: Change `$PORT = 8888` to your desired port
- `install_service.ps1`: Change `$PORT = 8888` to your desired port

### Firewall Configuration
To allow external access, add firewall rule:
```powershell
New-NetFirewallRule -DisplayName "TTU Dashboard" -Direction Inbound -LocalPort 8888 -Protocol TCP -Action Allow
```

### Environment Variables
The application uses these settings in `app.py`:
- `USE_LOCAL_DATA`: Set to `True` for local JSON data, `False` for API
- `API_URL`: Configure your API endpoint
- `SECRET_KEY`: Change for production security

## Troubleshooting

### Python Not Found
- Install Python from https://www.python.org/downloads/
- During installation, check "Add Python to PATH"

### Permission Denied
- Run PowerShell or Command Prompt as Administrator
- Check folder permissions for `C:\Users\8527\PYTHON\ttu_dash`

### Port Already in Use
- Change the port number in deployment scripts
- Or stop the service using that port:
  ```powershell
  netstat -ano | findstr :8888
  taskkill /PID <PID_NUMBER> /F
  ```

### Service Won't Start
- Check Windows Event Viewer for errors
- Verify Python path in service configuration
- Ensure all dependencies are installed in virtual environment

## Production Checklist

- [ ] Change `SECRET_KEY` in `app.py` to a secure random value
- [ ] Set `USE_LOCAL_DATA = False` if using live API
- [ ] Configure firewall rules for port 8888
- [ ] Test application access from network
- [ ] Set up automatic backups for `data/` folder
- [ ] Configure Windows Service for auto-start
- [ ] Set up monitoring/logging
- [ ] Document admin credentials securely

## Login Credentials

Default credentials (change in production):
- Admin: `admin` / `admin123`
- User: `user` / `user123`

## Support

For issues or questions:
1. Check application logs in the console output
2. Review Flask error messages
3. Check Windows Event Viewer for service errors
4. Verify all dependencies are installed correctly

## Server Specifications

**Waitress WSGI Server:**
- Production-ready WSGI server for Windows
- Multi-threaded (4 threads by default)
- Handles concurrent requests efficiently
- No external dependencies

**Performance:**
- Suitable for 100+ concurrent users
- Adjust threads in deployment scripts if needed
- Monitor server resources and scale as required
