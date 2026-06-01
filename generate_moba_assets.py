import asyncio
import os
import sys
import time
import logging
from PIL import Image
import numpy as np
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add current folder to path to import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import config
from chatgpt_browser import ChatGPTBrowser

# Target directory for output assets
MOBA_ASSETS_DIR = r"d:\pycharmProject\moba\public\assets"
os.makedirs(MOBA_ASSETS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Image Processing: Flood-fill Transparency & Colorization
# ---------------------------------------------------------------------------
def make_transparent_floodfill(image_path, output_path, tolerance=40):
    """Detects off-white background and turns it transparent using flood fill."""
    logger.info(f"Processing transparency for {image_path}...")
    img = Image.open(image_path).convert("RGBA")
    width, height = img.size
    pixels = np.array(img)

    # Use corner color as baseline background color
    bg_color = pixels[0, 0][:3]
    logger.info(f"Corner color detected: {bg_color}")

    # Breadth-First Search queue starting from corners
    visited = np.zeros((height, width), dtype=bool)
    queue = deque()
    
    # Add four corners
    for x, y in [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]:
        queue.append((x, y))
        visited[y, x] = True

    while queue:
        cx, cy = queue.popleft()
        # Set alpha to 0 (fully transparent)
        pixels[cy, cx, 3] = 0

        # Check 4 cardinal neighbors
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < width and 0 <= ny < height and not visited[ny, nx]:
                current_rgb = pixels[ny, nx][:3]
                
                # Check color distance to corner background color
                diff_bg = np.linalg.norm(current_rgb - bg_color)
                # Check color distance to pure white
                diff_white = np.linalg.norm(current_rgb - np.array([255, 255, 255]))
                
                if diff_bg < tolerance or diff_white < tolerance:
                    visited[ny, nx] = True
                    queue.append((nx, ny))

    result_img = Image.fromarray(pixels, "RGBA")
    
    # Crop borders to fit tightly if needed, or save directly
    result_img.save(output_path, "PNG")
    logger.info(f"Saved transparent PNG to {output_path}")

def colorize_image(image_path, output_path, team_color):
    """Tint the image to team colors (cyan for blue team, red for red team)."""
    logger.info(f"Colorizing {image_path} for {team_color} team...")
    img = Image.open(image_path).convert("RGBA")
    pixels = np.array(img)
    
    h, w, c = pixels.shape
    for y in range(h):
        for x in range(w):
            if pixels[y, x, 3] > 0: # Only tint non-transparent pixels
                r, g, b = pixels[y, x, 0], pixels[y, x, 1], pixels[y, x, 2]
                
                # Convert to grayscale to keep light value, then apply tint
                gray = int(r * 0.299 + g * 0.587 + b * 0.114)
                
                if team_color == 'blue':
                    # Cyan/Blue tint
                    pixels[y, x, 0] = int(gray * 0.2)
                    pixels[y, x, 1] = int(gray * 0.8)
                    pixels[y, x, 2] = min(255, int(gray * 1.5))
                elif team_color == 'red':
                    # Red tint
                    pixels[y, x, 0] = min(255, int(gray * 1.5))
                    pixels[y, x, 1] = int(gray * 0.2)
                    pixels[y, x, 2] = int(gray * 0.2)
                    
    result_img = Image.fromarray(pixels, "RGBA")
    result_img.save(output_path, "PNG")
    logger.info(f"Saved colorized image to {output_path}")

# ---------------------------------------------------------------------------
# Drawing Tasks configuration
# ---------------------------------------------------------------------------
drawing_tasks = [
  {
    "name": "warrior",
    "prompt": "A 2D top-down game sprite avatar icon of a high-tech glowing warrior wearing cyan crystal power armor, circular icon boundary, isolated on a solid white background, digital clean vectors, game art, sharp details.",
    "is_team_specific": False
  },
  {
    "name": "mage",
    "prompt": "A 2D top-down game sprite avatar icon of a glowing mage wearing dark purple wizard robes, holding a flame staff, circular icon boundary, isolated on a solid white background, digital clean vectors, game art, sharp details.",
    "is_team_specific": False
  },
  {
    "name": "archer",
    "prompt": "A 2D top-down game sprite avatar icon of a stealthy forest elven archer holding a glowing green longbow, circular icon boundary, isolated on a solid white background, digital clean vectors, game art, sharp details.",
    "is_team_specific": False
  },
  {
    "name": "minion",
    "prompt": "A 2D top-down game sprite avatar icon of a simple round mini-robot minion with mechanical wheels, isolated on a solid white background, digital clean flat vectors, game art.",
    "is_team_specific": True
  },
  {
    "name": "tower",
    "prompt": "A 2D top-down game sprite avatar icon of a crystal-tipped defense tower, glowing power core, isolated on a solid white background, digital clean vectors, game art.",
    "is_team_specific": True
  },
  {
    "name": "base",
    "prompt": "A 2D top-down game sprite avatar icon of a huge glowing nexus energy crystal base, isolated on a solid white background, digital clean vectors, game art.",
    "is_team_specific": True
  }
]

async def main():
    browser = ChatGPTBrowser(cdp_url=config.CDP_URL, temp_dir=config.TEMP_DIR)
    
    logger.info("Connecting to browser...")
    await browser.start()
    
    try:
        for task in drawing_tasks:
            name = task["name"]
            
            # Check if assets already exist to skip regeneration
            if task["is_team_specific"]:
                blue_path = os.path.join(MOBA_ASSETS_DIR, f"{name}_blue.png")
                red_path = os.path.join(MOBA_ASSETS_DIR, f"{name}_red.png")
                if os.path.exists(blue_path) and os.path.exists(red_path):
                    logger.info(f"Asset {name}_blue.png and {name}_red.png already exist. Skipping.")
                    continue
            else:
                final_path = os.path.join(MOBA_ASSETS_DIR, f"{name}.png")
                if os.path.exists(final_path):
                    logger.info(f"Asset {name}.png already exists. Skipping.")
                    continue

            prompt = task["prompt"]
            logger.info(f"==================================================")
            logger.info(f"Starting asset generation for: {name}")
            logger.info(f"Prompt: {prompt}")
            
            # Send prompt to ChatGPT
            res = await browser.send_message(prompt)
            
            if res.get("status") == "success" and res.get("images"):
                downloaded_path = res["images"][0]
                logger.info(f"DALL-E 3 image successfully generated: {downloaded_path}")
                
                # Base transparent output path
                temp_transparent_path = os.path.join(config.TEMP_DIR, f"{name}_transparent.png")
                make_transparent_floodfill(downloaded_path, temp_transparent_path)
                
                if task["is_team_specific"]:
                    # Create blue and red tinted versions
                    blue_out = os.path.join(MOBA_ASSETS_DIR, f"{name}_blue.png")
                    red_out = os.path.join(MOBA_ASSETS_DIR, f"{name}_red.png")
                    colorize_image(temp_transparent_path, blue_out, 'blue')
                    colorize_image(temp_transparent_path, red_out, 'red')
                else:
                    # Generic output directly to moba assets
                    final_out = os.path.join(MOBA_ASSETS_DIR, f"{name}.png")
                    # Copy or save as final
                    img = Image.open(temp_transparent_path)
                    img.save(final_out)
                    logger.info(f"Saved generic asset to {final_out}")
                
                # Clean up local temporary transparent file
                if os.path.exists(temp_transparent_path):
                    os.remove(temp_transparent_path)
                if os.path.exists(downloaded_path):
                    os.remove(downloaded_path)
            else:
                error_msg = res.get("message", "Unknown error")
                logger.error(f"Failed to generate asset {name}: {error_msg}")
                logger.info("Proceeding to next task...")
                
            # Add delay to avoid aggressive rate limit
            await asyncio.sleep(5)
            
    finally:
        await browser.stop()
        logger.info("Asset generation finished!")

if __name__ == "__main__":
    asyncio.run(main())
