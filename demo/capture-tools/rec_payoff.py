"""PHASE D take 6: read-only payoff — REV 6 approved card + approved v6 detail."""
import asyncio, time
from playwright.async_api import async_playwright

OUT = 'C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots'
T0 = time.time()

def mark(n):
    print('MARK %s t=%.1f' % (n, time.time() - T0), flush=True)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel='chrome', args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 1920, 'height': 1080},
            record_video_dir=OUT, record_video_size={'width': 1920, 'height': 1080})
        try:
            pg = await ctx.new_page()
            await pg.goto('http://localhost:5173', wait_until='networkidle')
            await pg.wait_for_timeout(1500)
            await pg.get_by_role('button', name='Procedures').first.click()
            await pg.wait_for_timeout(2500)
            mark('procedures')
            box = pg.locator('input[placeholder^="Search title"]').first
            await box.click()
            await box.press_sequentially('Chocolate chip cookie preparation', delay=20)
            await pg.wait_for_timeout(2500)
            mark('scoped')
            await pg.wait_for_timeout(2500)
            card = pg.locator('article', has_text='6 versions').first
            for _ in range(3):
                await card.locator('button').nth(2).click()
                await pg.wait_for_timeout(2500)
                try:
                    await pg.get_by_role('button', name='Library').first.wait_for(timeout=3000)
                    break
                except Exception:
                    continue
            await pg.wait_for_timeout(1500)
            mark('v6-approved-detail')
            for y in (400, 1100, 1800, 1100, 300):
                await pg.evaluate('window.scrollTo({top:%d,behavior:"smooth"})' % y)
                await pg.wait_for_timeout(2200)
            mark('scrolled')
            await pg.wait_for_timeout(3000)
            mark('end')
        finally:
            await ctx.close()
            await b.close()

asyncio.run(main())
