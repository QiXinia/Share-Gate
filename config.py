import os
import secrets
import logging
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from .env (override=False: real env vars win)
load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)

# Temp directory for image downloads/uploads
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Persistent data directory (user accounts, sessions, secret key)
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Telegram Bot
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# ---------------------------------------------------------------------------
# Browser CDP
# ---------------------------------------------------------------------------
CDP_URL = os.getenv("CDP_URL", "http://127.0.0.1:9222")

# Dedicated browser profile used when the orchestrator launches the browser.
# Previously a hard-coded personal Windows path; now defaults to a portable
# folder inside the project and can be overridden via .env.
BROWSER_PROFILE_DIR = os.getenv("BROWSER_PROFILE_DIR", "").strip() or os.path.join(
    BASE_DIR, "chrome-dev-profile"
)
# Debugging port extracted from CDP_URL (used by the orchestrator's probes).
try:
    from urllib.parse import urlparse
    _parsed_cdp = urlparse(CDP_URL)
    CDP_PORT = _parsed_cdp.port or 9222
    CDP_HOST = _parsed_cdp.hostname or "127.0.0.1"
except Exception:
    CDP_PORT = 9222
    CDP_HOST = "127.0.0.1"

# ---------------------------------------------------------------------------
# AI platforms (ChatGPT / Google Gemini)
# ---------------------------------------------------------------------------
# Static metadata for every supported provider. The host fragments are used to
# match already-open tabs in the connected browser.
PLATFORMS = {
    "chatgpt": {
        "label": "ChatGPT",
        "home_url": "https://chatgpt.com",
        "new_chat_url": "https://chatgpt.com",
        "host_fragments": ["chatgpt.com"],
        "login_url_fragments": ["auth.openai.com", "/auth/login"],
    },
    "gemini": {
        "label": "Google Gemini",
        "home_url": "https://gemini.google.com/app",
        "new_chat_url": "https://gemini.google.com/app",
        "host_fragments": ["gemini.google.com"],
        "login_url_fragments": ["accounts.google.com", "accounts.youtube.com"],
    },
}


def _parse_platforms(raw):
    """Parse a comma-separated platform list, always keeping a sane default."""
    requested = [chunk.strip().lower() for chunk in (raw or "").replace(";", ",").split(",")]
    requested = [p for p in requested if p in PLATFORMS]
    if not requested:
        requested = ["chatgpt"]
    # De-duplicate while preserving order.
    seen = set()
    result = []
    for p in requested:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


# Comma-separated list of enabled providers, e.g. "chatgpt" or "chatgpt,gemini".
AI_PLATFORMS = _parse_platforms(os.getenv("AI_PLATFORMS", "chatgpt"))
# The platform used by clients that do not pass an explicit platform argument.
DEFAULT_PLATFORM = os.getenv("DEFAULT_PLATFORM", "chatgpt").strip().lower()
if DEFAULT_PLATFORM not in AI_PLATFORMS:
    DEFAULT_PLATFORM = AI_PLATFORMS[0]

# ---------------------------------------------------------------------------
# Proxy settings for requests/bot and playwright
# ---------------------------------------------------------------------------
HTTP_PROXY = os.getenv("HTTP_PROXY")
HTTPS_PROXY = os.getenv("HTTPS_PROXY")

PROXIES = {}
if HTTP_PROXY:
    PROXIES["http"] = HTTP_PROXY
if HTTPS_PROXY:
    PROXIES["https"] = HTTPS_PROXY

# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------
def _get_bool(name, default=False):
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")


def _get_int(name, default):
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


# Bind 127.0.0.1 by default so the UI is NOT exposed to the LAN/public network
# unless the operator explicitly opts in. Set WEB_HOST=0.0.0.0 or
# ALLOW_REMOTE=true to accept external connections (authentication is then
# mandatory).
ALLOW_REMOTE = _get_bool("ALLOW_REMOTE", False)
WEB_HOST = os.getenv("WEB_HOST", "").strip()
if not WEB_HOST:
    WEB_HOST = "0.0.0.0" if ALLOW_REMOTE else "127.0.0.1"
WEB_PORT = _get_int("WEB_PORT", 8501)

# Trust the X-Forwarded-* headers only when behind a reverse proxy / tunnel.
TRUST_FORWARDED_HEADERS = _get_bool("TRUST_FORWARDED_HEADERS", False)

# ---------------------------------------------------------------------------
# Authentication / sessions
# ---------------------------------------------------------------------------
USERS_FILE = os.path.join(DATA_DIR, "users.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
SECRET_KEY_FILE = os.path.join(DATA_DIR, "secret.key")

# Bootstrap admin account: created automatically on first startup if it does
# not exist yet. After first boot the password can be changed via CLI/Web.
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()

# Allow self-service registration through the login page. Disabled by default;
# accounts are normally created by the admin (`python auth.py adduser`).
ALLOW_REGISTRATION = _get_bool("ALLOW_REGISTRATION", False)

SESSION_LIFETIME_DAYS = _get_int("SESSION_LIFETIME_DAYS", 7)
# Hard cap on concurrent sessions kept per user (oldest are pruned).
MAX_SESSIONS_PER_USER = _get_int("MAX_SESSIONS_PER_USER", 5)

# Standalone Streamlit console password (falls back to the admin password).
STREAMLIT_PASSWORD = os.getenv("STREAMLIT_PASSWORD", "").strip() or ADMIN_PASSWORD

# Brute-force protection: lock out an IP after N failures within a window.
LOGIN_MAX_FAILURES = _get_int("LOGIN_MAX_FAILURES", 5)
LOGIN_LOCK_MINUTES = _get_int("LOGIN_LOCK_MINUTES", 15)

# Upload limits (defense in depth for the JSON /api/chat endpoint).
MAX_UPLOAD_MB = _get_int("MAX_UPLOAD_MB", 20)
MAX_UPLOAD_FILES = _get_int("MAX_UPLOAD_FILES", 5)

# Thread pool ceiling for request handling threads.
WEB_MAX_WORKERS = _get_int("WEB_MAX_WORKERS", 32)

# ---------------------------------------------------------------------------
# Telegram access control
# ---------------------------------------------------------------------------
def _parse_id_list(raw):
    ids = set()
    for chunk in (raw or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            logging.getLogger(__name__).warning("Ignoring invalid numeric ID in config: %r", chunk)
    return ids


# Empty whitelist = allow everyone (legacy behavior); once any IDs are listed,
# only those Telegram users may interact with the bot.
ALLOWED_TELEGRAM_IDS = _parse_id_list(os.getenv("ALLOWED_TELEGRAM_IDS", ""))
# Admin IDs may use management commands (/log etc.). Defaults to the whitelist.
TELEGRAM_ADMIN_IDS = _parse_id_list(os.getenv("TELEGRAM_ADMIN_IDS", "")) or ALLOWED_TELEGRAM_IDS

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()

# Blocked upload extensions (script/executable content).
BLOCKED_UPLOAD_EXTS = {
    ".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".scr", ".com",
    ".sh", ".apk", ".jar", ".dll", ".sys", ".lnk",
}


def get_or_create_secret_key():
    """Return the persistent server secret, generating it on first run.

    Used to sign/scope session cookies. The file is written with owner-only
    permissions where the OS supports it.
    """
    if os.path.exists(SECRET_KEY_FILE):
        try:
            with open(SECRET_KEY_FILE, "r", encoding="utf-8") as fh:
                key = fh.read().strip()
            if key:
                return key
        except OSError:
            pass
    key = secrets.token_hex(32)
    try:
        with open(SECRET_KEY_FILE, "w", encoding="utf-8") as fh:
            fh.write(key)
        try:
            os.chmod(SECRET_KEY_FILE, 0o600)
        except OSError:
            pass
    except OSError as exc:
        logging.getLogger(__name__).error("Failed to persist secret key: %s", exc)
    return key


SECRET_KEY = get_or_create_secret_key()
