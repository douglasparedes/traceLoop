import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":390,"height":844}, is_mobile=True, has_touch=True)
        pg = await ctx.new_page()
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        try:
            await pg.locator("nav button", has_text="Procedures").first.click(timeout=5000)
        except Exception:
            await pg.get_by_role("button", name="Procedures").first.click()
        await pg.wait_for_timeout(2000)
        await pg.get_by_text("Adjustment-knob check").first.click()
        await pg.wait_for_timeout(2500)
        badges = await pg.evaluate("Array.from(document.querySelectorAll('*')).filter(e=>e.children.length===0).map(e=>e.textContent.trim()).filter(t=>/APPROVED|REJECTED|DRAFT|OFFLINE|Start job|Save for offline|Update offline/i.test(t)).slice(0,20).join(' | ')")
        print("BADGES:", badges)
        await pg.screenshot(path="C:/Users/dougl/Documents/MetaHackaton/demo/assets/captures/c-titledetail.png")
        await b.close()

asyncio.run(main())
