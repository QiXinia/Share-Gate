@echo off
chcp 65001 >nul
title WebGPT2API - 一键启动

echo ============================================
echo   WebGPT2API 一键启动脚本
echo ============================================
echo.

REM --- 1. 启动 Chrome（指定 Profile + 远程调试端口 + 自动打开 ChatGPT）---
echo [1/3] 正在启动 Chrome (远程调试模式)...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
    --user-data-dir="C:\Users\86150\Chrome_Hermes_Profile" ^
    --remote-debugging-port=9222 ^
    "https://chatgpt.com"

REM 等待 Chrome 完全启动并加载页面
echo       等待 Chrome 就绪 (5 秒)...
timeout /t 5 /nobreak >nul

REM --- 2. 启动 Telegram Bot 后端 ---
echo [2/3] 正在启动 Telegram Bot 后端...
start "WebGPT2API - Bot" cmd /k "cd /d d:\pycharmProject\webgpt2api && venv\Scripts\python.exe bot.py"

REM 短暂间隔，避免两个进程同时抢占浏览器连接
timeout /t 2 /nobreak >nul

REM --- 3. 启动 Streamlit 前端 ---
echo [3/3] 正在启动 Streamlit 前端...
start "WebGPT2API - Streamlit" cmd /k "cd /d d:\pycharmProject\webgpt2api && venv\Scripts\streamlit.exe run app_streamlit.py"

echo.
echo ============================================
echo   全部服务已启动！
echo   - Chrome: https://chatgpt.com (调试端口 9222)
echo   - Telegram Bot: 独立窗口运行中
echo   - Streamlit 前端: http://localhost:8501
echo ============================================
echo.
echo 按任意键关闭此启动窗口（不影响已启动的服务）...
pause >nul
