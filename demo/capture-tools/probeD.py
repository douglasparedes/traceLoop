"""Session D (desktop): feedback, proposal, approve v4, pinning proof."""
import asyncio, json, re, time
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
            labels.append((await btns.nth(i).text_content() or "").strip()[:44])
        except Exception:
            labels.append("?")
    print(tag, json.dumps(labels))

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":1920,"height":1080},
            record_video_dir=OUT, record_video_size={"width":1920,"height":1080})
        pg = await ctx.new_page()
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        await pg.get_by_role("button", name="Activity").first.click()
        await pg.wait_for_timeout(2500)
        mark("activity")
        await pg.screenshot(path=f"{OUT}/d-activity.png")
        await dump(pg, "ACT:")
        # open latest finished job details
        try:
            await pg.locator("button", has_text="View details").first.click(timeout=8000)
        except Exception:
            print("no View details")
        await pg.wait_for_timeout(2500)
        mark("job-open")
        await dump(pg, "JOBD:")
        txt = await pg.evaluate("document.body.innerText.slice(0,1200)")
        print("JOBTXT:", txt[:1200])
        await pg.screenshot(path=f"{OUT}/d-job.png")
        await pg.wait_for_timeout(3000)
        await ctx.close(); await b.close()

asyncio.run(main())
