"""REAL-CASE mobile: cookie procedure offline job, note+photo, finish, sync."""
import asyncio, json, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"
PHOTO = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/source-footage/whisk-frame.jpg"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

TITLE = "Chocolate chip cookie preparation"

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":390,"height":844}, is_mobile=True,
            has_touch=True, device_scale_factor=2,
            record_video_dir=OUT, record_video_size={"width":390,"height":844})
        try:
            await run(ctx)
        finally:
            await ctx.close(); await b.close()

async def card_js(action):
    # action: 'dl' or 'start'
    if action == "dl":
        return ("""var t=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/TITLEHERE \\(tutorial\\)/.test(e.textContent));
var el=t;var guard=0;while(el&&guard<14){var bs=[...el.querySelectorAll(':scope button')];if(bs.some(b=>/Start (job|additional run)|Run again/.test(b.textContent)))break;el=el.parentElement;guard++;}
var bs=[...el.querySelectorAll('button')];var i=bs.findIndex(b=>/Start (job|additional run)|Run again/.test(b.textContent));var dl=bs.slice(i).find(b=>b.textContent.trim()==='');window.__dl=!!dl;if(dl)dl.click();""".replace("TITLEHERE", TITLE))
    return ("""var t=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/TITLEHERE \\(tutorial\\)/.test(e.textContent));
var el=t;var guard=0;while(el&&guard<14){var bs=[...el.querySelectorAll(':scope button')];if(bs.some(b=>/Start (job|additional run)|Run again/.test(b.textContent)))break;el=el.parentElement;guard++;}
var b=[...el.querySelectorAll('button')].find(x=>/Start (job|additional run)|Run again/.test(x.textContent));window.__st=!!b;if(b)b.click();""".replace("TITLEHERE", TITLE))

async def run(ctx):
    pg = await ctx.new_page()
    await pg.goto("http://localhost:5173", wait_until="networkidle")
    await pg.wait_for_timeout(1500)
    try:
        await pg.locator("nav button", has_text="Procedures").first.click(timeout=5000)
    except Exception:
        await pg.get_by_role("button", name="Procedures").first.click()
    await pg.wait_for_timeout(2000)
    await pg.get_by_text(TITLE).first.scroll_into_view_if_needed()
    await pg.wait_for_timeout(1000)
    mark("card")
    await pg.wait_for_timeout(3500)
    await pg.screenshot(path=f"{OUT}/realM-card.png")
    await pg.evaluate(await card_js("dl"))
    print("DL:", await pg.evaluate("window.__dl"))
    await pg.wait_for_timeout(4000)
    mark("offline-saved")
    await pg.screenshot(path=f"{OUT}/realM-cached.png")
    await pg.evaluate(await card_js("start"))
    print("ST:", await pg.evaluate("window.__st"))
    await pg.wait_for_timeout(3000)
    mark("job-started")
    await pg.screenshot(path=f"{OUT}/realM-job.png")
    await ctx.set_offline(True)
    await pg.wait_for_timeout(2500)
    mark("airplane-on")
    await pg.screenshot(path=f"{OUT}/realM-offline.png")
    # steps 1-2 Next, step 3 handled below
    for s in (1, 2):
        await pg.locator("button", has_text="Next step").click(timeout=8000)
        await pg.wait_for_timeout(2500)
        mark(f"step{s}-done")
    await pg.screenshot(path=f"{OUT}/realM-step3.png")
    # photo on step 3
    try:
        async with pg.expect_file_chooser(timeout=8000) as fc:
            await pg.locator("button", has_text="Attach Photo").click()
        await (await fc.value).set_files(PHOTO)
        await pg.wait_for_timeout(3000)
        mark("photo-queued")
        await pg.screenshot(path=f"{OUT}/realM-photo.png")
    except Exception as e:
        print("PHOTO-FAIL", str(e)[:150])
    # field note with the real observation
    try:
        await pg.locator("button", has_text="Field Note").click(timeout=8000)
        await pg.wait_for_timeout(1500)
        await pg.locator("textarea[placeholder^='e.g. Left clip']").first.fill("Whisking in the video is brief - how do I know when the mixture is ready?")
        await pg.wait_for_timeout(800)
        await pg.locator("button", has_text="Save note").click(timeout=5000)
        await pg.wait_for_timeout(2000)
        mark("note-saved")
        await pg.screenshot(path=f"{OUT}/realM-note.png")
    except Exception as e:
        print("NOTE-FAIL", str(e)[:150])
    try:
        await pg.locator("button", has_text="Finish job").click(timeout=6000)
    except Exception:
        await pg.locator("button", has_text="Next step").click()
    await pg.wait_for_timeout(3000)
    mark("finished")
    await pg.screenshot(path=f"{OUT}/realM-finished.png")
    await ctx.set_offline(False)
    await pg.wait_for_timeout(2500)
    mark("reconnected")
    try:
        await pg.locator("nav button", has_text="Activity").first.click(timeout=5000)
    except Exception:
        await pg.get_by_role("button", name="Activity").first.click()
    await pg.wait_for_timeout(3000)
    mark("activity")
    await pg.screenshot(path=f"{OUT}/realM-activity.png")
    await pg.wait_for_timeout(4000)
    mark("session-done")

asyncio.run(main())
