"""FRESH tour (read-only): overview scroll, stages, visuals, content top."""
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
    await pg.get_by_role("button", name="Open", exact=True).first.click()
    await pg.wait_for_timeout(3000)
    mark("studio")
    for y in (500, 1100, 1700, 2200):
        await pg.evaluate(f"window.scrollTo({{top:{y},behavior:'smooth'}})")
        await pg.wait_for_timeout(2200)
    mark("overview")
    await pg.wait_for_timeout(2000)
    await pg.locator("button", has_text="Visuals").first.click(timeout=8000)
    await pg.wait_for_timeout(2500)
    mark("visuals")
    await pg.wait_for_timeout(5000)
    await pg.locator("button", has_text="Content").first.click(timeout=8000)
    await pg.wait_for_timeout(2000)
    mark("content")
    await pg.wait_for_timeout(5000)
    mark("end")

asyncio.run(main())
