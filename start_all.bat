@echo off
chcp 65001 >nul
title WebGPT2API

cd /d "%~dp0"

echo Starting ngrok...
start "ngrok" "C:\Users\86150\Desktop\黑魔法\内网穿透\ngrok.exe" http --url=main-faithful-lion.ngrok-free.app 8501 --host-header="localhost:8501"

if not exist venv\Scripts\python.exe (
    echo [ERROR] Virtual environment not found at 'venv'!
    echo Running with system default python...
    python run_all.py
) else (
    venv\Scripts\python.exe run_all.py
)

