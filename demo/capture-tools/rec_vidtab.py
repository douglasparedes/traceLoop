"""PHASE D pickup: Video tab showing v3 ready + in-page playback (silent captioned)."""
import asyncio, time
from playwright.async_api import async_playwright

OUT = 'C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots'
T0 = time.time()

def mark(n):
    print('MARK %s t=%.1f' % (n, time.time() - T0), flush=True)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel='chrome', args=['--no-sandbox',
            '--autoplay-policy=no-user-gesture-required'])
        ctx = await b.new_context(viewport={'width': 1920, 'height': 1080},
            record_video_dir=OUT, record_video_size={'width': 1920, 'height': 1080})
        try:
            pg = await ctx.new_page()
            await pg.goto('http://localhost:5173', wait_until='networkidle')
            await pg.wait_for_timeout(1500)
            await pg.get_by_role('button', name='Tutorials').first.click()
            await pg.wait_for_timeout(2000)
            for _ in range(6):
                await pg.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await pg.wait_for_timeout(700)
            await pg.evaluate('window.scrollTo(0,0)')
            await pg.get_by_role('button', name='Open', exact=True).first.click()
            await pg.wait_for_timeout(3500)
            mark('studio')
            await pg.locator('button', has_text='Video').first.click(timeout=8000)
            await pg.wait_for_timeout(3000)
            mark('video-tab')
            await pg.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await pg.wait_for_timeout(2000)
            mark('versions-visible')
            await pg.wait_for_timeout(3000)
            # play the ready v3 preview if present
            try:
                await pg.locator('button', has_text='Preview').first.click(timeout=6000)
                await pg.wait_for_timeout(3000)
                mark('preview-open')
                await pg.wait_for_timeout(12000)
                mark('preview-played')
            except Exception as e:
                print('PREVIEW-SKIP', str(e)[:150])
            mark('end')
        finally:
            await ctx.close()
            await b.close()

asyncio.run(main())
