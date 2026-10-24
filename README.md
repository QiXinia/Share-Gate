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
它作为一个代理客户端，通过 **钉钉机器人** 和 **Web UI** 收集好友们的请求，在后台通过排队机制（FIFO 队列）串行输入到同一个接管的浏览器中。
- **对话内容完全隔离**：每位好友在自己的钉钉会话窗口中只能看到自己的聊天上下文，绝对看不到其他人的聊天历史，保护隐私。
- **排队避免冲突**：后台自动管理会话排队，有序发送给 ChatGPT，彻底告别多人同时操作时的网页报错。
- **定位澄清**：本项目**不是**为了将网页端反代为 OpenAI 格式的 API 接口，而是纯粹为好友间共享使用、隔离对话而设计的人性化 UI 系统。

### 📊 与常见“网页反代 API”项目的对比

| 对比维度 | 常见网页转 API 项目 <br>(如 Chat2API / Pandora-Next 等) | 本项目 (ChatGPT-Share-Gate) |
| :--- | :---: | :---: |
| **核心定位** | 🛠️ 将网页逆向为 OpenAI 格式 API，用于接入第三方客户端 | 👥 亲友多用户共享同一个账号，提供独立的交互界面 |
| **开箱即用性** | ❌ **无直接交互界面**：只暴露 API，需要用户自行寻找/搭建第三方 Web UI |  **自带多端界面**：直接内置钉钉机器人与 Web UI，一键即用 |
| **对话隐私隔离** | ⚠️ **需自行打补丁**：必须在第三方 UI 中自行做用户鉴权或使用不同的 Access Token |  **原生隔离**：好友通过钉钉独立会话使用，后台自动串行执行，对话记录绝对不互通 |
| **封号与风控风险**| ❌ **极高**：通过伪造 HTTP 请求或逆向 API 并发请求，极易触发官方风控机制导致封号 | 🟢 **极低**：接管**本地真实运行的 Chrome/Edge 浏览器**，所有操作完全模拟真人点击，安全无虞 |
| **并发报错处理** | ❌ **并发冲突**：多用户同时请求时，直接高频打到网页后端易造成账号被限流或报错中断 | 🟢 **智能队列**：内置 FIFO 排队机制，好友请求串行依次执行，自动规避网页并发报错 |
| **多模态功能** | ⚠️ **受限**：部分逆向 API 对图片上传（Vision）、DALL-E 3 画图下载的支持较难维护或容易失效 | 🟢 **完全支持**：利用 Playwright 仿真上传与网页图片捕获，原生支持 Vision 分析与画图自动发送 |

---

## 🌟 核心特性

1. **账户共享与隐私隔离**：好友通过钉钉机器人提交指令，在后台共享同一个已登录的浏览器会话，但各自的对话历史在钉钉端相互隔离，互不干扰。
2. **免买 API 额度**：直接利用本地已登录的 Chrome 或 Edge 浏览器在网页端进行操作，免去昂贵的 API 官方 Token 费用，直接复用 Plus 账号的全部专属功能（如 DALL-E 3、GPT-4o 额度）。
3. **多端独立交互界面**：
   - 🤖 **钉钉机器人**：亲友们随时随地通过钉钉（单聊或群聊 @机器人）与您的 ChatGPT / Gemini 聊天、作图，各人拥有完全独立的对话上下文。采用企业内部应用 **Stream 长连接**模式，无需公网回调地址。
   - 🖥️ **1:1 共享桌面**：访客**钉钉扫码登录**后，在浏览器里直接看到并操作 1:1 还原的真实 ChatGPT / Gemini 页面，鼠标键盘与中文输入实时回传；每个用户独立标签页、独立对话，多人互不串话。提供**省流 DOM 镜像（默认）/ 高清像素**双模式一键切换；按用户过滤历史会话、隐藏登出与账号设置入口。
   - 💻 **Streamlit 网页端**：管理员本地运行的精美 Web UI 控制台，支持查看浏览器状态、直接对话与快速重置。
4. **多模态全功能支持**：
   - 💬 **文字对话**：完整的纯文本会话。
   - 🎨 **文生图**：自动截获并下载 ChatGPT 生成的 DALL-E 3 图片发送给对应的用户。
   - 🖼️ **图生图（上传图片）**：支持发送本地图片并输入指示（如“分析这幅图”或进行图片修改）。
5. **浏览器与穿透自动探测与降级**：
   - 🌐 **浏览器自动兜底**：系统会自动在常见目录寻找 Google Chrome；如果未安装 Chrome，将**自动降级使用 Windows 自带的 Microsoft Edge** 浏览器，同样完美适配。
   - 🔑 **钉钉机器人凭证容错**：如果未配置 `DINGTALK_APP_KEY/SECRET`，系统会自动进入“纯 Web 模式”运行，跳过机器人启动，不会引发崩溃。
   - 🔗 **Ngrok 智能识别**：若配置了内网穿透且系统装有 ngrok，会自动在后台静默拉起并分配公网域名，检测不到则会自动降级为仅本地运行。
6. **统一生命周期管理 (One-Click Start/Stop)**：
   - 双击 `start_all.bat` 一键完成所有运行环境（Python、Venv、依赖）的自检、浏览器接管、穿透绑定及服务拉起。
   - 按下 `Ctrl+C` 退出时，编排器会**安全且彻底地关闭所有后台子进程（包括 ngrok、bot 和 web）**：Windows 上使用 `taskkill /T /F` 终止整个进程树，Linux/macOS 使用进程组 kill，彻底避免端口占用与僵尸进程。

7. **多用户登录与账号体系** 🔐：
   - 网页端内置**用户名/密码登录**，会话基于服务端可撤销的随机 Token（HttpOnly + SameSite Cookie），未登录无法访问任何对话接口。
   - 密码使用 **PBKDF2-HMAC-SHA256（20 万次迭代 + 随机盐）** 加盐哈希存储，服务端不保存明文。
   - 支持管理员/普通用户角色、自助注册开关、登录失败锁定、命令行建号改密。
   - 钉钉机器人支持**用户 ID（staffId / unionId）白名单**与管理员指令控制。

8. **安全加固** 🛡️：
   - 默认仅监听 `127.0.0.1`；对外暴露（ngrok/局域网）时强制登录。
   - 修复了静态文件的**路径穿越漏洞**，并加入安全响应头（CSP、X-Frame-Options、X-Content-Type-Options、Referrer-Policy、Permissions-Policy）。
   - 限制上传文件大小/数量、拦截可执行脚本类型、请求体大小上限与请求线程背压，缓解 DoS。
   - 前端库（Vue / Tailwind / Marked）**本地托管**，CSP 脚本源收敛为同源；登录防爆破（同 IP 连续失败锁定）。

9. **服务器性能与稳定性** ⚡：
   - 有界线程池（线程复用，避免无限新建线程）、HTTP/1.1 keep-alive 连接复用、**gzip 压缩**（页面体积约压缩 80%）、静态资源 ETag/304 与缓存头。
   - 浏览器任务**全局排队计数**，可在侧边栏实时查看排队人数；队列满载时快速返回 503，避免雪崩。

10. **多租户远程浏览器与钉钉 SSO** 🖥️：
    - 双模式渲染：默认 **DOM 镜像（基于 [PhantomStream](https://github.com/fullselfbrowsing/PhantomStream)，MIT）**——服务器标签页只在开始时推一份**内联样式的完整快照**，之后仅通过 `MutationObserver` 推送**增量 DOM diff**（节点身份用稳定 node-id sidecar 维护，不再每次重发整页），前端在禁用脚本的沙箱 iframe 里原样重建，弱网下流量极小；可一键回退 **CDP screencast 逐帧 JPEG**（高清像素）。两者都配合坐标化的远程控制回传（点击/滚轮/键盘/中文输入），视口随画布自适应。
    - 每“用户 × 平台”独立标签页会话池（`browser_pool.py`），支持并发、空闲回收与全局标签页上限；桌面服务基于异步 `aiohttp`，与旧控制台共存、共享会话。
    - **按人会话隔离**：`ownership.py` 记录每用户实际打开的对话 id，注入脚本（`page_inject.py`）隐藏他人历史、登出与账号/套餐/设置入口并守卫跳转，他人会话不进入下发快照；管理员可见全部。
    - **资源中继** `/resource`：仅在平台域名白名单内、带共享浏览器登录态取回图片/字体/样式，含登录校验与 SSRF 防护；不转发页面/API，非反代。
    - 钉钉 OAuth2 授权码扫码登录（`dingtalk_sso.py`），以 openId 建立稳定本地账号，state 防 CSRF、WebSocket 校验同源、会话 Cookie 与旧控制台一致。

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
   - **`DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET`**：在[钉钉开放平台](https://open.dingtalk.com)创建「企业内部应用」→ 添加「机器人」能力 → 消息接收模式选择 **Stream 模式**，在「凭证与基础信息」获取 Client ID（AppKey）/ Client Secret（AppSecret）。不使用机器人时留空，程序自动降级为纯 Web 模式。
   - **`ALLOWED_DINGTALK_IDS`**（强烈建议）：允许使用机器人的钉钉用户 ID（staffId 或 unionId），逗号分隔。留空表示任何能与机器人会话的人都能使用（有风险）；首次被拒时机器人会回显该用户的 ID。
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
6. 自动启动内网穿透（可选）、钉钉机器人（可选，Stream 长连接）与带登录的 Web 服务。

---

### 第四步：使用与停止
* **使用**：
  - 本地网页端：浏览器打开 [http://localhost:8501](http://localhost:8501)，**首次进入会显示登录页**，输入 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录。
  - 钉钉：在钉钉中把机器人添加到单聊（或群聊后 @机器人），发送 `/start`（须在白名单内）。
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
- 网页端侧边栏顶部会出现 **ChatGPT / Google Gemini** 切换按钮；钉钉机器人中可用 `/platform` 查看/切换、`/new gemini` 切换并开新会话。

**2. Gemini 登录**

- Gemini 使用 **Google 账号**登录：首次启动后在自动打开的 `gemini.google.com` 标签页中手动登录一次即可，之后由配置目录保持登录。
- 若未登录就发送消息，系统会返回明确提示“请在浏览器中登录 Google 账号”，不会卡死；`/status` 也会显示各平台的登录状态。

**3. 对话隔离**

- 每次点击「新建对话」或调用 `/new <平台>` 都会在对应平台开启一个**全新的会话线程**（ChatGPT 重新打开首页，Gemini 点击“新建对话”），清空上一轮上下文，避免不同用户互相串话。
- 网页端的本地历史记录也按平台分别保存，ChatGPT 与 Gemini 的对话互不混合。
- 所有平台仍共用一个浏览器、串行 FIFO 排队，因此高并发下会自动排队，不会出现两个请求同时操作同一标签页。

> 📌 **关于 Gemini 页面选择器**：Gemini 网页的 DOM 由 Google 频繁更新且随语言变化，驱动层（`gemini_adapter.py`）已将所有选择器集中为一组多重容错列表（输入框、发送/停止按钮、新建对话、回复容器）。若日后 Google 改版导致某个步骤失效，只需在该文件顶部的 `SELECTORS` 中补充新的选择器即可。

---

## 📨 钉钉机器人配置（企业内部应用 · Stream 模式）

机器人采用钉钉官方的**企业内部应用 + Stream 长连接**：由本地程序主动向钉钉建立 WebSocket 长连接接收消息，**不需要公网 IP / 回调地址**，非常适合本地一键启动。

**第一步：创建应用与机器人**

1. 打开 [钉钉开放平台](https://open.dingtalk.com) → 应用开发 → 创建「企业内部应用」。
2. 在应用的「应用能力」中添加「机器人」能力。
3. 在机器人配置中，把「消息接收模式」选择为 **Stream 模式**（无需填写回调地址）。
4. 在「凭证与基础信息」中复制 **Client ID（AppKey）** 与 **Client Secret（AppSecret）**，填入 `.env`：
   ```bash
   DINGTALK_APP_KEY=dingxxxxxxxx
   DINGTALK_APP_SECRET=xxxxxxxxxxxxxxxx
   ```
5. 发布应用（或先在测试企业内使用），然后在钉钉里把机器人**添加到单聊**或**群聊**。

**第二步：配置白名单（强烈建议）**

- 先留空 `ALLOWED_DINGTALK_IDS`，给机器人发一条消息；若未配置白名单即可正常使用；配置了白名单后，未授权用户会收到一条**回显其钉钉用户 ID（staffId / unionId）**的提示。
- 把要放行的 ID 填入 `.env`（逗号分隔），管理员用 `DINGTALK_ADMIN_IDS`（留空则默认等同白名单）：
  ```bash
  ALLOWED_DINGTALK_IDS=staff001,staff002
  DINGTALK_ADMIN_IDS=staff001
  ```

**使用方式**

- 单聊：直接给机器人发文字、图片或文件，或发送指令 `/start`、`/help`。
- 群聊：在群里 **@机器人** 再发送内容（例如 `@机器人 讲个冷笑话`），系统会自动去掉 @ 前缀。
- 指令：`/start`、`/new [平台]`、`/platform [平台]`、`/status`、`/log`（管理员）、`/help`。

> 说明：
> - 钉钉机器人消息发送后**不能编辑**，因此排队与处理进度以独立提示消息发送，结果就绪后再回复（不像 Telegram 那样在同一条消息上倒计时）。
> - 生成的图片会先上传到钉钉换取 mediaId，再以图片消息回传，依赖官方的 `sampleImage` 消息格式；若你所在企业的钉钉版本对此有限制，文字回复不受影响，可查看 `bot.log` 定位。
> - 机器人收发 OpenAPI 走标准 HTTPS（`requests` 会读取 `HTTP_PROXY/HTTPS_PROXY`）；若你的网络访问钉钉开放平台需要代理，在 `.env` 配置即可。

---

## 🖥️ 1:1 共享桌面 + 钉钉扫码登录（多人分账号隔离）

除了“命令式”的网页控制台和钉钉机器人，Share-Gate 还提供一套**像素级 1:1 还原 ChatGPT / Gemini 网页**的共享桌面：每个钉钉用户扫码登录后，在自己的浏览器里直接看到并操作一个真实的平台标签页，鼠标、键盘、中文输入、滚轮全部实时回传，多人同时使用互不串话。

### 工作原理

后端提供**两种渲染模式**，可在工具栏一键切换：

- **省流 DOM 镜像（默认）**：服务器上的真实标签页照常登录并运行平台 JS，通过 CDP 注入 PhantomStream capture 脚本：开始时采集一份**内联计算样式的完整 DOM 快照**（外加一份按文档顺序排列的稳定 node-id sidecar），随后只在 DOM 发生变化时由 `MutationObserver` 产出**增量 diff**（add / remove / attr / text / value 等操作，仅携带变化的节点），经 WebSocket 推给前端；前端 PhantomStream viewer 用一个**禁用脚本的沙箱 iframe（`sandbox="allow-same-origin"`，不含 `allow-scripts`）**依据 node-id 原地打补丁，首屏之后不再重发整页（实测增量帧通常仅数百字节，远小于首屏快照）。图片 / 字体等二进制资源经带登录态的 `/resource` 端点按需加载（带浏览器侧缓存）。
- **高清像素（回退）**：经典 CDP `Page.startScreencast` 逐帧 JPEG 串流（`Input.dispatchMouseEvent / dispatchKeyEvent / insertText` 回传），保真度最高，适合带宽充足、需要看到 canvas / 复杂动画时使用。

两种模式下鼠标 / 键盘 / 滚轮 / 中文输入均通过**坐标化远程控制**回传到真实标签页（DOM 模式按视口缩放映射，像素模式坐标天然对齐），前端只请求“控制权”、由共享标签页批准后生效。

> **这是 DOM 镜像，不是反代**：目标网页的 JS 始终在服务器那台**已登录 Chrome** 里运行（保留登录态与会员）；访客浏览器里**不运行目标站点脚本、也不持有目标站 Cookie**，只收到一份结构化的页面快照与增量补丁。`/resource` 只中继图片 / 字体 / 样式等静态资源（平台域名白名单 + 登录态校验，且只对纯静态 CDN 域名做镜像内 URL 改写），**不转发页面文档与 API 请求**，因此不是传统网页反向代理。我们评估过 [Scramjet](https://github.com/MercuryWorkshop/scramjet)：它是“客户端拦截式代理”——在访客浏览器里劫持并运行目标站点、访客各自登录，既不共享服务器会员、也不省流量，与本项目“共享一台已登录会员、按人隔离”的目标冲突，故最终采用 PhantomStream 这类**服务端 DOM 镜像**（在服务器侧采集、向访客只读重建）。
>
> **两处工程适配**：① 原生 CDP `Runtime.addBinding` 只能向宿主机转发单个字符串参数（传对象会被静默丢弃），而 PhantomStream 官方 Node 适配器使用的是 Playwright `page.exposeBinding`（内部做了 JSON 序列化）；因此注入脚本里加了一个 raw-binding shim，把 `__phantomStreamBridge(对象)` 统一 `JSON.stringify` 后再经 CDP 绑定传出。② 我们引入的预构建 capture 产物早于上游 `maskAssetUrlFn` 资源改写钩子，故静态资源 URL 改写放在后端完成（`PhantomSession._rewrite_asset_urls`，对快照与增量帧中出现的静态 CDN 链接统一改写为 `/resource`，字段无关、更鲁棒）。

- **账号模型**：所有用户共享同一台机器上**同一个已登录的 Chrome 配置**（即同一个 ChatGPT Plus / Gemini 账号），但系统为每个“用户 × 平台”分配一个**独立的浏览器标签页并打开平台根地址（全新对话）**。不同标签页的对话天然隔离、可并行，互不影响。
- **会话归属与历史隔离**：注入脚本记录每个用户实际打开过的对话 id（`data/ownership.json`，按用户持久化），侧边栏中**不属于本人的历史对话会被隐藏，并且不会进入下发的 DOM 快照**，因此访客只能看到自己发出的会话、也能正确回看自己的历史；**管理员（role=admin）不过滤，可见全部历史**，便于排障。
- 钉钉用户通过 **OAuth2 授权码流程**扫码登录，以 openId 作为稳定唯一标识自动建立本地账号；账号密码登录仍作为兜底。
- 桌面服务独立运行在 **8502 端口**（`DESKTOP_PORT`，默认管理控制台 +1），与旧控制台（8501）共存，共享同一份用户 / 会话数据和同一个 Chrome；ngrok 隧道默认转发桌面端口。

### 界面限制（防止访客退出或改动共享账号）

共享标签页内注入脚本会强制：

- 隐藏并拦截 **登出 / Sign out / 注销** 入口（捕获阶段拦截点击，阻止导航）；
- 隐藏 **Settings / 设置**、账号 / 套餐 / 升级 / 切换组织（工作区）等菜单；
- URL 守卫：任何指向 `/auth/login|logout`、`/account(s)`、`/settings`、`signin/signup` 的跳转都会被重定向回平台根地址，并向前端推送“已阻止登出/跳转账号页面”的提示。

这些限制只作用于访客视角的共享标签页，不影响你在本机直接使用 Chrome。

### 配置步骤

1. 在钉钉开放平台你的**企业内部应用**中，进入「登录与分享 / 重定向 URL（登录回调地址）」，添加可信回调：
   `https://<你的 ngrok 域名>/auth/dingtalk/callback`
   （机器人 Stream 模式与网页登录共用同一个 `DINGTALK_APP_KEY / DINGTALK_APP_SECRET`。）
2. 在 `.env` 中：
   ```bash
   # 已配置真实 AppKey/AppSecret 时桌面登录默认开启，也可显式开关
   DINGTALK_SSO_ENABLED=True
   # 外部域名（一般是 ngrok 域名）；留空则按请求域名自动推导
   DINGTALK_OAUTH_BASE=https://your-domain.ngrok-free.app
   ```
   公网暴露时同时按本文“公网暴露安全清单”设置 `TRUST_FORWARDED_HEADERS=True`。
3. 运行 `run_all` 后，打开 **`http://localhost:8502/desktop`**（公网为 `https://<域名>/desktop`），点击「钉钉扫码登录」即可。

### 使用与调参

- 顶部工具栏可切换 **ChatGPT / Gemini** 标签、在 **「省流模式（DOM 镜像）/ 高清模式（像素）」** 之间一键切换（会用新 WebSocket 重连），以及开启「新对话」、「刷新」。
- 点击画面即可操作；中文输入法在画面内直接上屏（通过隐藏输入框捕获 IME 合成文本）。
- 弱网 / 大流量场景默认用省流模式；需要看 canvas、复杂动画或像素级保真时切到高清模式。
- 标签页断开后会保留一段时间（默认 30 分钟）以便刷新续用，超时自动回收；相关参数：
  ```bash
  DESKTOP_PORT=8502            # 桌面服务端口
  DESKTOP_MAX_TABS=12          # 全局最大并发标签页
  DESKTOP_IDLE_CLOSE_MIN=30    # 空闲标签页回收时间
  DESKTOP_MAX_WIDTH=1280       # 画面分辨率上限
  DESKTOP_MAX_HEIGHT=800
  DESKTOP_JPEG_QUALITY=60      # 画质（越低越省带宽）
  DESKTOP_FPS=8                # 串流帧率
  ```

> 注意：
> - 这是“**共享一个已登录会员账号、每人独立对话**”的模型，适合把自己的会员额度分享给信任的朋友；它**不是**为每个访客登录其本人的 ChatGPT 账号。如需每人独立会员账号，需为每人准备独立的浏览器配置（本项目当前不提供）。
> - 实时画面的流畅度取决于服务器到访客的带宽：DOM 模式默认即可省流；高清模式可通过降低分辨率 / 画质 / 帧率适配弱网。
> - DOM 镜像以文本还原页面，常规排版、对话气泡、代码块、图片与表单均可正常呈现；个别依赖 `<canvas>` / WebGL / 复杂动画的细节在 DOM 模式下可能不完整，此时切到高清像素模式即可。真实 ChatGPT / Gemini 的历史项选择器与登录 / 套餐菜单结构如随官网改版变化，需在 `page_inject.py` 顶部的选择器与正则处做真机校准（沙箱用本地等价页面验证了机制）。
> - 钉钉扫码登录与真实平台页面的真机交互，需在你自己的机器（能访问钉钉与 ChatGPT/Gemini）上联调；自动化沙箱已验证双模式渲染、输入、按人历史隔离、界面限制、资源白名单与 OAuth 流程，但无法代替真机确认。

---

## 🌐 公网（ngrok / 局域网）暴露安全清单

将网页通过 ngrok 或局域网开放给朋友时，请务必：

1. 在 `.env` 中设置 `WEB_HOST=0.0.0.0`（或 `ALLOW_REMOTE=True`）并设置一个强 `ADMIN_PASSWORD`——所有接口都会强制登录，未登录返回 401。
2. 设置 `TRUST_FORWARDED_HEADERS=True`，以便透过 ngrok 正确识别真实访客 IP 与 HTTPS（登录 Cookie 会自动带上 `Secure`）。
3. 配置 `ALLOWED_DINGTALK_IDS` 限制钉钉机器人使用范围。
4. 仅在需要时开放 `ALLOW_REGISTRATION`，日常保持关闭。

> 服务默认只监听 `127.0.0.1`，不会暴露到局域网/公网。

---

## 📂 项目结构

- **`start_all.bat`** / **`start_all.sh`**：Windows / macOS·Linux 一键自检、安装、接管与运行脚本。
- **`run_all.py`**：主 Python 编排服务，跨平台负责浏览器探测、ngrok 配置、子进程监控与进程树生命周期回收。
- **`web_server.py`**：带登录鉴权、安全头、gzip 与线程池的 Web 服务（默认入口，取代旧的 Streamlit 运行方式）。
- **`desktop_server.py`**：1:1 共享桌面服务（aiohttp + WebSocket），负责钉钉 SSO 登录路由与两条画面通道：`/pws`（DOM 镜像：PhantomStream 快照/增量帧中继、坐标化远程控制、出站 deflate-raw 解码、静态资源 URL 改写）与 `/ws`（高清像素：screencast JPEG 回退），以及带登录态的 `/resource` 子资源中继（默认 8502 端口）。
- **`phantom_inject.py`**：构建注入共享标签页的 PhantomStream capture 脚本（注入桥接 token、隔离用 `skipElement`、raw-binding shim 与 relay origin）。
- **`page_inject.py`**：页面归属/隔离/限制注入脚本——标记本人对话、隐藏他人历史与登出/设置/账号入口、URL 守卫（capture 据此跳过这些节点）。
- **`vendor/phantom-stream/`**：PhantomStream 预构建、自包含的 capture 注入脚本（classic script，无 Node 构建步骤，CDP 直接注入）与 MIT 许可。
- **`static/vendor/phantom-stream/`**：PhantomStream 前端 ESM（renderer / protocol / transport），由 `desktop.html` 动态 import。
- **`browser_pool.py`**：每“用户 × 平台”独立标签页的会话池，负责并发标签页管理、空闲回收与上限保护。
- **`dingtalk_sso.py`**：钉钉 OAuth2 授权码登录客户端（授权跳转、换取 userAccessToken、拉取 openId / 昵称）。
- **`auth.py`**：用户认证模块（PBKDF2 密码哈希、服务端会话、登录限流、账号管理 CLI、SSO 账号接入）。
- **`bot.py`**：钉钉机器人（企业内部应用 Stream 长连接）逻辑，含串行 FIFO 排队、白名单/管理员控制、指令响应、图片/文件接收与生成图片回传。
- **`app_streamlit.py`**：Streamlit 本地管理员控制台（可选，已加访问密码门）。
- **`chatgpt_browser.py`**：基于 Playwright 的多平台浏览器控制器（ChatGPT / Gemini），含 CDP 连接、标签页管理、图片下载、跨进程文件锁、队列计数与健康指标。
- **`gemini_adapter.py`**：Google Gemini 网页驱动，负责登录检测、新建对话隔离、内容输入、发送、等待完成与回复提取（选择器集中容错）。
- **`config.py`**：全局配置加载（含 Web、安全、白名单、上传限制、桌面串流、跨平台路径等）。
- **`static/index.html`**：网页端控制台（Vue 3），含登录/注册页、用户菜单与会话管理。
- **`static/desktop.html`**：1:1 共享桌面前端（DOM 模式动态 import PhantomStream viewer 重建沙箱镜像并叠加坐标控制层；像素模式走 canvas；键鼠 / IME 采集、平台切换、模式切换、钉钉登录）。
- **`static/vendor/`**：本地托管的前端库（Vue / Tailwind / Marked / PhantomStream ESM），无需外网 CDN 即可加载。
- **`data/`**（运行时生成，已 gitignore）：账户、会话与服务端密钥。
- **`.env.example`**：配置指南模板。

---

## 📄 开源协议

本项目基于 **MIT License** 协议开源，欢迎自由分发、修改与使用！

### 第三方组件

- DOM 镜像能力基于 [PhantomStream](https://github.com/fullselfbrowsing/PhantomStream)（[fullselfbrowsing](https://github.com/fullselfbrowsing)，**MIT License**），其 capture 注入脚本与前端 ESM 源码及对应许可已分别随附在 `vendor/phantom-stream/LICENSE` 与 `static/vendor/phantom-stream/LICENSE`；本项目仅做协议中继、隔离与远程控制接入，未修改其核心算法。
- 其余前端库（Vue / Tailwind / Marked）均为各自许可下的开源软件。

