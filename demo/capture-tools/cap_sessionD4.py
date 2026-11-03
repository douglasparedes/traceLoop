"""Session D4 desktop reviewer: approve v5, history pinning proof."""
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
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        await pg.locator(".avatar-btn").click()
        await pg.wait_for_timeout(800)
        await pg.locator("#demo-role").select_option("reviewer")
        await pg.wait_for_timeout(1200)
        mark("reviewer")
        await pg.get_by_role("button", name=re.compile(r"^Review")).first.click()
        await pg.wait_for_timeout(2500)
        mark("review-queue")
        await pg.screenshot(path=f"{OUT}/d4-queue.png")
        await pg.wait_for_timeout(2500)
        try:
            await pg.get_by_role("button", name="Drafts in progress").click(timeout=6000)
            await pg.wait_for_timeout(1500)
        except Exception:
            print("no drafts tab")
        await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent));
var scored=rows.map(b=>{var r=b.closest('div');var t=r?r.innerText:'';return t.slice(0,120)});
window.__draftrows=scored;""")
        rows = await pg.evaluate("window.__draftrows")
        print("DRAFTS:", json.dumps(rows))
        idx = 0
        for i, t in enumerate(rows or []):
            if "v5" in t or "feedback" in t.lower() or "proposal" in t.lower():
                idx = i
                break
        print("OPEN IDX:", idx)
        await pg.evaluate(f"var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent)); if(rows[{idx}]) rows[{idx}].click()")
        await pg.wait_for_timeout(2500)
        mark("v5-open")
        await pg.screenshot(path=f"{OUT}/d4-v5.png")
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f"{OUT}/d4-v5-diff.png")
        await pg.wait_for_timeout(3000)
        await pg.get_by_role("button", name="Submit for review").click()
        await pg.wait_for_timeout(2500)
        mark("v5-submitted")
        await pg.screenshot(path=f"{OUT}/d4-v5-submitted.png")
        await pg.get_by_role("button", name="Approve").click()
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f"{OUT}/d4-confirm.png")
        await pg.get_by_role("button", name="Yes, approve").click()
        await pg.wait_for_timeout(3000)
        mark("approved-v5")
        await pg.screenshot(path=f"{OUT}/d4-approved.png")
        await dump(pg, "APPROVED:")
        await pg.wait_for_timeout(5000)
        # procedures history proof
        await pg.get_by_role("button", name="Procedures").first.click()
        await pg.wait_for_timeout(2000)
        await pg.evaluate("var bs=[...document.querySelectorAll('button')].filter(b=>/Review draft|View revision|history/i.test(b.textContent));")
        await pg.screenshot(path=f"{OUT}/d4-procedures.png")
        mark("procedures")
        await pg.wait_for_timeout(4000)
        await ctx.close(); await b.close()

asyncio.run(main())
