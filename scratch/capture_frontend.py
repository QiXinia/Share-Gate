import asyncio
import os
from playwright.async_api import async_playwright

async def main():
    pw = await async_playwright().start()
    try:
        # Launch a clean browser to load the frontend
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        # Set viewport to standard desktop or user-like size
        await page.set_viewport_size({"width": 1024, "height": 768})
        
        # Navigate to frontend server
        url = "http://127.0.0.1:8501"
        print(f"Navigating to {url}...")
        try:
            await page.goto(url, timeout=10000)
            await page.wait_for_load_state("networkidle")
            print("Page loaded successfully.")
        except Exception as e:
            print(f"Failed to load page: {e}")
            return
            
        # Take screenshot
        out_path = r"C:\Users\86150\.gemini\antigravity-ide\brain\88302c25-8575-4856-bb6b-f18435ba23b2\static_screenshot.png"
        await page.screenshot(path=out_path)
        print(f"Screenshot saved to {out_path}")
        
        # Click new session or send a test message if we want, but let's just see layout first
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
