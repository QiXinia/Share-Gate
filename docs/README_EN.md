<div align="center">

<img src="../resources/banner.png" alt="ChatGPT-Share-Gate Banner" width="100%"/>

<br/>

[![License](https://img.shields.io/github/license/tfboy1/webgpt2api?style=for-the-badge&color=blue)](../LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/tfboy1/webgpt2api?style=for-the-badge&logo=github&color=yellow)](https://github.com/tfboy1/webgpt2api/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/tfboy1/webgpt2api?style=for-the-badge&logo=git&color=orange)](https://github.com/tfboy1/webgpt2api/network/members)
[![爱发电](https://img.shields.io/badge/爱发电-Support%20Me-FF69B4?style=for-the-badge&logo=buy-me-a-coffee&logoColor=white)](https://www.ifdian.net/item/1a20ed042f0711f1865a52540025c377)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-☕-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.creem.io/payment/prod_1yc40mIhKwwrc7iqFOG9G2)

<br/>

[![简体中文](https://img.shields.io/badge/简体中文-README-blue?style=flat-square)](../README.md)
[![English](https://img.shields.io/badge/English-Current%20Language-red?style=flat-square)](#)
[![日本語](https://img.shields.io/badge/日本語-README-blue?style=flat-square)](README_JA.md)

<br/>

A private session-sharing client that automates a local logged-in ChatGPT browser session via Playwright,<br/>
designed to **safely share one ChatGPT account (e.g. Plus) with family/friends while completely isolating chat history**.

</div>

### 💡 Core Design Philosophy
Many people share one ChatGPT Plus subscription with friends to split costs or share premium DALL-E 3 quotas. However, sharing a single browser account has two major pain points:
1. **Privacy Leakage**: Everyone can see each other's chat histories, revealing personal/business privacy.
2. **Concurrency Conflict**: When multiple users send prompts at the same time, the ChatGPT page breaks, halts, or hijacks the current text flow.

**This project elegantly solves these pain points.**
Acting as a localized gateway, it queues user prompts via a **Telegram Bot** and a **Streamlit Web UI**, processing them sequentially (FIFO) using an automated local browser.
- **Strict Context Isolation**: Friends chat with the bot in their private chat window, so they only see their own conversation history. 
- **Conflict Prevention**: The backend automatically serializes requests so they never interrupt each other, preventing page crashes.
- **Clarification**: This project is **not** a public Web API reverse proxy. It is an end-user UI tool meant for private sharing and privacy isolation.

### 📊 Comparison with "Web Reverse API" Projects

| Dimension | Common Web-to-API Projects <br>(e.g., Chat2API / Pandora-Next) | This Project (ChatGPT-Share-Gate) |
| :--- | :---: | :---: |
| **Core Goal** | 🛠️ Reverse web calls into standard OpenAI API formats for third-party bots | 👥 Share one account securely with friends using integrated UI endpoints |
| **Out-of-the-Box** | ❌ **No UI Included**: Only exposes raw endpoints; users must deploy separate web interfaces | 🟢 **Dual-UI Built-in**: Ready-to-use Telegram Bot and Streamlit Admin UI |
| **Privacy Isolation** | ⚠️ **Manual Setup**: Requires third-party UI configuration, user tokens, or custom database rules | 🟢 **Native Isolation**: Private chats remain local to each user's Telegram or browser session |
| **Account Ban Risk** | ❌ **High Risk**: Spoofs HTTP requests or reverses backend APIs. Easily flagged by Cloudflare/OpenAI | 🟢 **Very Low**: Hooks directly into a **real running local Chrome/Edge browser** simulating human clicks |
| **Concurrency Fix** | ❌ **Concurrency Errors**: Concurrent API requests on one account trigger rapid rate-limiting | 🟢 **FIFO Queue**: Requests are serialized in a strict queue, avoiding ChatGPT interface page crashes |
| **Multimodal Support** | ⚠️ **Limited**: Often breaks when handling image uploads (Vision) or retrieving DALL-E 3 output links | 🟢 **Full Support**: Native file uploads and automated image extraction from the real browser |

---

## 🌟 Key Features

1. **Secure Session Isolation**: Users communicate via their private Telegram Bot windows. The backend shares one logged-in browser, but individual histories never leak to other users.
2. **Zero API Key Cost**: Directly drives your local Google Chrome or Edge browser, bypassing expensive API usage fees and utilizing Plus subscription benefits.
3. **Rich Frontend Interfaces**:
   - 🤖 **Telegram Bot**: Chat and draw anytime on Telegram.
   - 💻 **Streamlit Console**: An elegant admin control board to monitor browser connection status, test prompts, and reset context.
4. **Multimodal Interactions**:
   - 💬 **Text Chat**: Complete, continuous context conversations.
   - 🎨 **Image Generation**: Automatically captures, downloads, and forwards generated DALL-E 3 drawings back to Telegram.
   - 🖼️ **Vision Prompts**: Supports uploading local images (e.g. "What is in this picture?").
5. **Auto Browser Hook & Failover**:
   - 🌐 **Browser Fallback**: Scans common system directories for Google Chrome; if missing, it **automatically falls back to Microsoft Edge**.
   - 🔑 **Telegram Token Fallback**: If the Bot Token is absent, the system gracefully bypasses bot initialization and runs Streamlit Web-only mode.
   - 🔗 **Smart Ngrok Tunneling**: Automatically fires up a background ngrok tunnel if enabled, exposing Streamlit globally.
6. **One-Click Start/Stop Lifecycle**:
   - Double-clicking `start_all.bat` automatically configures the Python venv, installs requirements, spawns the Chrome/Edge instance, and launches Streamlit and the Bot.
   - Pressing `Ctrl+C` in the terminal triggers a cleanup sequence that **gracefully terminates all child processes (including ngrok, Streamlit, and the bot)**.

---

## 🛠️ Setup & Running

### Step 1: Prerequisites
Ensure you have installed:
1. **Python 3.8+** (Must check `Add Python to PATH` during installation).
2. **Google Chrome** or **Microsoft Edge**.

---

### Step 2: Configure Environment
1. In the project root, copy `\.env.example` and rename it to **`\.env`**.
2. Edit `.env` to input your parameters:
   - **`TELEGRAM_BOT_TOKEN`**: The API token obtained from @BotFather (leave blank to run in Web-only mode).
   - **`USE_NGROK`** & **`NGROK_PATH`**: (Optional, for exposing Streamlit globally).

> ⚠️ **【Important Path Formatting】**:
> In the `.env` file, **never wrap Windows folder paths in double quotes**!
> *Wrong*: `NGROK_PATH="C:\Users\Desktop\ngrok.exe"`
> *Right*: `NGROK_PATH=C:\Users\Desktop\ngrok.exe`
> The parser interprets `\n` inside double quotes as a newline escape character, which breaks the path.

---

### Step 3: Run
Double-click **`start_all.bat`**:
1. It creates the `venv` virtual environment and installs dependencies.
2. It hooks a Chrome remote debugging (CDP) port. If not already active, a new browser window opens and navigates to `chatgpt.com`.
3. **【Action Required】**: **Log into your ChatGPT account** in the opened browser (this session is saved; you won't need to log in again).
4. Streamlit and the Telegram Bot launch in the background.

---

### Step 4: Interacting & Stopping
* **Usage**:
  - Local UI: Navigate to [http://localhost:8501](http://localhost:8501).
  - Telegram: Message `/start` to your bot.
* **Stop**:
  - Press **`Ctrl+C`** in the CMD execution window. The orchestrator cleanly kills the browser process, ngrok tunnel, and python servers.

---

## 📂 Project Structure

- [start_all.bat](../start_all.bat): Windows batch file for environment setup, CDP initialization, and run execution.
- [run_all.py](../run_all.py): Central Python orchestrator that handles browser detection, ngrok tunnels, subprocesses, and signal termination.
- [bot.py](../bot.py): Telegram Bot implementation featuring a FIFO queue and image-generating download workflows.
- [app_streamlit.py](../app_streamlit.py): Streamlit web console dashboard.
- [chatgpt_browser.py](../chatgpt_browser.py): Playwright driver manipulating the CDP browser, handling image downloads and cross-process file locks.
- [config.py](../config.py): Static project configuration loader.
- [.env](../.env): Active environment credentials (do not commit to Git).
- [.env.example](../.env.example): Configuration template.

---

## 📄 License

This project is licensed under the **[MIT License](../LICENSE)**. You are free to distribute, modify, and use it as you see fit.
