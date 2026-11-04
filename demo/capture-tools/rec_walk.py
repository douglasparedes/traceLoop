"""PHASE D take 4: read-only scoped walkthrough (no mutations).
Procedures search-scoped to the cookie chain -> v5 APPROVED detail scroll.
Activity job 7e34ab30 detail: events, feedback, proposal link."""
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
            await pg.locator('.avatar-btn').click()
            await pg.wait_for_timeout(800)
            await pg.locator('#demo-role').select_option('reviewer')
            await pg.wait_for_timeout(1200)
            mark('reviewer')
            await pg.get_by_role('button', name='Procedures').first.click()
            await pg.wait_for_timeout(2500)
            mark('procedures')
            # scope to the chain with the supported search box (no data hidden by mutation)
            try:
                await pg.locator('input[placeholder^="Search title"]').first.click(timeout=6000)
                await pg.locator('input[placeholder^="Search title"]').first.press_sequentially(
                    'Chocolate chip cookie preparation', delay=30)
                await pg.wait_for_timeout(2000)
                mark('search-scoped')
            except Exception as e:
                print('SEARCH-FAIL', str(e)[:150])
            await pg.wait_for_timeout(2500)
            # open the v5 detail: cards are <article>; the canonical one is
            # unique ('6 versions'). Buttons: [Run again, download, eye, View last].
            card = pg.locator('article', has_text='6 versions').first
            await card.locator('button').nth(2).click()
            await pg.wait_for_timeout(3500)
            mark('v5-detail')
            await pg.wait_for_timeout(1500)
            # open revision history, then the approved v5 row
            try:
                await pg.get_by_role('button', name='View revision history').click(timeout=6000)
                await pg.wait_for_timeout(2500)
                mark('rev-history')
                await pg.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await pg.wait_for_timeout(1500)
                # click the v5 / approved row (versioned list)
                n = await pg.evaluate("""var els=[...document.querySelectorAll('button,a,[role=\"button\"]')].filter(e=>/\\bv5\\b/.test(e.textContent||'')&&/approv/i.test((e.closest('div')||{}).innerText||''));els.length""")
                print('v5-row candidates:', n)
                await pg.screenshot(path=OUT + '/rec-revhist.png')
            except Exception as e:
                print('REVHIST-FAIL', str(e)[:150])
            for y in (500, 1100, 1700, 2200, 1700, 1100, 400):
                await pg.evaluate('window.scrollTo({top:%d,behavior:"smooth"})' % y)
                await pg.wait_for_timeout(2200)
            mark('v5-scrolled')
            await pg.wait_for_timeout(2000)
            await pg.get_by_role('button', name='Activity').first.click()
            await pg.wait_for_timeout(2500)
            mark('activity')
            # open job rows until the 7e34ab30 one (whisking note) is found
            for i in range(6):
                try:
                    await pg.locator('button', has_text='View details').nth(i).click(timeout=6000)
                except Exception:
                    break
                await pg.wait_for_timeout(2000)
                body = await pg.evaluate('document.body.innerText.slice(0,2000)')
                if 'Whisking in the video is brief' in body:
                    print('CANONICAL JOB at row', i)
                    break
                try:
                    await pg.get_by_role('button', name='Hide details').click(timeout=4000)
                    await pg.wait_for_timeout(1000)
                except Exception:
                    pass
            mark('job-open')
            for y in (600, 1300, 2100, 2900, 2100, 1300, 500):
                await pg.evaluate('window.scrollTo({top:%d,behavior:"smooth"})' % y)
                await pg.wait_for_timeout(2200)
            mark('job-scrolled')
            await pg.wait_for_timeout(3000)
            mark('end')
        finally:
            await ctx.close()
            await b.close()

asyncio.run(main())
