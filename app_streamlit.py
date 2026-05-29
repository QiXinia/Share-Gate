import os
import time
import urllib.parse
import logging
import threading
import asyncio
from PIL import Image
import streamlit as st

# Configure logger to output to both console and bot.log file
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

import config
from chatgpt_browser import ChatGPTBrowser

class BrowserRunner:
    def __init__(self):
        logger.info("Initializing BrowserRunner background thread event loop...")
        self.browser = ChatGPTBrowser(cdp_url=config.CDP_URL, temp_dir=config.TEMP_DIR)
        if os.name == 'nt':
            self.loop = asyncio.ProactorEventLoop()
        else:
            self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.browser.start())
            logger.info("Browser connection initialized successfully inside background thread.")
        except Exception as e:
            logger.error(f"Error starting browser in background loop: {e}")
        self.loop.run_forever()

    def run_coroutine(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

@st.cache_resource
def get_browser_runner():
    return BrowserRunner()

def load_image_to_memory(file_path):
    try:
        with open(file_path, "rb") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load image {file_path} to memory: {e}")
        return None

# 1. Page Configuration & Aesthetic Style injection
st.set_page_config(
    page_title="ChatGPT 网页控制台",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Premium styling using fonts and header custom styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&family=Outfit:wght@300;400;600;800&display=swap');
    
    html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        font-family: 'Outfit', 'Inter', sans-serif;
    }
    
    /* Header background glow */
    .header-container {
        padding: 2rem 0rem;
        background: linear-gradient(90deg, rgba(137, 180, 250, 0.15) 0%, rgba(203, 166, 247, 0.15) 100%);
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        margin-bottom: 2rem;
        text-align: center;
    }
    
    .header-title {
        font-size: 2.8rem;
        font-weight: 800;
        background: linear-gradient(90deg, #89b4fa 0%, #cba6f7 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    .header-subtitle {
        color: #a6adc8;
        font-size: 1.1rem;
    }
</style>
""", unsafe_allow_html=True)

# Render main header banner
st.markdown("""
<div class="header-container">
    <div class="header-title">🤖 ChatGPT 网页控制台</div>
    <div class="header-subtitle">基于 Playwright CDP 协议的浏览器自动化助手</div>
</div>
""", unsafe_allow_html=True)

# 2. Setup/retrieve browser runner singleton
runner = get_browser_runner()

# 3. Sidebar setup & status monitoring
st.sidebar.markdown("### 🌐 浏览器连接状态")

# Refresh button to trigger manual status fetch
if st.sidebar.button("🔄 刷新状态"):
    st.rerun()

try:
    browser_status = runner.run_coroutine(runner.browser.get_status()).result(timeout=5)
    # If disconnected, the background thread may still be initializing — wait and retry once
    if browser_status.get("status") != "connected":
        time.sleep(3)
        browser_status = runner.run_coroutine(runner.browser.get_status()).result(timeout=5)
except Exception as e:
    browser_status = {"status": "error", "message": str(e)}

if browser_status.get("status") == "connected":
    st.sidebar.success(f"已连接 | {browser_status.get('title', 'ChatGPT')}")
    st.sidebar.caption(f"**URL**: {browser_status.get('url', 'N/A')}")
else:
    st.sidebar.error(f"未连接 | 原因: {browser_status.get('message', 'CDP 端口未开启')}")

# Reset/New Chat operation — two-step confirmation to prevent accidental context loss
st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ 会话控制")

if "confirm_new_chat" not in st.session_state:
    st.session_state.confirm_new_chat = False

if not st.session_state.confirm_new_chat:
    if st.sidebar.button("🗑️ 清理会话 (开启新对话)", use_container_width=True):
        st.session_state.confirm_new_chat = True
        st.rerun()
else:
    st.sidebar.warning(
        "⚠️ **确认清理？**\n\n"
        "此操作会清除当前 ChatGPT 的对话上下文，"
        "所有用户（包括 Telegram Bot 端）的对话都会受到影响。"
    )
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("✅ 确认清理", use_container_width=True):
            st.session_state.confirm_new_chat = False
            with st.sidebar.spinner("正在重置浏览器会话..."):
                res = runner.run_coroutine(runner.browser.new_chat()).result()
                if res["status"] == "success":
                    st.session_state.messages = []
                    st.sidebar.success("会话重置成功！")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.sidebar.error(f"重置失败: {res.get('message')}")
    with col2:
        if st.button("❌ 取消", use_container_width=True):
            st.session_state.confirm_new_chat = False
            st.rerun()

# Image Uploader for Image-to-Image / Vision prompts
st.sidebar.markdown("---")
st.sidebar.markdown("### 🖼️ 图生图分析 (Vision)")
uploaded_file = st.sidebar.file_uploader(
    "上传单张图片，并在下方对话框中输入你的指令：",
    type=["png", "jpg", "jpeg"]
)
if uploaded_file is not None:
    st.sidebar.image(uploaded_file, caption="待上传图片预览", use_column_width=True)



# 4. Chat messages container & renderer
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("text"):
            st.markdown(msg["text"])
        if msg.get("images"):
            for img_bytes in msg["images"]:
                st.image(img_bytes, caption="图片内容")

# 5. Handle chat inputs
if prompt := st.chat_input("输入对话内容，或输入 '帮我画一只奶龙' 进行绘图..."):
    # Append user message with text & optional uploaded image preview bytes
    user_msg = {"role": "user", "text": prompt}
    
    temp_upload_path = None
    user_img_bytes = None
    if uploaded_file is not None:
        # Save file to disk temporarily for Playwright input element submission
        suffix = os.path.splitext(uploaded_file.name)[1]
        temp_filename = f"st_upload_{int(time.time())}{suffix}"
        temp_upload_path = os.path.join(config.TEMP_DIR, temp_filename)
        with open(temp_upload_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        user_img_bytes = uploaded_file.getvalue()
        user_msg["images"] = [user_img_bytes]

    st.session_state.messages.append(user_msg)
    
    # Render user message immediately
    with st.chat_message("user"):
        st.markdown(prompt)
        if user_img_bytes:
            st.image(user_img_bytes, caption="已上传图片")
            
    # Process ChatGPT Response
    with st.chat_message("assistant"):
        try:
            # Dispatch command and get future
            # Lock serialization is handled inside browser.send_message() itself
            future = runner.run_coroutine(runner.browser.send_message(prompt, temp_upload_path))
            
            # Display real-time progress counter/spinner
            progress_placeholder = st.empty()
            seconds = 0
            while not future.done():
                time.sleep(1)
                seconds += 1
                hourglass = ["⏳", "⌛"][seconds % 2]
                progress_placeholder.info(f"{hourglass} **ChatGPT 正在控制浏览器执行请求...** (当前已用时: `{seconds}` 秒)")
            
            # Retrieve final result
            result = future.result()
            progress_placeholder.empty()
        except Exception as e:
            logger.error(f"Failed execution block: {e}", exc_info=True)
            result = {"status": "error", "message": str(e)}
        finally:
            # Delete temp uploaded file from local filesystem
            if temp_upload_path and os.path.exists(temp_upload_path):
                try:
                    os.remove(temp_upload_path)
                except Exception as e:
                    logger.warning(f"Error removing temp upload file {temp_upload_path}: {e}")

        # Handle successful response
        if result.get("status") == "success":
            response_text = result.get("text", "")
            img_paths = result.get("images", [])
            
            # Load images into RAM as bytes and delete local temp files
            assistant_images = []
            for path in img_paths:
                img_data = load_image_to_memory(path)
                if img_data:
                    assistant_images.append(img_data)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception as e:
                        logger.warning(f"Error deleting temp generated image {path}: {e}")
            
            # Render response content
            if response_text:
                st.markdown(response_text)
            
            for img_bytes in assistant_images:
                st.image(img_bytes, caption="DALL-E 3 生成的图片")

            # Store assistant response to session state messages list
            assistant_msg = {"role": "assistant", "text": response_text}
            if assistant_images:
                assistant_msg["images"] = assistant_images
            st.session_state.messages.append(assistant_msg)
        else:
            error_msg = result.get("message", "未知浏览器自动化错误")
            st.error(f"❌ 浏览器控制失败\n**原因**: {error_msg}")
            st.session_state.messages.append({"role": "assistant", "text": f"❌ 浏览器控制失败: {error_msg}"})
            
    # Refresh/rerun Streamlit context
    st.rerun()
