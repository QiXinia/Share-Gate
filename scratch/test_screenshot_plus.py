import asyncio
from playwright.async_api import async_playwright

async def main():
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_viewport_size({"width": 1024, "height": 768})
        
        await page.goto("http://127.0.0.1:8501")
        await page.wait_for_load_state("networkidle")
        
        # Click the plus button inside the input container
        plus_btn = page.locator('button[title="添加文件和更多"]').first
        print("Clicking plus button...")
        await plus_btn.click()
        await asyncio.sleep(1.0) # Wait for menu to open
        
        # Take screenshot of the opened state
        out_path = r"C:\Users\86150\.gemini\antigravity-ide\brain\88302c25-8575-4856-bb6b-f18435ba23b2\plus_menu_screenshot.png"
        await page.screenshot(path=out_path)
        print(f"Plus menu screenshot saved to {out_path}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
