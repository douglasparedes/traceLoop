"""LIVE-evidence probe: upload -visual clip, visual-first, force_new; dump stages+content."""
import asyncio, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"
CLIP = "C:/Users/dougl/Documents/MetaHackaton/demo/demostration-visual.mp4"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":1920,"height":1080})
        try:
            pg = await ctx.new_page()
            await pg.goto("http://localhost:5173", wait_until="networkidle")
            await pg.wait_for_timeout(1500)
            await pg.get_by_role("button", name="Tutorials").first.click()
            await pg.wait_for_timeout(1500)
            try:
                await pg.locator("button", has_text="Visual-First").first.click(timeout=5000)
                mark("vf-mode")
            except Exception as e:
                print("MODE-FAIL", str(e)[:120])
            await pg.get_by_role("button", name="Upload existing video").click()
            await pg.wait_for_timeout(1000)
            await pg.locator('input[type="file"]').set_input_files(CLIP)
            await pg.wait_for_timeout(1200)
            await pg.locator("#up-title").fill("LIVE probe cookie")
            await pg.locator("#up-equip").fill("Home kitchen")
            await pg.locator("#up-task").fill("Live pipeline check.")
            mark("form")
            await pg.wait_for_timeout(2000)
            await pg.get_by_role("button", name="Upload & generate guide").click()
            try:
                await pg.get_by_role("button", name="Upload as new instead").wait_for(timeout=20000)
                mark("dedupe")
                await pg.get_by_role("button", name="Upload as new instead").click()
            except Exception:
                print("no dedupe notice")
            await pg.get_by_role("button", name="Open in Tutorial Studio").wait_for(timeout=600000)
            mark("done-processing")
            await pg.wait_for_timeout(2500)
            await pg.get_by_role("button", name="Open in Tutorial Studio").click()
            await pg.wait_for_timeout(3000)
            mark("studio")
            await pg.evaluate("window.scrollTo(0, 900)")
            await pg.wait_for_timeout(1200)
            await pg.screenshot(path=f"{OUT}/live-overview.png")
            txt = await pg.evaluate("document.body.innerText.slice(0,2500)")
            import sys
            sys.stdout.buffer.write(("STAGES: " + txt[:2000].replace("\n", " | ")).encode("utf-8", "replace"))
            print()
            await pg.locator("button", has_text="Content").first.click(timeout=8000)
            await pg.wait_for_timeout(2000)
            await pg.screenshot(path=f"{OUT}/live-content.png")
            txt2 = await pg.evaluate("document.body.innerText.slice(0,2000)")
            sys.stdout.buffer.write(("CONTENT: " + txt2[:1500].replace("\n", " | ")).encode("utf-8", "replace"))
            print()
            mark("end")
        finally:
            await ctx.close(); await b.close()

asyncio.run(main())
