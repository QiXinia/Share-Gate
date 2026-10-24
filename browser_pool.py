"""Per-user browser tab pool for the 1:1 shared desktop.

All users share the SAME logged-in Chrome profile (the same ChatGPT Plus /
Gemini account), but each user gets an INDEPENDENT browser tab pointed at a
fresh conversation. Tabs are keyed by (user, platform) and are reused across
reconnects, so a page refresh keeps the same conversation; idle tabs are
reclaimed after a configurable timeout.

The browser itself is launched once with remote debugging; this module only
connects over CDP and manages tabs. It deliberately does NOT use the global
serialization lock from chatgpt_browser.py because each user drives their own
tab concurrently (different tabs on the same account are isolated).
"""
import time
import asyncio
import logging

from playwright.async_api import async_playwright

import config

logger = logging.getLogger(__name__)


class PoolOverflow(Exception):
    """Raised when the global tab cap is reached."""


class BrowserPool:
    def __init__(self, cdp_url=None, max_tabs=None, idle_close_min=None):
        self.cdp_url = cdp_url or config.CDP_URL
        self.max_tabs = max_tabs or config.DESKTOP_MAX_TABS
        self.idle_close_sec = (idle_close_min if idle_close_min is not None
                               else config.DESKTOP_IDLE_CLOSE_MIN) * 60
        self.playwright = None
        self.browser = None
        self.context = None
        # (user, platform) -> {"page", "viewers", "last_active"}
        self.entries = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    async def start(self):
        if self.context is not None:
            return
        self.playwright = await async_playwright().start()
        logger.info("Pool connecting to browser via CDP: %s", self.cdp_url)
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url)
        except Exception as e:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
            raise RuntimeError(
                f"Could not connect to Chrome debugging port at {self.cdp_url}: {e}"
            ) from e
        self.context = self.browser.contexts[0]
        logger.info("Browser pool ready (profile context acquired).")

    async def _ensure(self):
        if self.context is None:
            await self.start()

    async def stop(self):
        async with self._lock:
            for key in list(self.entries.keys()):
                await self._close_entry(key)
            self.entries.clear()
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
        self.context = None
        self.browser = None
        self.playwright = None

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------
    async def _open_fresh_tab(self, platform):
        meta = config.PLATFORMS.get(platform)
        if not meta:
            raise ValueError(f"Unknown platform: {platform}")
        page = await self.context.new_page()
        # A root URL without a conversation id opens a fresh composer and keeps
        # different users on independent conversation threads.
        try:
            await page.goto(meta["home_url"], wait_until="domcontentloaded",
                            timeout=30000)
        except Exception as e:
            logger.warning("Initial navigation for %s returned: %s",
                           platform, e)
        return page

    async def _close_entry(self, key):
        entry = self.entries.get(key)
        if not entry:
            return
        page = entry.get("page")
        if page:
            try:
                await page.close()
            except Exception:
                pass
        self.entries.pop(key, None)

    async def acquire(self, user, platform):
        """Return (page, is_new) for the user/platform; register a viewer."""
        await self._ensure()
        if platform not in config.AI_PLATFORMS:
            raise ValueError(f"Platform not enabled: {platform}")
        key = (user, platform)
        async with self._lock:
            entry = self.entries.get(key)
            if entry is not None:
                page = entry["page"]
                if page.is_closed():
                    await self._close_entry(key)
                    entry = None
            if entry is None:
                if len(self.entries) >= self.max_tabs:
                    # Try to reclaim an idle tab before giving up.
                    reclaimed = await self._reap_locked(force=True)
                    if not reclaimed:
                        raise PoolOverflow(
                            f"已达并发标签页上限（{self.max_tabs}），请稍后再试。"
                        )
                page = await self._open_fresh_tab(platform)
                entry = {"page": page, "viewers": 0, "last_active": time.time()}
                self.entries[key] = entry
                is_new = True
            else:
                is_new = False
            entry["viewers"] += 1
            entry["last_active"] = time.time()
            return entry["page"], is_new

    async def release(self, user, platform):
        key = (user, platform)
        async with self._lock:
            entry = self.entries.get(key)
            if entry:
                entry["viewers"] = max(0, entry["viewers"] - 1)
                entry["last_active"] = time.time()

    async def touch(self, user, platform):
        key = (user, platform)
        async with self._lock:
            entry = self.entries.get(key)
            if entry:
                entry["last_active"] = time.time()

    async def new_cdp_session(self, page):
        """Attach a CDP session to a managed page (for screencast / input)."""
        await self._ensure()
        return await self.context.new_cdp_session(page)

    async def new_chat(self, user, platform):
        """Navigate the user's tab back to a fresh conversation root."""
        key = (user, platform)
        meta = config.PLATFORMS.get(platform)
        if not meta:
            return {"status": "error", "message": f"未知平台: {platform}"}
        async with self._lock:
            entry = self.entries.get(key)
            page = entry.get("page") if entry else None
            if page is None or page.is_closed():
                page = await self._open_fresh_tab(platform)
                self.entries[key] = {"page": page, "viewers": 0,
                                     "last_active": time.time()}
            else:
                try:
                    await page.goto(meta["home_url"], wait_until="domcontentloaded",
                                    timeout=30000)
                except Exception as e:
                    return {"status": "error", "message": str(e)}
            self.entries[key]["last_active"] = time.time()
        return {"status": "success", "message": "已开启新会话"}

    async def reload(self, user, platform):
        key = (user, platform)
        async with self._lock:
            entry = self.entries.get(key)
            if entry and entry.get("page") and not entry["page"].is_closed():
                await entry["page"].reload(wait_until="domcontentloaded",
                                           timeout=30000)
                return {"status": "success"}
        return {"status": "error", "message": "页面不存在"}

    async def _reap_locked(self, force=False):
        """Close one/zero-viewer tabs. Must run while holding self._lock."""
        now = time.time()
        for key, entry in list(self.entries.items()):
            if entry["viewers"] > 0:
                continue
            if force or now - entry["last_active"] > self.idle_close_sec:
                logger.info("Reclaiming idle desktop tab: %s", key)
                await self._close_entry(key)
                return True
        return False

    async def reap_once(self):
        async with self._lock:
            while await self._reap_locked(force=False):
                pass

    async def status(self):
        async with self._lock:
            live = []
            for (user, platform), e in self.entries.items():
                if not e["page"].is_closed():
                    live.append({"user": user, "platform": platform,
                                 "viewers": e["viewers"]})
            return {"tabs": len(live), "max_tabs": self.max_tabs, "items": live}
