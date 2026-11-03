import asyncio, json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1920,"height":1080})
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1200)
        # reject stale pendings via API-shaped UI: use Review queue
        await pg.locator(".avatar-btn").click()
        await pg.wait_for_timeout(600)
        await pg.locator("#demo-role").select_option("reviewer")
        await pg.wait_for_timeout(1000)
        import re
        await pg.get_by_role("button", name=re.compile(r"^Review")).first.click()
        await pg.wait_for_timeout(2000)
        # open v1 pending
        for ver in ["v1", "v2"]:
            try:
                await pg.evaluate("window.scrollTo(0,0)")
                await pg.wait_for_timeout(500)
                items = await pg.eval_on_selector_all("button", "els => els.map(e => (e.textContent||'').trim().slice(0,80))")
                print("QUEUE:", json.dumps([x for x in items if 'djustment' in x or 'eview draft' in x or 'eject' in x][:12]))
                await pg.screenshot(path=f"C:/Users/dougl/Documents/MetaHackaton/demo/assets/captures/cleanup-queue.png")
                break
            except Exception as e:
                print("ERR", str(e)[:150])
        await b.close()

asyncio.run(main())
