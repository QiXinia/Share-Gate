import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CDP_URL = os.getenv("CDP_URL", "http://127.0.0.1:9222")

# Proxy settings for requests/bot and playwright
HTTP_PROXY = os.getenv("HTTP_PROXY")
HTTPS_PROXY = os.getenv("HTTPS_PROXY")

PROXIES = {}
if HTTP_PROXY:
    PROXIES["http"] = HTTP_PROXY
if HTTPS_PROXY:
    PROXIES["https"] = HTTPS_PROXY

# Temp directory for image downloads/uploads
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)
