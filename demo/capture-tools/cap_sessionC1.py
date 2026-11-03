"""Session C full (mobile 390x844): offline save, airplane job, evidence, sync."""
import asyncio, json, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/captures"
PHOTO = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/source-footage/trainer.png"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

async def dump(pg, tag):
    btns = pg.locator("button")
    n = await btns.count()
    labels = []
    for i in range(n):
        try:
            labels.append((await btns.nth(i).text_content() or "").strip()[:44])
        except Exception:
            labels.append("?")
    print(tag, json.dumps(labels))

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":390,"height":844}, is_mobile=True,
            has_touch=True, device_scale_factor=2,
            record_video_dir=OUT, record_video_size={"width":390,"height":844})
        pg = await ctx.new_page()
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        try:
            await pg.locator("nav button", has_text="Procedures").first.click(timeout=5000)
        except Exception:
            await pg.get_by_role("button", name="Procedures").first.click()
        await pg.wait_for_timeout(2000)
        await pg.get_by_text("Adjustment-knob check").first.scroll_into_view_if_needed()
        await pg.wait_for_timeout(1000)
        mark("card-approved")
        await pg.wait_for_timeout(4000)
        await pg.screenshot(path=f"{OUT}/c-card-before.png")
        await pg.locator("button").nth(15).click()  # download icon
        await pg.wait_for_timeout(4000)
        mark("offline-saved")
        await pg.screenshot(path=f"{OUT}/c-cached.png")
        await dump(pg, "AFTER-DL:")
        await pg.locator("button", has_text="Start job").first.click()  # our card first
        await pg.wait_for_timeout(3000)
        mark("job-started")
        await dump(pg, "JOB:")
        await pg.screenshot(path=f"{OUT}/c-job.png")
        await pg.wait_for_timeout(4000)
        await ctx.close(); await b.close()

asyncio.run(main())
