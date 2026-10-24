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
        # Retry connection up to 10 times (total ~30s) to handle
        # the race condition where Chrome CDP port isn't ready yet.
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                self.loop.run_until_complete(self.browser.start())
                logger.info("Browser connection initialized successfully inside background thread.")
                break
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"Browser connect attempt {attempt}/{max_retries} failed: {e}. Retrying in 3s...")
                    import time
                    time.sleep(3)
                else:
                    logger.error(f"Failed to connect to browser after {max_retries} attempts: {e}")
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

def format_file_size(size_in_bytes):
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"
    elif size_in_bytes < 1024 * 1024:
        return f"{size_in_bytes / 1024:.1f} KB"
    else:
        return f"{size_in_bytes / (1024 * 1024):.1f} MB"

def get_file_icon(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
        return "🖼️"
    elif ext in ('.pdf'):
        return "📕"
    elif ext in ('.doc', '.docx'):
        return "📝"
    elif ext in ('.xls', '.xlsx', '.csv'):
        return "📊"
    elif ext in ('.txt', '.md', '.py', '.js', '.html', '.css', '.json'):
        return "📄"
    elif ext in ('.zip', '.rar', '.7z', '.tar', '.gz'):
        return "📦"
    else:
        return "📁"

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

    /* Style file uploader to be sleek and compact like ChatGPT */
    [data-testid="stFileUploader"] {
        border: 1px dashed rgba(255, 255, 255, 0.15) !important;
        border-radius: 12px !important;
        padding: 10px !important;
        background-color: rgba(255, 255, 255, 0.02) !important;
        transition: border-color 0.3s;
    }
    [data-testid="stFileUploader"]:hover {
        border-color: #89b4fa !important;
    }

    /* Custom premium styling for chat bubbles */
    [data-testid="stChatMessage"] {
        border-radius: 12px !important;
        padding: 1.25rem !important;
        margin-bottom: 1rem !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        background-color: rgba(255, 255, 255, 0.02) !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    
    [data-testid="stChatMessage"][data-user="true"] {
        background-color: rgba(137, 180, 250, 0.08) !important;
        border-left: 4px solid #89b4fa !important;
    }
    
    [data-testid="stChatMessage"][data-user="false"] {
        background-color: rgba(203, 166, 247, 0.05) !important;
        border-left: 4px solid #cba6f7 !important;
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

# ---------------------------------------------------------------------------
# Access gate: the standalone Streamlit console is a local admin tool and must
# not be open to anyone reaching the port. Unlock with STREAMLIT_PASSWORD /
# ADMIN_PASSWORD from .env.
# ---------------------------------------------------------------------------
def _show_login_gate():
    if st.session_state.get("streamlit_authed"):
        return True
    if not config.STREAMLIT_PASSWORD:
        st.error(
            "未配置访问密码。请在 .env 中设置 ADMIN_PASSWORD（或 "
            "STREAMLIT_PASSWORD）后重启本服务。"
        )
        st.stop()
        return False

    st.markdown("#### 🔒 控制台访问验证")
    st.caption("这是本地管理员控制台，请输入访问密码。")
    with st.form("streamlit_login_form", clear_on_submit=True):
        password = st.text_input("访问密码", type="password", placeholder="请输入密码")
        submitted = st.form_submit_button("登录")
    if submitted:
        import hmac as _hmac
        if _hmac.compare_digest(password, config.STREAMLIT_PASSWORD):
            st.session_state.streamlit_authed = True
            st.rerun()
        else:
            st.error("密码错误，请重试。")
    st.stop()
    return False


_show_login_gate()

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
        "此操作会清除当前 AI 平台的对话上下文，"
        "所有用户（包括钉钉机器人端）的对话都会受到影响。"
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

# 4. Chat messages container & renderer
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("text"):
            st.markdown(msg["text"])
        
        # Render files/images if present in user message
        if msg.get("files"):
            img_files = [f for f in msg["files"] if f["is_image"]]
            doc_files = [f for f in msg["files"] if not f["is_image"]]
            
            if img_files:
                for img in img_files:
                    st.image(img["bytes"], caption=img["name"], width=300)
            
            if doc_files:
                chips_html = '<div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; margin-bottom: 8px;">'
                for doc in doc_files:
                    icon = get_file_icon(doc["name"])
                    size_str = format_file_size(len(doc["bytes"]))
                    chips_html += f"""
                    <div style="
                        display: flex;
                        align-items: center;
                        background-color: #1e1e1e;
                        border: 1px solid rgba(255, 255, 255, 0.08);
                        border-radius: 8px;
                        padding: 6px 12px;
                        gap: 8px;
                        max-width: 200px;
                    ">
                        <span style="font-size: 1.2rem;">{icon}</span>
                        <div style="display: flex; flex-direction: column; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            <span style="font-size: 0.8rem; color: #ececec; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">{doc["name"]}</span>
                            <span style="font-size: 0.65rem; color: #8a8a8a;">{size_str}</span>
                        </div>
                    </div>
                    """
                chips_html += '</div>'
                st.markdown(chips_html, unsafe_allow_html=True)

        if msg.get("images"):
            for img_bytes in msg["images"]:
                st.image(img_bytes, caption="图片内容", width=300)

# ChatGPT Style attachment upload area on the main chat panel
st.markdown("---")
col_upload_title, _ = st.columns([2, 1])
with col_upload_title:
    st.markdown("""
    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
        <span style="font-size: 1.05rem; font-weight: 600; color: #ececec;">📎 附件上传 (支持图片及各类文档)</span>
    </div>
    """, unsafe_allow_html=True)

uploaded_files = st.file_uploader(
    "上传附件",
    type=None,
    accept_multiple_files=True,
    label_visibility="collapsed"
)

# Render attachment preview chips if files are uploaded
if uploaded_files:
    chips_html = '<div class="chatgpt-attachments-container" style="display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; margin-bottom: 12px;">'
    for f in uploaded_files:
        icon = get_file_icon(f.name)
        size_str = format_file_size(f.size)
        chips_html += f"""
        <div style="
            display: flex;
            align-items: center;
            background-color: #212121;
            border: 1px solid rgba(255, 255, 255, 0.10);
            border-radius: 10px;
            padding: 8px 12px;
            gap: 10px;
            max-width: 250px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        ">
            <span style="font-size: 1.4rem; line-height: 1;">{icon}</span>
            <div style="display: flex; flex-direction: column; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                <span style="font-size: 0.85rem; color: #f9f9f9; font-weight: 500; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">{f.name}</span>
                <span style="font-size: 0.7rem; color: #9b9b9b;">{size_str}</span>
            </div>
        </div>
        """
    chips_html += '</div>'
    st.markdown(chips_html, unsafe_allow_html=True)

# 5. Handle chat inputs
if prompt := st.chat_input("输入对话内容，或输入 '帮我画一只奶龙' 进行绘图..."):
    # Append user message with text & optional uploaded image/file preview bytes
    user_msg = {"role": "user", "text": prompt}
    
    temp_file_paths = []
    user_files = []
    
    if uploaded_files:
        for index, uploaded_file in enumerate(uploaded_files):
            # Save file to disk temporarily for Playwright input element submission
            # Preserve original filename for ChatGPT file analysis
            original_name = uploaded_file.name
            safe_name = os.path.basename(original_name)
            temp_filename = f"st_upload_{index}_{int(time.time())}_{safe_name}"
            temp_path = os.path.join(config.TEMP_DIR, temp_filename)
            
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            temp_file_paths.append(temp_path)
            
            is_image = uploaded_file.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif'))
            user_files.append({
                "name": uploaded_file.name,
                "bytes": uploaded_file.getvalue(),
                "is_image": is_image
            })
            
        user_msg["files"] = user_files

    st.session_state.messages.append(user_msg)
    
    # Render user message immediately
    with st.chat_message("user"):
        st.markdown(prompt)
        if user_files:
            img_files = [f for f in user_files if f["is_image"]]
            doc_files = [f for f in user_files if not f["is_image"]]
            
            if img_files:
                for img in img_files:
                    st.image(img["bytes"], caption=img["name"], width=300)
            if doc_files:
                chips_html = '<div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; margin-bottom: 8px;">'
                for doc in doc_files:
                    icon = get_file_icon(doc["name"])
                    size_str = format_file_size(len(doc["bytes"]))
                    chips_html += f"""
                    <div style="
                        display: flex;
                        align-items: center;
                        background-color: #1e1e1e;
                        border: 1px solid rgba(255, 255, 255, 0.08);
                        border-radius: 8px;
                        padding: 6px 12px;
                        gap: 8px;
                        max-width: 200px;
                    ">
                        <span style="font-size: 1.2rem;">{icon}</span>
                        <div style="display: flex; flex-direction: column; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            <span style="font-size: 0.8rem; color: #ececec; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">{doc["name"]}</span>
                            <span style="font-size: 0.65rem; color: #8a8a8a;">{size_str}</span>
                        </div>
                    </div>
                    """
                chips_html += '</div>'
                st.markdown(chips_html, unsafe_allow_html=True)
            
    # Process ChatGPT Response
    with st.chat_message("assistant"):
        try:
            # Dispatch command and get future
            # Lock serialization is handled inside browser.send_message() itself
            future = runner.run_coroutine(runner.browser.send_message(prompt, file_paths=temp_file_paths))
            
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
            # Delete temp uploaded files from local filesystem
            if temp_file_paths:
                for path in temp_file_paths:
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception as e:
                            logger.warning(f"Error removing temp upload file {path}: {e}")

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
                st.image(img_bytes, caption="DALL-E 3 生成的图片", width=500)

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
