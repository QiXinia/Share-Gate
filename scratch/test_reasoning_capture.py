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
        
        # Locate prompt textarea
        textarea = page.locator("#prompt-textarea")
        if await textarea.count() == 0:
            print("Prompt textarea not found!")
            return
            
        # Clear and fill prompt
        await textarea.click()
        await textarea.fill("用简短的一句话回答：什么是量子力学？")
        
        # Open plus menu and enable Thinking
        plus_btn = page.locator('button[data-testid="composer-plus-btn"], button[aria-label="Add files and more"]').first
        await plus_btn.click()
        await asyncio.sleep(1.0)
        
        menu_items = await page.locator('[role="menuitemradio"]').all()
        thinking_item = None
        for item in menu_items:
            text = await item.inner_text()
            if "thinking" in text.lower() or "思考" in text:
                thinking_item = item
                break
                
        if thinking_item:
            aria_checked = await thinking_item.get_attribute("aria-checked")
            data_state = await thinking_item.get_attribute("data-state")
            is_checked = (aria_checked == "true") or (data_state == "checked")
            print(f"Thinking menu item current state: checked={is_checked}")
            if not is_checked:
                print("Toggling Thinking mode to ON...")
                await thinking_item.click()
                await asyncio.sleep(1.0)
            else:
                print("Thinking is already ON. Closing menu...")
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
        else:
            print("Thinking menu item not found!")
            await page.keyboard.press("Escape")
            
        # Click send button
        send_btn = page.locator('button[data-testid="send-button"]')
        await send_btn.click()
        print("Sent prompt! Waiting for response...")
        
        # Wait for stop-button to disappear
        stop_btn = page.locator('button[data-testid="stop-button"]')
        await asyncio.sleep(3) # Initial wait
        
        while await stop_btn.is_visible():
            await asyncio.sleep(1)
            
        print("Response finished streaming. Waiting 2s for page to settle...")
        await asyncio.sleep(2)
        
        # Capture assistant turn elements
        last_assistant = page.locator('.agent-turn, [data-message-author-role="assistant"]').last
        
        # Dump HTML to inspect
        html = await last_assistant.inner_html()
        out_file = r"C:\Users\86150\.gemini\antigravity-ide\brain\88302c25-8575-4856-bb6b-f18435ba23b2\assistant_html.txt"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Assistant turn HTML written to {out_file}")
        
        # Dump markdown content
        markdown_el = last_assistant.locator('.markdown').first
        if await markdown_el.count() > 0:
            print(f"Markdown Inner Text:\n{await markdown_el.inner_text()}")
        else:
            print("No .markdown element found!")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
