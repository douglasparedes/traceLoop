"""Open the v5 draft (scroll queue first), slow diff scroll. Read-only."""
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
    await pg.locator("#demo-role").select_option("reviewer")
    await pg.wait_for_timeout(1200)
    mark("reviewer")
    import re
    await pg.get_by_role("button", name=re.compile(r"^Review")).first.click()
    await pg.wait_for_timeout(2500)
    try:
        await pg.get_by_role("button", name="Drafts in progress").click(timeout=6000)
        await pg.wait_for_timeout(1500)
    except Exception:
        pass
    # scroll the queue panel to reveal all rows, then pick cookie v5
    for _ in range(4):
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await pg.wait_for_timeout(800)
    await pg.evaluate("window.scrollTo(0,0)")
    await pg.wait_for_timeout(800)
    found = await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent));
var info=rows.map(b=>{var r=b.closest('div');return (r?r.innerText:'').slice(0,90).replace(/\\n/g,' ');});
var idx=-1;for(var i=0;i<info.length;i++){if(/Chocolate|Cookie|cookie/.test(info[i])&&/\\bv5\\b/.test(info[i])){idx=i;break;}}
if(idx>=0)rows[idx].scrollIntoViewIfNeeded();""")
    await pg.wait_for_timeout(1000)
    await pg.screenshot(path=f"{OUT}/v5hunt-queue.png")
    rows = await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent));
rows.map(b=>{var r=b.closest('div');return (r?r.innerText:'').slice(0,90).replace(/\\n/g,' ');})""")
    print("ROWS:", rows)
    await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent));
for(var i=0;i<rows.length;i++){var r=rows[i].closest('div');var t=r?r.innerText:'';if(/Chocolate|Cookie|cookie/.test(t)&&/\\bv5\\b/.test(t)){rows[i].click();break;}}""")
    await pg.wait_for_timeout(3000)
    mark("v5-open")
    body = await pg.evaluate("document.body.innerText.slice(0,600)")
    print("OPENED:", body[:600].replace("\n", " | ")[:400])
    for y in (500, 1100, 1700, 1100, 400):
        await pg.evaluate(f"window.scrollTo({{top:{y},behavior:'smooth'}})")
        await pg.wait_for_timeout(2200)
    mark("v5-scrolled")
    await pg.screenshot(path=f"{OUT}/v5hunt-diff.png")
    await pg.wait_for_timeout(2000)
    mark("end")

asyncio.run(main())
