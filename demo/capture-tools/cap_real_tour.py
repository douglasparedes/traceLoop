"""REAL-CASE read-only studio tour for S3 (no mutations)."""
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
    await pg.get_by_role("button", name="Tutorials").first.click()
    await pg.wait_for_timeout(2000)
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await pg.wait_for_timeout(1000)
    await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/^Open$/.test(b.textContent.trim()));
var idx=0;for(var i=0;i<rows.length;i++){var r=rows[i].closest('div');var t=r?r.innerText:'';if(/visual-first|Cacao|Chocolate|Cookie|cookie|Home kitchen/.test(t)){idx=i;break;}}rows[idx].click();""")
    await pg.wait_for_timeout(3000)
    mark("studio")
    # slow scroll through overview: details -> source video -> processing -> stages
    for y in (400, 900, 1400, 1900):
        await pg.evaluate(f"window.scrollTo({{top:{y},behavior:'smooth'}})")
        await pg.wait_for_timeout(2200)
    mark("overview-tour")
    await pg.wait_for_timeout(3000)
    # keyframes strip if present (Visuals tab is read-only viewing)
    await pg.locator("button", has_text="Visuals").first.click(timeout=8000)
    await pg.wait_for_timeout(2500)
    mark("visuals")
    await pg.screenshot(path=f"{OUT}/realT-visuals.png")
    await pg.wait_for_timeout(5000)
    await pg.locator("button", has_text="Content").first.click(timeout=8000)
    await pg.wait_for_timeout(2000)
    mark("content-top")
    await pg.wait_for_timeout(5000)
    mark("end")

asyncio.run(main())
