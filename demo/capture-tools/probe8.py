"""Session C part 1: detail, save offline, start job, dump job UI."""
import asyncio, json, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/captures"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

async def dump(pg, tag):
    btns = pg.locator("button")
    n = await btns.count()
    labels = []
    for i in range(n):
        try:
            labels.append((await btns.nth(i).text_content() or "").strip()[:40])
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
        await pg.wait_for_timeout(800)
        mark("card")
        await pg.wait_for_timeout(3000)
        await pg.locator("button").nth(16).click()  # eye -> detail
        await pg.wait_for_timeout(2500)
        await dump(pg, "DETAIL:")
        await pg.screenshot(path=f"{OUT}/c-detail-open.png")
        mark("detail")
        await pg.wait_for_timeout(4000)
        await ctx.close(); await b.close()

asyncio.run(main())
