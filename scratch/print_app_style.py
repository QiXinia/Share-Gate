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
            const app = document.querySelector('#app');
            const style = window.getComputedStyle(app);
            return {
                id: app.id,
                display: style.display,
                flexDirection: style.flexDirection,
                className: app.className,
                offsetHeight: app.offsetHeight,
                offsetWidth: app.offsetWidth
            };
        }""")
        print("App Div Style:", style)
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
