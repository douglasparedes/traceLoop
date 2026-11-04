"""REAL-CASE re-upload: visual-first + force_new (fresh honest pipeline)."""
import asyncio, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"
CLIP = "C:/Users/dougl/Documents/MetaHackaton/demo/demostration.mp4"
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
    mark("tutorials")
    await pg.wait_for_timeout(3000)
    await pg.get_by_role("button", name="Upload existing video").click()
    await pg.wait_for_timeout(1000)
    # visual-first mode first
    try:
        await pg.locator("button", has_text="Visual-First").first.click(timeout=5000)
        mark("visual-first-mode")
    except Exception as e:
        print("MODE-FAIL", str(e)[:150])
    await pg.wait_for_timeout(1000)
    await pg.locator('input[type="file"]').set_input_files(CLIP)
    await pg.wait_for_timeout(1200)
    await pg.locator("#up-title").fill("Chocolate chip cookie preparation")
    await pg.locator("#up-equip").fill("Home kitchen")
    await pg.locator("#up-task").fill("Home baking: lay out cookie ingredients, whisk the mixture in a bowl, and line a baking tray with parchment.")
    mark("form")
    await pg.wait_for_timeout(2500)
    await pg.get_by_role("button", name="Upload & generate guide").click()
    # dedupe -> Upload as new instead
    try:
        await pg.get_by_role("button", name="Upload as new instead").wait_for(timeout=15000)
        mark("dedupe-notice")
        await pg.screenshot(path=f"{OUT}/real2-dedupe.png")
        await pg.get_by_role("button", name="Upload as new instead").click()
    except Exception:
        print("no dedupe notice (fresh upload)")
    await pg.get_by_role("button", name="Open in Tutorial Studio").wait_for(timeout=300000)
    mark("processing-done")
    await pg.wait_for_timeout(2500)
    await pg.get_by_role("button", name="Open in Tutorial Studio").click()
    await pg.wait_for_timeout(2500)
    mark("studio")
    await pg.screenshot(path=f"{OUT}/real2-overview.png")
    await pg.wait_for_timeout(5000)
    await pg.locator("button", has_text="Content").first.click(timeout=8000)
    await pg.wait_for_timeout(2000)
    mark("content")
    await pg.screenshot(path=f"{OUT}/real2-content.png")
    txt = await pg.evaluate("document.body.innerText.slice(0,1200)")
    print("CONTENT-HEAD:", txt[:1200].replace("\n", " | "))
    await pg.wait_for_timeout(4000)
    mark("done")

asyncio.run(main())
