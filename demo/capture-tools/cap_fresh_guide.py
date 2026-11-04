"""FRESH guide session: work-instruction format + generate + scroll (may fork draft; disclosed)."""
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
    await pg.get_by_role("button", name="Open", exact=True).first.click()
    await pg.wait_for_timeout(3000)
    mark("studio")
    await pg.locator("button", has_text="Guide").first.click(timeout=8000)
    await pg.wait_for_timeout(2000)
    mark("guide-tab")
    await pg.wait_for_timeout(3000)
    await pg.get_by_role("button", name="Change format").click()
    await pg.wait_for_timeout(1500)
    await pg.locator('[role="radio"]', has_text="Illustrated Work Instruction").click()
    mark("format-selected")
    await pg.wait_for_timeout(1500)
    try:
        await pg.get_by_role("button", name="Generate new version").click(timeout=6000)
    except Exception:
        await pg.get_by_role("button", name="Generate guide").click(timeout=6000)
    await pg.wait_for_timeout(8000)
    mark("generated")
    await pg.evaluate("window.scrollTo(0, 900)")
    await pg.wait_for_timeout(1000)
    await pg.screenshot(path=f"{OUT}/freshG-guide.png")
    await pg.wait_for_timeout(6000)
    mark("end")

asyncio.run(main())
