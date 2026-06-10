import asyncio
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
        
        # Ensure we are in a fresh prompt state or text area is visible
        textarea = page.locator("#prompt-textarea")
        await textarea.click()
        await textarea.fill("请用深度思考回答：12345 乘以 54321 等于多少？写出详细步骤。")
        
        # Enable Thinking
        plus_btn = page.locator('button[data-testid="composer-plus-btn"], button[aria-label="Add files and more"]').first
        await plus_btn.click()
        await asyncio.sleep(1.0)
        
        menu_items = await page.locator('[role="menuitemradio"]').all()
        for item in menu_items:
            text = await item.inner_text()
            if "thinking" in text.lower() or "思考" in text:
                aria_checked = await item.get_attribute("aria-checked")
                if aria_checked != "true":
                    await item.click()
                    await asyncio.sleep(1.0)
                else:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.5)
                break
        
        # Send
        send_btn = page.locator('button[data-testid="send-button"]')
        await send_btn.click()
        print("Sent! Waiting for streaming to finish...")
        
        stop_btn = page.locator('button[data-testid="stop-button"]')
        await asyncio.sleep(5)
        while await stop_btn.is_visible():
            await asyncio.sleep(1)
            
        print("Settle 3s...")
        await asyncio.sleep(3)
        
        last_assistant = page.locator('.agent-turn, [data-message-author-role="assistant"]').last
        
        # Check all child element tags and class names
        elements = await last_assistant.evaluate("""(turn) => {
            const results = [];
            const walk = (el, depth) => {
                results.push({
                    tag: el.tagName,
                    classes: el.className,
                    text: el.innerText ? el.innerText.substring(0, 50).replace(/\\n/g, ' ') : '',
                    depth
                });
                Array.from(el.children).forEach(child => walk(child, depth + 1));
            };
            walk(turn, 0);
            return results;
        }""")
        
        print(f"Found {len(elements)} nodes in assistant turn:")
        for idx, el in enumerate(elements[:60]):
            indent = "  " * el['depth']
            print(f"[{idx}] {indent}TAG={el['tag']} CLASS={el['classes']!r} TEXT={el['text']!r}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
