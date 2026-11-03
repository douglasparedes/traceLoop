"""Upload-only re-capture (new bytes -> full pipeline). Stops at processing done."""
import asyncio, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"
CLIP = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/source-footage/trainer-clip-20s-b.mp4"
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
    await pg.wait_for_timeout(1500)
    mark("recorder")
    await pg.wait_for_timeout(5000)
    await pg.get_by_role("button", name="Upload existing video").click()
    await pg.wait_for_timeout(1000)
    await pg.locator('input[type="file"]').set_input_files(CLIP)
    await pg.wait_for_timeout(1200)
    await pg.locator("#up-title").fill("Adjustment-knob check")
    await pg.locator("#up-equip").fill("Benchtop Cable Trainer BCT-1")
    await pg.locator("#up-task").fill("This is the adjustment knob. First, check the position. Then turn the knob until the indicator lines up.")
    mark("form")
    await pg.wait_for_timeout(3000)
    mark("upload-start")
    await pg.get_by_role("button", name="Upload & generate guide").click()
    await pg.get_by_role("button", name="Open in Tutorial Studio").wait_for(timeout=300000)
    mark("processing-done")
    await pg.wait_for_timeout(4000)
    mark("session-done")

asyncio.run(main())
