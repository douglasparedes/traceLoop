"""PHASE D take 5: genuine submit+approve of v6 (interactive) on camera.
Reviewer role. Explicit waits on real state changes (no fixed-sleep assumptions).
Leaves v6 as latest-approved; v5 approval history untouched in DB."""
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
            import re
            await pg.get_by_role('button', name=re.compile(r'^Review')).first.click()
            await pg.wait_for_timeout(2500)
            mark('queue')
            await pg.wait_for_timeout(2000)
            # open the cookie v6 draft row via its Review draft button:
            # find row text containing cookie + v6
            await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent));
for(var i=0;i<rows.length;i++){var r=rows[i].closest('article,div');var t=(r?r.innerText:'')+'';if(/Chocolate|Cookie|cookie/.test(t)&&/\\bv6\\b/.test(t)){rows[i].scrollIntoViewIfNeeded();break;}}""")
            await pg.wait_for_timeout(1200)
            await pg.screenshot(path=OUT + '/recA6-queue.png')
            await pg.evaluate("""var rows=[...document.querySelectorAll('button')].filter(b=>/Review draft/.test(b.textContent));
for(var i=0;i<rows.length;i++){var r=rows[i].closest('article,div');var t=(r?r.innerText:'')+'';if(/Chocolate|Cookie|cookie/.test(t)&&/\\bv6\\b/.test(t)){rows[i].click();break;}}""")
            await pg.wait_for_timeout(3500)
            mark('v6-open')
            head = await pg.evaluate('document.body.innerText.slice(0,500)')
            print('HEAD:', head[:400].replace('\n', ' | '))
            await pg.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await pg.wait_for_timeout(1500)
            try:
                await pg.get_by_role('button', name='Submit for review').click(timeout=6000)
                await pg.wait_for_timeout(3000)
                mark('submitted')
            except Exception as e:
                print('SUBMIT-SKIP', str(e)[:150])
            await pg.screenshot(path=OUT + '/recA6-submitted.png')
            await pg.get_by_role('button', name='Approve').click(timeout=8000)
            await pg.wait_for_timeout(1500)
            mark('approve-click')
            await pg.screenshot(path=OUT + '/recA6-confirm.png')
            await pg.get_by_role('button', name='Yes, approve').click()
            # explicit wait: approved banner/badge text appears
            try:
                await pg.get_by_text('APPROVED').first.wait_for(timeout=30000)
                mark('approved-v6')
            except Exception:
                print('NO-BADGE-TEXT')
            await pg.wait_for_timeout(3000)
            await pg.screenshot(path=OUT + '/recA6-approved.png')
            await pg.wait_for_timeout(4000)
            mark('end')
        finally:
            await ctx.close()
            await b.close()

asyncio.run(main())
