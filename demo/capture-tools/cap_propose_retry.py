"""Propose retry WITH dialog acceptance on the NEW job (7e34ab30); then slow diff scroll."""
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
    pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await pg.goto("http://localhost:5173", wait_until="networkidle")
    await pg.wait_for_timeout(1500)
    await pg.locator(".avatar-btn").click()
    await pg.wait_for_timeout(800)
    await pg.locator("#demo-role").select_option("reviewer")
    await pg.wait_for_timeout(1200)
    mark("reviewer")
    await pg.get_by_role("button", name="Activity").first.click()
    await pg.wait_for_timeout(2500)
    # open the NEW job: row with 1:21 AM timestamps (backend clock) - verify by whisking note
    for i in range(8):
        try:
            await pg.locator("button", has_text="View details").nth(i).click(timeout=6000)
        except Exception:
            break
        await pg.wait_for_timeout(2000)
        body = await pg.evaluate("document.body.innerText.slice(0,1500)")
        if "1:21:44 AM" in body and "Whisking in the video is brief" in body:
            print("NEW JOB at index", i)
            break
        try:
            await pg.get_by_role("button", name="Hide details").click(timeout=4000)
            await pg.wait_for_timeout(1000)
        except Exception:
            pass
    mark("job-open")
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await pg.wait_for_timeout(1500)
    await pg.screenshot(path=f"{OUT}/retry-pre.png")
    mark("pre-propose")
    await pg.wait_for_timeout(2000)
    await pg.get_by_role("button", name="Create improvement proposal").click(timeout=8000)
    await pg.wait_for_timeout(8000)
    mark("proposal")
    await pg.screenshot(path=f"{OUT}/retry-proposal.png")
    txt = await pg.evaluate("document.body.innerText.slice(0,900)")
    print("LAND:", txt[:900].replace("\n", " | ")[:700])
    # slow scroll through the diff
    for y in (500, 1100, 1700, 1100, 500):
        await pg.evaluate(f"window.scrollTo({{top:{y},behavior:'smooth'}})")
        await pg.wait_for_timeout(2000)
    mark("diff-scrolled")
    await pg.wait_for_timeout(2000)
    mark("end")

asyncio.run(main())
