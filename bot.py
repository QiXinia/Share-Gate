"""DingTalk (钉钉) robot for the Share-Gate browser controller.

使用钉钉企业内部应用的「Stream 长连接」模式接收消息：
  - 无需公网回调地址，长连接由本地主动发起，适合内网/本地一键启动。
  - 功能：访问白名单 / 管理员、FIFO 排队、多平台（ChatGPT / Gemini）
    切换、文本/图片/文件消息、生成图片回传。

配置见 .env：DINGTALK_APP_KEY / DINGTALK_APP_SECRET /
ALLOWED_DINGTALK_IDS / DINGTALK_ADMIN_IDS。
"""
import os
import re
import json
import logging
import asyncio

import requests
import dingtalk_stream
from dingtalk_stream import AckMessage

import config
from chatgpt_browser import ChatGPTBrowser


# ---------------------------------------------------------------------------
# Logging (shared bot.log file + console)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger(__name__)

# DingTalk single text message limit is generous, but we keep a conservative
# chunk size to stay compatible across clients.
TEXT_CHUNK_LIMIT = 4000

# Initialize the browser controller
browser = ChatGPTBrowser(cdp_url=config.CDP_URL, temp_dir=config.TEMP_DIR)

# Track active queue size (shared FIFO model)
queue_counter = 0
queue_lock = asyncio.Lock()

# Currently selected AI platform for plain chat messages (shared, FIFO model).
current_platform = config.DEFAULT_PLATFORM

# Friendly aliases accepted by /new and /platform.
PLATFORM_ALIASES = {
    "chatgpt": "chatgpt", "gpt": "chatgpt", "c": "chatgpt", "openai": "chatgpt",
    "gemini": "gemini", "google": "gemini", "g": "gemini", "谷歌": "gemini",
}


def resolve_platform_arg(raw):
    """Map a user-supplied platform token to an enabled platform, or None."""
    key = (raw or "").strip().lower()
    platform = PLATFORM_ALIASES.get(key, key)
    return platform if platform in config.AI_PLATFORMS else None


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def sender_ids(msg):
    """Return the set of identifiers attached to an incoming message.

    DingTalk exposes both an enterprise staffId and an encrypted unionId;
    the whitelist may contain either one.
    """
    ids = set()
    for value in (getattr(msg, "sender_staff_id", None),
                  getattr(msg, "sender_id", None)):
        if value:
            ids.add(str(value))
    return ids


def is_user_allowed(msg) -> bool:
    """Empty whitelist means the bot is open to everyone (legacy behavior)."""
    if not config.ALLOWED_DINGTALK_IDS:
        return True
    return bool(sender_ids(msg) & config.ALLOWED_DINGTALK_IDS)


def is_admin(msg) -> bool:
    return bool(sender_ids(msg) & config.DINGTALK_ADMIN_IDS)


# ---------------------------------------------------------------------------
# Small reply helpers (DingTalk's SDK reply_* methods are blocking requests)
# ---------------------------------------------------------------------------
async def reply_text(msg, text: str):
    """Send a plain-text reply, splitting oversized content into chunks."""
    text = text or ""
    if not text:
        return
    if len(text) <= TEXT_CHUNK_LIMIT:
        chunks = [text]
    else:
        chunks = [text[i:i + TEXT_CHUNK_LIMIT]
                  for i in range(0, len(text), TEXT_CHUNK_LIMIT)]
    for chunk in chunks:
        await asyncio.to_thread(handler.reply_text, chunk, msg)


async def reply_image(msg, image_path: str, caption: str = None):
    """Upload a generated image and send it back as a sampleImage message."""
    def _do():
        with open(image_path, "rb") as f:
            data = f.read()
        ext = os.path.splitext(image_path)[1].lstrip(".") or "png"
        mime = f"image/{'jpeg' if ext.lower() in ('jpg', 'jpeg') else ext.lower()}"
        media_id = handler.dingtalk_client.upload_to_dingtalk(
            data, filetype="image",
            filename=os.path.basename(image_path),
            mimetype=mime,
        )
        if not media_id:
            raise RuntimeError("上传图片到钉钉失败（mediaId 为空）")
        photo = media_id if media_id.startswith("@") else f"@{media_id}"
        payload = {
            "msgtype": "sampleImage",
            "sampleImage": {"photoMediaId": photo},
        }
        if caption:
            # Send the caption as a separate text message for reliability.
            requests.post(
                msg.session_webhook,
                headers={"Content-Type": "application/json"},
                data=json.dumps({"msgtype": "text",
                                 "text": {"content": caption}}),
                timeout=30,
            ).raise_for_status()
        resp = requests.post(
            msg.session_webhook,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=60,
        )
        resp.raise_for_status()
        return resp

    try:
        await asyncio.to_thread(_do)
    except Exception as e:
        logger.error("Failed to send image back to DingTalk: %s", e)
        await reply_text(msg, "⚠️ 图片回传失败：%s" % e)


# ---------------------------------------------------------------------------
# Request orchestration (FIFO queue)
# ---------------------------------------------------------------------------
async def handle_request(msg, prompt: str, image_path: str = None,
                         file_paths: list = None):
    """Process a chat/image request sequentially via browser automation."""
    global queue_counter

    async with queue_lock:
        queue_counter += 1
        current_pos = queue_counter

    try:
        if current_pos > 1:
            await reply_text(
                msg,
                f"⏳ 排队中...\n当前有 {current_pos - 1} 个任务在您前面，请稍候。"
            )
        else:
            await reply_text(msg, "🤖 正在为您准备会话，连接浏览器...")

        platform_label = config.PLATFORMS.get(current_platform, {}).get("label", "AI")
        await reply_text(
            msg,
            f"🚀 正在向 {platform_label} 提交请求，请稍候（可能需要 1-3 分钟）..."
        )

        logger.info("Processing request on [%s]: prompt='%s', image=%s, files=%s",
                    current_platform, (prompt or "")[:50], image_path, file_paths)

        # DingTalk robot messages cannot be edited after being sent, so we do
        # not live-edit a countdown timer; instead the request runs and we post
        # the final result (and any failure) once it completes.
        result = await browser.send_message(
            prompt, image_path=image_path, file_paths=file_paths,
            platform=current_platform,
        )

        if result["status"] == "success":
            response_text = result.get("text", "")
            if response_text:
                await reply_text(msg, response_text)

            img_paths = result.get("images", [])
            if img_paths:
                logger.info("Sending %d generated image(s) back to DingTalk...",
                            len(img_paths))
                for idx, img_p in enumerate(img_paths):
                    caption = "🎨 生成的图片" if len(img_paths) == 1 else f"🎨 生成的图片 {idx + 1}"
                    await reply_image(msg, img_p, caption)
            elif "画" in (prompt or "") or "draw" in (prompt or "").lower() \
                    or "image" in (prompt or "").lower():
                logger.warning("Generation succeeded but no images were found.")
                await reply_text(
                    msg,
                    "⚠️ 生成完成，但在页面上未提取到生成的图片，可能加载较慢或防盗链。"
                )

            # Cleanup uploaded temp files
            for tmp in ([image_path] if image_path else []) + (file_paths or []) + img_paths:
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError as e:
                        logger.warning("Failed to remove temp file %s: %s", tmp, e)
        else:
            await reply_text(
                msg,
                f"❌ 操作失败\n原因: {result.get('message', '未知错误')}"
            )

    except Exception as e:
        logger.error("Uncaught error in handle_request: %s", e, exc_info=True)
        await reply_text(msg, f"❌ 处理出错\n{e}")
    finally:
        async with queue_lock:
            queue_counter = max(0, queue_counter - 1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
async def cmd_start(msg):
    await reply_text(
        msg,
        "🤖 ChatGPT / Gemini 网页自动化机器人已启动\n\n"
        "你可以向我发送：\n"
        "1. 💬 纯文字对话 —— 比如：讲个冷笑话\n"
        "2. 🎨 文生图指令 —— 比如：帮我画一只猫咪\n"
        "3. 🖼️ 发送图片并附带文字 —— 进行图生图分析与修改\n"
        "4. 📄 发送文件（PDF / 文档等）进行分析\n\n"
        "⚠️ 注意：机器人直接在本地浏览器串行操作，多用户并发会自动进入队列排队。\n"
        "发送 /help 查看全部指令。"
    )


async def cmd_new(msg, args):
    """Start a fresh conversation on the current (or specified) platform."""
    global queue_counter, current_platform

    target = current_platform
    if args:
        parsed = resolve_platform_arg(args[0])
        if parsed is None:
            await reply_text(
                msg,
                f"⚠️ 未知平台：{args[0]}\n"
                f"当前启用：{', '.join(config.AI_PLATFORMS)}\n"
                "用法：/new gemini 或 /new chatgpt"
            )
            return
        target = parsed

    async with queue_lock:
        if queue_counter > 0:
            await reply_text(
                msg,
                "⚠️ 无法清理会话\n\n"
                f"当前有 {queue_counter} 个任务正在排队或执行中。\n"
                "请等待所有任务完成后再使用 /new 命令，以免破坏其他用户的对话上下文。"
            )
            return
        queue_counter += 1

    target_label = config.PLATFORMS.get(target, {}).get("label", target)
    await reply_text(msg, f"🔄 正在清理 {target_label} 上下文，开启新会话...")
    try:
        result = await browser.new_chat(platform=target)
        if result["status"] == "success":
            current_platform = target
            await reply_text(
                msg,
                f"✅ 已在 {target_label} 开启新会话！\n"
                "之前的上下文已被清除，后续消息将发送到该平台。\n\n"
                "⚠️ 注意：所有用户共享同一浏览器会话，切换平台会影响全局。"
            )
        else:
            await reply_text(msg, f"❌ 开启新会话失败: {result.get('message')}")
    except Exception as e:
        await reply_text(msg, f"❌ 操作出错: {e}")
    finally:
        async with queue_lock:
            queue_counter = max(0, queue_counter - 1)


async def cmd_platform(msg, args):
    """Show the current platform or switch it."""
    global current_platform
    if not args:
        lines = []
        for p in config.AI_PLATFORMS:
            marker = "👉" if p == current_platform else "  "
            lines.append(f"{marker} {config.PLATFORMS[p]['label']}  ({p})")
        await reply_text(
            msg,
            f"ℹ️ 当前平台：{config.PLATFORMS[current_platform]['label']}\n\n"
            + "\n".join(lines)
            + "\n\n切换：/platform gemini（切换后建议用 /new gemini 开启新会话）"
        )
        return
    parsed = resolve_platform_arg(args[0])
    if parsed is None:
        await reply_text(
            msg,
            f"⚠️ 未知平台：{args[0]}\n当前启用：{', '.join(config.AI_PLATFORMS)}"
        )
        return
    current_platform = parsed
    await reply_text(
        msg,
        f"✅ 已切换到 {config.PLATFORMS[parsed]['label']}。\n"
        f"发送 /new {parsed} 可开启该平台的全新隔离会话。"
    )


async def cmd_status(msg):
    browser_info = await browser.get_status()
    lines = []
    for p in browser_info.get("enabled_platforms", config.AI_PLATFORMS):
        st = browser_info.get("platforms", {}).get(p, {})
        login_flag = "✅已登录" if st.get("logged_in") else (
            "⚠️未登录" if st.get("status") == "connected" else "—")
        lines.append(f"  • {config.PLATFORMS[p]['label']}: {st.get('status')} {login_flag}")
    await reply_text(
        msg,
        "ℹ️ 当前状态信息\n\n"
        "🤖 Bot 状态: 运行中\n"
        f"🎛️ 当前平台: {config.PLATFORMS.get(current_platform, {}).get('label', current_platform)}\n"
        + "\n".join(lines)
        + f"\n👥 队列排队人数: {queue_counter}"
    )


async def cmd_log(msg):
    """Admin only: return the last 25 lines of the execution log."""
    log_path = "bot.log"
    if not os.path.exists(log_path):
        await reply_text(msg, "❌ 暂无日志文件。")
        return
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        last = "".join(lines[-25:])
        # Plain text (DingTalk text does not render markdown code fences).
        await reply_text(msg, "📋 最近的 25 行运行日志：\n\n" + last)
    except Exception as e:
        await reply_text(msg, f"❌ 读取日志出错: {e}")


async def cmd_help(msg):
    await reply_text(
        msg,
        "ℹ️ 可用指令列表：\n\n"
        "• /start - 查看机器人引导介绍\n"
        "• /platform - 查看 / 切换 AI 平台（chatgpt / gemini）\n"
        "• /new - 开启新对话，如 /new gemini（切换平台并清除上下文）\n"
        "• /status - 查看各平台连接/登录状态与队列排队人数\n"
        "• /log - 获取后台最近 25 行运行日志（管理员）\n"
        "• /help - 显示此帮助信息\n\n"
        "💡 提示：首次使用 Gemini 请在浏览器中用 Google 账号登录 gemini.google.com；"
        "之后可直接发送文字，或发送图片/文件进行交互。"
    )


# ---------------------------------------------------------------------------
# Incoming message handling
# ---------------------------------------------------------------------------
_AT_PREFIX = re.compile(r"^(\s*@[^\s@]+\s+)+")


def clean_text(content: str) -> str:
    """Strip the leading @robot mention used in group chats."""
    if not content:
        return ""
    return _AT_PREFIX.sub("", content).strip()


async def download_media(download_code: str, filename: str) -> str:
    """Resolve a DingTalk downloadCode and save the file locally."""
    download_url = await asyncio.to_thread(
        handler.get_image_download_url, download_code
    )
    if not download_url:
        raise RuntimeError("无法获取钉钉文件下载地址")
    resp = await asyncio.to_thread(requests.get, download_url)
    resp.raise_for_status()
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    safe_name = os.path.basename(filename) or f"media_{int(__import__('time').time())}"
    local_path = os.path.join(config.TEMP_DIR, f"upload_{download_code[:10]}_{safe_name}")
    with open(local_path, "wb") as f:
        f.write(resp.content)
    return local_path


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class ShareGateChatbotHandler(dingtalk_stream.ChatbotHandler):
    async def process(self, callback: dingtalk_stream.CallbackMessage):
        try:
            msg = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
            # Acknowledge immediately so DingTalk does not retry; the actual
            # request is dispatched as a background task.
            asyncio.create_task(self.dispatch(msg))
        except Exception as e:
            logger.error("Failed to parse incoming DingTalk message: %s",
                         e, exc_info=True)
        return AckMessage.STATUS_OK, 'OK'

    async def dispatch(self, msg):
        msg_type = getattr(msg, "message_type", None)
        nick = getattr(msg, "sender_nick", None)

        # Access control
        if not is_user_allowed(msg):
            ids = " / ".join(sorted(sender_ids(msg))) or "(未知)"
            logger.warning("Access denied for DingTalk user ids=%s nick=%s",
                           ids, nick)
            await reply_text(
                msg,
                "⛔ 访问被拒绝\n\n"
                "您不在该机器人的允许名单中，无法使用此服务。\n"
                f"您的钉钉用户 ID 是：{ids}\n"
                "请联系管理员将该 ID 加入 .env 的 ALLOWED_DINGTALK_IDS。"
            )
            return

        try:
            if msg_type == "text":
                await self.handle_text(msg)
            elif msg_type == "picture":
                await self.handle_picture(msg)
            elif msg_type == "richText":
                await self.handle_rich_text(msg)
            else:
                logger.info("Unsupported message type: %s", msg_type)
                await reply_text(
                    msg,
                    "⚠️ 暂不支持该类型的消息，请发送文字、图片或文件。发送 /help 查看帮助。"
                )
        except Exception as e:
            logger.error("dispatch error: %s", e, exc_info=True)
            await reply_text(msg, f"❌ 处理出错\n{e}")

    # -- text ---------------------------------------------------------------
    async def handle_text(self, msg):
        text = clean_text(getattr(msg.text, "content", ""))
        if not text:
            return

        if text.startswith("/"):
            parts = text.split()
            cmd = parts[0].lstrip("/").lower()
            args = parts[1:]
            if cmd in ("start", "help", "开始", "帮助"):
                await (cmd_help if cmd in ("help", "帮助") else cmd_start)(msg)
            elif cmd == "new":
                await cmd_new(msg, args)
            elif cmd in ("platform", "平台"):
                await cmd_platform(msg, args)
            elif cmd == "status":
                await cmd_status(msg)
            elif cmd == "log":
                if not is_admin(msg):
                    logger.warning("Admin command denied for ids=%s",
                                   sorted(sender_ids(msg)))
                    await reply_text(msg, "⛔ 该指令仅限管理员使用。")
                else:
                    await cmd_log(msg)
            else:
                await reply_text(msg, f"⚠️ 未知指令：/{cmd}，发送 /help 查看全部指令。")
            return

        # Plain chat message -> queue
        asyncio.create_task(handle_request(msg, prompt=text))

    # -- picture ------------------------------------------------------------
    async def handle_picture(self, msg):
        code = getattr(msg.image_content, "download_code", None)
        if not code:
            await reply_text(msg, "⚠️ 未能读取到图片。")
            return
        path = await download_media(code, "image.png")
        logger.info("Downloaded user picture to %s", path)
        asyncio.create_task(
            handle_request(msg, prompt="", image_path=path)
        )

    # -- rich text (text + image + file attachments) ------------------------
    async def handle_rich_text(self, msg):
        items = getattr(msg.rich_text_content, "rich_text_list", []) or []
        text_parts, image_paths, file_paths = [], [], []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" or "content" in item:
                t = item.get("text") or item.get("content")
                if t:
                    text_parts.append(str(t))
                continue
            code = item.get("downloadCode") or item.get("imageFileDownloadCode")
            if not code:
                continue
            filename = item.get("fileName") or "file"
            ext = os.path.splitext(filename)[1].lower()
            path = await download_media(code, filename)
            if ext in _IMAGE_EXTS or item.get("type") == "picture":
                image_paths.append(path)
            else:
                file_paths.append(path)

        prompt = clean_text(" ".join(text_parts))
        if not image_paths and not file_paths:
            # Treat as plain text if no attachment could be resolved.
            if prompt:
                asyncio.create_task(handle_request(msg, prompt=prompt))
            else:
                await reply_text(msg, "⚠️ 未能读取到附件内容。")
            return

        image_path = image_paths[0] if image_paths else None
        extra_images = image_paths[1:]
        asyncio.create_task(
            handle_request(
                msg, prompt=prompt,
                image_path=image_path,
                file_paths=(file_paths + extra_images) if (file_paths or extra_images) else None,
            )
        )


# Global handler instance (referenced by the module-level reply helpers).
handler = ShareGateChatbotHandler()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
def credentials_configured() -> bool:
    key = config.DINGTALK_APP_KEY.strip()
    secret = config.DINGTALK_APP_SECRET.strip()
    return bool(key and secret and key not in ("YOUR_APP_KEY_HERE",)
                and secret not in ("YOUR_APP_SECRET_HERE",))


async def run(client):
    logger.info("Connecting browser during startup...")
    try:
        await browser.start()
        logger.info("Browser connection ready.")
    except Exception as e:
        logger.warning(
            "Could not connect browser during startup (CDP port 9222 might not be open yet): %s",
            e,
        )
    try:
        # client.start() keeps a single event loop and auto-reconnects on drop.
        await client.start()
    finally:
        logger.info("Shutting down browser connection...")
        await browser.stop()


def main():
    if not credentials_configured():
        logger.critical(
            "DINGTALK_APP_KEY / DINGTALK_APP_SECRET not set or still placeholders "
            "in .env — starting DingTalk bot is skipped (web-only mode)."
        )
        return

    logger.info("Initializing DingTalk Stream robot...")
    if config.ALLOWED_DINGTALK_IDS:
        logger.info("DingTalk access whitelist enabled: %s",
                    sorted(config.ALLOWED_DINGTALK_IDS))
    else:
        logger.warning(
            "ALLOWED_DINGTALK_IDS is empty — the bot is OPEN to every DingTalk "
            "user who can reach it. Configure a whitelist in .env for safety."
        )
    if config.DINGTALK_ADMIN_IDS:
        logger.info("DingTalk admins: %s", sorted(config.DINGTALK_ADMIN_IDS))

    # The SDK uses `requests` for OpenAPI calls; honoring configured proxies
    # covers token fetch / media download / upload.
    proxy = config.HTTP_PROXY or config.HTTPS_PROXY
    if proxy:
        logger.info("Configuring outbound proxy: %s", proxy)
        os.environ.setdefault("HTTP_PROXY", proxy)
        os.environ.setdefault("HTTPS_PROXY", proxy)
        os.environ.setdefault("http_proxy", proxy)
        os.environ.setdefault("https_proxy", proxy)

    credential = dingtalk_stream.Credential(
        config.DINGTALK_APP_KEY, config.DINGTALK_APP_SECRET
    )
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.ChatbotMessage.TOPIC, handler
    )

    logger.info("Starting DingTalk Stream loop...")
    asyncio.run(run(client))


if __name__ == "__main__":
    main()
