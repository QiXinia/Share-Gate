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
        
        # Get bounding box of aside and main
        aside = page.locator("aside").first
        main_el = page.locator("main").first
        
        aside_box = await aside.bounding_box()
        main_box = await main_el.bounding_box()
        
        print(f"Aside Bounding Box: {aside_box}")
        print(f"Main Bounding Box: {main_box}")
        
        # Also print body HTML elements list
        body_children = await page.evaluate("""() => {
            return Array.from(document.body.children).map(el => ({
                tag: el.tagName,
                id: el.id,
                className: el.className,
                offsetHeight: el.offsetHeight,
                offsetTop: el.offsetTop
            }));
        }""")
        print("Body Children:")
        for c in body_children:
            print(c)
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
