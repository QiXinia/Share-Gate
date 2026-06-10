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
        
        # Evaluate a JS snippet that scans all elements for thought-related text or classes
        results = await page.evaluate("""() => {
            const items = [];
            // Find all divs, buttons, details, summary elements
            const elements = document.querySelectorAll('div, button, details, summary, section');
            elements.forEach((el, index) => {
                const text = el.innerText || '';
                const classes = el.className || '';
                const id = el.id || '';
                const testId = el.getAttribute('data-testid') || '';
                
                const matchesText = text.includes('思考') || text.toLowerCase().includes('thought') || text.includes('thinking');
                const matchesClass = classes.toLowerCase().includes('thought') || classes.toLowerCase().includes('thinking') || classes.toLowerCase().includes('reasoning');
                const matchesTestId = testId.toLowerCase().includes('thought') || testId.toLowerCase().includes('thinking') || testId.toLowerCase().includes('reasoning');
                
                if ((matchesClass || matchesTestId || (matchesText && text.length < 150)) && items.length < 100) {
                    items.push({
                        index,
                        tag: el.tagName,
                        id,
                        classes: classes.substring(0, 100),
                        testId,
                        text: text.substring(0, 100).replace(/\\n/g, ' ')
                    });
                }
            });
            return items;
        }""")
        
        print(f"Found {len(results)} matching elements:")
        for r in results:
            print(f"Tag={r['tag']} ID={r['id']!r} TestId={r['testId']!r} Classes={r['classes']!r} Text={r['text']!r}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
