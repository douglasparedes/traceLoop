"""Session D2 desktop: open finished job, reviewer, create proposal (no approve yet)."""
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
        await pg.locator(".avatar-btn").click()
        await pg.wait_for_timeout(800)
        await pg.locator("#demo-role").select_option("reviewer")
        await pg.wait_for_timeout(1200)
        mark("role-reviewer")
        await pg.get_by_role("button", name="Activity").first.click()
        await pg.wait_for_timeout(2500)
        await pg.locator("button", has_text="View details").first.click(timeout=8000)
        await pg.wait_for_timeout(2500)
        mark("job-open")
        await pg.screenshot(path=f"{OUT}/d2-job.png")
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await pg.wait_for_timeout(1200)
        await dump(pg, "D2BTNS:")
        await pg.screenshot(path=f"{OUT}/d2-bottom.png")
        try:
            await pg.get_by_role("button", name="Create improvement proposal").click(timeout=8000)
            await pg.wait_for_timeout(8000)
            mark("proposal-created")
            await pg.screenshot(path=f"{OUT}/d2-proposal.png")
            await dump(pg, "PROP:")
            txt = await pg.evaluate("document.body.innerText.slice(0,2500)")
            print("PROPTXT:", txt[:2500])
        except Exception as e:
            print("PROP-FAIL", str(e)[:300])
            await pg.screenshot(path=f"{OUT}/d2-proposal-fail.png")
        await pg.wait_for_timeout(4000)
        await ctx.close(); await b.close()

asyncio.run(main())
