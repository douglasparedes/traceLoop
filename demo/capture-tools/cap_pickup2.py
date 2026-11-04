"""READ-ONLY pickup: v3 diff scroll + v3 approved badge hold. No mutations."""
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
    # open the cookie v3 draft/approved: prefer row mentioning v3, else any cookie row
    await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent));
var idx=-1;for(var i=0;i<rows.length;i++){var r=rows[i].closest('div');var t=r?r.innerText:'';if(/Chocolate|Cookie|cookie/.test(t)&&/\\bv3\\b/.test(t)){idx=i;break;}}
if(idx<0){for(var i=0;i<rows.length;i++){var r=rows[i].closest('div');var t=r?r.innerText:'';if(/Chocolate|Cookie|cookie/.test(t)){idx=i;break;}}}
if(idx>=0)rows[idx].click();""")
    await pg.wait_for_timeout(3000)
    mark("v3-open")
    # slow scroll through the diff
    for y in (600, 1200, 1800, 1200, 600):
        await pg.evaluate(f"window.scrollTo({{top:{y},behavior:'smooth'}})")
        await pg.wait_for_timeout(2000)
    mark("diff-scrolled")
    await pg.screenshot(path=f"{OUT}/pick-diff.png")
    await pg.wait_for_timeout(2000)
    # procedures eye -> approved detail hold
    await pg.get_by_role("button", name="Procedures").first.click()
    await pg.wait_for_timeout(2500)
    await pg.get_by_text("Chocolate chip cookie preparation").first.scroll_into_view_if_needed()
    await pg.wait_for_timeout(800)
    await pg.evaluate("""var divs=[...document.querySelectorAll('div')].filter(d=>/Chocolate chip cookie preparation/.test(d.innerText||'')&&/APPROVED/.test(d.innerText||''));
divs.sort((a,b)=>a.innerHTML.length-b.innerHTML.length);var card=divs[0];
if(card){var eye=[...card.querySelectorAll('button')].filter(b=>b.textContent.trim()==='')[1];if(eye)eye.click();}""")
    await pg.wait_for_timeout(3000)
    mark("badge")
    await pg.screenshot(path=f"{OUT}/pick-badge.png")
    await pg.wait_for_timeout(7000)
    mark("end")

asyncio.run(main())
