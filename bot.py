import os
import logging
import asyncio
from telegram import Update, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

import config
from chatgpt_browser import ChatGPTBrowser

# Shared logger config supporting both bot.log file and console stream
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger(__name__)

# Initialize the browser controller
browser = ChatGPTBrowser(cdp_url=config.CDP_URL, temp_dir=config.TEMP_DIR)

# Track active queue size
queue_counter = 0
queue_lock = asyncio.Lock()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a greeting message when /start is run."""
    welcome_text = (
        "🤖 **ChatGPT 网页自动化机器人已启动**\n\n"
        "你可以向我发送：\n"
        "1. 💬 **纯文字对话** — 比如：`讲个冷笑话`\n"
        "2. 🎨 **文生图指令** — 比如：`帮我画一只猫咪`\n"
        "3. 🖼️ **发送图片并附带文字** — 进行**图生图**分析与修改！\n\n"
        "⚠️ *注意：机器人会直接在本地浏览器进行串行模拟操作，如遇多用户并发会自动进入队列排队。*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def send_long_message(update: Update, text: str):
    """Helper function to split and send messages longer than Telegram's limit (4096 chars)."""
    limit = 4000
    if len(text) <= limit:
        await update.message.reply_text(text)
    else:
        for i in range(0, len(text), limit):
            chunk = text[i:i + limit]
            await update.message.reply_text(chunk)

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, image_path: str = None):
    """Main orchestrator for processing chat/image requests sequentially via browser automation."""
    global queue_counter
    
    # Safely increment counter under lock
    async with queue_lock:
        queue_counter += 1
        current_pos = queue_counter

    status_msg = None
    try:
        # If queue is busy, notify user of their position
        if current_pos > 1:
            status_msg = await update.message.reply_text(
                f"⏳ **排队中...**\n当前有 {current_pos - 1} 个任务在您前面，请稍候。"
            )
        else:
            status_msg = await update.message.reply_text("🤖 **正在为您准备会话，连接浏览器...**")

        # Update status once execution begins
        if status_msg:
            try:
                await status_msg.edit_text("🚀 **正在向 ChatGPT 提交请求，请稍候（可能需要 1-3 分钟）...**")
            except Exception:
                pass
        
        # Start background progress reporter to update elapsed time every 5 seconds
        stop_progress = False
        async def progress_reporter():
            seconds = 0
            while not stop_progress:
                await asyncio.sleep(5)
                if stop_progress:
                    break
                seconds += 5
                hourglass = ["⏳", "⌛"][(seconds // 5) % 2]
                try:
                    await status_msg.edit_text(
                        f"🚀 **ChatGPT 正在处理您的请求...**\n"
                        f"⏱️ 当前已用时: `{seconds}` 秒 {hourglass}"
                    )
                except Exception:
                    pass

        reporter_task = asyncio.create_task(progress_reporter())

        logger.info(f"Processing request: prompt='{prompt[:50]}', image={image_path}")
        try:
            # Lock is now managed inside browser.send_message() itself
            result = await browser.send_message(prompt, image_path)
        finally:
            # Always ensure reporter task is stopped cleanly
            stop_progress = True
            await reporter_task
        
        # Delete status message
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

        if result["status"] == "success":
            # Send text response
            response_text = result.get("text", "")
            if response_text:
                await send_long_message(update, response_text)
            
            # Send generated images if any
            img_paths = result.get("images", [])
            if img_paths:
                logger.info(f"Sending {len(img_paths)} generated images back to Telegram...")
                if len(img_paths) == 1:
                    # Single photo
                    with open(img_paths[0], "rb") as photo:
                        await update.message.reply_photo(
                            photo=photo, 
                            caption="🎨 DALL-E 3 生成的图片",
                            write_timeout=120
                        )
                else:
                    # Multiple photos in media group
                    media = [InputMediaPhoto(media=open(p, "rb")) for p in img_paths]
                    await update.message.reply_media_group(
                        media=media,
                        write_timeout=120
                    )
            else:
                if "画" in prompt or "draw" in prompt.lower() or "image" in prompt.lower():
                    logger.warning("Generation succeeded but no images were found in the last turn.")
                    await update.message.reply_text("⚠️ **生成完成，但在页面上未提取到生成的图片，可能加载较慢或防盗链。**")
            
            # Clean up local temporary image file if we uploaded one
            if image_path and os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception as e:
                    logger.warning(f"Failed to remove temp upload image {image_path}: {e}")

            # Clean up generated images from local disk
            for img_p in img_paths:
                if os.path.exists(img_p):
                    try:
                        os.remove(img_p)
                    except Exception as e:
                        logger.warning(f"Failed to remove temp generated image {img_p}: {e}")
        else:
            error_msg = result.get("message", "未知错误")
            await update.message.reply_text(f"❌ **操作失败**\n原因: {error_msg}")

    except Exception as e:
        logger.error(f"Uncaught error in handle_request: {e}", exc_info=True)
        if status_msg:
            try:
                await status_msg.edit_text(f"❌ **处理出错**\n{e}")
            except Exception:
                await update.message.reply_text(f"❌ **处理出错**\n{e}")
    finally:
        async with queue_lock:
            queue_counter = max(0, queue_counter - 1)

async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered on plain text messages."""
    prompt = update.message.text
    # Run request in background task so Telegram handlers don't block
    asyncio.create_task(handle_request(update, context, prompt=prompt))

async def on_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered when user sends an image (with or without caption)."""
    photo_file = await update.message.photo[-1].get_file()
    caption = update.message.caption or ""
    
    # Save the photo to temporary location
    temp_filename = f"upload_{update.message.message_id}_{int(asyncio.get_event_loop().time())}.png"
    local_path = os.path.join(config.TEMP_DIR, temp_filename)
    
    await photo_file.download_to_drive(local_path)
    logger.info(f"Downloaded user photo to {local_path}")
    
    # Queue up the request
    asyncio.create_task(handle_request(update, context, prompt=caption, image_path=local_path))

async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to start a fresh ChatGPT conversation session.
    
    Refuses to execute if other tasks are currently queued/running,
    to prevent destroying another user's ongoing conversation context.
    """
    global queue_counter

    # Safety check: refuse if other tasks are active
    async with queue_lock:
        if queue_counter > 0:
            await update.message.reply_text(
                "⚠️ **无法清理会话**\n\n"
                f"当前有 {queue_counter} 个任务正在排队或执行中。\n"
                "请等待所有任务完成后再使用 `/new` 命令，以免破坏其他用户的对话上下文。",
                parse_mode="Markdown"
            )
            return
        queue_counter += 1
    
    status_msg = await update.message.reply_text("🔄 **正在请求开启新会话...**")
    try:
        await status_msg.edit_text("🚀 **正在清理浏览器上下文，开启新会话...**")
        # Lock is now managed inside browser.new_chat() itself
        result = await browser.new_chat()
        await status_msg.delete()
        if result["status"] == "success":
            await update.message.reply_text(
                "✅ **成功开启新会话！**\n"
                "之前的上下文已被清除。\n\n"
                "⚠️ *注意：所有用户（包括 Streamlit 前端）的对话上下文均已重置。*",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"❌ **开启新会话失败**: {result.get('message')}")
    except Exception as e:
        await update.message.reply_text(f"❌ **操作出错**: {e}")
    finally:
        async with queue_lock:
            queue_counter = max(0, queue_counter - 1)

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to retrieve current browser connection and queue status."""
    browser_info = await browser.get_status()
    status_text = (
        f"ℹ️ **当前状态信息**\n\n"
        f"🤖 **Bot 状态**: 运行中\n"
        f"🌐 **浏览器连接**: `{browser_info.get('status')}`\n"
        f"📄 **当前标签页**: `{browser_info.get('title')}`\n"
        f"🔗 **当前 URL**: `{browser_info.get('url')}`\n"
        f"👥 **队列排队人数**: `{queue_counter}`"
    )
    await update.message.reply_text(status_text)

async def show_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to fetch the last 20 lines of the execution log."""
    log_path = "bot.log"
    if not os.path.exists(log_path):
        await update.message.reply_text("❌ 暂无日志文件。")
        return
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        last_lines = lines[-25:]
        log_content = "".join(last_lines)
        await update.message.reply_text(
            f"📋 **最近的 25 行运行日志：**\n```\n{log_content}\n```",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 读取日志出错: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to show help details."""
    help_text = (
        "ℹ️ **可用指令列表：**\n\n"
        "• `/start` - 查看机器人引导介绍\n"
        "• `/new` - 开启新对话（清除当前 ChatGPT 对话上下文）\n"
        "• `/status` - 查看浏览器连接状态与当前队列排队人数\n"
        "• `/log` - 获取后台最近 25 行运行日志\n"
        "• `/help` - 显示此帮助信息\n\n"
        "💡 *提示：您可以直接向我发送任何文字进行聊天，或发送图片附带文字进行图生图交互。*"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

def main():
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN.strip() in ("", "YOUR_BOT_TOKEN_HERE"):
        logger.critical("TELEGRAM_BOT_TOKEN environment variable not set or invalid placeholder in .env!")
        return

    logger.info("Initializing Telegram Bot...")
    
    # Build application with proxy settings if defined
    builder = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN)
    
    if config.HTTP_PROXY or config.HTTPS_PROXY:
        proxy_url = config.HTTP_PROXY or config.HTTPS_PROXY
        logger.info(f"Configuring bot client proxy: {proxy_url}")
        # Build custom request with proxy
        request_obj = HTTPXRequest(proxy_url=proxy_url)
        builder = builder.request(request_obj)
        
    app = builder.build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_chat))
    app.add_handler(CommandHandler("status", bot_status))
    app.add_handler(CommandHandler("log", show_log))
    app.add_handler(CommandHandler("help", help_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_message))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo_message))

    # Initialize browser and commands on startup
    async def on_startup(application):
        # Set Telegram bot command list for UI auto-complete popup
        from telegram import BotCommand
        bot_commands = [
            BotCommand("start", "查看机器人引导和指令介绍"),
            BotCommand("new", "开启新对话（清除当前上下文）"),
            BotCommand("status", "查看浏览器连接状态与排队人数"),
            BotCommand("log", "获取后台最近 25 行运行日志"),
            BotCommand("help", "显示指令帮助信息"),
        ]
        try:
            await application.bot.set_my_commands(bot_commands)
            logger.info("Set Telegram bot commands successfully.")
        except Exception as e:
            logger.warning(f"Failed to set Telegram commands: {e}")

        logger.info("Connecting browser during startup...")
        try:
            await browser.start()
            logger.info("Browser connection ready.")
        except Exception as e:
            logger.warning(f"Could not connect browser during startup (CDP port 9222 might not be open yet): {e}")

    async def on_shutdown(application):
        logger.info("Shutting down browser connection...")
        await browser.stop()

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    logger.info("Starting Telegram Bot poll loop...")
    app.run_polling()

if __name__ == "__main__":
    main()
