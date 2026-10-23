@echo off
title ChatGPT-Share-Gate
setlocal enabledelayedexpansion

cd /d "%~dp0"

REM Switch the console to UTF-8 so non-ASCII output renders correctly.
chcp 65001 >nul 2>&1

echo ============================================
echo   ChatGPT-Share-Gate Environment ^& Setup
echo ============================================
echo.

REM 1. Locate a Python interpreter (python, then the py launcher).
set "PYTHON_CMD="
python --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    echo [ERROR] Python 3.8+ was not found.
    echo         Install Python and tick "Add Python to PATH", or use the py launcher.
    echo.
    pause
    exit /b 1
)
echo [INFO] Python interpreter: %PYTHON_CMD%
%PYTHON_CMD% --version

REM 2. Create the virtual environment if needed.
if not exist venv\Scripts\python.exe (
    echo [INFO] Virtual environment 'venv' not found. Creating it...
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
    echo [INFO] Virtual environment created.
)

REM 3. Install / update dependencies.
echo [INFO] Installing Python dependencies from requirements.txt...
venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Check your network connection.
    pause
    exit /b 1
)
echo [INFO] Dependencies are up to date.

REM 4. Create .env from the documented template if it does not exist.
if not exist .env (
    echo [INFO] .env not found. Generating one from .env.example ...
    copy /y .env.example .env >nul
    echo.
    echo [WARNING] A new .env has been generated from the template.
    echo [WARNING] Please edit .env and set at least ADMIN_PASSWORD (web login)
    echo [WARNING] and DINGTALK_APP_KEY / DINGTALK_APP_SECRET (if you use the robot), then run again.
    echo.
    pause
    exit /b 0
)

REM 5. Make sure at least one web login account exists.
venv\Scripts\python.exe -c "import auth, config; auth.AuthManager(config.USERS_FILE, config.SESSIONS_FILE).ensure_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)"
if errorlevel 1 (
    echo [WARNING] Could not initialise the admin account. You can create one later with:
    echo           venv\Scripts\python.exe auth.py adduser ^<username^> ^<password^>
)

REM 6. Launch the orchestrator.
echo [INFO] Launching services...
venv\Scripts\python.exe run_all.py

echo.
echo ============================================
echo   Services stopped.
echo ============================================
pause
