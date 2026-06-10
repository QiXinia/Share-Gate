import asyncio
from playwright.async_api import async_playwright

async def main():
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://127.0.0.1:8501")
        await page.wait_for_load_state("networkidle")
        
        style = await page.evaluate("""() => {
            const body = document.body;
            const style = window.getComputedStyle(body);
            return {
                display: style.display,
                flexDirection: style.flexDirection,
                className: body.className,
                htmlHeight: window.getComputedStyle(document.documentElement).height,
                bodyHeight: style.height
            };
        }""")
        print("Body Style:", style)
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
