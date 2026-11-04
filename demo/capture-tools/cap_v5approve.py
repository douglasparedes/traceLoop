"""Approve v5 (genuine completion): submit if needed, approve, badge hold."""
import asyncio, re, time
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
    await pg.locator("#demo-role").select_option("reviewer")
    await pg.wait_for_timeout(1200)
    mark("reviewer")
    await pg.get_by_role("button", name=re.compile(r"^Review")).first.click()
    await pg.wait_for_timeout(2500)
    await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent));
var idx=-1;for(var i=0;i<rows.length;i++){var r=rows[i].closest('div');var t=r?r.innerText:'';if(/Chocolate|Cookie|cookie/.test(t)&&/\\bv5\\b/.test(t)){idx=i;break;}}
if(idx>=0)rows[idx].click();""")
    await pg.wait_for_timeout(3000)
    mark("v5-open")
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await pg.wait_for_timeout(1500)
    try:
        await pg.get_by_role("button", name="Submit for review").click(timeout=6000)
        await pg.wait_for_timeout(2500)
        mark("submitted")
    except Exception:
        mark("already-submitted")
    await pg.get_by_role("button", name="Approve").click(timeout=8000)
    await pg.wait_for_timeout(1500)
    mark("approve-click")
    await pg.screenshot(path=f"{OUT}/v5a-confirm.png")
    await pg.get_by_role("button", name="Yes, approve").click()
    await pg.wait_for_timeout(4000)
    mark("approved-v5")
    await pg.screenshot(path=f"{OUT}/v5a-approved.png")
    await pg.wait_for_timeout(5000)
    mark("end")

asyncio.run(main())
