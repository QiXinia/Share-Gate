"""User authentication and session management for the Share-Gate web server.

Design goals:
  * Zero third-party dependencies — only the Python standard library, so the
    Windows one-click installer never needs to compile native packages.
  * Safe password storage (PBKDF2-HMAC-SHA256 with a per-user random salt).
  * Server-side, revocable sessions (random tokens stored on disk), so logout
    and "kick user" take effect immediately.
  * Brute-force protection via per-IP failure counters with lockout windows.
  * Atomic JSON persistence (temp file + os.replace) with conservative file
    permissions.

Usage (CLI):
  python auth.py init-admin                 # create/reset the .env admin account
  python auth.py adduser <name> [password]  # create an account (interactive pw)
  python auth.py passwd <name> [password]   # reset a password
  python auth.py deluser <name>             # delete an account
  python auth.py list                       # list accounts
"""

import os
import re
import sys
import json
import time
import base64
import getpass
import hashlib
import hmac
import secrets
import logging
import tempfile
import threading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hashing parameters
# ---------------------------------------------------------------------------
_PBKDF2_ALGO = "sha256"
_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LEN = 6
MAX_PASSWORD_LEN = 128


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Return a self-describing PBKDF2 hash string."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGO, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return "{}${}${}${}".format(
        _PBKDF2_ALGO,
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification against a stored hash produced above."""
    try:
        algo, iterations, salt_b64, hash_b64 = stored.split("$")
        iterations = int(iterations)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac(
        algo, password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(candidate, expected)


def validate_credentials(username: str, password: str):
    """Return (ok, error_message)."""
    if not username or not USERNAME_RE.match(username):
        return False, "用户名需为 3-32 位字母、数字或 _.- 字符"
    if not password or len(password) < MIN_PASSWORD_LEN:
        return False, f"密码至少需要 {MIN_PASSWORD_LEN} 位"
    if len(password) > MAX_PASSWORD_LEN:
        return False, f"密码不能超过 {MAX_PASSWORD_LEN} 位"
    return True, ""


class AuthManager:
    """File-backed user directory, session store and login rate limiter."""

    def __init__(
        self,
        users_file,
        sessions_file,
        session_lifetime_days=7,
        max_sessions_per_user=5,
        max_failures=5,
        lock_minutes=15,
    ):
        self.users_file = users_file
        self.sessions_file = sessions_file
        self.session_lifetime = session_lifetime_days * 86400
        self.max_sessions_per_user = max_sessions_per_user
        self.max_failures = max_failures
        self.lock_minutes = lock_minutes

        # In-process guards; persistence is atomic via os.replace.
        self._users_lock = threading.RLock()
        self._sessions_lock = threading.RLock()

        self._users = self._load_json(self.users_file, default={})
        self._sessions = self._load_json(self.sessions_file, default={})
        # ip -> {"count": int, "lock_until": epoch}
        self._failures = {}
        self._prune_expired_sessions()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _load_json(path, default):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, type(default)) else default
        except FileNotFoundError:
            return default
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read %s: %s", path, exc)
            return default

    @staticmethod
    def _atomic_write_json(path, data):
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # User account management
    # ------------------------------------------------------------------
    def ensure_admin(self, username, password):
        """Create the bootstrap admin from .env on first startup."""
        with self._users_lock:
            if not username:
                return
            if username in self._users:
                return
            if not password:
                logger.warning(
                    "Admin account '%s' does not exist and ADMIN_PASSWORD is "
                    "not set. Run `python auth.py adduser` to create accounts.",
                    username,
                )
                return
            ok, err = validate_credentials(username, password)
            if not ok:
                logger.error("Cannot create bootstrap admin: %s", err)
                return
            self._users[username] = {
                "password": hash_password(password),
                "role": "admin",
                "created_at": time.time(),
            }
            self._atomic_write_json(self.users_file, self._users)
            logger.info("Bootstrap admin account '%s' created.", username)

    def create_user(self, username, password, role="user"):
        ok, err = validate_credentials(username, password)
        if not ok:
            return False, err
        if role not in ("user", "admin"):
            role = "user"
        with self._users_lock:
            if username in self._users:
                return False, "用户名已存在"
            self._users[username] = {
                "password": hash_password(password),
                "role": role,
                "created_at": time.time(),
            }
            self._atomic_write_json(self.users_file, self._users)
        return True, "用户创建成功"

    def change_password(self, username, new_password):
        ok, err = validate_credentials(username, new_password)
        if not ok:
            return False, err
        with self._users_lock:
            if username not in self._users:
                return False, "用户不存在"
            self._users[username]["password"] = hash_password(new_password)
            self._users[username]["password_changed_at"] = time.time()
            self._atomic_write_json(self.users_file, self._users)
        # Changing password invalidates all existing sessions for the user.
        self.revoke_user_sessions(username)
        return True, "密码修改成功，请重新登录"

    def delete_user(self, username):
        with self._users_lock:
            if username not in self._users:
                return False, "用户不存在"
            admins = [u for u, v in self._users.items() if v.get("role") == "admin"]
            if username in admins and len(admins) == 1:
                return False, "不能删除唯一的管理员账户"
            del self._users[username]
            self._atomic_write_json(self.users_file, self._users)
        self.revoke_user_sessions(username)
        return True, "用户已删除"

    def list_users(self):
        with self._users_lock:
            return [
                {
                    "username": name,
                    "role": info.get("role", "user"),
                    "created_at": info.get("created_at"),
                }
                for name, info in self._users.items()
            ]

    def user_count(self):
        with self._users_lock:
            return len(self._users)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def authenticate(self, username, password):
        """Return user info dict on success, None on failure."""
        with self._users_lock:
            user = self._users.get(username)
            if not user:
                # Perform a dummy hash to keep timing roughly uniform.
                verify_password(password, hash_password("dummy-password"))
                return None
            if not verify_password(password, user.get("password", "")):
                return None
            return {"username": username, "role": user.get("role", "user")}

    # ------------------------------------------------------------------
    # Login rate limiting
    # ------------------------------------------------------------------
    def check_rate_limit(self, ip):
        """Return (allowed: bool, retry_after_seconds: int)."""
        entry = self._failures.get(ip)
        if not entry:
            return True, 0
        if entry.get("lock_until", 0) > time.time():
            return False, int(entry["lock_until"] - time.time()) + 1
        # Lock window elapsed -> reset.
        if entry.get("lock_until"):
            self._failures.pop(ip, None)
        return True, 0

    def record_failure(self, ip):
        entry = self._failures.setdefault(ip, {"count": 0, "lock_until": 0})
        entry["count"] += 1
        if entry["count"] >= self.max_failures:
            entry["lock_until"] = time.time() + self.lock_minutes * 60
        return entry["count"]

    def record_success(self, ip):
        self._failures.pop(ip, None)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_session(self, username):
        now = time.time()
        token = secrets.token_urlsafe(32)
        with self._sessions_lock:
            # Enforce per-user session cap.
            own = [
                (tok, meta)
                for tok, meta in self._sessions.items()
                if meta.get("username") == username and meta.get("expires", 0) > now
            ]
            own.sort(key=lambda item: item[1].get("created", 0))
            while len(own) >= self.max_sessions_per_user:
                old_token, _ = own.pop(0)
                self._sessions.pop(old_token, None)
            self._sessions[token] = {
                "username": username,
                "created": now,
                "expires": now + self.session_lifetime,
            }
            self._atomic_write_json(self.sessions_file, self._sessions)
        return token

    def get_session_user(self, token):
        """Return the user dict for a valid token, else None."""
        if not token:
            return None
        now = time.time()
        with self._sessions_lock:
            meta = self._sessions.get(token)
            if not meta:
                return None
            if meta.get("expires", 0) < now:
                self._sessions.pop(token, None)
                self._atomic_write_json(self.sessions_file, self._sessions)
                return None
            username = meta.get("username")
            user = self._users.get(username)
            if not user:
                self._sessions.pop(token, None)
                return None
            return {"username": username, "role": user.get("role", "user")}

    def revoke_session(self, token):
        with self._sessions_lock:
            if token in self._sessions:
                del self._sessions[token]
                self._atomic_write_json(self.sessions_file, self._sessions)

    def revoke_user_sessions(self, username):
        with self._sessions_lock:
            tokens = [t for t, m in self._sessions.items() if m.get("username") == username]
            for token in tokens:
                self._sessions.pop(token, None)
            if tokens:
                self._atomic_write_json(self.sessions_file, self._sessions)

    def _prune_expired_sessions(self):
        now = time.time()
        with self._sessions_lock:
            expired = [t for t, m in self._sessions.items() if m.get("expires", 0) < now]
            for token in expired:
                self._sessions.pop(token, None)
            if expired:
                self._atomic_write_json(self.sessions_file, self._sessions)


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------
def _get_auth_manager():
    import config
    return AuthManager(
        config.USERS_FILE,
        config.SESSIONS_FILE,
        session_lifetime_days=config.SESSION_LIFETIME_DAYS,
        max_sessions_per_user=config.MAX_SESSIONS_PER_USER,
        max_failures=config.LOGIN_MAX_FAILURES,
        lock_minutes=config.LOGIN_LOCK_MINUTES,
    )


def _prompt_password(confirm=True):
    password = getpass.getpass("密码（输入时不显示）: ")
    if confirm:
        again = getpass.getpass("再次输入密码: ")
        if password != again:
            print("两次输入的密码不一致。")
            return None
    return password


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    auth = _get_auth_manager()

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    cmd = argv[0]

    if cmd == "init-admin":
        import config
        if not config.ADMIN_PASSWORD:
            print("ADMIN_PASSWORD 未在 .env 中设置，跳过。可使用 adduser 命令手动创建。")
            return 1
        auth.ensure_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)
        print(f"管理员账户 '{config.ADMIN_USERNAME}' 已就绪。")
        return 0

    if cmd == "list":
        users = auth.list_users()
        if not users:
            print("（暂无账户）")
            return 0
        for user in users:
            print(f"- {user['username']:<20} role={user['role']}")
        return 0

    if cmd == "adduser":
        if len(argv) < 2:
            print("用法: python auth.py adduser <用户名> [密码]")
            return 1
        username = argv[1]
        password = argv[2] if len(argv) > 2 else _prompt_password()
        if not password:
            return 1
        role = "admin" if "--admin" in argv[3:] else "user"
        ok, msg = auth.create_user(username, password, role=role)
        print(("OK: " if ok else "ERROR: ") + msg)
        return 0 if ok else 1

    if cmd == "passwd":
        if len(argv) < 2:
            print("用法: python auth.py passwd <用户名> [新密码]")
            return 1
        username = argv[1]
        password = argv[2] if len(argv) > 2 else _prompt_password()
        if not password:
            return 1
        ok, msg = auth.change_password(username, password)
        print(("OK: " if ok else "ERROR: ") + msg)
        return 0 if ok else 1

    if cmd == "deluser":
        if len(argv) < 2:
            print("用法: python auth.py deluser <用户名>")
            return 1
        username = argv[1]
        ok, msg = auth.delete_user(username)
        print(("OK: " if ok else "ERROR: ") + msg)
        return 0 if ok else 1

    print(f"未知命令: {cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
