import os
import re
import json
import gzip
import base64
import logging
import asyncio
import threading
import time
import signal
import socket
import secrets
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

import config
from auth import AuthManager
from chatgpt_browser import ChatGPTBrowser

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_FILE = os.path.join(config.BASE_DIR, "web_server.log")
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger("web_server")

# Quiet the noisy default request logger; we emit our own structured lines.
logging.getLogger("http.server").setLevel(logging.WARNING)

STATIC_ROOT = os.path.realpath(os.path.join(config.BASE_DIR, "static"))
MAX_BODY_BYTES = config.MAX_UPLOAD_MB * 1024 * 1024
# Hard cap on queued browser tasks across web users (FIFO is enforced in the
# browser layer; this only rejects obvious overload early).
MAX_WAITING_TASKS = 10

SESSION_COOKIE = "sg_session"
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# ---------------------------------------------------------------------------
# Asyncio event loop driving the browser (single background thread)
# ---------------------------------------------------------------------------
loop = asyncio.new_event_loop()


def start_event_loop(loop_obj):
    asyncio.set_event_loop(loop_obj)
    loop_obj.run_forever()


loop_thread = threading.Thread(target=start_event_loop, args=(loop,), daemon=True)
loop_thread.start()

browser = ChatGPTBrowser(cdp_url=config.CDP_URL, temp_dir=config.TEMP_DIR)

auth_manager = AuthManager(
    config.USERS_FILE,
    config.SESSIONS_FILE,
    session_lifetime_days=config.SESSION_LIFETIME_DAYS,
    max_sessions_per_user=config.MAX_SESSIONS_PER_USER,
    max_failures=config.LOGIN_MAX_FAILURES,
    lock_minutes=config.LOGIN_LOCK_MINUTES,
)
# Bootstrap the admin account from .env on first startup.
auth_manager.ensure_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)

startup_future = asyncio.run_coroutine_threadsafe(browser.start(), loop)
try:
    startup_future.result(timeout=15)
    logger.info("Successfully connected to ChatGPT browser instance on startup.")
except Exception as ex:
    logger.error("Failed to connect to browser on startup: %s", ex)


# ---------------------------------------------------------------------------
# HTTP server with a bounded thread pool
# ---------------------------------------------------------------------------
class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer backed by a reusable thread pool with backpressure."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass):
        self._executor = ThreadPoolExecutor(
            max_workers=config.WEB_MAX_WORKERS, thread_name_prefix="http-worker"
        )
        # At most 2x workers of queued (not yet running) requests.
        self._slots = threading.BoundedSemaphore(config.WEB_MAX_WORKERS * 2)
        super().__init__(server_address, RequestHandlerClass)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self._reject_request(request)
            return
        def runner():
            try:
                self.process_request_thread(request, client_address)
            finally:
                self._slots.release()
        try:
            self._executor.submit(runner)
        except RuntimeError:
            self._slots.release()
            self.shutdown_request(request)

    @staticmethod
    def _reject_request(request):
        payload = json.dumps(
            {"status": "error", "message": "服务器繁忙，请稍后再试"},
            ensure_ascii=False,
        ).encode("utf-8")
        raw = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Content-Length: " + str(len(payload)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + payload
        )
        try:
            request.sendall(raw)
        except OSError:
            pass
        finally:
            try:
                request.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            request.close()

    def server_close(self):
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # Python < 3.9 has no cancel_futures
            self._executor.shutdown(wait=False)
        super().server_close()


class ChatGPTWebHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ShareGate/1.0"
    sys_version = ""

    # ------------------------------------------------------------------
    # Infrastructure helpers
    # ------------------------------------------------------------------
    def log_message(self, fmt, *args):
        # Route through our logger instead of stderr; never log headers/cookies.
        logger.debug("%s - %s", self.client_ip, fmt % args)

    @property
    def client_ip(self):
        if config.TRUST_FORWARDED_HEADERS:
            xff = self.headers.get("X-Forwarded-For", "")
            if xff:
                return xff.split(",")[0].strip()
        return self.client_address[0]

    def is_https(self):
        if config.TRUST_FORWARDED_HEADERS:
            return self.headers.get("X-Forwarded-Proto", "http").lower() == "https"
        return False

    def _safe_static_path(self, url_path):
        """Map a URL path to a file inside static/, defeating path traversal."""
        clean = url_path.split('?', 1)[0].split('#', 1)[0]
        # Strip leading slashes and URL-encoded variants AFTER decoding
        try:
            clean = urlparse(clean).path
        except Exception:
            return None
        rel = clean.lstrip('/')
        if not rel:
            rel = 'index.html'
        candidate = os.path.realpath(os.path.join(STATIC_ROOT, rel))
        # Ensure the resolved path stays inside STATIC_ROOT (blocks ../ traversal).
        if os.path.commonpath([candidate, STATIC_ROOT]) != STATIC_ROOT:
            return None
        return candidate

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=()",
        )
        # JS libraries are self-hosted under /vendor. 'unsafe-eval' is required
        # by the Tailwind in-browser JIT runtime; 'unsafe-inline' is required by
        # the in-page Vue app. Only style/font CDNs remain on the allow-list.
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
            "https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        self.send_header("Content-Security-Policy", csp)

    def _maybe_gzip(self, body: bytes, content_type: str):
        """Return (body, headers_list), gzipping when the client accepts it."""
        ae = self.headers.get("Accept-Encoding", "")
        if "gzip" in ae.lower() and len(body) > 1024 and content_type.startswith(
            ("text/", "application/json", "application/javascript")
        ):
            return gzip.compress(body, compresslevel=6), [("Content-Encoding", "gzip")]
        return body, []

    def send_json_response(self, data, status_code=200, extra_headers=None, cookies=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        body, enc_headers = self._maybe_gzip(body, "application/json; charset=utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        for name, value in enc_headers:
            self.send_header(name, value)
        for name, value in extra_headers or []:
            self.send_header(name, value)
        for cookie in cookies or []:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json_error(self, status_code, message, extra_headers=None):
        self.send_json_response(
            {"status": "error", "message": message},
            status_code=status_code,
            extra_headers=extra_headers,
        )

    def _session_cookie(self, token, clear=False):
        max_age = 0 if clear else config.SESSION_LIFETIME_DAYS * 86400
        parts = [
            f"{SESSION_COOKIE}={'' if clear else token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={max_age}",
        ]
        if self.is_https():
            parts.append("Secure")
        return "; ".join(parts)

    def current_user(self):
        """Resolve the logged-in user from the session cookie, or None."""
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        try:
            cookie = SimpleCookie()
            cookie.load(raw_cookie)
            token = cookie.get(SESSION_COOKIE)
            if not token:
                return None
            return auth_manager.get_session_user(token.value)
        except Exception:
            return None

    def require_user(self):
        """Return the user dict or send 401 and return None."""
        user = self.current_user()
        if not user:
            self.send_json_error(401, "未登录或登录已过期，请重新登录")
            return None
        return user

    def require_admin(self):
        user = self.require_user()
        if not user:
            return None
        if user.get("role") != "admin":
            self.send_json_error(403, "需要管理员权限")
            return None
        return user

    def _read_json_body(self, max_bytes=MAX_BODY_BYTES):
        """Read and parse a JSON body, enforcing the size ceiling."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self.send_json_error(400, "无效的 Content-Length")
            return None
        if length <= 0:
            return {}
        if length > max_bytes:
            # We are not going to drain the oversized body, so the keep-alive
            # connection must be closed to avoid desyncing the next request.
            self.close_connection = True
            self.send_json_error(
                413,
                f"请求体过大（上限 {config.MAX_UPLOAD_MB} MB）",
                extra_headers=[("Connection", "close")],
            )
            return None
        # Read at most max_bytes + 1 to also catch bodies that lie about length.
        raw = self.rfile.read(min(length, max_bytes + 1))
        if len(raw) > max_bytes:
            self.close_connection = True
            self.send_json_error(
                413, "请求体超出大小限制",
                extra_headers=[("Connection", "close")],
            )
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            self.send_json_error(400, f"无效的 JSON 请求体: {exc}")
            return None
        if not isinstance(data, dict):
            self.send_json_error(400, "请求体必须是 JSON 对象")
            return None
        return data

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json_response({"status": "ok"})
        elif path == "/api/auth/config":
            self.send_json_response(
                {
                    "allow_registration": config.ALLOW_REGISTRATION,
                    "max_upload_mb": config.MAX_UPLOAD_MB,
                    "max_upload_files": config.MAX_UPLOAD_FILES,
                }
            )
        elif path == "/api/auth/me":
            user = self.current_user()
            if user:
                self.send_json_response(
                    {"status": "success", "user": user}
                )
            else:
                self.send_json_error(401, "未登录")
        elif path == "/api/status":
            self._require_get_user_then(self.handle_status)
        elif path.startswith("/api/"):
            self.send_json_error(404, "API 接口不存在")
        else:
            self.serve_static(path)

    def do_HEAD(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.send_json_error(405, "不支持的方法")
        else:
            self.serve_static(path, head=True)

    def do_POST(self):
        path = urlparse(self.path).path
        # Public auth endpoints
        if path == "/api/auth/login":
            self.handle_login()
            return
        if path == "/api/auth/register":
            self.handle_register()
            return
        # Everything else requires authentication
        if path == "/api/auth/logout":
            self.handle_logout()
        elif path == "/api/new_chat":
            self._require_post_user_then(self.handle_new_chat)
        elif path == "/api/chat":
            self._require_post_user_then(self.handle_chat)
        elif path == "/api/admin/users":
            admin = self.require_admin()
            if admin:
                self.handle_admin_create_user()
        else:
            self.send_json_error(404, "API 接口不存在")

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path == "/api/admin/users":
            admin = self.require_admin()
            if admin:
                self.handle_admin_delete_user()
        else:
            self.send_json_error(404, "API 接口不存在")

    def do_OPTIONS(self):
        # Same-origin only: no CORS negotiation needed.
        self.send_json_error(405, "不支持的方法")

    def _require_get_user_then(self, handler):
        user = self.require_user()
        if user:
            handler(user)

    def _require_post_user_then(self, handler):
        user = self.require_user()
        if user:
            handler(user)

    # ------------------------------------------------------------------
    # Static files
    # ------------------------------------------------------------------
    def serve_static(self, path, head=False):
        file_path = self._safe_static_path(path)
        if not file_path or not os.path.isfile(file_path):
            self.send_json_error(404, "页面不存在")
            return
        try:
            stat = os.stat(file_path)
            ctype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            if file_path.endswith(".html"):
                ctype = "text/html; charset=utf-8"

            # Conditional request support (If-Modified-Since / If-None-Match).
            etag = f'"{stat.st_size:x}-{int(stat.st_mtime):x}"'
            inm = self.headers.get("If-None-Match")
            ims = self.headers.get("If-Modified-Since")
            if inm and inm == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self._security_headers()
                self.end_headers()
                return
            if ims:
                try:
                    from email.utils import parsedate_to_datetime
                    if parsedate_to_datetime(ims).timestamp() >= stat.st_mtime:
                        self.send_response(304)
                        self.send_header("ETag", etag)
                        self._security_headers()
                        self.end_headers()
                        return
                except Exception:
                    pass

            with open(file_path, "rb") as fh:
                body = fh.read()
            body, enc_headers = self._maybe_gzip(body, ctype)

            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", etag)
            if os.path.basename(file_path) == "index.html":
                self.send_header("Cache-Control", "no-cache")
            else:
                self.send_header("Cache-Control", "public, max-age=86400")
            self._security_headers()
            for name, value in enc_headers:
                self.send_header(name, value)
            self.end_headers()
            if not head:
                self.wfile.write(body)
        except (OSError, ConnectionError):
            return

    # ------------------------------------------------------------------
    # Auth endpoints
    # ------------------------------------------------------------------
    def handle_login(self):
        body = self._read_json_body(max_bytes=4096)
        if body is None:
            return
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""

        allowed, retry_after = auth_manager.check_rate_limit(self.client_ip)
        if not allowed:
            logger.warning("Login rate-limited for ip=%s user=%r", self.client_ip, username)
            self.send_json_error(
                429,
                f"登录失败次数过多，请 {retry_after // 60 + 1} 分钟后再试",
                extra_headers=[("Retry-After", str(retry_after))],
            )
            return

        user = auth_manager.authenticate(username, password)
        if not user:
            failures = auth_manager.record_failure(self.client_ip)
            remaining = max(0, config.LOGIN_MAX_FAILURES - failures)
            logger.warning("Failed login ip=%s user=%r (failures=%d)", self.client_ip, username, failures)
            self.send_json_error(
                401,
                f"用户名或密码错误，剩余尝试次数 {remaining} 次"
                if remaining > 0
                else f"登录失败次数过多，请 {config.LOGIN_LOCK_MINUTES} 分钟后再试",
            )
            return

        auth_manager.record_success(self.client_ip)
        token = auth_manager.create_session(user["username"])
        logger.info("User logged in: %s (ip=%s)", user["username"], self.client_ip)
        self.send_json_response(
            {"status": "success", "user": user},
            cookies=[self._session_cookie(token)],
        )

    def handle_register(self):
        if not config.ALLOW_REGISTRATION:
            self.send_json_error(403, "本站未开放注册，请联系管理员创建账户")
            return
        body = self._read_json_body(max_bytes=4096)
        if body is None:
            return
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        ok, msg = auth_manager.create_user(username, password, role="user")
        if not ok:
            self.send_json_error(400, msg)
            return
        token = auth_manager.create_session(username)
        logger.info("New user registered: %s (ip=%s)", username, self.client_ip)
        self.send_json_response(
            {"status": "success", "user": {"username": username, "role": "user"}},
            cookies=[self._session_cookie(token)],
        )

    def handle_logout(self):
        raw_cookie = self.headers.get("Cookie")
        if raw_cookie:
            try:
                cookie = SimpleCookie()
                cookie.load(raw_cookie)
                token = cookie.get(SESSION_COOKIE)
                if token:
                    auth_manager.revoke_session(token.value)
            except Exception:
                pass
        self.send_json_response(
            {"status": "success"},
            cookies=[self._session_cookie("", clear=True)],
        )

    # ------------------------------------------------------------------
    # Admin user management
    # ------------------------------------------------------------------
    def handle_admin_create_user(self):
        body = self._read_json_body(max_bytes=4096)
        if body is None:
            return
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        role = "admin" if body.get("role") == "admin" else "user"
        ok, msg = auth_manager.create_user(username, password, role=role)
        if not ok:
            self.send_json_error(400, msg)
            return
        self.send_json_response({"status": "success", "message": msg})

    def handle_admin_delete_user(self):
        body = self._read_json_body(max_bytes=4096)
        if body is None:
            return
        username = (body.get("username") or "").strip()
        ok, msg = auth_manager.delete_user(username)
        if not ok:
            self.send_json_error(400, msg)
            return
        self.send_json_response({"status": "success", "message": msg})

    # ------------------------------------------------------------------
    # Browser-backed endpoints
    # ------------------------------------------------------------------
    def handle_status(self, user):
        future = asyncio.run_coroutine_threadsafe(browser.get_status(), loop)
        try:
            status = future.result(timeout=5)
            self.send_json_response(status)
        except Exception as e:
            logger.error("Error fetching status: %s", e)
            self.send_json_response({"status": "error", "message": str(e)}, status_code=500)

    def _resolve_platform(self, body):
        """Validate and normalise the requested platform from a JSON body."""
        platform = body.get("platform") if isinstance(body, dict) else None
        platform = (platform or config.DEFAULT_PLATFORM).strip().lower()
        if platform not in config.AI_PLATFORMS:
            self.send_json_error(400, f"平台 {platform} 未启用或不受支持")
            return None
        return platform

    def handle_new_chat(self, user):
        body = self._read_json_body()
        if body is None:
            return
        platform = self._resolve_platform(body)
        if platform is None:
            return
        future = asyncio.run_coroutine_threadsafe(browser.new_chat(platform=platform), loop)
        try:
            result = future.result(timeout=30)
            self.send_json_response(result)
        except Exception as e:
            logger.error("Error resetting session: %s", e)
            self.send_json_response({"status": "error", "message": str(e)}, status_code=500)

    def handle_chat(self, user):
        body = self._read_json_body()
        if body is None:
            return

        prompt = body.get('prompt', '')
        if not isinstance(prompt, str):
            self.send_json_error(400, "prompt 必须是字符串")
            return
        prompt = prompt.strip()
        files = body.get('files', [])
        features = body.get('features', {}) or {}
        if not isinstance(files, list) or not isinstance(features, dict):
            self.send_json_error(400, "请求参数格式错误")
            return
        platform = self._resolve_platform(body)
        if platform is None:
            return
        if not prompt and not files:
            self.send_json_error(400, "消息内容不能为空")
            return
        if len(files) > config.MAX_UPLOAD_FILES:
            self.send_json_error(400, f"单次最多上传 {config.MAX_UPLOAD_FILES} 个文件")
            return
        waiting = max(0, browser.pending_count - browser.active_count)
        if waiting >= MAX_WAITING_TASKS:
            self.send_json_error(503, "队列已满，请等待当前任务完成后再提交")
            return

        temp_files = []
        try:
            # Decode base64 attachments and write them to disk temporarily.
            for f in files:
                if not isinstance(f, dict):
                    self.send_json_error(400, "files 数组格式错误")
                    return
                name = os.path.basename(f.get('name', 'file'))
                name = SAFE_FILENAME_RE.sub("_", name) or "file"
                data = f.get('data', '')
                if not isinstance(data, str) or not data:
                    self.send_json_error(400, f"文件 {name} 数据缺失")
                    return

                ext = os.path.splitext(name)[1].lower()
                if ext in config.BLOCKED_UPLOAD_EXTS:
                    self.send_json_error(400, f"出于安全考虑，不允许上传 {ext} 类型文件")
                    return

                if ',' in data:
                    data = data.split(',', 1)[1]
                try:
                    file_bytes = base64.b64decode(data, validate=True)
                except Exception:
                    self.send_json_error(400, f"文件 {name} 不是有效的 base64 数据")
                    return
                if len(file_bytes) > MAX_BODY_BYTES:
                    self.send_json_error(413, f"文件 {name} 超出大小限制")
                    return

                temp_filename = f"web_{int(time.time()*1000)}_{secrets.token_hex(4)}_{name}"
                temp_path = os.path.join(config.TEMP_DIR, temp_filename)
                with open(temp_path, "wb") as fh:
                    fh.write(file_bytes)
                temp_files.append(temp_path)
                logger.info("Saved upload from %s: %s (%d bytes)",
                            user["username"], temp_path, len(file_bytes))

            logger.info("Chat request by %s on [%s]: prompt=%r files=%d",
                        user["username"], platform, prompt[:60], len(temp_files))

            # Feature toggles are ChatGPT-specific; ignore them on Gemini.
            future = asyncio.run_coroutine_threadsafe(
                browser.send_message(
                    prompt, file_paths=temp_files,
                    features=features if platform == "chatgpt" else None,
                    platform=platform,
                ),
                loop
            )
            result = future.result(timeout=360)  # 6 minutes max

            # Convert returned image paths to base64 for the client.
            if result.get("status") == "success":
                base64_images = []
                for img_path in result.get("images", []):
                    if os.path.exists(img_path):
                        try:
                            with open(img_path, "rb") as image_file:
                                base64_images.append(
                                    base64.b64encode(image_file.read()).decode('utf-8')
                                )
                            os.remove(img_path)
                        except Exception as img_err:
                            logger.error("Error encoding/deleting image %s: %s", img_path, img_err)
                result["images"] = base64_images

            self.send_json_response(result)

        except Exception as e:
            logger.error("Error handling chat request: %s", e)
            self.send_json_response({"status": "error", "message": str(e)}, status_code=500)
        finally:
            for path in temp_files:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError as err:
                        logger.warning("Failed to remove temp file %s: %s", path, err)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------
def run_server(host=None, port=None):
    host = host or config.WEB_HOST
    port = port or config.WEB_PORT
    httpd = BoundedThreadingHTTPServer((host, port), ChatGPTWebHandler)

    def shutdown_handler(signum, frame):
        logger.info("Shutdown signal received, stopping Web Server...")
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, shutdown_handler)
        except (ValueError, OSError):
            # Not available in all thread/platform contexts.
            pass

    scope = "all interfaces (0.0.0.0)" if host == "0.0.0.0" else host
    logger.info("Starting Web Server on %s:%s (listening on %s)...", host, port, scope)
    if host == "0.0.0.0" and not auth_manager.user_count():
        logger.warning(
            "Server is exposed on all interfaces but no user accounts exist yet! "
            "Create one with: python auth.py adduser <name> <password>"
        )
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        logger.info("Web Server stopped.")


if __name__ == "__main__":
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    run_server()
