@echo off
chcp 65001 >nul
title WebGPT2API

echo ============================================
echo   WebGPT2API
echo ============================================
echo.

echo [1/3] Starting Chrome...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\Users\86150\Chrome_Hermes_Profile" --remote-debugging-port=9222 "https://chatgpt.com"

echo       Waiting 8s for Chrome...
timeout /t 8 /nobreak >nul

echo [2/3] Starting Telegram Bot...
start "Bot" cmd /k "cd /d d:\pycharmProject\webgpt2api && venv\Scripts\python.exe bot.py"

timeout /t 2 /nobreak >nul

echo [3/3] Starting Streamlit...
start "Streamlit" cmd /k "cd /d d:\pycharmProject\webgpt2api && venv\Scripts\streamlit.exe run app_streamlit.py"

echo.
echo ============================================
echo   All services started!
echo   - Chrome: https://chatgpt.com (port 9222)
echo   - Telegram Bot: running
echo   - Streamlit: http://localhost:8501
echo ============================================
echo.
pause >nul
