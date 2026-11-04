"""REAL-CASE pickup shots: guide format-switch+regen, approved-v2 badge hold, procedures card."""
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
    await pg.wait_for_timeout(3000)
    mark("studio")
    await pg.locator("button", has_text="Guide").first.click(timeout=8000)
    await pg.wait_for_timeout(2000)
    mark("guide-tab")
    await pg.wait_for_timeout(3000)
    await pg.get_by_role("button", name="Change format").click()
    await pg.wait_for_timeout(1500)
    await pg.locator('[role="radio"]', has_text="Reference Manual").click()
    mark("format-manual")
    await pg.wait_for_timeout(1500)
    try:
        await pg.get_by_role("button", name="Generate new version").click(timeout=6000)
    except Exception:
        await pg.get_by_role("button", name="Generate guide").click(timeout=6000)
    await pg.wait_for_timeout(6000)
    mark("manual-generated")
    await pg.evaluate("window.scrollTo(0, 900)")
    await pg.wait_for_timeout(1000)
    await pg.screenshot(path=f"{OUT}/realP-manual.png")
    await pg.wait_for_timeout(5000)
    # approved v2 badge hold via procedures eye
    await pg.get_by_role("button", name="Procedures").first.click()
    await pg.wait_for_timeout(2500)
    await pg.get_by_text("Chocolate chip cookie preparation").first.scroll_into_view_if_needed()
    await pg.wait_for_timeout(800)
    await pg.evaluate("""var t=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/Chocolate chip cookie preparation \\(tutorial\\)/.test(e.textContent));
var el=t;var guard=0;while(el&&guard<14){var bs=[...el.querySelectorAll(':scope button')];if(bs.some(b=>/Run again|Start job|Start additional/.test(b.textContent)))break;el=el.parentElement;guard++;}
var bs=[...el.querySelectorAll('button')];var empt=bs.filter(b=>b.textContent.trim()==='');if(empt[1])empt[1].click();""")
    await pg.wait_for_timeout(3000)
    mark("v2-detail")
    await pg.screenshot(path=f"{OUT}/realP-v2.png")
    await pg.wait_for_timeout(7000)
    mark("end")

asyncio.run(main())
