import asyncio, json, re
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/captures"

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
        await pg.get_by_role("button", name="Procedures").first.click()
        await pg.wait_for_timeout(2000)
        await pg.get_by_text("Adjustment-knob check").first.scroll_into_view_if_needed()
        await pg.wait_for_timeout(800)
        # eye = 2nd empty button after first Start button
        await pg.evaluate("var bs=[...document.querySelectorAll('button')];var i=bs.findIndex(b=>/Start (job|additional run)/.test(b.textContent));var eye=bs.slice(i).filter(b=>b.textContent.trim()==='')[1];if(eye)eye.click();")
        await pg.wait_for_timeout(2500)
        txt = await pg.evaluate("document.body.innerText.slice(0,600)")
        print("DETAIL:", txt[:600].replace("\n", " | "))
        await pg.screenshot(path=f"{OUT}/d5-detail.png")
        await pg.wait_for_timeout(2500)
        # try revision history
        try:
            await pg.get_by_role("button", name=re.compile(r"revision history", re.I)).click(timeout=6000)
            await pg.wait_for_timeout(2000)
            txt2 = await pg.evaluate("document.body.innerText.slice(0,1200)")
            print("HIST:", txt2[:1200].replace("\n", " | "))
            await pg.screenshot(path=f"{OUT}/d5-history.png")
        except Exception as e:
            print("NOHIST", str(e)[:150])
        await pg.wait_for_timeout(2000)
        await ctx.close(); await b.close()

asyncio.run(main())
