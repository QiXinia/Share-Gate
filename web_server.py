import os
import json
import base64
import logging
import asyncio
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import config
from chatgpt_browser import ChatGPTBrowser

# Logger configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("web_server.log", encoding="utf-8"),
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger(__name__)

# Shared asyncio event loop running in a background thread
loop = asyncio.new_event_loop()

def start_event_loop(loop_obj):
    asyncio.set_event_loop(loop_obj)
    loop_obj.run_forever()

loop_thread = threading.Thread(target=start_event_loop, args=(loop,), daemon=True)
loop_thread.start()

# Initialize ChatGPT browser
browser = ChatGPTBrowser(cdp_url=config.CDP_URL, temp_dir=config.TEMP_DIR)

# Connect to browser asynchronously on startup
startup_future = asyncio.run_coroutine_threadsafe(browser.start(), loop)
try:
    startup_future.result(timeout=15)
    logger.info("Successfully connected to ChatGPT browser instance on startup.")
except Exception as ex:
    logger.error(f"Failed to connect to browser on startup: {ex}")

class ChatGPTWebHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Override to serve all non-API paths from the "static" subdirectory
        if not path.startswith('/api/'):
            clean_path = path.split('?')[0].split('#')[0]
            rel_path = clean_path.lstrip('/')
            if not rel_path or rel_path == 'index.html':
                rel_path = 'index.html'
            return os.path.join(os.getcwd(), 'static', rel_path)
        return super().translate_path(path)

    def end_headers(self):
        # Prevent caching for APIs
        if self.path.startswith('/api/'):
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        if self.path == '/api/status':
            self.handle_status()
        else:
            # Fallback to serving static files
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/new_chat':
            self.handle_new_chat()
        elif self.path == '/api/chat':
            self.handle_chat()
        else:
            self.send_error(404, "API endpoint not found")

    def handle_status(self):
        future = asyncio.run_coroutine_threadsafe(browser.get_status(), loop)
        try:
            status = future.result(timeout=5)
            self.send_json_response(status)
        except Exception as e:
            logger.error(f"Error fetching status: {e}")
            self.send_json_response({"status": "error", "message": str(e)}, status_code=500)

    def handle_new_chat(self):
        future = asyncio.run_coroutine_threadsafe(browser.new_chat(), loop)
        try:
            result = future.result(timeout=20)
            self.send_json_response(result)
        except Exception as e:
            logger.error(f"Error resetting session: {e}")
            self.send_json_response({"status": "error", "message": str(e)}, status_code=500)

    def handle_chat(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            body = json.loads(post_data.decode('utf-8'))
        except Exception as e:
            self.send_json_response({"status": "error", "message": f"Invalid JSON body: {e}"}, status_code=400)
            return

        prompt = body.get('prompt', '')
        files = body.get('files', [])
        features = body.get('features', {})
        temp_files = []

        try:
            # Decode base64 attachments and write them to disk temporarily
            for f in files:
                name = f.get('name', 'file')
                data = f.get('data', '')
                
                # Check for base64 schema prefix
                if ',' in data:
                    data = data.split(',', 1)[1]
                
                file_bytes = base64.b64decode(data)
                
                # Create a secure temp file path
                safe_name = os.path.basename(name)
                temp_filename = f"web_{int(time.time())}_{safe_name}"
                temp_path = os.path.join(config.TEMP_DIR, temp_filename)
                
                with open(temp_path, "wb") as fh:
                    fh.write(file_bytes)
                
                temp_files.append(temp_path)
                logger.info(f"Saved temporary uploaded file to: {temp_path}")

            logger.info(f"Submitting chat request: prompt='{prompt[:60]}', files count={len(temp_files)}, features={features}")
            
            # Execute browser message send
            future = asyncio.run_coroutine_threadsafe(
                browser.send_message(prompt, file_paths=temp_files, features=features),
                loop
            )
            result = future.result(timeout=360) # 6 minutes max

            # Convert returned image paths to base64 encoding for client display
            if result.get("status") == "success":
                base64_images = []
                for img_path in result.get("images", []):
                    if os.path.exists(img_path):
                        try:
                            with open(img_path, "rb") as image_file:
                                encoded = base64.b64encode(image_file.read()).decode('utf-8')
                                base64_images.append(encoded)
                            # Remove the image file from local temp folder to save space
                            os.remove(img_path)
                        except Exception as img_err:
                            logger.error(f"Error encoding/deleting image {img_path}: {img_err}")
                result["images"] = base64_images

            self.send_json_response(result)

        except Exception as e:
            logger.error(f"Error handling chat request: {e}")
            self.send_json_response({"status": "error", "message": str(e)}, status_code=500)
            
        finally:
            # Always clean up temporary uploaded files immediately
            for path in temp_files:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.info(f"Removed temporary upload file: {path}")
                    except Exception as err:
                        logger.warning(f"Failed to remove temp file {path}: {err}")

    def send_json_response(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        response_bytes = json.dumps(data).encode('utf-8')
        self.send_header('Content-Length', str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

def run_server(port=8501):
    server_address = ('', port)
    httpd = ThreadingHTTPServer(server_address, ChatGPTWebHandler)
    logger.info(f"Starting Web Server on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down Web Server...")
    finally:
        httpd.server_close()

if __name__ == "__main__":
    # Ensure temporary upload directory exists
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    run_server(port=8501)
