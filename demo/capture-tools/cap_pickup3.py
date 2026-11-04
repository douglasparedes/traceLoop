"""READ-ONLY: v3 proposal banner + diff scroll (approved view), then eye banner."""
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
            await run(ctx)
        finally:
            await ctx.close(); await b.close()

async def run(ctx):
    pg = await ctx.new_page()
    await pg.goto("http://localhost:5173", wait_until="networkidle")
    await pg.wait_for_timeout(1500)
    await pg.locator(".avatar-btn").click()
    await pg.wait_for_timeout(800)
    await pg.locator("#demo-role").select_option("reviewer")
    await pg.wait_for_timeout(1200)
    mark("reviewer")
    import re
    await pg.get_by_role("button", name=re.compile(r"^Review")).first.click()
    await pg.wait_for_timeout(2500)
    # open cookie v3 row
    await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent));
var idx=-1;for(var i=0;i<rows.length;i++){var r=rows[i].closest('div');var t=r?r.innerText:'';if(/Chocolate|Cookie|cookie/.test(t)&&/\\bv3\\b/.test(t)){idx=i;break;}}
if(idx>=0)rows[idx].click();""")
    await pg.wait_for_timeout(3000)
    mark("v3-open")
    for y in (500, 1100, 1700, 1100, 400):
        await pg.evaluate(f"window.scrollTo({{top:{y},behavior:'smooth'}})")
        await pg.wait_for_timeout(2000)
    mark("v3-scrolled")
    await pg.screenshot(path=f"{OUT}/pickV3-diff.png")
    await pg.wait_for_timeout(2000)
    mark("end")

asyncio.run(main())
