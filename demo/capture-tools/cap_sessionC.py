"""Session C full mobile: download, offline job, photo, note, finish, sync."""
import asyncio, json, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/captures"
PHOTO = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/source-footage/trainer.png"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

async def dump(pg, tag):
    btns = pg.locator("button")
    n = await btns.count()
    labels = []
    for i in range(n):
        try:
            labels.append((await btns.nth(i).text_content() or "").strip()[:40])
        except Exception:
            labels.append("?")
    print(tag, json.dumps(labels))

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":390,"height":844}, is_mobile=True,
            has_touch=True, device_scale_factor=2,
            record_video_dir=OUT, record_video_size={"width":390,"height":844})
        pg = await ctx.new_page()
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        try:
            await pg.locator("nav button", has_text="Procedures").first.click(timeout=5000)
        except Exception:
            await pg.get_by_role("button", name="Procedures").first.click()
        await pg.wait_for_timeout(2000)
        await pg.get_by_text("Adjustment-knob check").first.scroll_into_view_if_needed()
        await pg.wait_for_timeout(1000)
        mark("card")
        await pg.wait_for_timeout(3500)
        # download icon = first empty-text button after first "Start job"
        await pg.evaluate("var bs=[...document.querySelectorAll('button')];var i=bs.findIndex(b=>/Start (job|additional run)/.test(b.textContent));var dl=bs.slice(i).find(b=>b.textContent.trim()==='');if(dl)dl.click();")
        await pg.wait_for_timeout(4000)
        mark("offline-saved")
        await pg.screenshot(path=f"{OUT}/c2-cached.png")
        await pg.evaluate("var b=[...document.querySelectorAll('button')].find(x=>/Start (job|additional run)/.test(x.textContent));if(b)b.click()")
        await pg.wait_for_timeout(3000)
        mark("job-started")
        await pg.screenshot(path=f"{OUT}/c2-job1.png")
        await ctx.set_offline(True)
        await pg.wait_for_timeout(2500)
        mark("airplane-on")
        await pg.screenshot(path=f"{OUT}/c2-offline.png")
        await dump(pg, "JOBBTN:")
        # step 1 complete
        await pg.locator("button", has_text="Next step").click()
        await pg.wait_for_timeout(2500)
        mark("step1-done")
        await pg.screenshot(path=f"{OUT}/c2-step2.png")
        await dump(pg, "STEP2BTN:")
        # attach photo (queues offline)
        try:
            async with pg.expect_file_chooser(timeout=8000) as fc:
                await pg.locator("button", has_text="Attach Photo").click()
            chooser = await fc.value
            await chooser.set_files(PHOTO)
            await pg.wait_for_timeout(3000)
            mark("photo-queued")
            await pg.screenshot(path=f"{OUT}/c2-photo.png")
        except Exception as e:
            print("PHOTO-FAIL", str(e)[:200])
            await pg.screenshot(path=f"{OUT}/c2-photo-fail.png")
        # field note
        try:
            await pg.locator("button", has_text="Field Note").click(timeout=8000)
            await pg.wait_for_timeout(1500)
            await pg.screenshot(path=f"{OUT}/c2-note-open.png")
            await dump(pg, "NOTEBTN:")
            inputs = pg.locator("textarea, input[type=text], input:not([type])")
            cnt = await inputs.count()
            print("NOTEINPUTS:", cnt)
            if cnt:
                await inputs.first.fill("Knob label not visible from this angle.")
                await pg.wait_for_timeout(800)
                try:
                    await pg.locator("button", has_text="Save note").click(timeout=5000)
                    await pg.wait_for_timeout(2000)
                    mark("note-saved")
                except Exception as e2:
                    print("NOTESAVE-FAIL", str(e2)[:150])
        except Exception as e:
            print("NOTE-FAIL", str(e)[:200])
        await pg.screenshot(path=f"{OUT}/c2-note.png")
        await dump(pg, "PREFINISH:")
        # finish (Next on last step or Finish job)
        try:
            await pg.locator("button", has_text="Finish job").click(timeout=6000)
        except Exception:
            await pg.locator("button", has_text="Next step").click()
        await pg.wait_for_timeout(3000)
        mark("finished")
        await pg.screenshot(path=f"{OUT}/c2-finished.png")
        await dump(pg, "DONEBTN:")
        await ctx.set_offline(False)
        await pg.wait_for_timeout(2000)
        mark("reconnected")
        try:
            await pg.locator("nav button", has_text="Activity").first.click(timeout=5000)
        except Exception:
            await pg.get_by_role("button", name="Activity").first.click()
        await pg.wait_for_timeout(2500)
        await dump(pg, "ACTBTN:")
        await pg.screenshot(path=f"{OUT}/c2-activity.png")
        try:
            await pg.locator("button", has_text="Sync now").click(timeout=6000)
            await pg.wait_for_timeout(5000)
            mark("synced")
            await pg.screenshot(path=f"{OUT}/c2-synced.png")
        except Exception as e:
            print("SYNC-FAIL", str(e)[:200])
        await ctx.close(); await b.close()

asyncio.run(main())
