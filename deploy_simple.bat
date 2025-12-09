@echo off
REM TTU Dashboard - Simple Deployment Script
REM This script sets up and runs the application in production mode

echo ========================================
echo TTU Dashboard - Production Deployment
echo ========================================
echo.

REM Set Python path
set PYTHON_PATH=C:\Users\8527\PYTHON\python_3_11_4\python.exe
set PIP_PATH=C:\Users\8527\PYTHON\python_3_11_4\Scripts\pip.exe

cd /d C:\Users\8527\PYTHON\ttu_dash

echo Checking Python installation...
"%PYTHON_PATH%" --version
if errorlevel 1 (
    echo ERROR: Python not found at %PYTHON_PATH%!
    echo Please verify Python installation path
    pause
    exit /b 1
)

echo.
echo Creating virtual environment...
if exist venv (
    echo Virtual environment already exists. Skipping creation...
) else (
    "%PYTHON_PATH%" -m venv venv
)

echo.
echo Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo Upgrading pip...
"%PYTHON_PATH%" -m pip install --upgrade pip

echo.
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Installing Waitress WSGI server...
pip install waitress

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo Starting production server on port 8888...
echo Server will be available at: http://localhost:8888
echo Press Ctrl+C to stop the server
echo.

"%PYTHON_PATH%" -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=8888, threads=4)"
