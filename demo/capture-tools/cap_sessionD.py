"""Session D full desktop: feedback on finished job, proposal, approve v4."""
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
        await pg.get_by_role("button", name="Activity").first.click()
        await pg.wait_for_timeout(2500)
        mark("activity")
        await pg.wait_for_timeout(3000)
        await pg.locator("button", has_text="View details").first.click(timeout=8000)
        await pg.wait_for_timeout(2500)
        mark("job-open")
        await pg.screenshot(path=f"{OUT}/d-job-open.png")
        await pg.wait_for_timeout(2000)
        # scroll to feedback
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await pg.wait_for_timeout(1200)
        await pg.screenshot(path=f"{OUT}/d-feedback-form.png")
        # step 2 confusing (2nd), visuals No, note text
        try:
            await pg.locator("button", has_text="confusing").nth(1).click(timeout=8000)
            mark("step2-confusing")
        except Exception as e:
            print("CONF-FAIL", str(e)[:150])
        await pg.wait_for_timeout(1000)
        try:
            await pg.locator("button", has_text="No", exact=True).first.click(timeout=5000)
        except Exception as e:
            print("NO-FAIL", str(e)[:150])
        fields = await pg.eval_on_selector_all("textarea", "els => els.map(e => (e.placeholder||'').slice(0,60))")
        print("TEXTAREAS:", json.dumps(fields))
        try:
            for i, ph in enumerate(fields):
                if "missing" in ph.lower() or "feedback" in ph.lower() or "note" in ph.lower() or "improve" in ph.lower() or "wrong" in ph.lower() or "confus" in ph.lower():
                    await pg.locator("textarea").nth(i).fill("Knob label is not visible from this angle.")
                    print("FILLED textarea", i)
                    break
            else:
                if len(fields):
                    await pg.locator("textarea").last.fill("Knob label is not visible from this angle.")
                    print("FILLED last textarea")
        except Exception as e:
            print("FILL-FAIL", str(e)[:150])
        await pg.wait_for_timeout(1000)
        await pg.screenshot(path=f"{OUT}/d-feedback-filled.png")
        mark("feedback-filled")
        await pg.wait_for_timeout(2000)
        await pg.get_by_role("button", name="Submit feedback").click()
        await pg.wait_for_timeout(3000)
        mark("feedback-submitted")
        await pg.screenshot(path=f"{OUT}/d-feedback-done.png")
        await pg.wait_for_timeout(2000)
        # reviewer + proposal
        await pg.locator(".avatar-btn").click()
        await pg.wait_for_timeout(800)
        await pg.locator("#demo-role").select_option("reviewer")
        await pg.wait_for_timeout(1200)
        mark("role-reviewer")
        try:
            await pg.get_by_role("button", name="Create improvement proposal").click(timeout=8000)
            await pg.wait_for_timeout(6000)
            mark("proposal-created")
            await pg.screenshot(path=f"{OUT}/d-proposal.png")
            await dump(pg, "PROP:")
        except Exception as e:
            print("PROP-FAIL", str(e)[:200])
            await pg.screenshot(path=f"{OUT}/d-proposal-fail.png")
        await pg.wait_for_timeout(4000)
        await ctx.close(); await b.close()

asyncio.run(main())
