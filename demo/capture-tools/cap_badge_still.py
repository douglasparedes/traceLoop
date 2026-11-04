import asyncio
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"
JS_OPEN_APPROVED_CARD = """var divs=[...document.querySelectorAll('div')].filter(function(d){return /Chocolate chip cookie preparation/.test(d.innerText||'') && /APPROVED/.test(d.innerText||'');});
divs.sort(function(a,b){return a.innerHTML.length-b.innerHTML.length;});
var card=divs[0];
if(card){var eye=[...card.querySelectorAll('button')].filter(function(b){return b.textContent.trim()==='';})[1];if(eye){eye.click();}}"""

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1920,"height":1080})
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        await pg.locator(".avatar-btn").click()
        await pg.wait_for_timeout(800)
        await pg.locator("#demo-role").select_option("reviewer")
        await pg.wait_for_timeout(1200)
        await pg.get_by_role("button", name="Procedures").first.click()
        await pg.wait_for_timeout(2500)
        await pg.get_by_text("Chocolate chip cookie preparation").first.scroll_into_view_if_needed()
        await pg.wait_for_timeout(800)
        await pg.evaluate(JS_OPEN_APPROVED_CARD)
        await pg.wait_for_timeout(3000)
        await pg.screenshot(path=f"{OUT}/badge-v2.png")
        print("shot ok")
        await b.close()

asyncio.run(main())
