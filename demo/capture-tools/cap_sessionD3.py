"""Session D3 desktop reviewer: proposal via UI, approve v4, history proof."""
import asyncio, json, re, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/captures"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

async def dump(pg, tag):
    btns = pg.locator("button")
    n = await btns.count()
    labels = []
    for i in range(n):
        try:
            labels.append((await btns.nth(i).text_content() or "").strip()[:44])
        except Exception:
            labels.append("?")
    print(tag, json.dumps(labels))

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":1920,"height":1080},
            record_video_dir=OUT, record_video_size={"width":1920,"height":1080})
        pg = await ctx.new_page()
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        await pg.locator(".avatar-btn").click()
        await pg.wait_for_timeout(800)
        await pg.locator("#demo-role").select_option("reviewer")
        await pg.wait_for_timeout(1200)
        mark("reviewer")
        await pg.get_by_role("button", name="Activity").first.click()
        await pg.wait_for_timeout(2500)
        await pg.locator("button", has_text="View details").first.click(timeout=8000)
        await pg.wait_for_timeout(2500)
        mark("job-open")
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f"{OUT}/d3-before-propose.png")
        mark("pre-proposal")
        await pg.wait_for_timeout(3000)
        await pg.get_by_role("button", name="Create improvement proposal").click(timeout=8000)
        await pg.wait_for_timeout(3000)
        mark("propose-clicked")
        await pg.screenshot(path=f"{OUT}/d3-after-click.png")
        await dump(pg, "AFTERCLICK:")
        await pg.wait_for_timeout(6000)
        await pg.screenshot(path=f"{OUT}/d3-landed.png")
        await dump(pg, "LANDED:")
        url_txt = await pg.evaluate("document.body.innerText.slice(0,1500)")
        print("LANDED-TXT:", url_txt[:1500].replace("\n", " | ")[:1500])
        await pg.wait_for_timeout(3000)
        await ctx.close(); await b.close()

asyncio.run(main())
