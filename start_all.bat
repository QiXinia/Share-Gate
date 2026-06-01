@echo off
title ChatGPT-Share-Gate

cd /d "%~dp0"

echo ============================================
echo   ChatGPT-Share-Gate Environment ^& Setup
echo ============================================
echo.

REM 1. Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not added to system PATH!
    echo Please install Python 3.8+ first before running this script.
    echo.
    pause
    exit /b 1
)

REM 2. Check and Create Virtual Environment
if not exist venv\Scripts\python.exe (
    echo [INFO] Virtual environment 'venv' not found. Creating a new one...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        echo.
        pause
        exit /b 1
    )
    echo [INFO] Virtual environment created successfully.
)

REM 3. Install/Update Dependencies
echo [INFO] Verifying and installing Python dependencies from requirements.txt...
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies! Please check your network connection.
    echo.
    pause
    exit /b 1
)
echo [INFO] Dependencies are up to date.

REM 4. Check/Create .env file if it doesn't exist
if not exist .env (
    echo [INFO] .env file not found. Creating a template .env file...
    (
        echo TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
        echo CDP_URL=http://127.0.0.1:9222
        echo # Optional proxy settings:
        echo HTTP_PROXY=
        echo HTTPS_PROXY=
        echo.
        echo # Ngrok Config - Optional
        echo USE_NGROK=True
        echo NGROK_PATH=
        echo NGROK_TUNNEL_URL=main-faithful-lion.ngrok-free.app
    ) > .env
    echo.
    echo [WARNING] A new .env template has been generated!
    echo [WARNING] Please fill in your TELEGRAM_BOT_TOKEN in the .env file before running.
    echo.
    pause
    exit /b 0
)

REM 5. Run the main orchestrator (now including ngrok management)
echo [INFO] Launching services...
venv\Scripts\python.exe run_all.py

echo.
echo ============================================
echo   Services stopped.
echo ============================================
pause