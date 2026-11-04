"""REAL-CASE feedback loop: cookie job feedback, proposal, approve v2."""
import asyncio, json, re, time
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
    await pg.get_by_role("button", name="Activity").first.click()
    await pg.wait_for_timeout(2500)
    mark("activity")
    # open View details until the cookie job is open (check title)
    for i in range(6):
        await pg.locator("button", has_text="View details").nth(i).click(timeout=8000)
        await pg.wait_for_timeout(2000)
        body = await pg.evaluate("document.body.innerText.slice(0,800)")
        if "Chocolate chip cookie" in body or "cookie" in body.lower():
            print("COOKIE JOB at index", i)
            break
        try:
            await pg.get_by_role("button", name="Hide details").click(timeout=4000)
            await pg.wait_for_timeout(1000)
        except Exception:
            pass
    mark("job-open")
    await pg.screenshot(path=f"{OUT}/realF-job.png")
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await pg.wait_for_timeout(1200)
    # step 2 confusing
    try:
        await pg.locator("button", has_text="confusing").nth(1).click(timeout=8000)
        mark("step2-confusing")
    except Exception as e:
        print("CONF-FAIL", str(e)[:150])
    await pg.wait_for_timeout(1000)
    # visuals question -> No
    try:
        await pg.get_by_role("button", name="No", exact=True).click(timeout=5000)
    except Exception as e:
        print("NO-FAIL", str(e)[:120])
    # overall notes
    try:
        tas = await pg.eval_on_selector_all("textarea", "els => els.map(e => (e.placeholder||'').slice(0,50))")
        print("TAS:", json.dumps(tas))
        for i, ph in enumerate(tas):
            if "again as written" in ph or "Overall" in ph:
                await pg.locator("textarea").nth(i).fill("Whisking in the video is brief - how do I know when the mixture is ready?")
                print("FILLED overall", i)
                break
    except Exception as e:
        print("FILL-FAIL", str(e)[:150])
    await pg.wait_for_timeout(1000)
    await pg.screenshot(path=f"{OUT}/realF-filled.png")
    mark("feedback-filled")
    await pg.wait_for_timeout(2000)
    await pg.get_by_role("button", name="Submit feedback").click()
    await pg.wait_for_timeout(3000)
    mark("feedback-submitted")
    await pg.screenshot(path=f"{OUT}/realF-submitted.png")
    # reviewer + proposal
    await pg.locator(".avatar-btn").click()
    await pg.wait_for_timeout(800)
    await pg.locator("#demo-role").select_option("reviewer")
    await pg.wait_for_timeout(1200)
    mark("reviewer")
    await pg.get_by_role("button", name="Activity").first.click()
    await pg.wait_for_timeout(2500)
    for i in range(6):
        await pg.locator("button", has_text="View details").nth(i).click(timeout=8000)
        await pg.wait_for_timeout(2000)
        body = await pg.evaluate("document.body.innerText.slice(0,800)")
        if "Chocolate chip cookie" in body:
            print("COOKIE JOB again at index", i)
            break
        try:
            await pg.get_by_role("button", name="Hide details").click(timeout=4000)
            await pg.wait_for_timeout(1000)
        except Exception:
            pass
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await pg.wait_for_timeout(1000)
    await pg.screenshot(path=f"{OUT}/realF-pre-propose.png")
    await pg.get_by_role("button", name="Create improvement proposal").click(timeout=8000)
    await pg.wait_for_timeout(8000)
    mark("proposal")
    await pg.screenshot(path=f"{OUT}/realF-proposal.png")
    txt = await pg.evaluate("document.body.innerText.slice(0,1800)")
    print("PROP:", txt[:1800].replace("\n", " | ")[:1500])
    await pg.wait_for_timeout(3000)
    mark("end")

asyncio.run(main())
