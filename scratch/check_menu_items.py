import asyncio
import os
import sys
from playwright.async_api import async_playwright

async def main():
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = None
        for p in context.pages:
            if "chatgpt.com" in p.url:
                page = p
                break
        
        if not page:
            print("No ChatGPT page found!")
            return
            
        print(f"Connected to page: {await page.title()}")
        
        # Click plus button to open the menu
        plus_btn = page.locator('button[data-testid="composer-plus-btn"], button[aria-label="Add files and more"]').first
        if await plus_btn.count() == 0:
            print("Composer plus button not found!")
            return
            
        await plus_btn.click()
        await asyncio.sleep(1.5)
        
        # Dump all menu items
        menu_items = await page.locator('[role="menuitem"], [role="menuitemcheckbox"], [role="menuitemradio"], button').all()
        print(f"Found {len(menu_items)} potential menu elements:")
        for idx, item in enumerate(menu_items):
            try:
                tag = await item.evaluate("el => el.tagName")
                role = await item.get_attribute("role")
                text = await item.inner_text()
                aria_checked = await item.get_attribute("aria-checked")
                data_state = await item.get_attribute("data-state")
                print(f"[{idx}] TAG={tag} ROLE={role} TEXT={text!r} CHECKED={aria_checked} STATE={data_state}")
            except Exception as e:
                pass
                
        # Close menu
        await page.keyboard.press("Escape")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
