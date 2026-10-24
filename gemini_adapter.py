"""Google Gemini web adapter for Share-Gate.

This module drives the public Gemini web app (https://gemini.google.com/app)
inside the same CDP-connected browser that ChatGPT uses. It is intentionally
isolated from the locking/queue/CDP machinery in ``chatgpt_browser.py`` — that
controller owns the browser connection and the page, and passes the live
``page`` object in here while holding the global locks.

Important note
--------------
Google ships frequent, silent UI changes and localises aria-labels, so every
selector is expressed as an ordered list of fallbacks. The selectors are
gathered in :data:`SELECTORS` so they can be adjusted in one place if Google
changes the DOM. Login is performed manually in the shared browser profile;
Gemini remembers the Google account afterwards.
"""

import asyncio
import base64
import logging
import os
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Selector fallbacks (most specific / stable first)
# ---------------------------------------------------------------------------
SELECTORS = {
    # Composer
    "editor": [
        "input-area rich-textarea div[contenteditable='true']",
        "rich-textarea div[contenteditable='true']",
        "div[contenteditable='true']",
        "rich-textarea textarea",
    ],
    "send_button": [
        "button.send-button",
        "button[aria-label='Send message']",
        "button[aria-label='发送消息']",
        "button[aria-label*='Send']",
        "button[aria-label*='发送']",
        "input-area button[mattooltip]",
    ],
    "stop_button": [
        "button.stop-button",
        "button[aria-label='Stop response']",
        "button[aria-label='停止回复']",
        "button[aria-label*='Stop']",
        "button[aria-label*='停止']",
    ],
    "new_chat_button": [
        "button[aria-label='New chat']",
        "button[aria-label='New conversation']",
        "button[aria-label='新建对话']",
        "button[aria-label='开始新的对话']",
        "button[aria-label*='New chat']",
        "button[aria-label*='新建']",
        "button[aria-label*='new chat' i]",
    ],
    "file_input": [
        "input[type='file']",
    ],
    # Conversation / messages
    "model_response": [
        "model-response",
        "model-response-message",
        "div.model-response",
    ],
    "response_markdown": [
        ".markdown-main-panel .markdown",
        "model-response-message .markdown",
        "model-response .markdown",
        ".markdown",
    ],
    "response_in_progress": [
        "model-response.in-progress",
        "model-response-message.in-progress",
        ".in-progress",
        ".loading",
        ".generating",
    ],
    "user_query": [
        "user-query .query-text",
        "user-query",
        "div.question",
    ],
    "signin_button": [
        "a[href*='accounts.google.com']",
        "button[aria-label*='Sign in']",
        "button[aria-label*='登录']",
        "a[aria-label*='Sign in']",
    ],
}

# A Gemini response is considered "done" after this many consecutive idle polls.
REQUIRED_IDLE_CHECKS = 3


class GeminiLoginRequired(RuntimeError):
    """Raised when the Gemini tab is sitting on the Google sign-in page."""


class GeminiAdapter:
    """Stateless helpers that operate on a CDP-connected Gemini page."""

    HOME_URL = "https://gemini.google.com/app"

    def __init__(self, temp_dir=None):
        self.temp_dir = temp_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "temp"
        )
        os.makedirs(self.temp_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Small locator helpers
    # ------------------------------------------------------------------
    async def _first_present(self, page, key, timeout=0.0):
        """Return the first visible locator for a selector key, or None."""
        for sel in SELECTORS[key]:
            loc = page.locator(sel).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception:
                continue
        if timeout:
            deadline = time.time() + timeout
            while time.time() < deadline:
                for sel in SELECTORS[key]:
                    loc = page.locator(sel).first
                    try:
                        if await loc.count() > 0 and await loc.is_visible():
                            return loc
                    except Exception:
                        continue
                await asyncio.sleep(0.4)
        return None

    async def _count_any(self, page, key):
        """Count elements matching any selector for a key (dedup is not needed)."""
        total = 0
        for sel in SELECTORS[key]:
            try:
                total += await page.locator(sel).count()
            except Exception:
                continue
        return total

    async def _any_visible(self, page, key):
        for sel in SELECTORS[key]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return True
            except Exception:
                continue
        return False

    # ------------------------------------------------------------------
    # Login / page readiness
    # ------------------------------------------------------------------
    async def ensure_app_loaded(self, page, timeout_s=20):
        """Navigate to the app if needed and detect the sign-in wall.

        Returns True when the Gemini composer is reachable. Raises
        GeminiLoginRequired when the user must log in first.
        """
        url = page.url or ""
        needs_navigation = "gemini.google.com" not in url
        if needs_navigation:
            logger.info("Opening Gemini app at %s", self.HOME_URL)
            try:
                await page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            except Exception as e:
                # Timeout here is often just slow assets; keep going if URL is on Gemini.
                logger.warning("Gemini navigation warning: %s", e)
                if "gemini.google.com" not in (page.url or ""):
                    raise

        # Wait for either the composer or a sign-in redirect.
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            cur = page.url or ""
            if any(frag in cur for frag in ("accounts.google.com", "accounts.youtube.com",
                                            "signin", "ServiceLogin")):
                raise GeminiLoginRequired(
                    "Gemini 尚未登录：请在自动打开的浏览器标签页中使用 Google 账号登录 "
                    "gemini.google.com，登录完成后再发送消息。"
                )
            editor = await self._first_present(page, "editor")
            if editor is not None:
                return True
            # Some logged-out states stay on gemini.google.com but show a Sign in button.
            if await self._any_visible(page, "signin_button") and not await self._any_visible(page, "editor"):
                raise GeminiLoginRequired(
                    "Gemini 尚未登录：请在浏览器中打开 gemini.google.com 并使用 Google 账号登录。"
                )
            await asyncio.sleep(0.6)

        # Last attempt: distinguish a slow load from a sign-in wall.
        cur = page.url or ""
        if any(frag in cur for frag in ("accounts.google.com", "accounts.youtube.com")):
            raise GeminiLoginRequired(
                "Gemini 尚未登录：请在浏览器中登录 Google 账号后再试。"
            )
        logger.warning("Gemini composer did not appear within %ss (url=%s)", timeout_s, cur)
        return False

    # ------------------------------------------------------------------
    # Conversation isolation
    # ------------------------------------------------------------------
    async def new_chat(self, page):
        """Start a fresh, isolated Gemini conversation.

        Strategy: reload the app home (which resets the active thread), then
        explicitly click the “New chat” button when available.
        """
        try:
            await self.ensure_app_loaded(page)
        except GeminiLoginRequired as e:
            return {"status": "error", "message": str(e)}

        try:
            btn = await self._first_present(page, "new_chat_button", timeout=4)
            if btn is not None:
                await btn.click()
                await asyncio.sleep(1.2)
                logger.info("Clicked Gemini 'New chat' button.")
            else:
                # Fallback: a fresh navigation to /app already opens a blank thread.
                await page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1.0)
            await self.ensure_app_loaded(page)
            return {"status": "success", "message": "已成功创建并开启新的 Gemini 会话！"}
        except GeminiLoginRequired as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.error("Error starting new Gemini chat: %s", e)
            return {"status": "error", "message": f"创建新的 Gemini 会话失败: {e}"}

    # ------------------------------------------------------------------
    # File upload
    # ------------------------------------------------------------------
    async def _upload_files(self, page, valid_paths):
        """Attach files using the first enabled file input."""
        file_input = None
        for sel in SELECTORS["file_input"]:
            candidates = await page.locator(sel).all()
            for inp in candidates:
                try:
                    if await inp.is_enabled():
                        file_input = inp
                        break
                except Exception:
                    continue
            if file_input is not None:
                break
        if file_input is None:
            raise RuntimeError("未找到 Gemini 的文件上传控件。")
        await file_input.wait_for(state="attached", timeout=5000)
        await file_input.set_input_files(valid_paths)
        logger.info("Uploading %d file(s) to Gemini, waiting for processing...", len(valid_paths))
        # Wait for the attachment chips to settle.
        await asyncio.sleep(4)

    # ------------------------------------------------------------------
    # Typing (Angular contenteditable)
    # ------------------------------------------------------------------
    async def _type_prompt(self, page, editor, prompt):
        """Fill the Gemini contenteditable, falling back to keystroke typing."""
        await editor.click()
        try:
            await editor.fill("")
        except Exception:
            pass
        # fill() on a contenteditable usually fires the input event Angular needs.
        try:
            await editor.fill(prompt)
            value = await editor.inner_text()
            if value and value.strip():
                return
        except Exception:
            pass
        # Fallback: type keystroke by keystroke (fires beforeinput/input).
        logger.info("Gemini fill() did not register, falling back to keyboard typing.")
        await editor.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await editor.press_sequentially(prompt, delay=8)

    async def _click_send(self, page, editor):
        """Click an enabled send button; fall back to pressing Enter."""
        deadline = time.time() + 8
        while time.time() < deadline:
            for sel in SELECTORS["send_button"]:
                btn = page.locator(sel).first
                try:
                    if await btn.count() and await btn.is_visible():
                        disabled = await btn.get_attribute("disabled")
                        aria_disabled = await btn.get_attribute("aria-disabled")
                        if disabled is None and aria_disabled != "true":
                            await btn.click()
                            logger.info("Gemini send button clicked (%s).", sel)
                            return True
                except Exception:
                    continue
            await asyncio.sleep(0.4)
        # Fallback: Gemini sends on Enter.
        logger.warning("Send button not enabled, pressing Enter to submit.")
        await editor.click()
        await page.keyboard.press("Enter")
        return True

    # ------------------------------------------------------------------
    # Completion detection
    # ------------------------------------------------------------------
    async def _is_generating(self, page):
        if await self._any_visible(page, "stop_button"):
            return True
        for sel in SELECTORS["response_in_progress"]:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    return True
            except Exception:
                continue
        return False

    # ------------------------------------------------------------------
    # Response extraction
    # ------------------------------------------------------------------
    async def _extract_last_response(self, page):
        """Return the markdown text of the latest model response."""
        for resp_sel in SELECTORS["model_response"]:
            responses = page.locator(resp_sel)
            try:
                count = await responses.count()
            except Exception:
                continue
            if not count:
                continue
            last = responses.last
            for md_sel in SELECTORS["response_markdown"]:
                md = last.locator(md_sel).first
                try:
                    if await md.count() > 0:
                        text = await md.inner_text()
                        if text and text.strip():
                            return text.strip()
                except Exception:
                    continue
            # Fallback: whole last response inner text.
            try:
                text = await last.inner_text()
                if text and text.strip():
                    return text.strip()
            except Exception:
                continue
        return ""

    async def download_image(self, page, img_element, output_path):
        """Download an image using the page's fetch context (bypasses CORS)."""
        try:
            src = await img_element.get_attribute("src")
            if not src:
                return False
            js_code = """
            async (url) => {
                const iframe = document.createElement('iframe');
                iframe.style.display = 'none';
                document.body.appendChild(iframe);
                try {
                    const cleanFetch = iframe.contentWindow.fetch;
                    const response = await cleanFetch(url);
                    const blob = await response.blob();
                    return await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result.split(',')[1]);
                        reader.onerror = reject;
                        reader.readAsDataURL(blob);
                    });
                } finally {
                    iframe.remove();
                }
            }
            """
            data = await page.evaluate(js_code, src)
            image_bytes = base64.b64decode(data)
            with open(output_path, "wb") as fh:
                fh.write(image_bytes)
            logger.info("Saved Gemini image to %s (%d bytes)", output_path, len(image_bytes))
            return True
        except Exception as e:
            logger.warning("Gemini image download failed: %s", e)
            return False

    async def _extract_images(self, page, initial_srcs):
        """Download new images contained in the latest model response."""
        downloaded = []
        for resp_sel in SELECTORS["model_response"]:
            responses = page.locator(resp_sel)
            try:
                if await responses.count() == 0:
                    continue
                last = responses.last
                imgs = await last.locator("img").all()
            except Exception:
                continue
            idx = 1
            for img in imgs:
                try:
                    src = await img.get_attribute("src") or ""
                    width_attr = await img.get_attribute("width") or ""
                    if not (src.startswith("http") or src.startswith("blob:")):
                        continue
                    if src in initial_srcs:
                        continue
                    if width_attr and int(width_attr) <= 48:
                        continue
                    out = os.path.join(self.temp_dir, f"gemini_{int(time.time())}_{idx}.png")
                    if await self.download_image(page, img, out):
                        downloaded.append(out)
                        idx += 1
                except Exception:
                    continue
            if downloaded:
                break
        return downloaded

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    async def send_message(self, page, prompt, file_paths=None, timeout_minutes=6):
        file_paths = file_paths or []
        try:
            await self.ensure_app_loaded(page)
        except GeminiLoginRequired as e:
            return {"status": "error", "message": str(e)}

        try:
            # 1. Uploads
            valid_paths = [p for p in file_paths if os.path.exists(p)]
            if valid_paths:
                await self._upload_files(page, valid_paths)

            editor = await self._first_present(page, "editor", timeout=10)
            if editor is None:
                return {"status": "error", "message": "未找到 Gemini 输入框，可能未登录或页面尚未加载完成。"}

            if not prompt and valid_paths:
                prompt = "请分析这些文件"
            elif not prompt:
                prompt = "你好"

            # Snapshot for image de-duplication.
            initial_srcs = set()
            try:
                for img in await page.locator("img").all():
                    src = await img.get_attribute("src") or ""
                    if src:
                        initial_srcs.add(src)
            except Exception:
                pass

            initial_responses = await self._count_any(page, "model_response")

            # 2. Type
            await self._type_prompt(page, editor, prompt)
            await asyncio.sleep(0.5)

            # 3. Send
            await self._click_send(page, editor)

            # 4. Wait for the response to start.
            start_wait = 0.0
            started = False
            while start_wait < 20.0:
                await asyncio.sleep(0.5)
                start_wait += 0.5
                if await self._any_visible(page, "stop_button"):
                    started = True
                    break
                if await self._count_any(page, "model_response") > initial_responses:
                    started = True
                    break
            if not started:
                logger.warning("Gemini did not show a response/stop indicator within 20s.")

            # 5. Wait for completion.
            max_seconds = timeout_minutes * 60
            elapsed = start_wait
            idle_checks = 0
            while elapsed < max_seconds:
                await asyncio.sleep(1.0)
                elapsed += 1.0
                generating = await self._is_generating(page)
                if generating:
                    idle_checks = 0
                else:
                    idle_checks += 1
                if idle_checks >= REQUIRED_IDLE_CHECKS:
                    logger.info("Gemini response settled after %.1fs.", elapsed)
                    break
            else:
                return {"status": "error", "message": "等待 Gemini 回复超时。"}

            await asyncio.sleep(2)

            # 6. Extract text + images.
            text = await self._extract_last_response(page)
            images = await self._extract_images(page, initial_srcs)

            if not text and not images:
                return {"status": "error", "message": "未能提取到 Gemini 的回复内容（可能仍在生成或发生了错误）。"}

            return {
                "status": "success",
                "text": text or "（已收到回复，但未能提取文本内容。）",
                "images": images,
            }
        except GeminiLoginRequired as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.error("Gemini send_message error: %s", e)
            return {"status": "error", "message": f"Gemini 浏览器交互错误: {e}"}
