"""PHASE D take 1: full upload take (empty form -> typed fields -> file -> progress -> done).
Polls real terminal state (Open in Tutorial Studio button). Ends with tutorial id print.
Caller archives the new tutorial afterwards (separate step)."""
import asyncio, time, sys
from playwright.async_api import async_playwright

OUT = 'C:/Users/dougl/AppData/Local/Temp/traceloop_stage/shots'
CLIP = 'C:/Users/dougl/Documents/MetaHackaton/demo/demostration-visual.mp4'
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
            mark('home')
            await pg.get_by_role('button', name='Tutorials').first.click()
            await pg.wait_for_timeout(2000)
            mark('tutorials')
            await pg.wait_for_timeout(2500)
            # ensure Visual-First mode on the upload card
            try:
                cards = pg.locator('div', has_text='Upload an existing video')
                mark('upload-card-visible')
            except Exception as e:
                print('CARD-FAIL', str(e)[:150])
            await pg.wait_for_timeout(2000)
            try:
                await pg.locator('button', has_text='Visual-First').first.click(timeout=5000)
                mark('vf-mode')
            except Exception as e:
                print('MODE-FAIL', str(e)[:120])
            await pg.get_by_role('button', name='Upload existing video').click()
            await pg.wait_for_timeout(1200)
            mark('form-empty')
            await pg.wait_for_timeout(2500)
            await pg.locator('input[type=\"file\"]').set_input_files(CLIP)
            await pg.wait_for_timeout(1500)
            mark('file-selected')
            # typed entry (sequential keystrokes); fields may carry a filename
            # prefill, so select-all + delete first (real user behavior)
            for sel, text, delay in (
                ('#up-title', 'Chocolate chip cookie preparation', 25),
                ('#up-equip', 'Home kitchen', 25),
                ('#up-task', 'Home baking: lay out cookie ingredients, whisk the mixture in a bowl, and line a baking tray with parchment.', 12),
            ):
                await pg.locator(sel).click()
                await pg.wait_for_timeout(300)
                await pg.keyboard.press('ControlOrMeta+a')
                await pg.wait_for_timeout(200)
                await pg.keyboard.press('Backspace')
                await pg.wait_for_timeout(300)
                await pg.locator(sel).press_sequentially(text, delay=delay)
                await pg.wait_for_timeout(600)
            mark('form-typed')
            await pg.wait_for_timeout(2000)
            await pg.get_by_role('button', name='Upload & generate guide').click()
            mark('upload-clicked')
            try:
                await pg.get_by_role('button', name='Upload as new instead').wait_for(timeout=30000)
                mark('dedupe-shown')
                await pg.screenshot(path=OUT + '/rec-dedupe.png')
                await pg.get_by_role('button', name='Upload as new instead').click()
                mark('force-new')
            except Exception:
                print('no dedupe notice (fresh upload)')
            # explicit readiness: wait for terminal UI state, bounded 10 min
            await pg.get_by_role('button', name='Open in Tutorial Studio').wait_for(timeout=600000)
            mark('processing-done')
            url = pg.url
            print('URL:', url)
            await pg.wait_for_timeout(3000)
            await pg.get_by_role('button', name='Open in Tutorial Studio').click()
            await pg.wait_for_timeout(3000)
            mark('studio-open')
            await pg.wait_for_timeout(4000)
            mark('end')
        finally:
            await ctx.close()
            await b.close()

asyncio.run(main())
