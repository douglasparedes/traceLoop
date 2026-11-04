"""PHASE D take 2: read-only canonical tour (tutorial a15e048d). No mutations.
Overview (with per-stage provenance) -> Visuals (keyframes) -> Content (rev2
steps + honest 0-transcript) -> Guide (formats + version history) -> Video tab
(empty state, honest). Slow readable scrolls with handles."""
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
            mark('home')
            await pg.get_by_role('button', name='Tutorials').first.click()
            await pg.wait_for_timeout(2000)
            # open canonical tutorial via library Open (first Open = newest; canonical
            # may not be first, so scroll library and click its row explicitly)
            for _ in range(6):
                await pg.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await pg.wait_for_timeout(800)
            await pg.evaluate('window.scrollTo(0,0)')
            await pg.wait_for_timeout(800)
            # find the row for the canonical tutorial by title+date is unreliable;
            # open via direct tutorial id through the Open button of the matching card:
            # instead click Tutorials rows: use page search for exact title text occurrence
            # that belongs to a library card (has Open button sibling).
            n = await pg.evaluate("""var els=[...document.querySelectorAll('*')].filter(e=>e.children.length===0&&e.textContent.trim()==='Chocolate chip cookie preparation');els.length""")
            print('title hits:', n)
            mark('library')
            await pg.wait_for_timeout(3000)
            # click the first Open button (newest tutorial cards are dupes of same file;
            # canonical a15e048d: navigate directly by discovering its library link is
            # fragile, so use the tutorial list API? No - stay UI-only: open each Open
            # until the Studio header shows rev 2 + READY work instruction state is skipped;
            # simpler: open first Open, check header, go back if wrong.)
            # open candidate library rows until the canonical tutorial is found:
            # header = title + rev 2, and Visuals shows the live keyframes.
            found = False
            for attempt in range(6):
                try:
                    await pg.get_by_role('button', name='Open', exact=True).nth(attempt).click(timeout=6000)
                except Exception as e:
                    print('OPEN-FAIL', attempt, str(e)[:120])
                    break
                await pg.wait_for_timeout(3500)
                head = await pg.evaluate('document.body.innerText.slice(0,1200)')
                if 'a15e048d' in head or ('rev 2' in head and 'Chocolate chip cookie preparation' in head):
                    found = True
                    print('CANONICAL at row', attempt)
                    break
                await pg.evaluate('window.history.back()')
                await pg.wait_for_timeout(2000)
            if not found:
                print('CANONICAL-NOT-FOUND via rows; trying direct studio deep-link is unsupported, stopping honest')
                return
            mark('studio-open')
            # Overview: slow scroll through provenance
            for y in (500, 1100, 1700, 2200, 1700, 1100, 400):
                await pg.evaluate('window.scrollTo({top:%d,behavior:"smooth"})' % y)
                await pg.wait_for_timeout(2200)
            mark('overview')
            await pg.wait_for_timeout(2000)
            await pg.locator('button', has_text='Visuals').first.click(timeout=8000)
            await pg.wait_for_timeout(2500)
            mark('visuals')
            await pg.wait_for_timeout(5000)
            await pg.locator('button', has_text='Content').first.click(timeout=8000)
            await pg.wait_for_timeout(2500)
            mark('content')
            await pg.wait_for_timeout(5000)
            await pg.locator('button', has_text='Guide').first.click(timeout=8000)
            await pg.wait_for_timeout(2500)
            mark('guide')
            for y in (500, 1100, 1700, 1100, 400):
                await pg.evaluate('window.scrollTo({top:%d,behavior:"smooth"})' % y)
                await pg.wait_for_timeout(2200)
            mark('guide-scrolled')
            await pg.locator('button', has_text='Video').first.click(timeout=8000)
            await pg.wait_for_timeout(2500)
            mark('video-tab')
            await pg.wait_for_timeout(4000)
            mark('end')
        finally:
            await ctx.close()
            await b.close()

asyncio.run(main())
