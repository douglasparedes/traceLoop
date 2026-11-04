"""LIVE-CASE authoring: rewrite untitled + add 2 true steps, save, guide, review, approve."""
import asyncio, re, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

STEPS = [
    ("Lay out the baking ingredients",
     "Arrange the sugar, flour, margarine, eggs, baking soda and chocolate chips on the work surface.",
     "All ingredients visible and within reach."),
    ("Whisk the mixture in the bowl",
     "Combine the ingredients and whisk the mixture in the steel bowl until evenly mixed.",
     "Mixture looks even, with no dry pockets visible."),
    ("Line the baking tray with parchment",
     "Cover the baking tray with parchment paper and smooth it flat.",
     "Tray fully lined with the paper lying flat."),
]

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
    await pg.get_by_role("button", name="Open", exact=True).first.click()
    await pg.wait_for_timeout(3000)
    mark("studio")
    await pg.locator("button", has_text="Content").first.click(timeout=8000)
    await pg.wait_for_timeout(2000)
    mark("content-empty")
    await pg.wait_for_timeout(4000)
    # rewrite step 1 in place
    await pg.locator('input[placeholder^="e.g. Power"]').nth(0).fill(STEPS[0][0])
    await pg.locator('textarea[placeholder^="Imperative"]').nth(0).fill(STEPS[0][1])
    await pg.locator('input[placeholder^="What the technician"]').nth(0).fill(STEPS[0][2])
    mark("step1-authored")
    await pg.wait_for_timeout(1500)
    # add steps 2-3 via Add step (fills the new last editor)
    for i in (1, 2):
        await pg.get_by_role("button", name="Add step").click()
        await pg.wait_for_timeout(1500)
        n = await pg.locator('input[placeholder^="e.g. Power"]').count()
        await pg.locator('input[placeholder^="e.g. Power"]').nth(n-1).fill(STEPS[i][0])
        m = await pg.locator('textarea[placeholder^="Imperative"]').count()
        await pg.locator('textarea[placeholder^="Imperative"]').nth(m-1).fill(STEPS[i][1])
        k = await pg.locator('input[placeholder^="What the technician"]').count()
        await pg.locator('input[placeholder^="What the technician"]').nth(k-1).fill(STEPS[i][2])
        mark(f"step{i+1}-authored")
        await pg.wait_for_timeout(1500)
    await pg.screenshot(path=f"{OUT}/liveA-steps.png")
    await pg.get_by_role("button", name="Save steps").click()
    await pg.wait_for_timeout(3500)
    mark("steps-saved")
    await pg.screenshot(path=f"{OUT}/liveA-saved.png")
    # guide: work instruction + generate
    await pg.evaluate("window.scrollTo(0,0)")
    await pg.locator("button", has_text="Guide").first.click(timeout=8000)
    await pg.wait_for_timeout(2000)
    try:
        await pg.get_by_role("button", name="Change format").click(timeout=6000)
        await pg.wait_for_timeout(1500)
        await pg.locator('[role="radio"]', has_text="Illustrated Work Instruction").click()
        mark("format-selected")
        await pg.wait_for_timeout(1500)
        try:
            await pg.get_by_role("button", name="Generate new version").click(timeout=6000)
        except Exception:
            await pg.get_by_role("button", name="Generate guide").click(timeout=6000)
        await pg.wait_for_timeout(6000)
        mark("guide-generated")
    except Exception as e:
        print("FORMAT-SKIP", str(e)[:150])
    await pg.screenshot(path=f"{OUT}/liveA-guide.png")
    await pg.get_by_role("button", name="Regenerate guide").click()
    await pg.wait_for_timeout(6000)
    mark("guide-regenerated")
    await pg.evaluate("window.scrollTo(0, 900)")
    await pg.wait_for_timeout(1000)
    await pg.screenshot(path=f"{OUT}/liveA-guide-final.png")
    await pg.wait_for_timeout(3000)
    # review submit + approve
    await pg.evaluate("window.scrollTo(0,0)")
    await pg.get_by_role("button", name="Open in Review").click()
    await pg.wait_for_timeout(3000)
    mark("review-draft")
    await pg.screenshot(path=f"{OUT}/liveA-review.png")
    await pg.wait_for_timeout(4000)
    try:
        await pg.get_by_role("button", name="Submit for review").click(timeout=6000)
        await pg.wait_for_timeout(2500)
        mark("submitted")
    except Exception:
        mark("already-submitted")
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
    await pg.evaluate("var bs=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent)); if(bs[0]) bs[0].click()")
    await pg.wait_for_timeout(2500)
    mark("draft-open")
    await pg.get_by_role("button", name="Approve").click()
    await pg.wait_for_timeout(1500)
    await pg.get_by_role("button", name="Yes, approve").click()
    await pg.wait_for_timeout(3500)
    mark("approved-v1")
    await pg.screenshot(path=f"{OUT}/liveA-approved.png")
    await pg.wait_for_timeout(4000)
    mark("end")

asyncio.run(main())
