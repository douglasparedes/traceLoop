"""Session C (mobile 390x844): save offline, airplane job, photo, reconnect, sync."""
import asyncio, json, re, time
from playwright.async_api import async_playwright

OUT = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/captures"
PHOTO = "C:/Users/dougl/Documents/MetaHackaton/demo/assets/source-footage/trainer.png"
T0 = time.time()
def mark(n):
    print(f"MARK {n} t={time.time()-T0:.1f}", flush=True)

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
        # open detail via eye (icon button, 3rd in card) — find card then its buttons
        cards = pg.locator("div", has_text="Adjustment-knob check")
        await pg.get_by_text("Adjustment-knob check").first.scroll_into_view_if_needed()
        await pg.wait_for_timeout(800)
        # eye button: last icon button in first matching card region — click via index among card buttons
        btns = pg.locator("button")
        n = await btns.count()
        labels = []
        for i in range(n):
            try:
                labels.append((i, (await btns.nth(i).text_content() or "").strip()[:20]))
            except Exception:
                pass
        print("ALLBTNS:", json.dumps(labels))
        await pg.screenshot(path=f"{OUT}/c-detail.png")
        await ctx.close(); await b.close()

asyncio.run(main())
