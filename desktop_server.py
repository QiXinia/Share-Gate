"""1:1 shared desktop service (aiohttp + WebSocket + CDP screencast).

Each logged-in DingTalk user opens a dedicated browser tab on the shared,
logged-in profile and streams the REAL ChatGPT/Gemini page into the browser.
Mouse / keyboard / wheel input is relayed back over the Chrome DevTools
Protocol, so the experience is a pixel-faithful remote browser tab.

Endpoints
---------
  GET  /desktop                 desktop page
  GET  /static/*                static assets
  GET  /auth/me                 current user (JSON)
  POST /auth/login              username/password login (kept as fallback)
  POST /auth/logout
  GET  /auth/dingtalk/login     start DingTalk OAuth2 (redirect)
  GET  /auth/dingtalk/callback  OAuth2 callback -> session cookie
  GET  /ws?platform=chatgpt     WebSocket streaming + input channel
  GET  /api/pool                pool status (admin)
"""
import os
import json
import time
import asyncio
import logging
import mimetypes

from aiohttp import web, WSMsgType

from urllib.parse import urlparse

import config
from auth import AuthManager
from browser_pool import BrowserPool, PoolOverflow
from dingtalk_sso import DingTalkSSO, DingTalkSSOError
from ownership import OwnershipStore
from page_inject import build_inject_script, RESOURCE_HOST_ALLOW

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("desktop")

STATIC_ROOT = os.path.realpath(os.path.join(config.BASE_DIR, "static"))
SESSION_COOKIE = "sg_session"
OAUTH_STATE_COOKIE = "sg_oauth_state"

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

# CDP mouse button number -> name.
_MOUSE_BUTTONS = {0: "left", 1: "middle", 2: "right"}


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
    import secrets
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
# Desktop page & static
# ---------------------------------------------------------------------------
async def index(_request):
    return web.HTTPFound("/desktop")


async def desktop_page(_request):
    path = os.path.join(STATIC_ROOT, "desktop.html")
    return web.FileResponse(path)


# ---------------------------------------------------------------------------
# WebSocket streaming
# ---------------------------------------------------------------------------
class StreamSession:
    def __init__(self, ws, user, platform, request, mode="dom", role="user"):
        self.ws = ws
        self.user = user
        self.platform = platform
        self.request = request
        self.mode = mode if mode in ("dom", "stream") else "dom"
        self.role = role
        self.cdp = None
        self.page = None
        self.closed = False
        self.last_frame_sent = 0.0
        self.frame_interval = 1.0 / max(1, config.DESKTOP_FPS)
        self.viewport = {"width": config.DESKTOP_MAX_WIDTH,
                         "height": config.DESKTOP_MAX_HEIGHT}

    # ------------------------------------------------------------------
    # Shared setup: ownership + lockdown + DOM bindings
    # ------------------------------------------------------------------
    async def _setup_page(self):
        self.page, is_new = await pool.acquire(self.user, self.platform)
        self.cdp = await pool.new_cdp_session(self.page)
        await self.cdp.send("Runtime.enable")
        await self.cdp.send("Page.enable")
        # Bindings the page script calls into.
        for name in ("__sgPush", "__sgOwn", "__sgEvent"):
            await self.cdp.send("Runtime.addBinding", {"name": name})
        self.cdp.on("Runtime.bindingCalled", self._on_binding)
        # Main-frame full navigations need the ownership set re-pushed.
        self.cdp.on("Page.frameNavigated", self._on_frame_navigated)
        # Inject on every future navigation ...
        await self._inject_script()
        # ... and once for the currently loaded document.
        await self._evaluate_script()
        w, h = self.viewport["width"], self.viewport["height"]
        await self.cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        return is_new

    def _owned_ids(self):
        return ownership.get(self.user, self.platform)

    def _script_source(self):
        return build_inject_script(
            self.platform, self._owned_ids(),
            is_admin=self.role == "admin", lock_ui=True, mode=self.mode)

    def _inject_script(self):
        return self.cdp.send("Page.addScriptToEvaluateOnNewDocument",
                             {"source": self._script_source()})

    def _evaluate_script(self):
        return self.cdp.send("Runtime.evaluate",
                             {"expression": self._script_source(),
                              "runImmediately": True})

    async def _sync_owned(self):
        """After a full-document navigation, push the latest ownership set."""
        ids = self._owned_ids()
        try:
            await self.cdp.send("Runtime.evaluate", {
                "expression":
                f"window.__sgSetOwned && window.__sgSetOwned({json.dumps(ids)})"})
        except Exception:
            pass

    def _on_frame_navigated(self, params):
        frame = params.get("frame", {})
        if not frame.get("parentId"):  # main frame, full (non same-document) nav
            asyncio.create_task(self._sync_owned())

    def _on_binding(self, params):
        if self.closed:
            return
        name = params.get("name")
        raw = params.get("payload", "")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        if name == "__sgPush":
            asyncio.create_task(self._send_dom(data))
        elif name == "__sgOwn":
            asyncio.create_task(self._handle_ownership(data))
        elif name == "__sgEvent":
            asyncio.create_task(self._handle_page_event(data))

    async def _send_dom(self, data):
        if self.mode != "dom":
            return
        try:
            data["mode"] = "dom"
            await self.ws.send_json(data)
        except Exception:
            self.closed = True

    async def _handle_ownership(self, data):
        conv_id = data.get("id")
        platform = data.get("platform", self.platform)
        if ownership.add(self.user, platform, conv_id):
            logger.info("Attributed conversation %s/%s to %s",
                        platform, conv_id, self.user)
            # Push the updated set so the page can show/hide history.
            ids = ownership.get(self.user, platform)
            try:
                await self.cdp.send("Runtime.evaluate", {
                    "expression": f"window.__sgSetOwned && window.__sgSetOwned({json.dumps(ids)})"
                })
            except Exception:
                pass

    async def _handle_page_event(self, data):
        if data.get("what") in ("logout", "nav"):
            try:
                await self.ws.send_json(
                    {"type": "notice", "message": "已阻止登出/跳转账号页面"})
            except Exception:
                pass

    async def _start_dom(self):
        await self.cdp.send("Runtime.evaluate",
                            {"expression": "window.__sgMirrorStart && window.__sgMirrorStart()"})

    async def _start_stream(self):
        self.cdp.on("Page.screencastFrame", self._on_frame)
        await self.cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": config.DESKTOP_JPEG_QUALITY,
            "maxWidth": config.DESKTOP_MAX_WIDTH,
            "maxHeight": config.DESKTOP_MAX_HEIGHT,
            "everyNthFrame": 1,
        })

    def _on_frame(self, params):
        # Playwright invokes this on the event loop thread.
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
                "type": "frame",
                "data": params.get("data", ""),
                "width": meta.get("width", self.viewport["width"]),
                "height": meta.get("height", self.viewport["height"]),
            })
        except Exception:
            self.closed = True

    async def _input(self, d):
        sub = d.get("subtype")
        mods = int(d.get("modifiers", 0))
        if sub in ("mouseMove", "mouseDown", "mouseUp"):
            cdp_type = {"mouseMove": "mouseMoved", "mouseDown": "mousePressed",
                        "mouseUp": "mouseReleased"}[sub]
            args = {
                "type": cdp_type,
                "x": float(d.get("x", 0)), "y": float(d.get("y", 0)),
                "modifiers": mods,
            }
            if sub != "mouseMove":
                btn = _MOUSE_BUTTONS.get(int(d.get("button", 0)), "left")
                args["button"] = btn
                args["buttons"] = int(d.get("buttons", 1))
                args["clickCount"] = int(d.get("clickCount", 1))
            else:
                args["buttons"] = int(d.get("buttons", 0))
            await self.cdp.send("Input.dispatchMouseEvent", args)
        elif sub == "mouseWheel":
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": float(d.get("x", 0)), "y": float(d.get("y", 0)),
                "deltaX": float(d.get("deltaX", 0)),
                "deltaY": float(d.get("deltaY", 0)),
                "modifiers": mods,
            })
        elif sub == "keyDown":
            payload = {"type": "rawKeyDown", "key": d.get("key", ""),
                       "code": d.get("code", ""), "modifiers": mods}
            if d.get("vk"):
                payload["windowsVirtualKeyCode"] = int(d["vk"])
                payload["nativeVirtualKeyCode"] = int(d["vk"])
            await self.cdp.send("Input.dispatchKeyEvent", payload)
        elif sub == "keyUp":
            payload = {"type": "keyUp", "key": d.get("key", ""),
                       "code": d.get("code", ""), "modifiers": mods}
            if d.get("vk"):
                payload["windowsVirtualKeyCode"] = int(d["vk"])
                payload["nativeVirtualKeyCode"] = int(d["vk"])
            await self.cdp.send("Input.dispatchKeyEvent", payload)
        elif sub == "insertText":
            await self.cdp.send("Input.insertText", {"text": d.get("text", "")})

    async def _control(self, d):
        action = d.get("action")
        if action == "new_chat":
            result = await pool.new_chat(self.user, self.platform)
            await self.ws.send_json({"type": "control_result", "action": action,
                                     **result})
        elif action == "reload":
            result = await pool.reload(self.user, self.platform)
            await self.ws.send_json({"type": "control_result", "action": action,
                                     **result})

    async def _resize(self, width, height):
        width = max(320, min(int(width), config.DESKTOP_MAX_WIDTH))
        height = max(240, min(int(height), config.DESKTOP_MAX_HEIGHT))
        self.viewport = {"width": width, "height": height}
        await self.cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1,
            "mobile": False,
        })
        if self.mode == "dom":
            await self.cdp.send(
                "Runtime.evaluate",
                {"expression": "window.__sgMirrorRequestFrame && window.__sgMirrorRequestFrame()"})

    async def run(self):
        is_new = await self._setup_page()
        try:
            if self.mode == "dom":
                await self._start_dom()
            else:
                await self._start_stream()
            await self.ws.send_json({"type": "ready", "platform": self.platform,
                                     "mode": self.mode, "new_tab": is_new})

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
                        await self._resize(d.get("width", self.viewport["width"]),
                                           d.get("height", self.viewport["height"]))
                    elif mtype == "input":
                        await pool.touch(self.user, self.platform)
                        await self._input(d)
                    elif mtype == "control":
                        await pool.touch(self.user, self.platform)
                        await self._control(d)
                except Exception as e:
                    logger.warning("WS handler error (%s): %s", mtype, e)
        finally:
            self.closed = True
            if self.cdp:
                if self.mode == "stream":
                    try:
                        await self.cdp.send("Page.stopScreencast")
                    except Exception:
                        pass
                try:
                    await self.cdp.detach()
                except Exception:
                    pass
            await pool.release(self.user, self.platform)


async def ws_handler(request):
    user = current_user(request)
    if not user:
        return web.json_response({"detail": "未登录"}, status=401)
    # Origin check for cross-site WebSocket protection.
    origin = request.headers.get("Origin")
    if origin:
        from urllib.parse import urlparse
        origin_host = urlparse(origin).netloc
        host = (request.headers.get("X-Forwarded-Host")
                or request.headers.get("Host", ""))
        if origin_host and origin_host != host.split(",")[0].strip():
            return web.json_response({"detail": "跨域来源被拒绝"}, status=403)

    platform = request.query.get("platform", config.DEFAULT_PLATFORM)
    if platform not in config.AI_PLATFORMS:
        platform = config.DEFAULT_PLATFORM
    mode = request.query.get("mode", "dom").lower()
    if mode not in ("dom", "stream"):
        mode = "dom"

    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)
    session = StreamSession(ws, user["username"], platform, request,
                            mode=mode, role=user.get("role", "user"))
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
        try:
            await ws.close()
        except Exception:
            pass
    return ws


async def desktop_config(request):
    return web.json_response({"default_mode": config.DESKTOP_DEFAULT_MODE})


async def pool_status(request):
    user = current_user(request)
    if not user or user.get("role") != "admin":
        return web.json_response({"detail": "需要管理员"}, status=403)
    return web.json_response(await pool.status())


async def resource(request):
    """Relay a binary/asset request (image/css/font) using the shared browser's
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
        resp = await pool.context.request.get(
            url, timeout=30000,
            headers={"Referer": config.PLATFORMS.get(
                request.query.get("platform", "chatgpt"),
                {"home_url": "https://chatgpt.com"})["home_url"]})
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
