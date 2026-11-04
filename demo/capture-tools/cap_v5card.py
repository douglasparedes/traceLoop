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
            await pg.wait_for_timeout(1000)
            mark("card")
            await pg.screenshot(path=f"{OUT}/v5card.png")
            await pg.wait_for_timeout(8000)
            mark("end")
        finally:
            await ctx.close(); await b.close()

asyncio.run(main())
