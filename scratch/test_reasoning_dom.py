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
        
        # Look for the last assistant turn
        last_assistant = page.locator('.agent-turn, [data-message-author-role="assistant"]').last
        if await last_assistant.count() == 0:
            print("No assistant message found on the page to analyze.")
            return
            
        # Dump the HTML of the last assistant turn
        html = await last_assistant.inner_html()
        print("--- LAST ASSISTANT TURN HTML (TRUNCATED) ---")
        print(html[:4000])
        print("---------------------------------------------")
        
        # Let's check for reasoning selectors: e.g. divs with specific classes
        # Look for elements with text "Thought" or "思考"
        thought_els = await last_assistant.locator('div').all()
        for idx, el in enumerate(thought_els):
            try:
                classes = await el.get_attribute("class") or ""
                text = await el.inner_text()
                if "thought" in classes.lower() or "思考" in text or "thought" in text.lower():
                    print(f"Candidate thought element [{idx}]: class={classes!r}, text={text[:100]!r}")
            except Exception:
                pass
                
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
