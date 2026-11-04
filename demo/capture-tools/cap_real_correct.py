"""REAL-CASE correction: find clean tutorial, rewrite placeholders, delete 4th, save."""
import asyncio, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

STEPS = [
    ("Lay out the baking ingredients",
     "Arrange the sugar, flour, margarine, eggs, baking soda and chocolate chips on the work surface.",
     "All ingredients visible and within reach.", "0", "30"),
    ("Whisk the mixture in the bowl",
     "Combine the ingredients and whisk the mixture in the steel bowl until evenly mixed.",
     "Mixture looks even, with no dry pockets visible.", "55", "75"),
    ("Line the baking tray with parchment",
     "Cover the baking tray with parchment paper and smooth it flat.",
     "Tray fully lined with the paper lying flat.", "78", "89"),
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
    # discover rows: click each Open (buttons with text Open) until Content shows placeholders
    for attempt in range(8):
        opens = pg.get_by_role("button", name="Open", exact=True)
        cnt = await opens.count()
        print("OPENCOUNT:", cnt, "attempt:", attempt)
        if attempt >= cnt:
            break
        await opens.nth(attempt).click()
        await pg.wait_for_timeout(2500)
        try:
            await pg.locator("button", has_text="Content").first.click(timeout=6000)
            await pg.wait_for_timeout(1500)
        except Exception:
            pass
        body = await pg.evaluate("document.body.innerText.slice(0,2000)")
        if "Observed activity segment" in body:
            print("CLEAN TUTORIAL FOUND at row", attempt)
            mark("clean-found")
            break
        await pg.screenshot(path=f"{OUT}/real4-row{attempt}.png")
        # back to library
        try:
            await pg.get_by_role("button", name="Library").click(timeout=5000)
        except Exception:
            await pg.get_by_role("button", name="Tutorials").first.click()
        await pg.wait_for_timeout(1500)
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await pg.wait_for_timeout(800)
    await pg.screenshot(path=f"{OUT}/real4-clean.png")
    # ensure Content tab
    await pg.locator("button", has_text="Content").first.click(timeout=8000)
    await pg.wait_for_timeout(1500)
    mark("content-open")
    # rewrite steps 1-3
    for i, (title, instr, exp, s0, s1) in enumerate(STEPS):
        if i > 0:
            await pg.evaluate(f"var items=[...document.querySelectorAll('button')].filter(b=>/Observed activity segment {i+1}/.test(b.textContent)); if(items[0]) items[0].click()")
            await pg.wait_for_timeout(1200)
        await pg.locator('input[placeholder^="e.g. Power"]').nth(0).fill(title)
        await pg.locator('textarea[placeholder^="Imperative"]').nth(0).fill(instr)
        await pg.locator('input[placeholder^="What the technician"]').nth(0).fill(exp)
        mark(f"step{i+1}-fixed")
        await pg.wait_for_timeout(1200)
    await pg.screenshot(path=f"{OUT}/real4-steps.png")
    # delete step 4
    await pg.evaluate("var items=[...document.querySelectorAll('button')].filter(b=>/Observed activity segment 4/.test(b.textContent)); if(items[0]) items[0].click()")
    await pg.wait_for_timeout(1500)
    pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await pg.get_by_role("button", name="Delete", exact=True).click()
    await pg.wait_for_timeout(2500)
    mark("step4-deleted")
    await pg.screenshot(path=f"{OUT}/real4-deleted.png")
    await pg.get_by_role("button", name="Save steps").click()
    await pg.wait_for_timeout(3000)
    mark("steps-saved")
    await pg.screenshot(path=f"{OUT}/real4-saved.png")
    await pg.wait_for_timeout(2000)
    mark("end")

asyncio.run(main())
