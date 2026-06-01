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

一个通过 Playwright 自动化接管本地已登录 ChatGPT 网页端的浏览器，<br/>
旨在**与好友或家人安全共享同一个 ChatGPT 账号（如 Plus 账号），并实现对话内容完全隔离**的私密共享系统。

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
5. **统一生命周期管理 (One-Click Start/Stop)**：
   - 双击 `start_all.bat` 一键完成所有运行环境（Python、Venv、依赖）的自检、浏览器接管、穿透绑定及服务拉起。
   - 按下 `Ctrl+C` 退出时，编排器会**安全且彻底地关闭所有后台子进程（包括 ngrok、bot 和 streamlit）**，彻底避免端口占用与僵尸进程。

---

## 🛠️ 快速配置与运行

### 第一步：环境准备
确保您的电脑上安装了：
1. **Python 3.8 或以上版本**（安装时请务必勾选 `Add Python to PATH`）。
2. **Google Chrome** 或 **Microsoft Edge** 浏览器。

---

### 第二步：配置文件设置
1. 在项目根目录下，复制 `\.env.example` 文件，并将其重命名为 **`\.env`**。
2. 打开 `.env`，填入您的配置：
   - **`TELEGRAM_BOT_TOKEN`**：填入您通过 Telegram @BotFather 申请到的机器人令牌（如果不使用 Telegram 接口，请留空或保持原样，程序会自适应降级）。
   - **`USE_NGROK`** 与 **`NGROK_PATH`**：（可选，仅限需要公网访问网页端时配置）。

> ⚠️ **【重要避坑提示】**：
> 在 `.env` 配置文件中配置 **`NGROK_PATH`** 等 Windows 路径时，**切勿使用双引号包裹路径**！
> *错误写法*：`NGROK_PATH="C:\Users\Desktop\ngrok.exe"`
> *正确写法*：`NGROK_PATH=C:\Users\Desktop\ngrok.exe`
> 因为解析器会把双引号里的 `\n`（例如 `\ngrok.exe` 中的 `\n`）误当成“换行符”转义，从而导致路径找不到。

---

### 第三步：一键运行
直接双击运行项目根目录下的 **`start_all.bat`**：
1. 脚本会自动检查 Python 并建立 `venv` 虚拟环境。
2. 自动检查并安装 `requirements.txt` 中的全部 Python 依赖包。
3. 检查本地 CDP（Chrome 远程调试）端口，如果没有开启，会自动帮您开启一个专用的浏览器窗口，并自动跳转至 `chatgpt.com`。
4. **【核心步骤】**：请在自动打开的浏览器窗口中**完成您的 ChatGPT 账号登录**（登录后即可保持会话，以后无需重复登录）。
5. 自动启动后台内网穿透（如有）、Telegram 机器人以及 Streamlit 网页服务。

---

### 第四步：使用与停止
* **使用**：
  - 本地网页端访问：浏览器打开 [http://localhost:8501](http://localhost:8501)。
  - Telegram 交互：在 Telegram 中找到您的机器人发送 `/start`。
* **优雅退出**：
  - 当您不想使用时，直接在运行 `start_all.bat` 的 CMD 窗口按下 **`Ctrl+C`**，系统会干净利落地关闭包括浏览器调试链接、Ngrok 以及所有 python 服务，释放端口。

---

## 📂 项目结构

- [start_all.bat](file:///d:/pycharmProject/webgpt2api/start_all.bat)：一键自检、安装、接管与运行批处理文件。
- [run_all.py](file:///d:/pycharmProject/webgpt2api/run_all.py)：主 Python 编排服务，负责浏览器检测、ngrok 配置、并发子进程运行监控和生命周期统一回收。
- [bot.py](file:///d:/pycharmProject/webgpt2api/bot.py)：Telegram 机器人逻辑，包含串行 FIFO 排队机制、指令响应和多模态交互。
- [app_streamlit.py](file:///d:/pycharmProject/webgpt2api/app_streamlit.py)：Streamlit 本地网页前端交互界面。
- [chatgpt_browser.py](file:///d:/pycharmProject/webgpt2api/chatgpt_browser.py)：基于 Playwright 的底层浏览器操纵驱动，含 CORS 绕过的图片下载及防多进程写冲突文件锁。
- [config.py](file:///d:/pycharmProject/webgpt2api/config.py)：全局静态参数配置加载。
- [.env](file:///d:/pycharmProject/webgpt2api/.env)：用户密钥与代理配置文件。
- [.env.example](file:///d:/pycharmProject/webgpt2api/.env.example)：配置指南模板。

---

## 📄 开源协议

本项目基于 **[MIT License](file:///d:/pycharmProject/webgpt2api/LICENSE)** 协议开源，欢迎自由分发、修改与使用！

