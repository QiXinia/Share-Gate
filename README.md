<div align="center">

<img src="resources/banner.png" alt="ChatGPT-Share-Gate Banner" width="100%"/>

<br/>

[![License](https://img.shields.io/github/license/tfboy1/webgpt2api?style=for-the-badge&color=blue)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/tfboy1/webgpt2api?style=for-the-badge&logo=github&color=yellow)](https://github.com/tfboy1/webgpt2api/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/tfboy1/webgpt2api?style=for-the-badge&logo=git&color=orange)](https://github.com/tfboy1/webgpt2api/network/members)
[![爱发电](https://img.shields.io/badge/爱发电-Support%20Me-FF69B4?style=for-the-badge&logo=buy-me-a-coffee&logoColor=white)](https://www.ifdian.net/item/1a20ed042f0711f1865a52540025c377)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-☕-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.creem.io/payment/prod_1yc40mIhKwwrc7iqFOG9G2)

<br/>

[![简体中文](https://img.shields.io/badge/简体中文-当前语言-red?style=flat-square)](#)
[![English](https://img.shields.io/badge/English-README-blue?style=flat-square)](docs/README_EN.md)
[![日本語](https://img.shields.io/badge/日本語-README-blue?style=flat-square)](docs/README_JA.md)

<br/>

一个通过 Playwright 自动化接管本地已登录 **ChatGPT / Google Gemini** 网页端的浏览器，<br/>
旨在**与好友或家人安全共享同一个 AI 账号（如 ChatGPT Plus / Gemini），并实现对话内容完全隔离**的私密共享系统，内置多用户登录鉴权与安全加固。

</div>

### 💡 核心设计初衷
许多人希望能与好友共用一个 ChatGPT Plus 账号以分摊成本或共享作图功能。然而，直接多人在同一个浏览器或 App 上共用账号存在两大痛点：
1. **隐私泄露**：所有人都能看到彼此的聊天记录，无法隔离对话隐私。
2. **并发冲突**：多人同时发送消息时网页端会报错、中断，或者抢占对话流。

**本项目优雅地解决了这些痛点。** 
它作为一个代理客户端，通过 **Telegram 机器人** 和 **Streamlit Web UI** 收集好友们的请求，在后台通过排队机制（FIFO 队列）串行输入到同一个接管的浏览器中。
- **对话内容完全隔离**：每位好友在自己的 Telegram 窗口中只能看到自己的聊天上下文，绝对看不到其他人的聊天历史，保护隐私。
- **排队避免冲突**：后台自动管理会话排队，有序发送给 ChatGPT，彻底告别多人同时操作时的网页报错。
- **定位澄清**：本项目**不是**为了将网页端反代为 OpenAI 格式的 API 接口，而是纯粹为好友间共享使用、隔离对话而设计的人性化 UI 系统。

### 📊 与常见“网页反代 API”项目的对比

| 对比维度 | 常见网页转 API 项目 <br>(如 Chat2API / Pandora-Next 等) | 本项目 (ChatGPT-Share-Gate) |
| :--- | :---: | :---: |
| **核心定位** | 🛠️ 将网页逆向为 OpenAI 格式 API，用于接入第三方客户端 | 👥 亲友多用户共享同一个账号，提供独立的交互界面 |
| **开箱即用性** | ❌ **无直接交互界面**：只暴露 API，需要用户自行寻找/搭建第三方 Web UI |  **自带多端界面**：直接内置 Telegram Bot 与 Streamlit UI，一键即用 |
| **对话隐私隔离** | ⚠️ **需自行打补丁**：必须在第三方 UI 中自行做用户鉴权或使用不同的 Access Token |  **原生隔离**：好友通过 Telegram 独立窗口使用，后台自动串行执行，对话记录绝对不互通 |
| **封号与风控风险**| ❌ **极高**：通过伪造 HTTP 请求或逆向 API 并发请求，极易触发官方风控机制导致封号 | 🟢 **极低**：接管**本地真实运行的 Chrome/Edge 浏览器**，所有操作完全模拟真人点击，安全无虞 |
| **并发报错处理** | ❌ **并发冲突**：多用户同时请求时，直接高频打到网页后端易造成账号被限流或报错中断 | 🟢 **智能队列**：内置 FIFO 排队机制，好友请求串行依次执行，自动规避网页并发报错 |
| **多模态功能** | ⚠️ **受限**：部分逆向 API 对图片上传（Vision）、DALL-E 3 画图下载的支持较难维护或容易失效 | 🟢 **完全支持**：利用 Playwright 仿真上传与网页图片捕获，原生支持 Vision 分析与画图自动发送 |

---

## 🌟 核心特性

1. **账户共享与隐私隔离**：好友通过 Telegram 机器人提交指令，在后台共享同一个已登录的浏览器会话，但各自的对话历史在 Telegram 端相互隔离，互不干扰。
2. **免买 API 额度**：直接利用本地已登录的 Chrome 或 Edge 浏览器在网页端进行操作，免去昂贵的 API 官方 Token 费用，直接复用 Plus 账号的全部专属功能（如 DALL-E 3、GPT-4o 额度）。
3. **多端独立交互界面**：
   - 🤖 **Telegram 机器人**：亲友们随时随地通过 Telegram 与您的 ChatGPT 聊天、作图，各人拥有完全独立的对话上下文。
   - 💻 **Streamlit 网页端**：管理员本地运行的精美 Web UI 控制台，支持查看浏览器状态、直接对话与快速重置。
4. **多模态全功能支持**：
   - 💬 **文字对话**：完整的纯文本会话。
   - 🎨 **文生图**：自动截获并下载 ChatGPT 生成的 DALL-E 3 图片发送给对应的用户。
   - 🖼️ **图生图（上传图片）**：支持发送本地图片并输入指示（如“分析这幅图”或进行图片修改）。
5. **浏览器与穿透自动探测与降级**：
   - 🌐 **浏览器自动兜底**：系统会自动在常见目录寻找 Google Chrome；如果未安装 Chrome，将**自动降级使用 Windows 自带的 Microsoft Edge** 浏览器，同样完美适配。
   - 🔑 **Telegram Bot Token 容错**：如果未配置 Token，系统会自动进入“纯 Web 模式”运行，跳过 Bot 启动，不会引发崩溃。
   - 🔗 **Ngrok 智能识别**：若配置了内网穿透且系统装有 ngrok，会自动在后台静默拉起并分配公网域名，检测不到则会自动降级为仅本地运行。
6. **统一生命周期管理 (One-Click Start/Stop)**：
   - 双击 `start_all.bat` 一键完成所有运行环境（Python、Venv、依赖）的自检、浏览器接管、穿透绑定及服务拉起。
   - 按下 `Ctrl+C` 退出时，编排器会**安全且彻底地关闭所有后台子进程（包括 ngrok、bot 和 web）**：Windows 上使用 `taskkill /T /F` 终止整个进程树，Linux/macOS 使用进程组 kill，彻底避免端口占用与僵尸进程。

7. **多用户登录与账号体系** 🔐：
   - 网页端内置**用户名/密码登录**，会话基于服务端可撤销的随机 Token（HttpOnly + SameSite Cookie），未登录无法访问任何对话接口。
   - 密码使用 **PBKDF2-HMAC-SHA256（20 万次迭代 + 随机盐）** 加盐哈希存储，服务端不保存明文。
   - 支持管理员/普通用户角色、自助注册开关、登录失败锁定、命令行建号改密。
   - Telegram 机器人支持**用户 ID 白名单**与管理员指令控制。

8. **安全加固** 🛡️：
   - 默认仅监听 `127.0.0.1`；对外暴露（ngrok/局域网）时强制登录。
   - 修复了静态文件的**路径穿越漏洞**，并加入安全响应头（CSP、X-Frame-Options、X-Content-Type-Options、Referrer-Policy、Permissions-Policy）。
   - 限制上传文件大小/数量、拦截可执行脚本类型、请求体大小上限与请求线程背压，缓解 DoS。
   - 前端库（Vue / Tailwind / Marked）**本地托管**，CSP 脚本源收敛为同源；登录防爆破（同 IP 连续失败锁定）。

9. **服务器性能与稳定性** ⚡：
   - 有界线程池（线程复用，避免无限新建线程）、HTTP/1.1 keep-alive 连接复用、**gzip 压缩**（页面体积约压缩 80%）、静态资源 ETag/304 与缓存头。
   - 浏览器任务**全局排队计数**，可在侧边栏实时查看排队人数；队列满载时快速返回 503，避免雪崩。

---

## 🛠️ 快速配置与运行

### 第一步：环境准备
确保您的电脑上安装了：
1. **Python 3.8 或以上版本**（安装时请务必勾选 `Add Python to PATH`）。
2. **Google Chrome** 或 **Microsoft Edge** 浏览器。

---

### 第二步：配置文件设置
1. 在项目根目录下，复制 `\.env.example` 文件，并将其重命名为 **`\.env`**（`start_all.bat` 首次运行时也会自动生成）。
2. 打开 `.env`，**至少填写以下关键项**：
   - **`ADMIN_PASSWORD`**（必填，网页登录）：网页端管理员的初始密码。首次启动时会据此创建 `ADMIN_USERNAME`（默认 `admin`）账户。**请务必设置一个强密码**。
   - **`TELEGRAM_BOT_TOKEN`**：Telegram @BotFather 申请的机器人令牌；不使用 Telegram 时留空，程序自动降级为纯 Web 模式。
   - **`ALLOWED_TELEGRAM_IDS`**（强烈建议）：允许使用机器人的 Telegram 数字 ID，逗号分隔。留空表示任何人都能使用机器人（有风险）。
   - **`USE_NGROK`** 与 **`NGROK_PATH`**：（可选）需要公网访问时配置。

> ⚠️ **【重要避坑提示】**：
> 在 `.env` 中配置 **`NGROK_PATH`** 等 Windows 路径时，**切勿使用双引号包裹路径**！
> *错误写法*：`NGROK_PATH="C:\Users\Desktop\ngrok.exe"`
> *正确写法*：`NGROK_PATH=C:\Users\Desktop\ngrok.exe`
> 因为解析器会把双引号里的 `\n`（例如 `\ngrok.exe` 中的 `\n`）误当成“换行符”转义，从而导致路径找不到。

---

### 第三步：一键运行
- **Windows**：双击运行根目录下的 **`start_all.bat`**。
- **macOS / Linux**：在终端执行 `./start_all.sh`（首次会自动 `chmod +x` 或用 `bash start_all.sh`）。

启动流程：
1. 自动检查 Python（Windows 上会依次尝试 `python` 与 `py` 启动器）并建立 `venv` 虚拟环境。
2. 自动安装 `requirements.txt` 中的全部依赖（**新增登录功能无需任何额外依赖**，均由 Python 标准库实现）。
3. 自动探测 Chrome / Edge / Chromium（Windows 注册表、macOS、Linux 常见路径与 PATH），检查 CDP 调试端口；未开启则使用项目内的便携用户目录启动浏览器并跳转 `chatgpt.com`。
4. 初始化网页管理员账户。
5. **【核心步骤】**：在自动打开的浏览器窗口中**完成您的 ChatGPT 账号登录**（登录态保存在浏览器配置目录，以后无需重复登录）。
6. 自动启动内网穿透（可选）、Telegram 机器人（可选）与带登录的 Web 服务。

---

### 第四步：使用与停止
* **使用**：
  - 本地网页端：浏览器打开 [http://localhost:8501](http://localhost:8501)，**首次进入会显示登录页**，输入 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录。
  - Telegram：在 Telegram 中找到您的机器人发送 `/start`（须在白名单内）。
* **优雅退出**：
  - 在运行窗口按下 **`Ctrl+C`**，系统会用进程树方式干净地终止 ngrok、bot、web 等所有托管进程并释放端口；**浏览器会保留运行**以维持登录态。

---

## 👥 用户与账号管理

- **首次启动**：根据 `.env` 中的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 自动创建管理员（仅当该账户不存在时）。
- **命令行管理账号**（在项目根目录、激活虚拟环境后执行）：

```bash
venv\Scripts\python.exe auth.py adduser alice Password123   # Windows 建号
venv/bin/python auth.py adduser bob Password123             # macOS/Linux 建号
venv\Scripts\python.exe auth.py adduser carol Pw123 --admin # 创建管理员
venv\Scripts\python.exe auth.py list                        # 列出账户
venv\Scripts\python.exe auth.py passwd alice NewPassword456 # 重置密码（并使旧会话失效）
venv\Scripts\python.exe auth.py deluser alice               # 删除账户
```

- 账户与会话数据保存在 `data/` 目录（已被 `.gitignore` 忽略）：`users.json`（密码哈希）、`sessions.json`（会话）、`secret.key`（服务端密钥，自动生成，请勿泄露）。
- 若想开放网页端自助注册，将 `.env` 中 `ALLOW_REGISTRATION=True`，注册者默认为普通用户。

---

## 🤖 ChatGPT / Google Gemini 多平台与对话隔离

系统可在同一个已接管的浏览器中同时驱动 **ChatGPT** 与 **Google Gemini**，二者共享同一套登录、排队与安全机制。

**1. 启用平台**

在 `.env` 中配置（默认仅 ChatGPT）：

```bash
AI_PLATFORMS=chatgpt,gemini
DEFAULT_PLATFORM=chatgpt
```

- 启动器会自动打开 `chatgpt.com` 与 `gemini.google.com` 两个标签页（它们共用同一个浏览器配置目录，登录态都会被保存）。
- 网页端侧边栏顶部会出现 **ChatGPT / Google Gemini** 切换按钮；Telegram 中可用 `/platform` 查看/切换、`/new gemini` 切换并开新会话。

**2. Gemini 登录**

- Gemini 使用 **Google 账号**登录：首次启动后在自动打开的 `gemini.google.com` 标签页中手动登录一次即可，之后由配置目录保持登录。
- 若未登录就发送消息，系统会返回明确提示“请在浏览器中登录 Google 账号”，不会卡死；`/status` 也会显示各平台的登录状态。

**3. 对话隔离**

- 每次点击「新建对话」或调用 `/new <平台>` 都会在对应平台开启一个**全新的会话线程**（ChatGPT 重新打开首页，Gemini 点击“新建对话”），清空上一轮上下文，避免不同用户互相串话。
- 网页端的本地历史记录也按平台分别保存，ChatGPT 与 Gemini 的对话互不混合。
- 所有平台仍共用一个浏览器、串行 FIFO 排队，因此高并发下会自动排队，不会出现两个请求同时操作同一标签页。

> 📌 **关于 Gemini 页面选择器**：Gemini 网页的 DOM 由 Google 频繁更新且随语言变化，驱动层（`gemini_adapter.py`）已将所有选择器集中为一组多重容错列表（输入框、发送/停止按钮、新建对话、回复容器）。若日后 Google 改版导致某个步骤失效，只需在该文件顶部的 `SELECTORS` 中补充新的选择器即可。

---

## 🌐 公网（ngrok / 局域网）暴露安全清单

将网页通过 ngrok 或局域网开放给朋友时，请务必：

1. 在 `.env` 中设置 `WEB_HOST=0.0.0.0`（或 `ALLOW_REMOTE=True`）并设置一个强 `ADMIN_PASSWORD`——所有接口都会强制登录，未登录返回 401。
2. 设置 `TRUST_FORWARDED_HEADERS=True`，以便透过 ngrok 正确识别真实访客 IP 与 HTTPS（登录 Cookie 会自动带上 `Secure`）。
3. 配置 `ALLOWED_TELEGRAM_IDS` 限制机器人使用范围。
4. 仅在需要时开放 `ALLOW_REGISTRATION`，日常保持关闭。

> 服务默认只监听 `127.0.0.1`，不会暴露到局域网/公网。

---

## 📂 项目结构

- **`start_all.bat`** / **`start_all.sh`**：Windows / macOS·Linux 一键自检、安装、接管与运行脚本。
- **`run_all.py`**：主 Python 编排服务，跨平台负责浏览器探测、ngrok 配置、子进程监控与进程树生命周期回收。
- **`web_server.py`**：带登录鉴权、安全头、gzip 与线程池的 Web 服务（默认入口，取代旧的 Streamlit 运行方式）。
- **`auth.py`**：用户认证模块（PBKDF2 密码哈希、服务端会话、登录限流、账号管理 CLI）。
- **`bot.py`**：Telegram 机器人逻辑，含串行 FIFO 排队、白名单/管理员控制、指令响应和多模态交互。
- **`app_streamlit.py`**：Streamlit 本地管理员控制台（可选，已加访问密码门）。
- **`chatgpt_browser.py`**：基于 Playwright 的多平台浏览器控制器（ChatGPT / Gemini），含 CDP 连接、标签页管理、图片下载、跨进程文件锁、队列计数与健康指标。
- **`gemini_adapter.py`**：Google Gemini 网页驱动，负责登录检测、新建对话隔离、内容输入、发送、等待完成与回复提取（选择器集中容错）。
- **`config.py`**：全局配置加载（含 Web、安全、白名单、上传限制、跨平台路径等）。
- **`static/index.html`**：网页端控制台（Vue 3），含登录/注册页、用户菜单与会话管理。
- **`static/vendor/`**：本地托管的前端库（Vue / Tailwind / Marked），无需外网 CDN 即可加载。
- **`data/`**（运行时生成，已 gitignore）：账户、会话与服务端密钥。
- **`.env.example`**：配置指南模板。

---

## 📄 开源协议

本项目基于 **[MIT License](file:///d:/pycharmProject/webgpt2api/LICENSE)** 协议开源，欢迎自由分发、修改与使用！

