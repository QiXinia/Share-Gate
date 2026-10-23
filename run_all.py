"""Cross-platform service orchestrator for ChatGPT Share Gate.

Responsibilities
----------------
1. Detect / launch a Chromium-based browser with remote debugging enabled.
2. Start the ngrok tunnel (optional).
3. Start the DingTalk robot (optional, Stream long-connection mode).
4. Start the web server (with authentication).
5. On exit, terminate the whole process tree cleanly (no orphan processes or
   port conflicts on Windows).

Runs on Windows, macOS and Linux. The browser is intentionally NOT killed on
exit - it keeps the ChatGPT / Gemini login sessions alive for the next run.
"""

import subprocess
import sys
import os
import time
import socket
import signal
import threading
import shutil
import platform

# Reconfigure stdout/stderr to avoid UnicodeEncodeErrors on non-UTF-8 terminals
# (Windows CMD defaults to GBK/CP936).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")

# Make sibling modules importable regardless of the launch directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


# ---------------------------------------------------------------------------
# Port / process helpers
# ---------------------------------------------------------------------------
def is_port_open(host="127.0.0.1", port=9222):
    """Check whether a TCP port is already accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        try:
            s.connect((host, port))
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False


def stream_output(process, prefix):
    """Stream subprocess stdout with a prefix, with encoding fallback."""
    try:
        terminal_encoding = sys.stdout.encoding or "utf-8"
        for line in iter(process.stdout.readline, b""):
            try:
                decoded = line.decode("utf-8")
            except UnicodeDecodeError:
                decoded = line.decode(terminal_encoding, errors="replace")
            sys.stdout.write(f"[{prefix}] {decoded}")
            sys.stdout.flush()
    except Exception as e:
        print(f"[{prefix}] Error reading output: {e}")


def detached_popen_kwargs():
    """Keyword args that let the orchestrator kill the whole process tree."""
    if IS_WINDOWS:
        # Independent process group so Ctrl+C is not forwarded automatically;
        # we manage the lifecycle ourselves (taskkill /T).
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    # POSIX: child gets its own session/process group (killpg on shutdown).
    return {"start_new_session": True}


def terminate_process_tree(proc, name):
    """Terminate a process and ALL its children (cross-platform)."""
    if proc is None or proc.poll() is not None:
        return
    print(f"Terminating {name} (PID {proc.pid})...")
    if IS_WINDOWS:
        # /T kills the tree, /F forces; ignores failures if already gone.
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    # Force kill if still alive.
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except OSError:
            proc.kill()
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print(f"[WARNING] {name} did not fully exit.")


# ---------------------------------------------------------------------------
# Python / venv resolution (cross-platform)
# ---------------------------------------------------------------------------
def find_venv_python():
    """Return the project venv interpreter, falling back to the system one."""
    if IS_WINDOWS:
        candidates = [
            os.path.join(config.BASE_DIR, "venv", "Scripts", "python.exe"),
            os.path.join(config.BASE_DIR, ".venv", "Scripts", "python.exe"),
        ]
    else:
        candidates = [
            os.path.join(config.BASE_DIR, "venv", "bin", "python"),
            os.path.join(config.BASE_DIR, ".venv", "bin", "python"),
        ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return sys.executable


# ---------------------------------------------------------------------------
# Browser discovery (Windows / macOS / Linux)
# ---------------------------------------------------------------------------
def _find_browser_windows():
    # 1. PATH
    for name in ("chrome.exe", "msedge.exe"):
        path = shutil.which(name)
        if path:
            return path, "edge" if "edge" in name.lower() else "chrome"
    # 2. Registry "App Paths" (most reliable on Windows)
    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg:
        app_paths_root = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        for app_name, kind in (("chrome.exe", "chrome"), ("msedge.exe", "edge")):
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for access in (
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                    winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
                ):
                    try:
                        key = winreg.OpenKey(
                            hive,
                            app_paths_root + "\\" + app_name,
                            0,
                            access,
                        )
                        value, _ = winreg.QueryValueEx(key, "")
                        winreg.CloseKey(key)
                        value = value.strip().strip('"')
                        if value and os.path.exists(value):
                            return value, kind
                    except OSError:
                        continue
    # 3. Well-known install paths
    program_files = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    chrome_rel = os.path.join("Google", "Chrome", "Application", "chrome.exe")
    edge_rel = os.path.join("Microsoft", "Edge", "Application", "msedge.exe")
    for base in program_files:
        if not base:
            continue
        for rel, kind in ((chrome_rel, "chrome"), (edge_rel, "edge")):
            candidate = os.path.join(base, rel)
            if os.path.exists(candidate):
                return candidate, kind
    return None, None


def _find_browser_mac():
    candidates = [
        ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "chrome"),
        ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "edge"),
        ("/Applications/Chromium.app/Contents/MacOS/Chromium", "chrome"),
        (os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), "chrome"),
    ]
    for path, kind in candidates:
        if os.path.exists(path):
            return path, kind
    for name in ("google-chrome", "chromium", "microsoft-edge"):
        path = shutil.which(name)
        if path:
            return path, "edge" if "edge" in name else "chrome"
    return None, None


def _find_browser_linux():
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "microsoft-edge", "chrome"):
        path = shutil.which(name)
        if path:
            return path, "edge" if "edge" in name else "chrome"
    for path in (
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
        "/opt/google/chrome/chrome",
    ):
        if os.path.exists(path):
            return path, "edge" if "edge" in path else "chrome"
    return None, None


def find_browser():
    """Return (executable_path, browser_kind) or (None, None)."""
    if IS_WINDOWS:
        return _find_browser_windows()
    if IS_MAC:
        return _find_browser_mac()
    return _find_browser_linux()


def launch_browser(debug_port):
    """Launch the browser with remote debugging unless the port is open."""
    if is_port_open(config.CDP_HOST, debug_port):
        print(f"[1/4] Browser is already running with debugging port {debug_port}.")
        return
    print("[1/4] Starting Browser...")
    browser_bin, browser_type = find_browser()
    if not browser_bin:
        print("⚠️ [WARNING] No Google Chrome / Microsoft Edge / Chromium was found!")
        print("          Please install a Chromium browser, or launch it manually on the")
        print(f"          debugging port {debug_port}.")
        return

    profile_dir = config.BROWSER_PROFILE_DIR
    os.makedirs(profile_dir, exist_ok=True)

    # Open one tab per enabled platform (ChatGPT / Gemini).
    platform_urls = [config.PLATFORMS[p]["home_url"] for p in config.AI_PLATFORMS]
    browser_cmd = [
        browser_bin,
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={debug_port}",
        f"--remote-debugging-address={config.CDP_HOST}",
        *platform_urls,
    ]
    try:
        subprocess.Popen(
            browser_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **detached_popen_kwargs(),
        )
        print(f"      Started {browser_type.capitalize()}: {browser_bin}")
        print(f"      Profile path: {profile_dir}")
        print("      Waiting for the browser to initialize...")
        # Poll the port instead of a blind fixed sleep.
        for _ in range(20):
            if is_port_open(config.CDP_HOST, debug_port):
                break
            time.sleep(0.5)
        time.sleep(2)
    except Exception as e:
        print(f"⚠️ Error starting browser: {e}")


# ---------------------------------------------------------------------------
# ngrok discovery
# ---------------------------------------------------------------------------
def find_ngrok():
    """Find ngrok in .env, project directory, or PATH (cross-platform)."""
    env_path = os.getenv("NGROK_PATH", "").strip().strip("'\"")
    if env_path and os.path.exists(env_path):
        return env_path
    for name in ("ngrok.exe", "ngrok"):
        local_path = os.path.join(config.BASE_DIR, name)
        if os.path.exists(local_path):
            return local_path
    return shutil.which("ngrok")


def main():
    print("============================================")
    print("  ChatGPT Share Gate Services Starter")
    print(f"  Platform: {platform.platform()}")
    print("============================================")
    print()

    web_port = config.WEB_PORT
    desktop_port = config.DESKTOP_PORT

    # 1. Browser
    launch_browser(config.CDP_PORT)

    python_exe = find_venv_python()
    print(f"ℹ️ Using Python interpreter: {python_exe}")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    # 2. ngrok
    use_ngrok = os.getenv("USE_NGROK", "True").strip().lower() in ("true", "1", "yes")
    ngrok_process = None
    if use_ngrok:
        print("[2/5] Starting Ngrok Tunnel (targets the shared desktop)...")
        ngrok_bin = find_ngrok()
        if not ngrok_bin:
            print("⚠️ [WARNING] ngrok not found. Skipping tunnel; the desktop stays local.")
            print(f"          Local desktop: http://localhost:{desktop_port}/desktop")
        else:
            tunnel_url = os.getenv("NGROK_TUNNEL_URL", "").strip()
            ngrok_cmd = [ngrok_bin, "http"]
            if tunnel_url:
                ngrok_cmd.append(f"--url={tunnel_url}")
            ngrok_cmd.extend([str(desktop_port),
                              f"--host-header=localhost:{desktop_port}"])
            try:
                ngrok_process = subprocess.Popen(
                    ngrok_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    **detached_popen_kwargs(),
                )
                threading.Thread(
                    target=stream_output, args=(ngrok_process, "Ngrok"), daemon=True
                ).start()
                print(f"      Ngrok started: {ngrok_bin}")
                if tunnel_url:
                    print(f"      Tunnel URL: https://{tunnel_url}")
                time.sleep(2)
            except Exception as e:
                print(f"⚠️ Failed to start Ngrok: {e}. Continuing without tunnel...")
    else:
        print("[2/4] Ngrok is disabled in configuration.")

    # 3. DingTalk robot (optional)
    dt_key = os.getenv("DINGTALK_APP_KEY", "").strip()
    dt_secret = os.getenv("DINGTALK_APP_SECRET", "").strip()
    is_bot_configured = bool(
        dt_key and dt_secret
        and dt_key not in ("YOUR_APP_KEY_HERE",)
        and dt_secret not in ("YOUR_APP_SECRET_HERE",)
    )
    bot_process = None
    if is_bot_configured:
        print("[3/5] Starting DingTalk Robot...")
        try:
            bot_process = subprocess.Popen(
                [python_exe, os.path.join(config.BASE_DIR, "bot.py")],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=config.BASE_DIR,
                env=env,
                **detached_popen_kwargs(),
            )
            threading.Thread(
                target=stream_output, args=(bot_process, "Bot"), daemon=True
            ).start()
        except Exception as e:
            print(f"❌ Failed to start DingTalk Robot: {e}")
    else:
        print("[3/5] DingTalk Robot skipped (DINGTALK_APP_KEY/SECRET not set).")

    time.sleep(2)

    # 4. Web server
    print("[4/5] Starting Web Server...")
    web_process = None
    try:
        web_process = subprocess.Popen(
            [python_exe, os.path.join(config.BASE_DIR, "web_server.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=config.BASE_DIR,
            env=env,
            **detached_popen_kwargs(),
        )
        threading.Thread(
            target=stream_output, args=(web_process, "WebServer"), daemon=True
        ).start()
    except Exception as e:
        print(f"❌ Failed to start Web Server: {e}")

    time.sleep(1)

    # 5. 1:1 shared desktop (streaming + DingTalk SSO)
    print("[5/5] Starting Shared Desktop Service...")
    desktop_process = None
    try:
        desktop_process = subprocess.Popen(
            [python_exe, os.path.join(config.BASE_DIR, "desktop_server.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=config.BASE_DIR,
            env=env,
            **detached_popen_kwargs(),
        )
        threading.Thread(
            target=stream_output, args=(desktop_process, "Desktop"), daemon=True
        ).start()
    except Exception as e:
        print(f"❌ Failed to start Shared Desktop: {e}")

    print()
    print("============================================")
    print(f"  Shared desktop (1:1): http://localhost:{desktop_port}/desktop")
    print(f"  Admin console:        http://localhost:{web_port}")
    print("  Press Ctrl+C to terminate all services.")
    print("============================================")
    print()

    stopping = False

    def request_stop(signum=None, frame=None):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        print("\n[Interrupt] Terminating all services...")

    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

    try:
        ngrok_warned_dead = False
        while not stopping:
            time.sleep(1)
            if bot_process and bot_process.poll() is not None:
                print("⚠️ DingTalk Robot process terminated unexpectedly.")
                break
            if web_process and web_process.poll() is not None:
                print("⚠️ Web Server process terminated unexpectedly.")
                break
            if desktop_process and desktop_process.poll() is not None:
                print("⚠️ Shared Desktop process terminated unexpectedly.")
                break
            if ngrok_process and ngrok_process.poll() is not None and not ngrok_warned_dead:
                print("⚠️ Ngrok tunnel process terminated unexpectedly.")
                ngrok_warned_dead = True
    except KeyboardInterrupt:
        request_stop()
    finally:
        # Stop the managed services; the browser is deliberately kept alive.
        terminate_process_tree(bot_process, "DingTalk Robot")
        terminate_process_tree(web_process, "Web Server")
        terminate_process_tree(desktop_process, "Shared Desktop")
        terminate_process_tree(ngrok_process, "Ngrok")
        print("All managed processes stopped (browser left running).")


if __name__ == "__main__":
    main()
