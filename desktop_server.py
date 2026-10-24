"""1:1 shared desktop service (aiohttp + WebSocket + CDP).

Each logged-in DingTalk user opens a dedicated browser tab on the shared,
logged-in profile and drives the REAL ChatGPT/Gemini page. Two transport modes:

  * ``/pws``  DOM mirror (default, traffic-saving). The vendored PhantomStream
              capture streams one style-inlined snapshot plus incremental
              MutationObserver diffs over a CDP binding; the viewer rebuilds
              the page in a sandboxed iframe and relays remote control back.
              Conversation history is isolated per user and sub-resources are
              served through the same-origin /resource relay.
  * ``/ws``   High-fidelity pixel streaming (JPEG screencast) as a fallback for
              sites where the DOM mirror misses canvas/media.

Endpoints
---------
  GET  /desktop                 desktop page
  GET  /static/*                static assets (incl. the PhantomStream viewer)
  GET  /auth/me                 current user (JSON)
  POST /auth/login              username/password login (kept as fallback)
  POST /auth/logout
  GET  /auth/dingtalk/login     start DingTalk OAuth2 (redirect)
  GET  /auth/dingtalk/callback  OAuth2 callback -> session cookie
  GET  /pws?platform=chatgpt    PhantomStream DOM-mirror relay (role=viewer)
  GET  /ws?platform=chatgpt     JPEG pixel stream + raw input channel
  GET  /resource?u=<enc>        same-origin asset relay (shared browser cookies)
  GET  /api/pool                pool status (admin)
  GET  /api/desktop-config      default mode
"""
import os
import re
import json
import time
import base64
import zlib
import asyncio
import logging
import secrets

from urllib.parse import urlparse, quote
from html import unescape as html_unescape

from aiohttp import web, WSMsgType

import config
from auth import AuthManager
from browser_pool import BrowserPool, PoolOverflow
from dingtalk_sso import DingTalkSSO, DingTalkSSOError
from ownership import OwnershipStore
from page_inject import build_inject_script, RESOURCE_HOST_ALLOW
from phantom_inject import (build_phantom_script, build_origin_prefix,
                           RAW_BRIDGE)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("desktop")

STATIC_ROOT = os.path.realpath(os.path.join(config.BASE_DIR, "static"))
SESSION_COOKIE = "sg_session"
OAUTH_STATE_COOKIE = "sg_oauth_state"

# PhantomStream bridge binding + a process-wide token the capture echoes in
# every frame so the backend can trust binding calls.
PHANTOM_BRIDGE = "__phantomStreamBridge"
PHANTOM_TOKEN = secrets.token_urlsafe(24)
# Capture -> viewer message prefix (ext:) and viewer -> capture prefix (dash:).
_EXT_PREFIX = "ext:"
_DASH_PREFIX = "dash:"
RC_STATE = "ext:ps-control-state"

# Static asset CDNs: every https URL on these hosts is a fetchable sub-resource
# (image/font/media/css), never an in-app navigation link, so it is safe to
# rewrite them anywhere in a mirror frame (snapshot html AND attr/add diffs)
# to the same-origin /resource relay. Main hosts (chatgpt.com / gemini.google.com
# / google.com / accounts.google.com / ...) are deliberately excluded: they
# carry conversation/navigation hrefs and are handled only via the explicit
# stylesheets[] array.
STATIC_ASSET_HOSTS = (
    "oaistatic.com", "oaiusercontent.com",
    "gstatic.com", "googleusercontent.com",
    "kimi-img.moonshot.cn",   # Kimi image / uploaded-file CDN
)
_ASSET_URL_RE = re.compile(
    r"https://[A-Za-z0-9._-]*?(?:"
    + "|".join(re.escape(h) for h in STATIC_ASSET_HOSTS)
    + r")[^\s\"'<>\\)\]]*",
    re.IGNORECASE)

# CDP mouse button number -> name (pixel-mode input).
_MOUSE_BUTTONS = {0: "left", 1: "middle", 2: "right"}
# PhantomStream remote-control button -> CDP button + pressed bit mask.
_RC_BUTTON_MASK = {"left": ("left", 1), "middle": ("middle", 4),
                   "right": ("right", 2)}
# Named (non-printable) keys -> CDP (code, virtual key code).
_NAMED_KEYS = {
    "Enter": ("Enter", 13), "Backspace": ("Backspace", 8),
    "Tab": ("Tab", 9), "Delete": ("Delete", 46), "Escape": ("Escape", 27),
    "ArrowLeft": ("ArrowLeft", 37), "ArrowUp": ("ArrowUp", 38),
    "ArrowRight": ("ArrowRight", 39), "ArrowDown": ("ArrowDown", 40),
    "Home": ("Home", 36), "End": ("End", 35),
    "PageUp": ("PageUp", 33), "PageDown": ("PageDown", 34),
}

# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------
auth_manager = AuthManager(
    config.USERS_FILE,
    config.SESSIONS_FILE,
    session_lifetime_days=config.SESSION_LIFETIME_DAYS,
    max_sessions_per_user=config.MAX_SESSIONS_PER_USER,
    max_failures=config.LOGIN_MAX_FAILURES,
    lock_minutes=config.LOGIN_LOCK_MINUTES,
)
auth_manager.ensure_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)

sso = DingTalkSSO(config.DINGTALK_APP_KEY, config.DINGTALK_APP_SECRET)
pool = BrowserPool()
ownership = OwnershipStore(os.path.join(config.DATA_DIR, "ownership.json"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def current_user(request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return auth_manager.get_session_user(token)


def is_https(request):
    if config.TRUST_FORWARDED_HEADERS:
        if request.headers.get("X-Forwarded-Proto", "http").lower() == "https":
            return True
    return request.scheme == "https"


def public_base_url(request):
    """External base URL (for OAuth redirect), honoring ngrok forwarding."""
    if config.DINGTALK_OAUTH_BASE:
        return config.DINGTALK_OAUTH_BASE
    if config.TRUST_FORWARDED_HEADERS:
        proto = request.headers.get("X-Forwarded-Proto", request.scheme)
        proto = proto.split(",")[0].strip()
        host = (request.headers.get("X-Forwarded-Host")
                or request.headers.get("Host", "localhost"))
        host = host.split(",")[0].strip()
    else:
        proto, host = request.scheme, request.host
    return f"{proto}://{host}"


def same_origin_ok(request):
    """Cross-site WebSocket protection: Origin must equal the served host."""
    origin = request.headers.get("Origin")
    if not origin:
        return True
    origin_host = urlparse(origin).netloc
    host = (request.headers.get("X-Forwarded-Host")
            or request.headers.get("Host", ""))
    host = host.split(",")[0].strip()
    return not host or not origin_host or origin_host == host


def decode_wire(raw):
    """Decode a viewer wire frame. Plain JSON or a native deflate-raw envelope
    (``{_ps:'deflate-raw', d:base64}``) produced by the browser transport."""
    outer = json.loads(raw)
    if (isinstance(outer, dict) and outer.get("_ps") == "deflate-raw"
            and isinstance(outer.get("d"), str)):
        data = base64.b64decode(outer["d"])
        inner = zlib.decompress(data, wbits=-15).decode("utf-8")
        return json.loads(inner)
    return outer


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
async def me(request):
    user = current_user(request)
    if not user:
        return web.json_response({"authenticated": False}, status=401)
    profile = auth_manager.get_user_profile(user["username"]) or {
        "username": user["username"], "role": user["role"],
        "provider": "password", "display_name": user["username"], "avatar": "",
    }
    return web.json_response({"authenticated": True, **profile,
                              "sso_enabled": config.DINGTALK_SSO_ENABLED,
                              "platforms": config.AI_PLATFORMS,
                              "platform_labels": {p: config.PLATFORMS[p]["label"]
                                                  for p in config.AI_PLATFORMS}})


async def login(request):
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    ip = request.remote
    allowed, retry_after = auth_manager.check_rate_limit(ip)
    if not allowed:
        return web.json_response({"detail": f"尝试过于频繁，请 {retry_after} 秒后再试"},
                                 status=429)
    user = auth_manager.authenticate(username, password)
    if not user:
        auth_manager.record_failure(ip)
        return web.json_response({"detail": "用户名或密码错误"}, status=401)
    auth_manager.record_success(ip)
    token = auth_manager.create_session(user["username"])
    resp = web.json_response({"status": "ok", "username": user["username"]})
    resp.set_cookie(SESSION_COOKIE, token, max_age=config.SESSION_LIFETIME_DAYS * 86400,
                    path="/", httponly=True, samesite="Lax", secure=is_https(request))
    return resp


async def logout(request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_manager.revoke_session(token)
    resp = web.json_response({"status": "ok"})
    resp.set_cookie(SESSION_COOKIE, "", max_age=0, path="/", httponly=True,
                    samesite="Lax", secure=is_https(request))
    return resp


async def dingtalk_login(request):
    if not config.DINGTALK_SSO_ENABLED:
        return web.json_response({"detail": "钉钉登录未启用"}, status=400)
    state = secrets.token_urlsafe(16)
    redirect_uri = public_base_url(request) + config.DINGTALK_OAUTH_PATH
    url = sso.build_authorize_url(redirect_uri, state)
    resp = web.HTTPFound(url)
    resp.set_cookie(OAUTH_STATE_COOKIE, state, max_age=600, path="/",
                    httponly=True, samesite="Lax", secure=is_https(request))
    return resp


async def dingtalk_callback(request):
    if not config.DINGTALK_SSO_ENABLED:
        return web.json_response({"detail": "钉钉登录未启用"}, status=400)
    code = request.query.get("code")
    state = request.query.get("state")
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    fail = public_base_url(request) + "/desktop?login_error=1"
    if not code or not cookie_state or not state or state != cookie_state:
        logger.warning("DingTalk OAuth state mismatch or missing code.")
        return web.HTTPFound(fail)
    try:
        profile = await sso.exchange_profile(code)
    except DingTalkSSOError as e:
        logger.error("DingTalk OAuth exchange failed: %s", e)
        return web.HTTPFound(fail)
    # openId is the stable per-app unique identity; fall back to unionId.
    provider_id = profile["open_id"] or profile["union_id"]
    if not provider_id:
        logger.error("DingTalk OAuth returned no usable unique id.")
        return web.HTTPFound(fail)
    username = auth_manager.upsert_oauth_user(
        "dingtalk", provider_id,
        nickname=profile["nick"], avatar=profile["avatar"],
    )
    token = auth_manager.create_session(username)
    resp = web.HTTPFound(public_base_url(request) + "/desktop")
    resp.set_cookie(SESSION_COOKIE, token,
                    max_age=config.SESSION_LIFETIME_DAYS * 86400, path="/",
                    httponly=True, samesite="Lax", secure=is_https(request))
    resp.set_cookie(OAUTH_STATE_COOKIE, "", max_age=0, path="/",
                    httponly=True, samesite="Lax", secure=is_https(request))
    return resp


# ---------------------------------------------------------------------------
# Desktop page
# ---------------------------------------------------------------------------
async def index(_request):
    return web.HTTPFound("/desktop")


async def desktop_page(_request):
    return web.FileResponse(os.path.join(STATIC_ROOT, "desktop.html"))


# ---------------------------------------------------------------------------
# Shared tab session
# ---------------------------------------------------------------------------
class BaseSession:
    """Owns one user/platform tab: policy injection, ownership, viewport."""

    def __init__(self, ws, user, platform, request, role="user"):
        self.ws = ws
        self.user = user
        self.platform = platform
        self.request = request
        self.role = role
        self.cdp = None
        self.page = None
        self.closed = False
        self.viewport = {"width": config.DESKTOP_MAX_WIDTH,
                         "height": config.DESKTOP_MAX_HEIGHT}
        self._script_ids = []

    # -- setup -----------------------------------------------------------
    async def setup_page(self, phantom=False, relay_origin=""):
        self.relay_origin = relay_origin or ""
        self.page, is_new = await pool.acquire(self.user, self.platform)
        self.cdp = await pool.new_cdp_session(self.page)
        await self.cdp.send("Runtime.enable")
        await self.cdp.send("Page.enable")
        bindings = ["__sgOwn", "__sgEvent"]
        if phantom:
            # The raw, string-only CDP binding; the page-side prelude exposes
            # the object-accepting __phantomStreamBridge the capture expects.
            bindings.append(RAW_BRIDGE)
        for name in bindings:
            await self.cdp.send("Runtime.addBinding", {"name": name})
        self.cdp.on("Runtime.bindingCalled", self._on_binding)
        self.cdp.on("Page.frameNavigated", self._on_frame_navigated)

        # Policy script (isolation / lockdown / ownership).
        policy = build_inject_script(
            self.platform, ownership.get(self.user, self.platform),
            is_admin=self.role == "admin", lock_ui=True)
        r = await self.cdp.send("Page.addScriptToEvaluateOnNewDocument",
                                {"source": policy})
        self._script_ids.append(r.get("identifier"))
        capture = ""
        if phantom:
            capture = (build_origin_prefix(self.relay_origin)
                       + build_phantom_script(self.platform, PHANTOM_TOKEN))
            # Re-injected on every future navigation (reload / new chat) ...
            r = await self.cdp.send("Page.addScriptToEvaluateOnNewDocument",
                                    {"source": capture})
            self._script_ids.append(r.get("identifier"))
        await self.cdp.send("Runtime.evaluate",
                            {"expression": policy, "runImmediately": True})
        if phantom:
            # ... and evaluated once now on the already-loaded document. The
            # pool's tab has usually finished its initial goto() before this
            # CDP session exists, so addScriptToEvaluateOnNewDocument alone
            # would not run until the next navigation and the viewer would
            # never receive the first snapshot.
            await self.cdp.send("Runtime.evaluate",
                                {"expression": capture, "runImmediately": True})
            await self.cdp.send("Runtime.evaluate", {
                "expression": "window.__phantomStreamStart && "
                              "window.__phantomStreamStart();",
                "runImmediately": True})
        await self.set_viewport(self.viewport["width"], self.viewport["height"])
        return is_new

    async def set_viewport(self, width, height):
        width = max(320, min(int(width), config.DESKTOP_MAX_WIDTH))
        height = max(240, min(int(height), config.DESKTOP_MAX_HEIGHT))
        self.viewport = {"width": width, "height": height}
        await self.cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": 1, "mobile": False})

    async def teardown(self, stop_screencast=False):
        self.closed = True
        if self.cdp:
            if stop_screencast:
                try:
                    await self.cdp.send("Page.stopScreencast")
                except Exception:
                    pass
            for ident in self._script_ids:
                if ident:
                    try:
                        await self.cdp.send(
                            "Page.removeScriptToEvaluateOnNewDocument",
                            {"identifier": ident})
                    except Exception:
                        pass
            try:
                await self.cdp.detach()
            except Exception:
                pass
        await pool.release(self.user, self.platform)

    # -- bindings --------------------------------------------------------
    def _on_binding(self, params):
        if self.closed:
            return
        name = params.get("name")
        raw = params.get("payload", "")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        if name == "__sgOwn":
            asyncio.create_task(self._handle_ownership(data))
        elif name == "__sgEvent":
            asyncio.create_task(self._handle_page_event(data))
        elif name == RAW_BRIDGE:
            asyncio.create_task(self._on_phantom_bridge(raw))

    async def _handle_ownership(self, data):
        conv_id = data.get("id")
        platform = data.get("platform", self.platform)
        if ownership.add(self.user, platform, conv_id):
            logger.info("Attributed conversation %s/%s to %s",
                        platform, conv_id, self.user)
            ids = ownership.get(self.user, platform)
            try:
                await self.cdp.send("Runtime.evaluate", {
                    "expression": f"window.__sgSetOwned && window.__sgSetOwned({json.dumps(ids)})"})
            except Exception:
                pass

    async def _handle_page_event(self, data):
        if data.get("what") in ("logout", "nav"):
            try:
                await self.send_notice("已阻止登出/跳转账号页面")
            except Exception:
                pass

    async def send_notice(self, message):
        raise NotImplementedError

    async def _on_frame_navigated(self, params):
        frame = params.get("frame", {})
        if not frame.get("parentId"):
            asyncio.create_task(self._after_navigation())

    async def _after_navigation(self):
        ids = ownership.get(self.user, self.platform)
        try:
            await self.cdp.send("Runtime.evaluate", {
                "expression": f"window.__sgSetOwned && window.__sgSetOwned({json.dumps(ids)})"})
        except Exception:
            pass

    # -- CDP input -------------------------------------------------------
    async def cdp_mouse(self, subtype, d):
        mods = int(d.get("modifiers", 0))
        if subtype in ("mouseMove", "mouseDown", "mouseUp"):
            cdp_type = {"mouseMove": "mouseMoved", "mouseDown": "mousePressed",
                        "mouseUp": "mouseReleased"}[subtype]
            args = {"type": cdp_type, "x": float(d.get("x", 0)),
                    "y": float(d.get("y", 0)), "modifiers": mods}
            if subtype != "mouseMove":
                btn = _MOUSE_BUTTONS.get(int(d.get("button", 0)), "left")
                args["button"] = btn
                args["buttons"] = int(d.get("buttons", 1))
                args["clickCount"] = int(d.get("clickCount", 1))
            else:
                args["button"] = "none"
                args["buttons"] = int(d.get("buttons", 0))
            await self.cdp.send("Input.dispatchMouseEvent", args)
        elif subtype == "mouseWheel":
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": float(d.get("x", 0)),
                "y": float(d.get("y", 0)), "deltaX": float(d.get("deltaX", 0)),
                "deltaY": float(d.get("deltaY", 0)), "modifiers": mods})

    async def cdp_key(self, subtype, d):
        mods = int(d.get("modifiers", 0))
        payload = {"type": "rawKeyDown" if subtype == "keyDown" else "keyUp",
                   "key": d.get("key", ""), "code": d.get("code", ""),
                   "modifiers": mods}
        if d.get("vk"):
            payload["windowsVirtualKeyCode"] = int(d["vk"])
            payload["nativeVirtualKeyCode"] = int(d["vk"])
        await self.cdp.send("Input.dispatchKeyEvent", payload)

    async def cdp_insert_text(self, text):
        await self.cdp.send("Input.insertText", {"text": text})


# ---------------------------------------------------------------------------
# PhantomStream DOM-mirror session (/pws)
# ---------------------------------------------------------------------------
class PhantomSession(BaseSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def send_notice(self, message):
        await self._send_frame("sg:notice", {"message": message})

    async def _send_frame(self, mtype, payload):
        if self.closed:
            return
        frame = {"type": mtype, "payload": payload or {},
                 "ts": int(time.time() * 1000)}
        # Plain JSON; capture already truncates snapshots to the 1 MiB budget,
        # and incremental diffs are small. The viewer decodes plain JSON.
        await self.ws.send_str(json.dumps(frame, ensure_ascii=False))

    def _rewrite_stylesheets(self, payload):
        """Head <link rel=stylesheet> URLs are collected into a separate array
        (not routed through maskAssetUrlFn); rewrite them to /resource too."""
        origin = self.relay_origin
        if not origin or not isinstance(payload, dict):
            return
        prefix = origin + "/resource?u="

        def rel(u):
            if isinstance(u, str) and u.startswith("https://"):
                return prefix + quote(u, safe="") + "&platform=" + self.platform
            return u

        if isinstance(payload.get("stylesheets"), list):
            payload["stylesheets"] = [rel(u) for u in payload["stylesheets"]]
        for fr in payload.get("frames", []) or []:
            if isinstance(fr, dict) and isinstance(fr.get("stylesheets"), list):
                fr["stylesheets"] = [rel(u) for u in fr["stylesheets"]]

    def _rewrite_asset_urls(self, node):
        """Rewrite every static-CDN asset URL anywhere in a mirror frame to the
        same-origin /resource relay. Works uniformly across snapshot html and
        attr/add diffs (which may carry the URL in different fields), so it does
        not depend on the capture artifact exposing a maskAssetUrlFn seam.
        Entity-decoded first because serialized attributes encode '&' as &amp;.
        """
        origin = self.relay_origin
        if not origin:
            return
        prefix = origin + "/resource?u="

        def repl(m):
            url = html_unescape(m.group(0))
            return prefix + quote(url, safe="") + "&platform=" + self.platform

        def walk(n):
            if isinstance(n, dict):
                for k, v in list(n.items()):
                    n[k] = walk(v)
                return n
            if isinstance(n, list):
                for i, v in enumerate(n):
                    n[i] = walk(v)
                return n
            if isinstance(n, str) and "https://" in n:
                return _ASSET_URL_RE.sub(repl, n)
            return n

        walk(node)

    async def _on_phantom_bridge(self, raw):
        """Capture -> backend binding. Forward only ext: frames to the viewer."""
        if self.closed:
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if msg.get("token") != PHANTOM_TOKEN:
            logger.warning("Rejected PhantomStream frame with bad token.")
            return
        mtype = msg.get("type", "")
        if not mtype.startswith(_EXT_PREFIX):
            return
        payload = msg.get("payload", {})
        self._rewrite_stylesheets(payload)
        self._rewrite_asset_urls(payload)
        await self._send_frame(mtype, payload)

    async def _page_eval(self, expression, await_promise=False):
        return await self.cdp.send("Runtime.evaluate", {
            "expression": expression, "awaitPromise": await_promise,
            "returnByValue": True})

    async def _restart_capture(self):
        await self._page_eval(
            "window.__phantomStreamStart && window.__phantomStreamStart()")

    # -- remote control (viewer -> page) --------------------------------
    async def _rc_click(self, p):
        try:
            x, y = float(p["x"]), float(p["y"])
        except (KeyError, TypeError, ValueError):
            return
        button, mask = _RC_BUTTON_MASK.get(p.get("button", "left"),
                                          _RC_BUTTON_MASK["left"])
        click_count = max(1, int(p.get("clickCount", 1)))
        base = {"x": x, "y": y}
        await self.cdp.send("Input.dispatchMouseEvent",
                            {"type": "mouseMoved", **base, "button": "none",
                             "buttons": 0})
        await self.cdp.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", **base, "button": button, "buttons": mask,
            "clickCount": click_count})
        await self.cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", **base, "button": button, "buttons": 0,
            "clickCount": click_count})

    async def _rc_scroll(self, p):
        try:
            x, y = float(p["x"]), float(p["y"])
        except (KeyError, TypeError, ValueError):
            return
        await self.cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": x, "y": y,
            "deltaX": float(p.get("deltaX", 0)),
            "deltaY": float(p.get("deltaY", 0))})

    async def _rc_key(self, p):
        key = p.get("key", "")
        if not key:
            return
        down = p.get("event") in ("down", "keyDown")
        cdp_type = "rawKeyDown" if down else "keyUp"
        code, vk = _NAMED_KEYS.get(key, (key, 0))
        args = {"type": cdp_type, "key": key, "code": code}
        if vk:
            args["windowsVirtualKeyCode"] = vk
            args["nativeVirtualKeyCode"] = vk
        await self.cdp.send("Input.dispatchKeyEvent", args)

    async def _rc_text(self, p):
        text = p.get("text", "")
        if text:
            await self.cdp.send("Input.insertText", {"text": text})

    async def _handle_viewer_frame(self, mtype, p):
        # Host-level control frames (frontend convenience channel).
        if mtype == "sg:resize":
            await self.set_viewport(p.get("width", self.viewport["width"]),
                                    p.get("height", self.viewport["height"]))
            await self._restart_capture()
            return
        if mtype == "sg:control":
            await pool.touch(self.user, self.platform)
            action = p.get("action")
            if action == "new_chat":
                await pool.new_chat(self.user, self.platform)
            elif action == "reload":
                await pool.reload(self.user, self.platform)
            return
        if mtype == "ping":
            await self._send_frame("pong", {"ts": int(time.time() * 1000)})
            return
        if not mtype.startswith(_DASH_PREFIX):
            return

        if mtype == "dash:dom-stream-start":
            await self._restart_capture()
        elif mtype == "dash:dom-stream-stop":
            await self._page_eval("window.__phantomStreamStop && window.__phantomStreamStop()")
        elif mtype == "dash:dom-stream-resume":
            await self._restart_capture()
        elif mtype == "dash:dom-stream-pause":
            await self._page_eval("window.__phantomStreamStop && window.__phantomStreamStop()")
        elif mtype == "dash:ps-subtree-request":
            await self._page_eval(
                "window.__phantomStreamHandleControl(%s, %s)"
                % (json.dumps(mtype), json.dumps(p)), await_promise=True)
        elif mtype == "dash:ps-control-request":
            # Every logged-in visitor is authorized to drive their own tab.
            await self._send_frame(RC_STATE,
                                   {"state": "active", "reason": "authorization-approved"})
        elif mtype == "dash:ps-control-stop":
            await self._send_frame(RC_STATE,
                                   {"state": "stopped", "reason": "viewer-stop"})
        elif mtype == "dash:ps-control-click":
            await pool.touch(self.user, self.platform)
            await self._rc_click(p)
        elif mtype == "dash:ps-control-text":
            await pool.touch(self.user, self.platform)
            await self._rc_text(p)
        elif mtype == "dash:ps-control-key":
            await pool.touch(self.user, self.platform)
            await self._rc_key(p)
        elif mtype == "dash:ps-control-scroll":
            await pool.touch(self.user, self.platform)
            await self._rc_scroll(p)

    async def run(self):
        is_new = await self.setup_page(phantom=True, relay_origin=self.relay_origin)
        try:
            await self._restart_capture()
            await self._send_frame("sg:ready", {"platform": self.platform,
                                                "new_tab": is_new})
            async for msg in self.ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = decode_wire(msg.data)
                    mtype = data.get("type")
                    payload = data.get("payload", {}) if isinstance(data, dict) else {}
                except (json.JSONDecodeError, ValueError, zlib.error):
                    continue
                if not mtype:
                    continue
                try:
                    await self._handle_viewer_frame(mtype, payload)
                except Exception as e:
                    logger.warning("Phantom frame error (%s): %s", mtype, e)
        finally:
            await self.teardown()


# ---------------------------------------------------------------------------
# Pixel streaming session (/ws, high-fidelity fallback)
# ---------------------------------------------------------------------------
class PixelSession(BaseSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_frame_sent = 0.0
        self.frame_interval = 1.0 / max(1, config.DESKTOP_FPS)

    async def send_notice(self, message):
        await self.ws.send_json({"type": "notice", "message": message})

    def _on_frame(self, params):
        if self.closed:
            return
        asyncio.create_task(self._process_frame(params))

    async def _process_frame(self, params):
        sid = params.get("sessionId")
        try:
            if sid is not None:
                await self.cdp.send("Page.screencastFrameAck", {"sessionId": sid})
        except Exception:
            pass
        now = time.monotonic()
        if now - self.last_frame_sent < self.frame_interval:
            return
        self.last_frame_sent = now
        meta = params.get("metadata", {})
        try:
            await self.ws.send_json({
                "type": "frame", "data": params.get("data", ""),
                "width": meta.get("width", self.viewport["width"]),
                "height": meta.get("height", self.viewport["height"]),
            })
        except Exception:
            self.closed = True

    async def _control(self, d):
        action = d.get("action")
        if action == "new_chat":
            await pool.new_chat(self.user, self.platform)
            await self.ws.send_json({"type": "control_result", "action": action,
                                     "status": "success"})
        elif action == "reload":
            await pool.reload(self.user, self.platform)
            await self.ws.send_json({"type": "control_result", "action": action,
                                     "status": "success"})

    async def run(self):
        is_new = await self.setup_page(phantom=False)
        try:
            self.cdp.on("Page.screencastFrame", self._on_frame)
            await self.cdp.send("Page.startScreencast", {
                "format": "jpeg", "quality": config.DESKTOP_JPEG_QUALITY,
                "maxWidth": config.DESKTOP_MAX_WIDTH,
                "maxHeight": config.DESKTOP_MAX_HEIGHT, "everyNthFrame": 1})
            await self.ws.send_json({"type": "ready", "platform": self.platform,
                                     "mode": "stream", "new_tab": is_new})
            async for msg in self.ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    d = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                mtype = d.get("type")
                try:
                    if mtype in ("hello", "resize"):
                        await self.set_viewport(d.get("width", self.viewport["width"]),
                                                d.get("height", self.viewport["height"]))
                    elif mtype == "input":
                        await pool.touch(self.user, self.platform)
                        subtype = d.get("subtype")
                        if subtype in ("mouseMove", "mouseDown", "mouseUp", "mouseWheel"):
                            await self.cdp_mouse(subtype, d)
                        elif subtype in ("keyDown", "keyUp"):
                            await self.cdp_key(subtype, d)
                        elif subtype == "insertText":
                            await self.cdp_insert_text(d.get("text", ""))
                    elif mtype == "control":
                        await pool.touch(self.user, self.platform)
                        await self._control(d)
                except Exception as e:
                    logger.warning("WS handler error (%s): %s", mtype, e)
        finally:
            await self.teardown(stop_screencast=True)


# ---------------------------------------------------------------------------
# WebSocket handlers
# ---------------------------------------------------------------------------
def _platform_from_query(request):
    platform = request.query.get("platform", config.DEFAULT_PLATFORM)
    return platform if platform in config.AI_PLATFORMS else config.DEFAULT_PLATFORM


async def phantom_handler(request):
    user = current_user(request)
    if not user:
        return web.json_response({"detail": "未登录"}, status=401)
    if not same_origin_ok(request):
        return web.json_response({"detail": "跨域来源被拒绝"}, status=403)
    platform = _platform_from_query(request)
    relay_origin = public_base_url(request)
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)
    session = PhantomSession(ws, user["username"], platform, request,
                             role=user.get("role", "user"))
    session.relay_origin = relay_origin
    try:
        await session.run()
    except PoolOverflow as e:
        await ws.send_json({"type": "sg:error", "payload": {"message": str(e)}})
    except Exception as e:
        logger.error("Phantom session error: %s", e, exc_info=True)
        try:
            await ws.send_json({"type": "sg:error",
                                "payload": {"message": f"串流异常: {e}"}})
        except Exception:
            pass
    finally:
        await ws.close()
    return ws


async def ws_handler(request):
    user = current_user(request)
    if not user:
        return web.json_response({"detail": "未登录"}, status=401)
    if not same_origin_ok(request):
        return web.json_response({"detail": "跨域来源被拒绝"}, status=403)
    platform = _platform_from_query(request)
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)
    session = PixelSession(ws, user["username"], platform, request,
                           role=user.get("role", "user"))
    try:
        await session.run()
    except PoolOverflow as e:
        await ws.send_json({"type": "error", "message": str(e)})
    except Exception as e:
        logger.error("Stream session error: %s", e, exc_info=True)
        try:
            await ws.send_json({"type": "error", "message": f"串流异常: {e}"})
        except Exception:
            pass
    finally:
        await ws.close()
    return ws


async def desktop_config(request):
    return web.json_response({"default_mode": config.DESKTOP_DEFAULT_MODE})


async def pool_status(request):
    user = current_user(request)
    if not user or user.get("role") != "admin":
        return web.json_response({"detail": "需要管理员"}, status=403)
    return web.json_response(await pool.status())


async def resource(request):
    """Relay a sub-resource request (image/css/font) using the shared browser's
    cookies. Only platform main/static hosts are allowed (SSRF guard). This is
    NOT a page reverse proxy: it serves only sub-resources referenced by the
    DOM mirror; the page itself never runs on the client.
    """
    user = current_user(request)
    if not user:
        return web.json_response({"detail": "未登录"}, status=401)
    url = request.query.get("u", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return web.json_response({"detail": "非法资源地址"}, status=400)
    host = parsed.hostname.lower()
    if not any(host == d or host.endswith("." + d) for d in RESOURCE_HOST_ALLOW):
        logger.warning("Blocked resource host: %s", host)
        return web.json_response({"detail": "资源域名不被允许"}, status=403)
    try:
        await pool._ensure()
        platform = request.query.get("platform", "chatgpt")
        resp = await pool.context.request.get(
            url, timeout=30000,
            headers={"Referer": config.PLATFORMS.get(
                platform, {"home_url": "https://chatgpt.com"})["home_url"]})
        body = await resp.body()
        ctype = resp.headers.get("content-type", "application/octet-stream")
        return web.Response(
            body=body, status=resp.status, content_type=ctype,
            headers={"Cache-Control": "private, max-age=3600"})
    except Exception as e:
        logger.warning("Resource relay failed for %s: %s", url, e)
        return web.json_response({"detail": "资源获取失败"}, status=502)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
async def on_startup(app):
    try:
        await pool.start()
    except Exception as e:
        logger.warning("Pool not connected at startup (CDP may not be ready): %s", e)

    async def reaper():
        while True:
            await asyncio.sleep(60)
            try:
                await pool.reap_once()
            except Exception as e:
                logger.warning("Reaper error: %s", e)

    app["reaper_task"] = asyncio.create_task(reaper())


async def on_cleanup(app):
    task = app.get("reaper_task")
    if task:
        task.cancel()
    try:
        await pool.stop()
    except Exception as e:
        logger.warning("Pool stop error: %s", e)


def build_app():
    app = web.Application(client_max_size=8 * 1024 * 1024)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/", index)
    app.router.add_get("/desktop", desktop_page)
    app.router.add_get("/auth/me", me)
    app.router.add_post("/auth/login", login)
    app.router.add_post("/auth/logout", logout)
    app.router.add_get("/auth/dingtalk/login", dingtalk_login)
    app.router.add_get("/auth/dingtalk/callback", dingtalk_callback)
    app.router.add_get("/pws", phantom_handler)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/pool", pool_status)
    app.router.add_get("/api/desktop-config", desktop_config)
    app.router.add_get("/resource", resource)
    app.router.add_static("/static", STATIC_ROOT, name="static")
    return app


def main():
    host = config.WEB_HOST
    app = build_app()
    logger.info("1:1 desktop service on http://%s:%s/desktop", host, config.DESKTOP_PORT)
    web.run_app(app, host=host, port=config.DESKTOP_PORT, access_log=None)


if __name__ == "__main__":
    main()
