# TTU Dashboard - Production Deployment Setup Script
# Run this script with PowerShell as Administrator

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "TTU Dashboard - Production Deployment" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Set Python and project paths
$PYTHON_PATH = "C:\Users\8527\PYTHON\python_3_11_4\python.exe"
$PIP_PATH = "C:\Users\8527\PYTHON\python_3_11_4\Scripts\pip.exe"
$PROJECT_DIR = "C:\Users\8527\PYTHON\ttu_dash"
$VENV_DIR = "$PROJECT_DIR\venv"
$PORT = 8888

Write-Host "Python Path: $PYTHON_PATH" -ForegroundColor Yellow
Write-Host "Project Directory: $PROJECT_DIR" -ForegroundColor Yellow
Write-Host "Port: $PORT" -ForegroundColor Yellow
Write-Host ""

# Check if Python is installed
Write-Host "Checking Python installation..." -ForegroundColor Green
if (Test-Path $PYTHON_PATH) {
    $pythonVersion = & $PYTHON_PATH --version 2>&1
    Write-Host "Found: $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "ERROR: Python not found at $PYTHON_PATH!" -ForegroundColor Red
    Write-Host "Please verify Python installation path" -ForegroundColor Red
    exit 1
}

# Navigate to project directory
Write-Host ""
Write-Host "Navigating to project directory..." -ForegroundColor Green
Set-Location $PROJECT_DIR

# Create virtual environment
Write-Host ""
Write-Host "Creating virtual environment..." -ForegroundColor Green
if (Test-Path $VENV_DIR) {
    Write-Host "Virtual environment already exists. Removing old one..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $VENV_DIR
}
& $PYTHON_PATH -m venv venv

# Activate virtual environment
Write-Host ""
Write-Host "Activating virtual environment..." -ForegroundColor Green
& "$VENV_DIR\Scripts\Activate.ps1"

# Upgrade pip
Write-Host ""
Write-Host "Upgrading pip..." -ForegroundColor Green
& $PYTHON_PATH -m pip install --upgrade pip

# Install dependencies
Write-Host ""
Write-Host "Installing dependencies from requirements.txt..." -ForegroundColor Green
pip install -r requirements.txt

# Install production WSGI server (waitress)
Write-Host ""
Write-Host "Installing Waitress WSGI server for production..." -ForegroundColor Green
pip install waitress

# Create production run script
Write-Host ""
Write-Host "Creating production run script..." -ForegroundColor Green
$runScript = @"
# TTU Dashboard - Production Server
# This script runs the application using Waitress WSGI server

`$PYTHON_PATH = "C:\Users\8527\PYTHON\python_3_11_4\python.exe"
`$PROJECT_DIR = "C:\Users\8527\PYTHON\ttu_dash"
`$VENV_DIR = "`$PROJECT_DIR\venv"
`$PORT = 8888

Write-Host "Starting TTU Dashboard on port `$PORT..." -ForegroundColor Cyan

# Activate virtual environment
& "`$VENV_DIR\Scripts\Activate.ps1"

# Navigate to project directory
Set-Location `$PROJECT_DIR

# Run with Waitress
Write-Host "Server will be available at: http://localhost:`$PORT" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

& `$PYTHON_PATH -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=`$PORT, threads=4)"
"@

Set-Content -Path "$PROJECT_DIR\run_production.ps1" -Value $runScript

# Create batch file for easy execution
Write-Host ""
Write-Host "Creating batch file for easy execution..." -ForegroundColor Green
$batchScript = @"
@echo off
echo Starting TTU Dashboard Production Server...
powershell -ExecutionPolicy Bypass -File "C:\Users\8527\PYTHON\ttu_dash\run_production.ps1"
"@

Set-Content -Path "$PROJECT_DIR\run_production.bat" -Value $batchScript

# Create Windows Service installer script (optional)
Write-Host ""
Write-Host "Creating Windows Service installer script..." -ForegroundColor Green
$serviceScript = @"
# TTU Dashboard - Windows Service Setup
# Run this script as Administrator to install as Windows Service

`$SERVICE_NAME = "TTUDashboard"
`$PYTHON_PATH = "C:\Users\8527\PYTHON\python_3_11_4\python.exe"
`$PROJECT_DIR = "C:\Users\8527\PYTHON\ttu_dash"
`$VENV_PYTHON = "`$PROJECT_DIR\venv\Scripts\python.exe"
`$PORT = 8888

Write-Host "Installing NSSM (Non-Sucking Service Manager)..." -ForegroundColor Green

# Check if NSSM is installed
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Host "NSSM not found. Installing via Chocolatey..." -ForegroundColor Yellow
    
    # Check if Chocolatey is installed
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        Write-Host "Installing Chocolatey..." -ForegroundColor Yellow
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
        iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    }
    
    choco install nssm -y
}

Write-Host ""
Write-Host "Creating Windows Service..." -ForegroundColor Green

# Remove existing service if it exists
`$existingService = Get-Service -Name `$SERVICE_NAME -ErrorAction SilentlyContinue
if (`$existingService) {
    Write-Host "Stopping and removing existing service..." -ForegroundColor Yellow
    nssm stop `$SERVICE_NAME
    nssm remove `$SERVICE_NAME confirm
}

# Create service
nssm install `$SERVICE_NAME "`$VENV_PYTHON" "-c" "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=`$PORT, threads=4)"
nssm set `$SERVICE_NAME AppDirectory "`$PROJECT_DIR"
nssm set `$SERVICE_NAME DisplayName "TTU Dashboard"
nssm set `$SERVICE_NAME Description "TTU Safety & Health Excellence Dashboard"
nssm set `$SERVICE_NAME Start SERVICE_AUTO_START

Write-Host ""
Write-Host "Starting service..." -ForegroundColor Green
nssm start `$SERVICE_NAME

Write-Host ""
Write-Host "Service installed successfully!" -ForegroundColor Green
Write-Host "Service Name: `$SERVICE_NAME" -ForegroundColor Cyan
Write-Host "Status: Running" -ForegroundColor Cyan
Write-Host "URL: http://localhost:`$PORT" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service Management Commands:" -ForegroundColor Yellow
Write-Host "  Start:   nssm start `$SERVICE_NAME" -ForegroundColor White
Write-Host "  Stop:    nssm stop `$SERVICE_NAME" -ForegroundColor White
Write-Host "  Restart: nssm restart `$SERVICE_NAME" -ForegroundColor White
Write-Host "  Remove:  nssm remove `$SERVICE_NAME confirm" -ForegroundColor White
"@

Set-Content -Path "$PROJECT_DIR\install_service.ps1" -Value $serviceScript

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. To run the server manually:" -ForegroundColor White
Write-Host "   - Double-click: run_production.bat" -ForegroundColor Yellow
Write-Host "   - Or run: powershell -File run_production.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "2. To install as Windows Service (runs on startup):" -ForegroundColor White
Write-Host "   - Run PowerShell as Administrator" -ForegroundColor Yellow
Write-Host "   - Execute: .\install_service.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "Server will be available at: http://localhost:$PORT" -ForegroundColor Green
Write-Host "Or from network: http://YOUR_SERVER_IP:$PORT" -ForegroundColor Green
Write-Host ""
