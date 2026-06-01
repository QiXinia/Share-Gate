import subprocess
import sys
import os
import time
import socket
import threading
import shutil
from dotenv import load_dotenv

# Reconfigure stdout/stderr to avoid UnicodeEncodeErrors on non-UTF-8 terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(errors='replace')

# Load env variables
load_dotenv()

def is_chrome_running(port=9222):
    """Check if Chrome debugging port 9222 is already open."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (socket.timeout, ConnectionRefusedError):
            return False

def stream_output(process, prefix):
    """Stream process stdout/stderr to sys.stdout with a prefix, supporting multi-encoding fallback."""
    try:
        # Get terminal encoding, default to utf-8
        terminal_encoding = sys.stdout.encoding or 'utf-8'
        for line in iter(process.stdout.readline, b''):
            # Try to decode as UTF-8 first
            try:
                decoded = line.decode('utf-8')
            except UnicodeDecodeError:
                # Fallback to terminal/system encoding (e.g., gbk on Windows)
                decoded = line.decode(terminal_encoding, errors='replace')
            sys.stdout.write(f"[{prefix}] {decoded}")
            sys.stdout.flush()
    except Exception as e:
        print(f"[{prefix}] Error reading output: {e}")

def find_ngrok():
    """Find the path to ngrok executable in PATH, current dir, config, or custom desktop path."""
    # 1. Check custom path from .env
    env_path = os.getenv("NGROK_PATH")
    if env_path:
        env_path = env_path.strip('\'"').strip()
        if os.path.exists(env_path):
            return env_path
        
    # 2. Check project root folder
    for name in ["ngrok.exe", "ngrok"]:
        local_path = os.path.join(os.getcwd(), name)
        if os.path.exists(local_path):
            return local_path
            
    # 3. Check system PATH
    system_path = shutil.which("ngrok")
    if system_path:
        return system_path
        
    # 4. Check specific user fallback paths
    for path in [
        r"C:\Users\86150\Desktop\微信\电脑\ngrok.exe",
        r"C:\Users\86150\Desktop\ħ\͸\ngrok.exe"
    ]:
        if os.path.exists(path):
            return path
            
    return None

def find_chrome():
    """Find the path to Google Chrome or Microsoft Edge executable on Windows."""
    # 1. Check system PATH
    for name in ["chrome.exe", "chrome", "msedge.exe", "msedge"]:
        path = shutil.which(name)
        if path:
            return path, ("edge" if "edge" in name.lower() else "chrome")
            
    # 2. Try common Google Chrome paths
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    if "LOCALAPPDATA" in os.environ:
        chrome_paths.append(os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "Application", "chrome.exe"))
        
    for path in chrome_paths:
        if os.path.exists(path):
            return path, "chrome"
            
    # 3. Try common Microsoft Edge paths (fallback)
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in edge_paths:
        if os.path.exists(path):
            return path, "edge"
            
    return None, None

def main():
    print("============================================")
    print("  Unified WebGPT2API Services Starter")
    print("============================================")
    print()

    # 1. Chrome Check/Start
    if is_chrome_running():
        print("[1/4] Chrome is already running on port 9222.")
    else:
        print("[1/4] Starting Browser...")
        browser_bin, browser_type = find_chrome()
        if not browser_bin:
            print("⚠️ [WARNING] Neither Google Chrome nor Microsoft Edge was found on your system!")
            print("          Please install a Chromium browser or launch it manually on port 9222.")
        else:
            profile_dir = r"C:\Users\86150\Chrome_Hermes_Profile"
            if not os.path.exists(profile_dir):
                profile_dir = os.path.join(os.getcwd(), "chrome-dev-profile")
                
            chrome_cmd = [
                browser_bin,
                f"--user-data-dir={profile_dir}",
                "--remote-debugging-port=9222",
                "https://chatgpt.com"
            ]
            try:
                subprocess.Popen(chrome_cmd)
                print(f"      Started {browser_type.capitalize()} successfully using: {browser_bin}")
                print(f"      Profile path: {profile_dir}")
                print("      Waiting 8s for browser to initialize...")
                time.sleep(8)
            except Exception as e:
                print(f"⚠️ Error starting browser: {e}. Make sure Chrome or Edge is installed or running manually.")

    # Locate executable paths
    python_exe = os.path.join("venv", "Scripts", "python.exe")
    streamlit_exe = os.path.join("venv", "Scripts", "streamlit.exe")
    
    if not os.path.exists(python_exe):
        python_exe = sys.executable
        print(f"ℹ️ Venv python not found, fallback to system: {python_exe}")
    if not os.path.exists(streamlit_exe):
        streamlit_exe = "streamlit"
        print(f"ℹ️ Venv streamlit not found, fallback to global 'streamlit'")

    # Set environment variables (unbuffer stdout)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    # Start ngrok if enabled
    use_ngrok = os.getenv("USE_NGROK", "True").strip().lower() in ("true", "1", "yes")
    ngrok_process = None

    if use_ngrok:
        print("[2/4] Starting Ngrok Tunnel...")
        ngrok_bin = find_ngrok()
        if not ngrok_bin:
            print("⚠️ [WARNING] ngrok executable not found in PATH, current folder, or config. Skipping tunnel.")
            print("          Streamlit local server will still be running at http://localhost:8501.")
            print("          To expose it externally, please install ngrok or configure NGROK_PATH in .env.")
        else:
            tunnel_url = os.getenv("NGROK_TUNNEL_URL", "").strip()
            ngrok_cmd = [ngrok_bin, "http"]
            if tunnel_url:
                ngrok_cmd.append(f"--url={tunnel_url}")
            ngrok_cmd.extend(["8501", "--host-header=localhost:8501"])

            try:
                ngrok_process = subprocess.Popen(
                    ngrok_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT
                )
                t_ngrok = threading.Thread(target=stream_output, args=(ngrok_process, "Ngrok"), daemon=True)
                t_ngrok.start()
                print(f"      Ngrok started successfully using: {ngrok_bin}")
                if tunnel_url:
                    print(f"      Tunnel URL: https://{tunnel_url}")
                time.sleep(2)
            except Exception as e:
                print(f"⚠️ Failed to start Ngrok: {e}. Continuing without tunnel...")
    else:
        print("[2/4] Ngrok is disabled in configuration.")

    # Check if Telegram Bot token is configured
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    is_bot_configured = bot_token and bot_token != "YOUR_BOT_TOKEN_HERE"
    bot_process = None

    if is_bot_configured:
        print("[3/4] Starting Telegram Bot...")
        try:
            bot_process = subprocess.Popen(
                [python_exe, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env
            )
            t_bot = threading.Thread(target=stream_output, args=(bot_process, "Bot"), daemon=True)
            t_bot.start()
        except Exception as e:
            print(f"❌ Failed to start Telegram Bot: {e}")
    else:
        print("[3/4] Telegram Bot is skipped (TELEGRAM_BOT_TOKEN is not set or set to placeholder).")

    time.sleep(2)

    print("[4/4] Starting Streamlit...")
    streamlit_process = None
    try:
        streamlit_process = subprocess.Popen(
            [streamlit_exe, "run", "app_streamlit.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env
        )
        t_streamlit = threading.Thread(target=stream_output, args=(streamlit_process, "Streamlit"), daemon=True)
        t_streamlit.start()
    except Exception as e:
        print(f"❌ Failed to start Streamlit: {e}")

    print()
    print("============================================")
    print("  All services running under this window.")
    print("  Press Ctrl+C to terminate all services.")
    print("============================================")
    print()

    try:
        ngrok_warned_dead = False
        while True:
            time.sleep(1)
            # Check if any process exited unexpectedly
            if bot_process and bot_process.poll() is not None:
                print("⚠️ Telegram Bot process terminated unexpectedly.")
                break
            if streamlit_process and streamlit_process.poll() is not None:
                print("⚠️ Streamlit process terminated unexpectedly.")
                break
            if ngrok_process and ngrok_process.poll() is not None and not ngrok_warned_dead:
                print("⚠️ Ngrok tunnel process terminated unexpectedly.")
                ngrok_warned_dead = True
    except KeyboardInterrupt:
        print("\n[Ctrl+C detected] Terminating all services...")
    finally:
        # Clean termination
        if bot_process and bot_process.poll() is None:
            print("Terminating Telegram Bot...")
            bot_process.terminate()
        if streamlit_process and streamlit_process.poll() is None:
            print("Terminating Streamlit...")
            streamlit_process.terminate()
        if ngrok_process and ngrok_process.poll() is None:
            print("Terminating Ngrok...")
            ngrok_process.terminate()

        # Wait for processes to exit
        if bot_process:
            try:
                bot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                bot_process.kill()
        if streamlit_process:
            try:
                streamlit_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                streamlit_process.kill()
        if ngrok_process:
            try:
                ngrok_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ngrok_process.kill()
        
        print("All processes stopped.")

if __name__ == "__main__":
    main()
