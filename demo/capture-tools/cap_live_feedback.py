"""LIVE-CASE feedback+proposal on the new finished job, then approve v3."""
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
    await pg.locator("button", has_text="View details").first.click(timeout=8000)
    await pg.wait_for_timeout(2500)
    body = await pg.evaluate("document.body.innerText.slice(0,600)")
    print("JOB:", body[:400].replace("\n", " | "))
    mark("job-open")
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await pg.wait_for_timeout(1200)
    try:
        await pg.locator("button", has_text="confusing").nth(1).click(timeout=8000)
        mark("step2-confusing")
    except Exception as e:
        print("CONF-FAIL", str(e)[:150])
    await pg.wait_for_timeout(1000)
    try:
        await pg.get_by_role("button", name="No", exact=True).click(timeout=5000)
    except Exception:
        pass
    try:
        tas = await pg.eval_on_selector_all("textarea", "els => els.map(e => (e.placeholder||'').slice(0,60))")
        for i, ph in enumerate(tas):
            if "again as written" in ph:
                await pg.locator("textarea").nth(i).fill("Whisking in the video is brief - how do I know when the mixture is ready?")
                print("FILLED overall", i)
                break
    except Exception as e:
        print("FILL-FAIL", str(e)[:150])
    await pg.wait_for_timeout(1000)
    await pg.screenshot(path=f"{OUT}/liveF-filled.png")
    mark("feedback-filled")
    await pg.wait_for_timeout(1500)
    await pg.get_by_role("button", name="Submit feedback").click()
    await pg.wait_for_timeout(3000)
    mark("feedback-submitted")
    await pg.screenshot(path=f"{OUT}/liveF-submitted.png")
    await pg.locator(".avatar-btn").click()
    await pg.wait_for_timeout(800)
    await pg.locator("#demo-role").select_option("reviewer")
    await pg.wait_for_timeout(1200)
    mark("reviewer")
    await pg.get_by_role("button", name="Activity").first.click()
    await pg.wait_for_timeout(2500)
    await pg.locator("button", has_text="View details").first.click(timeout=8000)
    await pg.wait_for_timeout(2500)
    mark("job-reopen")
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await pg.wait_for_timeout(1200)
    await pg.screenshot(path=f"{OUT}/liveF-pre-propose.png")
    await pg.get_by_role("button", name="Create improvement proposal").click(timeout=8000)
    await pg.wait_for_timeout(8000)
    mark("proposal")
    await pg.screenshot(path=f"{OUT}/liveF-proposal.png")
    txt = await pg.evaluate("document.body.innerText.slice(0,1200)")
    print("PROP:", txt[:1200].replace("\n", " | ")[:1000])
    await pg.wait_for_timeout(3000)
    # approve the new draft if we landed in Review, else open it via queue
    try:
        await pg.get_by_role("button", name="Submit for review").click(timeout=6000)
        await pg.wait_for_timeout(2500)
        mark("v3-submitted")
    except Exception:
        print("no submit needed")
    try:
        await pg.get_by_role("button", name="Approve").click(timeout=8000)
        await pg.wait_for_timeout(1500)
        await pg.get_by_role("button", name="Yes, approve").click(timeout=6000)
        await pg.wait_for_timeout(3500)
        mark("approved-v3")
        await pg.screenshot(path=f"{OUT}/liveF-approved.png")
    except Exception as e:
        print("APPROVE-SKIP", str(e)[:200])
        await pg.screenshot(path=f"{OUT}/liveF-noapprove.png")
    await pg.wait_for_timeout(2000)
    mark("end")

asyncio.run(main())
