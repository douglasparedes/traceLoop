"""Archive the 4 cookie rehearsal tutorials via library Remove buttons (reversible)."""
import asyncio, time
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1920,"height":1080})
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        await pg.locator(".avatar-btn").click()
        await pg.wait_for_timeout(800)
        await pg.locator("#demo-role").select_option("reviewer")
        await pg.wait_for_timeout(1000)
        await pg.get_by_role("button", name="Tutorials").first.click()
        await pg.wait_for_timeout(2000)
        for round in range(6):
            await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await pg.wait_for_timeout(1000)
            # find a cookie row's Remove button
            found = await pg.evaluate("""var btns=[...document.querySelectorAll('button')].filter(b=>/^Remove$/.test(b.textContent.trim()));
for(var i=0;i<btns.length;i++){var r=btns[i];for(var g=0;g<8&&r;g++){r=r.parentElement;if(r&&/Chocolate chip cookie/.test(r.innerText||'')){btns[i].click();break;}} }""")
            await pg.wait_for_timeout(1500)
            # confirm dialog if any
            try:
                async with pg.expect_event("dialog", timeout=2000) as d:
                    pass
            except Exception:
                pass
            rows = await pg.evaluate("document.body.innerText")
            left = rows.count("Chocolate chip cookie preparation")
            print("round", round, "cookie mentions left:", left)
            if left == 0:
                break
            await pg.wait_for_timeout(1000)
        await b.close()

asyncio.run(main())
