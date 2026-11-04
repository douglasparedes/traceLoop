import asyncio
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":1920,"height":1080})
        pg = await ctx.new_page()
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        await pg.get_by_role("button", name="Procedures").first.click()
        await pg.wait_for_timeout(2000)
        await pg.get_by_text("Chocolate chip cookie preparation").first.scroll_into_view_if_needed()
        await pg.wait_for_timeout(800)
        await pg.screenshot(path=f"{OUT}/realC-lib.png")
        # eye buttons: empty-text buttons; find card-scoped via title walk
        await pg.evaluate("""var t=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/Chocolate chip cookie preparation \\(tutorial\\)/.test(e.textContent));
var el=t;var guard=0;while(el&&guard<14){var bs=[...el.querySelectorAll(':scope button')];if(bs.some(b=>/Run again|Start job|Start additional/.test(b.textContent)))break;el=el.parentElement;guard++;}
var bs=[...el.querySelectorAll('button')];var empt=bs.filter(b=>b.textContent.trim()==='');window.__n=empt.length;if(empt[1])empt[1].click();""")
        print("EYES:", await pg.evaluate("window.__n"))
        await pg.wait_for_timeout(2500)
        txt = await pg.evaluate("document.body.innerText.slice(0,700)")
        print("DETAIL:", txt[:700].replace("\n", " | "))
        await pg.screenshot(path=f"{OUT}/realC-detail.png")
        await b.close()

asyncio.run(main())
