import subprocess
import sys
import os
import time
import socket
import threading

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
    """Stream process stdout/stderr to sys.stdout with a prefix."""
    try:
        for line in iter(process.stdout.readline, b''):
            sys.stdout.write(f"[{prefix}] {line.decode('utf-8', errors='ignore')}")
            sys.stdout.flush()
    except Exception as e:
        print(f"[{prefix}] Error reading output: {e}")

def main():
    print("============================================")
    print("  Unified WebGPT2API Services Starter")
    print("============================================")
    print()

    # 1. Chrome Check/Start
    if is_chrome_running():
        print("[1/3] Chrome is already running on port 9222.")
    else:
        print("[1/3] Starting Chrome...")
        chrome_cmd = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "--user-data-dir=C:\\Users\\86150\\Chrome_Hermes_Profile",
            "--remote-debugging-port=9222",
            "https://chatgpt.com"
        ]
        try:
            subprocess.Popen(chrome_cmd)
            print("      Waiting 8s for Chrome to initialize...")
            time.sleep(8)
        except Exception as e:
            print(f"⚠️ Error starting Chrome: {e}. Make sure Chrome is installed or running manually.")

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

    print("[2/3] Starting Telegram Bot...")
    bot_process = None
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

    time.sleep(2)

    print("[3/3] Starting Streamlit...")
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
        while True:
            time.sleep(1)
            # Check if any process exited unexpectedly
            if bot_process and bot_process.poll() is not None:
                print("⚠️ Telegram Bot process terminated unexpectedly.")
                break
            if streamlit_process and streamlit_process.poll() is not None:
                print("⚠️ Streamlit process terminated unexpectedly.")
                break
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
        
        print("All processes stopped.")

if __name__ == "__main__":
    main()
