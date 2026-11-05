"""Browser acceptance test for the movement rules (not part of `npm test`).

Usage: start the server on a temporary data dir, then
  TOWN_DATA_DIR=$(mktemp -d) node server.mjs --port 8099 &
  python3 tests/browser/movement_rules.py http://127.0.0.1:8099
Needs Python Playwright with Chromium. Samples every character every 250 ms through
an idle period, a full meeting and the walk home, then checks the rules.
"""
import sys, asyncio, math, collections
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8099'
SAMPLE = """async()=>{const L=await import('/village-layout.js');const t=window.town;return [t.ceo,...t.people.values()].map(p=>({id:p.id,where:p.where,x:p.x,y:p.y,walking:!!p.walking,seated:!!p.seated,path:(p.path||[]).length+(p.hallPath||[]).length,ok:p.where!=='village'||L.isWalkable(p.x,p.y)}));}"""
POST = "b=>fetch('/api/meeting',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1600, 'height': 1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto(BASE + '/?hour=12&debug'); await page.wait_for_timeout(1500)
        log = []
        async def phase(name, seconds):
            for _ in range(int(seconds * 4)):
                log.append((name, await page.evaluate(SAMPLE))); await page.wait_for_timeout(250)
        await phase('idle', 30)
        await page.evaluate(POST, {'active': True}); await phase('meeting', 50)
        await page.evaluate(POST, {'active': False}); await phase('after', 40)
        await browser.close()
    problems = list(errors)
    prev, stuck, overlap = {}, collections.Counter(), collections.Counter()
    for name, snap in log:
        for c in snap:
            if not c['ok']: problems.append(f'{name}: {c["id"]} off the paths')
            q = prev.get(c['id'])
            if q and q['where'] == c['where'] == 'village':
                d = math.hypot(c['x'] - q['x'], c['y'] - q['y'])
                if d > .75: problems.append(f'{name}: {c["id"]} teleported {d:.2f}')
                stuck[c['id']] = stuck[c['id']] + 1 if c['path'] and d < .005 else 0
                if stuck[c['id']] == 16: problems.append(f'{name}: {c["id"]} stuck for 4 s')
            prev[c['id']] = c
        idle = [c for c in snap if c['where'] == 'village' and not c['walking']]
        for i, a in enumerate(idle):
            for b in idle[i + 1:]:
                if math.hypot(a['x'] - b['x'], a['y'] - b['y']) < .25:
                    overlap[(a['id'], b['id'])] += 1
                    if overlap[(a['id'], b['id'])] == 8: problems.append(f'{name}: {a["id"]} and {b["id"]} overlap for 2 s')
    meeting = [s for n, s in log if n == 'meeting'][-1]
    if sum(c['seated'] for c in meeting) < min(11, len(meeting)): problems.append('not everyone with a chair is seated')
    if not all(c['where'] == 'village' for c in log[-1][1]): problems.append('someone is still inside the Town Hall 40 s after the meeting')
    print('\n'.join(problems) or 'PASS: no off-path, teleport, stuck, overlap or seating problems')
    sys.exit(1 if problems else 0)

asyncio.run(run())
