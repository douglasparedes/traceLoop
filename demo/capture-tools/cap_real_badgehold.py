import asyncio, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":1920,"height":1080},
            record_video_dir=OUT, record_video_size={"width":1920,"height":1080})
        try:
            pg = await ctx.new_page()
            await pg.goto("http://localhost:5173", wait_until="networkidle")
            await pg.wait_for_timeout(1500)
            await pg.get_by_role("button", name="Procedures").first.click()
            await pg.wait_for_timeout(2500)
            await pg.get_by_text("Chocolate chip cookie preparation").first.scroll_into_view_if_needed()
            await pg.wait_for_timeout(800)
            await pg.evaluate("""var t=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/Chocolate chip cookie preparation \\(tutorial\\)/.test(e.textContent));
var el=t;var guard=0;while(el&&guard<14){var bs=[...el.querySelectorAll(':scope button')];if(bs.some(b=>/Run again|Start job|Start additional/.test(b.textContent)))break;el=el.parentElement;guard++;}
var bs=[...el.querySelectorAll('button')];var empt=bs.filter(b=>b.textContent.trim()==='');if(empt[1])empt[1].click();""")
            await pg.wait_for_timeout(3000)
            mark("detail")
            await pg.wait_for_timeout(8000)
            mark("hold-end")
        finally:
            await ctx.close(); await b.close()

asyncio.run(main())
