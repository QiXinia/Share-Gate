#!/usr/bin/env bash
# One-click launcher for ChatGPT Share Gate on macOS / Linux.
set -euo pipefail

cd "$(dirname "$0")"

# Pick a Python interpreter.
PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN=python
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "[ERROR] Python 3.8+ was not found. Please install Python 3 first." >&2
    exit 1
fi
echo "[INFO] Python interpreter: $PYTHON_BIN ($($PYTHON_BIN --version))"

# Create the virtual environment.
if [ ! -x "venv/bin/python" ]; then
    echo "[INFO] Creating virtual environment 'venv'..."
    "$PYTHON_BIN" -m venv venv
fi

# Install dependencies.
echo "[INFO] Installing dependencies..."
venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1 || true
venv/bin/python -m pip install -r requirements.txt

# Prepare .env from the template.
if [ ! -f ".env" ]; then
    echo "[INFO] Creating .env from .env.example ..."
    cp .env.example .env
    echo "[WARNING] Please edit .env (set ADMIN_PASSWORD / TELEGRAM_BOT_TOKEN) and re-run."
    exit 0
fi

# Initialise the bootstrap admin account.
venv/bin/python -c "import auth, config; auth.AuthManager(config.USERS_FILE, config.SESSIONS_FILE).ensure_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)" || true

# Launch the orchestrator.
echo "[INFO] Launching services..."
exec venv/bin/python run_all.py
