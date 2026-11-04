"""Hunt the v5 draft (contains 'Mixture is ready'): open each draft row, screenshot, report."""
import asyncio
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots"

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1920,"height":1080})
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        await pg.locator(".avatar-btn").click()
        await pg.wait_for_timeout(800)
        await pg.locator("#demo-role").select_option("reviewer")
        await pg.wait_for_timeout(1200)
        import re
        await pg.get_by_role("button", name=re.compile(r"^Review")).first.click()
        await pg.wait_for_timeout(2500)
        try:
            await pg.get_by_role("button", name="Drafts in progress").click(timeout=6000)
            await pg.wait_for_timeout(1500)
        except Exception:
            pass
        n = await pg.locator("button", has_text="Review draft").count()
        print("DRAFT ROWS:", n)
        await b.close()

asyncio.run(main())
