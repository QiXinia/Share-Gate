# Telegram Bot ChatGPT Web Automation

这是一个通过 Playwright 自动化操纵 Chrome 浏览器，实现模拟网页端 ChatGPT 对话的 Telegram 机器人项目。支持纯文字聊天、文生图（DALL-E 3）以及图生图功能。

## 🌟 特性

1. **完全模拟网页操作**：利用本地或服务器已登录的 Chrome 浏览器进行自动化操作，无需 API Key。
2. **多模态支持**：
   - 💬 纯文字对话
   - 🎨 自动下载并发送 ChatGPT 生成的 DALL-E 3 图片（文生图）
   - 🖼️ 支持发送图片并输入文字进行图生图（自动上传图片到 ChatGPT，并附带 Prompt）
3. **安全并发队列**：由于网页端 ChatGPT 同一时刻只能进行单线程会话，机器人内置了串行等待队列（FIFO 锁）与实时的排队位置通知。
4. **代理配置**：内置对 Telegram 客户端的 HTTP/HTTPS 代理配置，满足国内网络环境运行需求。

---

## 🛠️ 环境准备

### 1. 启动 Chrome 远程调试端口

在运行机器人前，**必须**启动一个打开了 CDP（Chrome 开发者工具协议）远程调试端口的 Chrome 浏览器。

#### 命令行启动方式（Windows）：

按下 `Win + R` 打开运行窗口，输入以下命令并回车：

```cmd
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\chrome-dev-profile"
```

> 💡 **注意**：
> - `--remote-debugging-port=9222` 是连接的关键，不能修改为其他端口（除非在 `.env` 中也做了修改）。
> - `--user-data-dir` 指定了一个独立的浏览器数据目录，确保你在该窗口中登录的 `chatgpt.com` 账号不会因为浏览器关闭而丢失，也防止和您平常使用的 Chrome 冲突。
> - 启动后，请在打开的浏览器窗口中访问 `https://chatgpt.com`，完成账号登录。

### 2. 配置 `.env`

项目根目录下已为您创建好了 `.env` 配置文件，包含以下配置项：

```env
TELEGRAM_BOT_TOKEN=8686206284:AAGs87Qc0wsvy6EI0M0jUUw6xjgYPbz9AH0
CDP_URL=http://127.0.0.1:9222

# 如果你的网络环境需要通过科学上网代理连接 Telegram
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
```

---

## 🚀 启动与运行

1. 打开命令行窗口，进入项目根目录：
   ```cmd
   cd d:\pycharmProject\webgpt2api
   ```

2. 激活虚拟环境并运行机器人：
   ```cmd
   # 激活虚拟环境
   .\venv\Scripts\activate

   # 启动机器人
   python bot.py
   ```

3. 打开 Telegram，找到你的 Bot，发送 `/start` 即可开始对话。

---

## 📂 项目结构

- [bot.py](file:///d:/pycharmProject/webgpt2api/bot.py)：Telegram 机器人服务端，负责消息拦截、图片下载、串行排队与消息发送。
- [chatgpt_browser.py](file:///d:/pycharmProject/webgpt2api/chatgpt_browser.py)：Playwright 浏览器驱动，操纵网页并提取结果。
- [config.py](file:///d:/pycharmProject/webgpt2api/config.py)：全局配置与路径管理。
- [.env](file:///d:/pycharmProject/webgpt2api/.env)：密钥与代理配置。
- [requirements.txt](file:///d:/pycharmProject/webgpt2api/requirements.txt)：依赖列表。
