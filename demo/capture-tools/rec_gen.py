"""PHASE D take 3: genuine feature generation on canonical tutorial.
(a) Interactive format snapshot (additive, versioned).
(b) In-app video guide generation (caption-led, silent source) with bounded
polling on the real version list. If render fails, we keep the honest
attempt on record and omit it from the film."""
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
            await pg.get_by_role('button', name='Tutorials').first.click()
            await pg.wait_for_timeout(2000)
            for _ in range(6):
                await pg.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await pg.wait_for_timeout(700)
            await pg.evaluate('window.scrollTo(0,0)')
            await pg.wait_for_timeout(800)
            await pg.get_by_role('button', name='Open', exact=True).first.click()
            await pg.wait_for_timeout(3500)
            mark('studio')
            head = await pg.evaluate('document.body.innerText.slice(0,400)')
            print('HEAD:', head[:300].replace('\n', ' | '))
            await pg.locator('button', has_text='Guide').first.click(timeout=8000)
            await pg.wait_for_timeout(2500)
            mark('guide-tab')
            # (a) interactive format
            try:
                await pg.get_by_role('button', name='Change format').click(timeout=6000)
                await pg.wait_for_timeout(1500)
                await pg.locator('[role="radio"]', has_text='Interactive').click()
                mark('interactive-selected')
                await pg.wait_for_timeout(1500)
                try:
                    await pg.get_by_role('button', name='Generate new version').click(timeout=6000)
                except Exception:
                    await pg.get_by_role('button', name='Generate guide').click(timeout=6000)
                # poll for the new snapshot: wait until Version history count grows or
                # a second guide card appears; bounded 5 min
                final = time.time() + 300
                done = False
                while time.time() < final:
                    await pg.wait_for_timeout(5000)
                    txt = await pg.evaluate('document.body.innerText')
                    if 'Interactive Guided Execution' in txt and 'CURRENT' in txt:
                        done = True
                        break
                mark('interactive-done' if done else 'interactive-timeout')
            except Exception as e:
                print('FORMAT-SKIP', str(e)[:200])
            await pg.wait_for_timeout(2000)
            # (b) video guide
            await pg.locator('button', has_text='Video').first.click(timeout=8000)
            await pg.wait_for_timeout(2500)
            mark('video-tab')
            await pg.screenshot(path=OUT + '/rec-videotab-before.png')
            try:
                await pg.get_by_role('button', name='Generate video guide').click(timeout=8000)
                mark('video-generate-clicked')
            except Exception as e:
                print('VIDEO-CLICK-FAIL', str(e)[:200])
            # poll for a ready version row, bounded 10 min
            final = time.time() + 600
            ready = False
            while time.time() < final:
                await pg.wait_for_timeout(10000)
                txt = await pg.evaluate('document.body.innerText.slice(0,3000)')
                if 'ready' in txt.lower() or 'Download' in txt:
                    ready = True
                    break
            mark('video-ready' if ready else 'video-timeout')
            await pg.screenshot(path=OUT + '/rec-videotab-after.png')
            await pg.wait_for_timeout(4000)
            mark('end')
        finally:
            await ctx.close()
            await b.close()

asyncio.run(main())
