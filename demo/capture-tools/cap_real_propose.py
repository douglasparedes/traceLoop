"""REAL-CASE proposal only (feedback already recorded): reviewer opens cookie job, proposes."""
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
    await pg.evaluate("""var btns=[...document.querySelectorAll('button')].filter(b=>/^View details$/.test(b.textContent.trim()));
window.__rows=btns.map(b=>{var el=b;for(var g=0;g<6&&el;g++){el=el.parentElement;if(el&&el.innerText&&el.innerText.length<600)break;}return (el?el.innerText:'').slice(0,160).replace(/\\n/g,' | ');});""")
    rows = await pg.evaluate("window.__rows")
    print("ROWS:", rows)
    idx = next((i for i, t in enumerate(rows or []) if "Chocolate chip cookie" in (t or "")), 0)
    print("OPEN IDX:", idx)
    await pg.evaluate(f"var btns=[...document.querySelectorAll('button')].filter(b=>/^View details$/.test(b.textContent.trim())); if(btns[{idx}]) btns[{idx}].click()")
    mark("job-open")
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await pg.wait_for_timeout(1500)
    await pg.screenshot(path=f"{OUT}/realF2-pre.png")
    mark("pre-proposal")
    await pg.wait_for_timeout(2500)
    await pg.get_by_role("button", name="Create improvement proposal").click(timeout=8000)
    await pg.wait_for_timeout(8000)
    mark("proposal")
    await pg.screenshot(path=f"{OUT}/realF2-proposal.png")
    txt = await pg.evaluate("document.body.innerText.slice(0,1500)")
    import sys
    sys.stdout.buffer.write(("PROP: " + txt[:1200].replace("\n", " | ")).encode("utf-8", "replace"))
    print()
    await pg.wait_for_timeout(3000)
    mark("end")

asyncio.run(main())
