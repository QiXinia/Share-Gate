import asyncio
import base64
import os
import sys
import time
import logging
from contextlib import contextmanager
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cross-process file lock
# ---------------------------------------------------------------------------
class _FileLock:
    """OS-level file lock that works across independent processes.

    On Windows uses msvcrt.locking; on POSIX uses fcntl.flock.
    This guarantees only one process can hold the lock at a time,
    preventing bot.py and app_streamlit.py from driving the browser
    simultaneously.
    """

    def __init__(self, path: str):
        self._path = path
        self._fd = None

    @contextmanager
    def acquire(self):
        """Context manager: acquires the lock, yields, then releases."""
        # Open (or create) the lock file; keep the fd open while held.
        self._fd = os.open(self._path, os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform == "win32":
                import msvcrt
                while True:
                    try:
                        msvcrt.locking(self._fd, msvcrt.LK_LOCK, 1)
                        break
                    except OSError as e:
                        if e.errno in (13, 36):
                            time.sleep(0.5)
                        else:
                            raise
            else:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_EX)
            logger.debug("File lock acquired: %s", self._path)
            yield
        finally:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None
                logger.debug("File lock released: %s", self._path)

class ChatGPTBrowser:
    def __init__(self, cdp_url="http://127.0.0.1:9222", temp_dir=None):
        self.cdp_url = cdp_url
        self.temp_dir = temp_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.lock = asyncio.Lock()
        # Cross-process file lock — prevents bot.py and Streamlit from
        # controlling the browser at the same time.
        self._file_lock = _FileLock(os.path.join(self.temp_dir, ".browser.lock"))
        # Queue / health metrics (mutated only from the asyncio loop thread).
        self.pending_count = 0   # tasks accepted, including the one running
        self.active_count = 0    # tasks currently driving the browser
        self.total_completed = 0
        self.last_activity_at = None

    async def start(self):
        """Connect to the Chrome instance via CDP and find/open the ChatGPT page."""
        # Always create a fresh playwright instance to avoid stale state from failed attempts
        if self.playwright is not None:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None

        self.playwright = await async_playwright().start()

        logger.info(f"Connecting to browser via CDP: {self.cdp_url}")
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url)
        except Exception as e:
            logger.error(f"Failed to connect to CDP: {e}")
            # Clean up so the next retry attempt starts fresh
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
            raise RuntimeError(
                f"Could not connect to Chrome debugging port at {self.cdp_url}. "
                "Please make sure Chrome is started with --remote-debugging-port=9222"
            ) from e

        self.context = self.browser.contexts[0]
        
        # Look for an existing ChatGPT tab
        self.page = None
        for p in self.context.pages:
            if "chatgpt.com" in p.url:
                self.page = p
                logger.info(f"Found active ChatGPT tab: '{await p.title()}' (URL: {p.url})")
                break

        # If not found, open a new page on chatgpt.com
        if not self.page:
            logger.info("No active ChatGPT tab found. Opening a new tab on chatgpt.com...")
            self.page = await self.context.new_page()
            await self.page.goto("https://chatgpt.com")
            # Wait for page to load
            await self.page.wait_for_load_state("networkidle")
            logger.info("Opened chatgpt.com in a new tab.")

    async def stop(self):
        """Disconnect from the browser and stop playwright."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        logger.info("Disconnected from browser.")

    def _get_dedup_key(self, src: str) -> str:
        """Extracts a normalized deduplication key from an image source URL."""
        if not src:
            return ""
        # Remove HTML escapes (e.g. &amp; -> &)
        normalized = src.replace("&amp;", "&")
        try:
            import urllib.parse
            parsed = urllib.parse.urlparse(normalized)
            params = urllib.parse.parse_qs(parsed.query)
            if "id" in params:
                return params["id"][0]
        except Exception:
            pass
        return normalized

    async def download_image(self, img_element, output_path):
        """Downloads an image using the page's fetch context to bypass CORS/cookies."""
        try:
            src = await img_element.get_attribute("src")
            if not src:
                return False

            # JS function to fetch image as base64 using a clean iframe to bypass monkey-patched global fetch
            js_code = """
            async (url) => {
                const iframe = document.createElement('iframe');
                iframe.style.display = 'none';
                document.body.appendChild(iframe);
                try {
                    const cleanFetch = iframe.contentWindow.fetch;
                    const response = await cleanFetch(url);
                    const blob = await response.blob();
                    return new Promise((resolve, reject) => {
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
            base64_data = await self.page.evaluate(js_code, src)
            image_bytes = base64.b64decode(base64_data)
            
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            
            logger.info(f"Saved image to {output_path} ({len(image_bytes)} bytes)")
            return True
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
            return False

    async def send_message(self, prompt, image_path=None, file_paths=None, features=None, timeout_minutes=6):
        """Sends a message to ChatGPT, handles image/file uploads if present, and returns the response.

        Uses both an asyncio.Lock (intra-process) and a file lock (cross-process)
        to ensure only one caller drives the browser at any given time.
        """
        self.pending_count += 1
        self.last_activity_at = time.time()
        try:
            async with self.lock:
                return await self._send_message_inner(prompt, image_path, file_paths, features, timeout_minutes)
        finally:
            self.pending_count = max(0, self.pending_count - 1)
            self.total_completed += 1
            self.last_activity_at = time.time()

    async def _send_message_inner(self, prompt, image_path=None, file_paths=None, features=None, timeout_minutes=6):
        """Inner implementation of send_message, called while holding the asyncio lock."""
        self.active_count += 1
        # Acquire cross-process file lock in a thread so we don't block the event loop
        loop = asyncio.get_running_loop()
        lock_ctx = self._file_lock.acquire()
        await loop.run_in_executor(None, lock_ctx.__enter__)
        try:
            return await self._do_send_message(prompt, image_path, file_paths, features, timeout_minutes)
        finally:
            try:
                await loop.run_in_executor(None, lock_ctx.__exit__, None, None, None)
            finally:
                self.active_count = max(0, self.active_count - 1)

    async def _do_send_message(self, prompt, image_path=None, file_paths=None, features=None, timeout_minutes=6):
        """Core send-message logic, called while holding both locks."""
        # Ensure browser is connected
        try:
            if not self.page or self.page.is_closed():
                await self.start()
        except Exception as e:
            return {"status": "error", "message": f"Connection error: {e}"}

        try:
            # Normalize inputs: combine image_path into file_paths if provided
            if not file_paths:
                file_paths = []
            if image_path:
                if image_path not in file_paths:
                    file_paths.append(image_path)

            # 1. Handle file upload for Image/Files if file_paths are provided
            if file_paths:
                valid_paths = [p for p in file_paths if os.path.exists(p)]
                if valid_paths:
                    logger.info(f"Uploading files: {valid_paths}")
                    # Look for hidden file inputs
                    file_input = self.page.locator('input[type="file"]').first
                    await file_input.wait_for(state="attached", timeout=5000)
                    await file_input.set_input_files(valid_paths)
                    
                    # Give it a few seconds to finish uploading and rendering in the DOM
                    logger.info("Waiting for file upload to process...")
                    await asyncio.sleep(5)

            # 2. Locate prompt textarea and fill it
            textarea = self.page.locator("#prompt-textarea")
            await textarea.wait_for(state="visible", timeout=10000)
            await textarea.click()

            # 2.5 Handle feature toggles (Thinking, Web Search, Deep Research) if requested
            if features:
                logger.info(f"Aligning browser features: {features}")
                for feature_name, target_state in features.items():
                    if feature_name not in ["thinking", "webSearch", "deepResearch"]:
                        continue
                    
                    label_map = {
                        "thinking": ["Thinking", "思考"],
                        "webSearch": ["Web search", "网络搜索"],
                        "deepResearch": ["Deep research", "深度搜索"]
                    }
                    keywords = label_map[feature_name]
                    
                    # 1. Open menu
                    plus_btn = self.page.locator('button[data-testid="composer-plus-btn"], button[aria-label="Add files and more"]').first
                    if await plus_btn.count() == 0:
                        logger.warning("Composer plus button not found in browser, skipping toggle.")
                        continue
                        
                    await plus_btn.click()
                    await asyncio.sleep(0.8)
                    
                    # 2. Inspect state and click if different
                    menu_items = await self.page.locator('[role="menuitemradio"]').all()
                    target_item = None
                    for item in menu_items:
                        text = await item.inner_text()
                        if any(kw.lower() in text.lower() for kw in keywords):
                            target_item = item
                            break
                            
                    if target_item:
                        aria_checked = await target_item.get_attribute("aria-checked")
                        data_state = await target_item.get_attribute("data-state")
                        current_state = (aria_checked == "true") or (data_state == "checked")
                        
                        logger.info(f"Browser feature '{feature_name}': current={current_state}, target={target_state}")
                        if current_state != target_state:
                            logger.info(f"Clicking menu item to toggle '{feature_name}' to {target_state}")
                            await target_item.click()
                            await asyncio.sleep(0.8) # Wait for click and menu auto-dismiss
                        else:
                            # It is already correct, press Escape to dismiss the menu
                            await self.page.keyboard.press("Escape")
                            await asyncio.sleep(0.3)
                    else:
                        # Item not found, press Escape
                        await self.page.keyboard.press("Escape")
                        await asyncio.sleep(0.3)
            
            # If prompt is empty but we uploaded files, provide a default prompt based on file types
            if not prompt and file_paths:
                has_non_img = any(not p.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')) for p in file_paths)
                prompt = "请分析这些文件" if has_non_img else "请分析这些图片"
            elif not prompt:
                prompt = "Hello"

            # Determine if this is likely a drawing prompt
            is_drawing_prompt = any(keyword in prompt.lower() for keyword in ["画", "draw", "image", "dalle", "paint", "poster", "sketch", "illustration"])
            
            # Helper to count generated DALL-E images on the page
            async def get_generated_images_count():
                try:
                    imgs = await self.page.locator('img').all()
                    count = 0
                    for img in imgs:
                        alt = await img.get_attribute("alt") or ""
                        src = await img.get_attribute("src") or ""
                        if (src.startswith("http") or src.startswith("blob:")) and alt.startswith("Generated image:"):
                            count += 1
                    return count
                except Exception as e:
                    logger.warning(f"Error counting images: {e}")
                    return 0

            # Record initial image count and sources snapshot to detect new image creation and avoid history duplicates
            initial_img_count = await get_generated_images_count()
            initial_srcs = set()
            try:
                imgs = await self.page.locator('img').all()
                for img in imgs:
                    src = await img.get_attribute("src") or ""
                    if src:
                        initial_srcs.add(self._get_dedup_key(src))
            except Exception as e:
                logger.warning(f"Error capturing initial image sources: {e}")
            logger.info(f"Initial generated DALL-E images: {initial_img_count}, total images on page: {len(initial_srcs)}")

            # Count existing assistant turns to verify when a new one starts
            assistant_locator = self.page.locator('.agent-turn, [data-message-author-role="assistant"]')
            initial_count = await assistant_locator.count()
            logger.info(f"Initial assistant message count: {initial_count}")

            logger.info(f"Filling prompt: {prompt[:100]}...")
            await textarea.fill(prompt)

            # 3. Locate and click the send button
            send_btn = self.page.locator('button[data-testid="send-button"]')
            await send_btn.wait_for(state="visible", timeout=5000)
            
            # Click send
            await send_btn.click()
            logger.info("Send button clicked.")

            # Wait for a new assistant turn to start (maximum 20 seconds)
            logger.info("Waiting for new assistant turn to appear...")
            start_wait_time = 0.0
            new_turn_started = False
            while start_wait_time < 20.0:
                await asyncio.sleep(0.5)
                start_wait_time += 0.5
                current_count = await assistant_locator.count()
                if current_count > initial_count:
                    new_turn_started = True
                    logger.info(f"New assistant turn detected after {start_wait_time}s (Count: {current_count})")
                    break
            
            if not new_turn_started:
                logger.warning("Timed out waiting for new assistant turn to appear. ChatGPT may not have received the message.")

            # 4. Wait for generation to finish (polling stop-button, streaming status, image count, and DALL-E loading frames)
            logger.info("Waiting for ChatGPT response to complete...")
            max_seconds = timeout_minutes * 60
            check_interval = 1.0
            elapsed = start_wait_time
            
            consecutive_idle_checks = 0
            required_idle_checks = 3
            
            while elapsed < max_seconds:
                await asyncio.sleep(check_interval)
                elapsed += check_interval
                
                # 4.1 Check if new DALL-E image has been rendered (the most reliable indicator for successful drawing)
                current_img_count = await get_generated_images_count()
                if is_drawing_prompt and current_img_count > initial_img_count:
                    logger.info(f"New generated image detected! (Count: {current_img_count} > {initial_img_count})")
                    break
                
                # 4.2 Check stop button visibility (indicates text generation / streaming is active)
                stop_btn = self.page.locator('button[data-testid="stop-button"]')
                has_stop = await stop_btn.is_visible()
                
                # 4.3 Check active streaming or aria-busy indicators on the page
                is_streaming = await self.page.locator('.result-streaming, [aria-busy="true"]').count() > 0
                
                # 4.4 Check if active DALL-E image generation loading frames are present
                is_drawing_state = await self.page.locator('[data-testid="image-gen-loading-state-frame"], [data-testid="image-gen-loading-state"]').count() > 0
                
                # Check if currently idle
                is_idle = not has_stop and not is_streaming and not is_drawing_state
                
                if is_idle:
                    consecutive_idle_checks += 1
                else:
                    consecutive_idle_checks = 0  # Reset counter if any generation/busy signal is active
                
                # For drawing prompts, if the image has not appeared yet, wait longer in case of text-only refusals or errors
                idle_limit = required_idle_checks if not is_drawing_prompt else 12
                if consecutive_idle_checks >= idle_limit:
                    logger.info(f"Generation completed successfully or text refusal received in {elapsed:.1f} seconds.")
                    break
            else:
                logger.warning("Generation timed out.")
                return {"status": "error", "message": "Generation timed out waiting for response."}

            # Let the page settle
            await asyncio.sleep(3)

            # 5. Extract response text using a robust fallback chain (scoped to last_assistant ONLY)
            text_response = ""
            last_assistant = self.page.locator('.agent-turn, [data-message-author-role="assistant"]').last
            
            # Extract thinking/reasoning process if present
            thinking_text = ""
            try:
                # 1. Look for details element
                details_el = last_assistant.locator('details').first
                if await details_el.count() > 0:
                    thinking_text = await details_el.inner_text()
                else:
                    # 2. Look for element with data-testid or class containing 'thought'
                    thought_el = last_assistant.locator('[data-testid="thought-process"], [class*="thought"], [class*="thinking"], [class*="reasoning"]').first
                    if await thought_el.count() > 0:
                        text_content = await thought_el.inner_text()
                        if text_content:
                            thinking_text = text_content
            except Exception as e:
                logger.warning(f"Error checking for thinking block: {e}")

            # Extract search queries if present
            search_text = ""
            try:
                search_el = last_assistant.locator('[data-testid*="search"], [class*="search"]').first
                if await search_el.count() > 0:
                    text_content = await search_el.inner_text()
                    if text_content and ("search" in text_content.lower() or "搜索" in text_content):
                        if len(text_content) < 300:
                            search_text = text_content
            except Exception as e:
                logger.warning(f"Error checking for search block: {e}")

            # Try 1: last_assistant's .markdown
            markdown_el = last_assistant.locator('.markdown').first
            if await markdown_el.count() > 0:
                text_response = await markdown_el.inner_text()
            else:
                # Try 2: last assistant turn inner text
                if await last_assistant.count() > 0:
                    text_response = await last_assistant.inner_text()
                else:
                    # Try 3: last assistant turn's .markdown.prose
                    prose_el = last_assistant.locator('.markdown.prose').first
                    if await prose_el.count() > 0:
                        text_response = await prose_el.inner_text()
                    else:
                        # Try 4: last assistant turn's .markdown
                        general_md = last_assistant.locator('.markdown').first
                        if await general_md.count() > 0:
                            text_response = await general_md.inner_text()

            # Format final response combining thinking process, search process, and text
            final_formatted = ""
            if thinking_text:
                thinking_text = thinking_text.strip()
                # Clean up header from innerText if present (e.g. "Thought\n" or "已思考")
                lines = thinking_text.split('\n')
                if len(lines) > 1 and ("thought" in lines[0].lower() or "思考" in lines[0]):
                    thinking_text = "\n".join(lines[1:])
                final_formatted += f"<details class='thought-details bg-purple-500/5 dark:bg-purple-950/20 p-3 rounded-xl border border-purple-500/10 dark:border-purple-500/20 mb-3'><summary class='cursor-pointer text-xs font-semibold text-purple-600 dark:text-purple-400 select-none'>💭 思考过程</summary><div class='text-xs text-gray-600 dark:text-gray-300 mt-2 whitespace-pre-wrap leading-relaxed'>{thinking_text}</div></details>\n\n"
                
            if search_text:
                search_text = search_text.strip()
                lines = search_text.split('\n')
                display_search = lines[0]
                final_formatted += f"<div class='search-indicator bg-blue-50/5 dark:bg-blue-950/20 p-2.5 rounded-xl border border-blue-500/10 dark:border-blue-500/20 text-xs text-blue-600 dark:text-blue-400 mb-3 flex items-center gap-2 select-none'><i class='fa-solid fa-globe animate-spin' style='animation-duration: 6s;'></i> <span>{display_search}</span></div>\n\n"

            if text_response:
                text_response = text_response.strip()
                if text_response.lower() == "edit":
                    text_response = ""
                final_formatted += text_response
            else:
                final_formatted += "[Failed to extract response content]"

            # 6. Extract generated images (check last turn first, fallback to page-wide reverse scan filtered against snapshot)
            downloaded_images = []
            img_index = 1
            downloaded_srcs = set() # Track already downloaded sources to avoid duplicates
            
            async def try_download_image(img_el):
                nonlocal img_index
                alt = await img_el.get_attribute("alt") or ""
                src = await img_el.get_attribute("src") or ""
                width_attr = await img_el.get_attribute("width") or ""
                height_attr = await img_el.get_attribute("height") or ""
                
                # Skip tiny icons / assistant avatars
                if alt == "ChatGPT" or (width_attr and int(width_attr) <= 48) or (height_attr and int(height_attr) <= 48):
                    return False
                    
                if src.startswith("http") or src.startswith("blob:"):
                    dedup_key = self._get_dedup_key(src)
                    # Avoid downloading the same image source multiple times
                    if dedup_key in downloaded_srcs:
                        return False
                    downloaded_srcs.add(dedup_key)
                    
                    out_filename = f"gen_{int(time.time())}_{img_index}.png"
                    out_path = os.path.join(self.temp_dir, out_filename)
                    logger.info(f"Found image candidate: alt='{alt}', src='{src[:100]}...'")
                    logger.info(f"Downloading image to {out_path}...")
                    success = await self.download_image(img_el, out_path)
                    if success:
                        downloaded_images.append(out_path)
                        img_index += 1
                        return True
                return False

            # Try scoped turn first
            if await last_assistant.count() > 0:
                imgs = await last_assistant.locator('img').all()
                for img in imgs:
                    await try_download_image(img)
                    
            # Fallback: scan all images page-wide in reverse order (bottom-up), matching only new items
            if not downloaded_images:
                logger.info("No images found in last assistant turn. Scanning page-wide in reverse order...")
                all_imgs = await self.page.locator('img').all()
                for img in reversed(all_imgs):
                    src = await img.get_attribute("src") or ""
                    alt = await img.get_attribute("alt") or ""
                    if src:
                        dedup_key = self._get_dedup_key(src)
                        # Ensure it is a newly generated DALL-E image and not in the pre-send snapshot
                        if dedup_key not in initial_srcs:
                            if alt.startswith("Generated image:"):
                                success = await try_download_image(img)
                                if success:
                                    logger.info("Successfully matched and downloaded page-wide new image.")
                                    break

            return {
                "status": "success",
                "text": final_formatted,
                "images": downloaded_images
            }

        except Exception as e:
            logger.error(f"Error during message submission: {e}")
            return {"status": "error", "message": f"Browser interaction error: {e}"}

    async def new_chat(self):
        """Navigates to chatgpt.com to start a new conversation thread.

        Acquires both the asyncio lock and the cross-process file lock
        to prevent conflicts with any concurrent send_message calls.
        """
        self.pending_count += 1
        self.active_count += 1
        self.last_activity_at = time.time()
        try:
            async with self.lock:
                loop = asyncio.get_running_loop()
                lock_ctx = self._file_lock.acquire()
                await loop.run_in_executor(None, lock_ctx.__enter__)
                try:
                    return await self._do_new_chat()
                finally:
                    await loop.run_in_executor(None, lock_ctx.__exit__, None, None, None)
        finally:
            self.pending_count = max(0, self.pending_count - 1)
            self.active_count = max(0, self.active_count - 1)
            self.total_completed += 1
            self.last_activity_at = time.time()

    async def _do_new_chat(self):
        """Inner new_chat implementation, called while holding both locks."""
        try:
            if not self.page or self.page.is_closed():
                await self.start()
            logger.info("Navigating to start a new chat...")
            await self.page.goto("https://chatgpt.com")
            await self.page.wait_for_load_state("networkidle")
            return {"status": "success", "message": "已成功创建并开启新会话！"}
        except Exception as e:
            logger.error(f"Error starting new chat: {e}")
            return {"status": "error", "message": f"创建新会话失败: {e}"}

    async def get_status(self):
        """Returns browser connection status, active tab and queue metrics."""
        queue_info = {
            "pending": self.pending_count,
            "active": self.active_count,
            "waiting": max(0, self.pending_count - self.active_count),
            "total_completed": self.total_completed,
            "last_activity_at": self.last_activity_at,
        }
        if not self.page or self.page.is_closed():
            return {"status": "disconnected", "url": "N/A", "title": "N/A", "queue": queue_info}
        try:
            title = await self.page.title()
            url = self.page.url
            return {"status": "connected", "url": url, "title": title, "queue": queue_info}
        except Exception as e:
            return {"status": "error", "message": str(e), "queue": queue_info}



# Quick self-testing loop
if __name__ == "__main__":
    async def test():
        browser = ChatGPTBrowser()
        try:
            await browser.start()
            result = await browser.send_message("画一只可爱的熊猫")
            print("TEST RESULT:", result)
        finally:
            await browser.stop()

    asyncio.run(test())
