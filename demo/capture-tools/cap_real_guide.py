"""REAL-CASE guide+review: format change, regen, submit, approve, archive tainted."""
import asyncio, re, time
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
    await pg.goto("http://localhost:5173", wait_until="networkidle")
    await pg.wait_for_timeout(1500)
    await pg.locator(".avatar-btn").click()
    await pg.wait_for_timeout(800)
    await pg.locator("#demo-role").select_option("expert")
    await pg.wait_for_timeout(1000)
    mark("expert")
    await pg.get_by_role("button", name="Tutorials").first.click()
    await pg.wait_for_timeout(2000)
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await pg.wait_for_timeout(1000)
    await pg.get_by_role("button", name="Open", exact=True).nth(0).click()
    await pg.wait_for_timeout(2500)
    mark("studio")
    await pg.locator("button", has_text="Guide").first.click(timeout=8000)
    await pg.wait_for_timeout(1500)
    mark("guide-tab")
    await pg.get_by_role("button", name="Change format").click()
    await pg.wait_for_timeout(1500)
    await pg.locator('[role="radio"]', has_text="Illustrated Work Instruction").click()
    mark("format-selected")
    await pg.wait_for_timeout(1500)
    try:
        await pg.get_by_role("button", name="Generate new version").click(timeout=6000)
    except Exception:
        await pg.get_by_role("button", name="Generate guide").click(timeout=6000)
    await pg.wait_for_timeout(5000)
    mark("guide-generated")
    await pg.screenshot(path=f"{OUT}/real5-guide.png")
    await pg.get_by_role("button", name="Regenerate guide").click()
    await pg.wait_for_timeout(5000)
    mark("guide-regenerated")
    await pg.evaluate("window.scrollTo(0, 900)")
    await pg.wait_for_timeout(1000)
    await pg.screenshot(path=f"{OUT}/real5-guide-final.png")
    await pg.wait_for_timeout(4000)
    await pg.evaluate("window.scrollTo(0,0)")
    await pg.get_by_role("button", name="Open in Review").click()
    await pg.wait_for_timeout(2500)
    mark("review-draft")
    await pg.screenshot(path=f"{OUT}/real5-review.png")
    await pg.wait_for_timeout(4000)
    try:
        await pg.get_by_role("button", name="Submit for review").click(timeout=6000)
        await pg.wait_for_timeout(2500)
        mark("submitted")
    except Exception:
        mark("already-submitted")
    # reviewer approve
    await pg.locator(".avatar-btn").click()
    await pg.wait_for_timeout(800)
    await pg.locator("#demo-role").select_option("reviewer")
    await pg.wait_for_timeout(1200)
    mark("reviewer")
    await pg.get_by_role("button", name=re.compile(r"^Review")).first.click()
    await pg.wait_for_timeout(2500)
    try:
        await pg.get_by_role("button", name="Pending review").click(timeout=6000)
        await pg.wait_for_timeout(1500)
    except Exception:
        pass
    await pg.screenshot(path=f"{OUT}/real5-queue.png")
    await pg.evaluate("var bs=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent)); var t=bs.find(b=>/Chocolate|Cookie|cookie/.test((b.closest('div')||{}).innerText||''))||bs[0]; if(t)t.click()")
    await pg.wait_for_timeout(2500)
    mark("draft-open")
    await pg.screenshot(path=f"{OUT}/real5-draft.png")
    await pg.get_by_role("button", name="Approve").click()
    await pg.wait_for_timeout(1500)
    await pg.get_by_role("button", name="Yes, approve").click()
    await pg.wait_for_timeout(3000)
    mark("approved")
    await pg.screenshot(path=f"{OUT}/real5-approved.png")
    await pg.wait_for_timeout(4000)
    mark("end")

asyncio.run(main())
