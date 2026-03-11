import asyncio, json
from playwright.async_api import async_playwright

BASE_URL = 'https://goals.sos.ga.gov/GASOSOneStop/s/licensee-search'
OPT_SEL  = 'lightning-base-combobox-item[role="option"]'

async def run():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='chrome', headless=False,
            args=['--disable-blink-features=AutomationControlled'])
        ctx = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
            viewport={'width':1400,'height':900})
        page = await ctx.new_page()
        await page.goto(BASE_URL, wait_until='load', timeout=45000)
        await page.wait_for_timeout(3000)

        btn = page.locator('lightning-combobox >> button').nth(0)
        await btn.click()
        await page.wait_for_timeout(1500)
        await page.locator('lightning-base-combobox-item[data-value="Residential & Commercial General Contractors"]').first.click()
        await page.wait_for_timeout(2500)

        btn2 = page.locator('lightning-combobox >> button').nth(1)
        for _ in range(20):
            val = await btn2.get_attribute('aria-disabled') or ''
            if val.lower() != 'true':
                break
            await page.wait_for_timeout(500)
        await btn2.click()
        await page.wait_for_timeout(1500)
        await page.locator('lightning-base-combobox-item[data-value="Residential Basic Qualifying Agent"]').first.click()
        await page.locator('button:has-text("Search")').first.click()
        await page.wait_for_timeout(6000)
        await page.wait_for_selector('table tbody tr', timeout=15000)

        # Find all nav-related buttons
        btns = await page.evaluate('''() => {
            const result = [];
            document.querySelectorAll("button, a").forEach(b => {
                const t = (b.title || b.textContent || "").trim();
                if (t.match(/next|prev|>/i) || b.getAttribute("name") === "Next") {
                    result.push({
                        tag: b.tagName,
                        title: b.title,
                        name: b.getAttribute("name"),
                        text: b.textContent.trim().slice(0,30),
                        disabled: b.disabled,
                        ariaDisabled: b.getAttribute("aria-disabled"),
                        className: b.className.slice(0,60)
                    });
                }
            });
            return result;
        }''')
        print("Nav buttons:", json.dumps(btns, indent=2))

        # Check result count text
        count_text = await page.evaluate('''() => {
            const els = document.querySelectorAll("*");
            for (const el of els) {
                if (el.children.length === 0 && el.textContent.match(/\\d+ Result/i)) {
                    return el.textContent.trim();
                }
            }
            return "not found";
        }''')
        print("Result count text:", count_text)

        await browser.close()

asyncio.run(run())
