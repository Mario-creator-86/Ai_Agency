// Real page markup/styles, isolated renderer: no backend, authentication or external jobs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import { chromium } from 'playwright';

const FRONTEND = fileURLToPath(new URL('../..', import.meta.url));
const EVIDENCE = process.env.E2E_EVIDENCE;

test('production scene fits its frame and supports wheel/drag navigation without trapping page scroll', async () => {
  const result = await build({ root: FRONTEND, configFile: false, publicDir: false, logLevel: 'warn',
    plugins: [tailwindcss(), { name: 'isolated-scene',
      resolveId: id => id.replaceAll('\\', '/').endsWith('/scene-review') || id === 'scene-review' ? '\0scene-review' : null,
      load: id => id === '\0scene-review' ? `import '${path.join(FRONTEND, 'src/style.css').replaceAll('\\', '/')}';
        import '${path.join(FRONTEND, 'src/office_scene.css').replaceAll('\\', '/')}';
        import '${path.join(FRONTEND, 'src/pixel_studio.css').replaceAll('\\', '/')}';
        export * from '${path.join(FRONTEND, 'src/pixel_office.js').replaceAll('\\', '/')}';` : null }],
    build: { write: false, minify: false, lib: { entry: 'scene-review', name: 'PixelScene', formats: ['iife'] } } });
  const output = (Array.isArray(result) ? result[0] : result).output;
  const code = output.find(o => o.type === 'chunk').code;
  const css = output.filter(o => o.type === 'asset' && o.fileName.endsWith('.css')).map(o => o.source).join('\n');
  const html = readFileSync(path.join(FRONTEND, 'index.html'), 'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
    .replace('</head>', `<style>${css}</style></head>`);
  const image = readFileSync(path.join(FRONTEND, 'public/assets/pixel/studio-detailed.png'));
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1700, height: 1100 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const capture = async name => {
    if (EVIDENCE) { mkdirSync(EVIDENCE, { recursive: true }); await page.screenshot({ path: path.join(EVIDENCE, `page-${name}.png`), fullPage: true }); }
  };
  try {
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/assets/pixel/studio-detailed.png') return route.fulfill({ body: image, contentType: 'image/png' });
      if (url.pathname === '/') return route.fulfill({ body: html, contentType: 'text/html' });
      return route.abort();
    });
    await page.goto('http://pixel-navigation.invalid/');
    await page.addScriptTag({ content: code });
    await page.clock.setFixedTime(new Date('2026-10-08T17:10:00Z'));
    await page.evaluate(async () => {
      document.body.classList.remove('is-title');
      document.getElementById('title-stage').hidden = true;
      document.getElementById('login').hidden = true;
      document.getElementById('workspace').hidden = false;
      document.documentElement.dataset.register = 'closed'; document.documentElement.dataset.side = 'closed';
      window.engine = new PixelScene.OfficeEngine(document.getElementById('office-canvas'), { parked: true,
        infoElement: document.getElementById('scene-info'), dataLive: () => false, reducedMotion: () => true,
        onSelectAgent: agent => { window.selectedId = agent.id; } });
      await window.engine.ready; window.engine.resize();
      window.engine.setAgents([{ id: 'pointer-fixture', display_name: 'Pointer fixture', role: 'Director', lifecycle: 'ACTIVE', runtime_state: 'IDLE' }]);
    });
    const bounds = await page.evaluate(() => {
      const frame = document.querySelector('.workspace-grid').getBoundingClientRect(), c = window.engine.canvas.getBoundingClientRect();
      return { frame: { top: frame.top, bottom: frame.bottom, height: frame.height }, canvas: { top: c.top, bottom: c.bottom, height: c.height } };
    });
    await capture('before-or-after-night');
    assert.ok(Math.abs(bounds.frame.height - bounds.canvas.height) < 2, JSON.stringify(bounds));
    assert.ok(bounds.canvas.bottom <= bounds.frame.bottom + 1, 'no scene area hidden below fixed frame');
    const worldFits = () => page.evaluate(() => {
      const e = window.engine, v = e.viewport, a = v.worldToScreen(0, 0), b = v.worldToScreen(e.worldW, e.worldH);
      return a.x >= -1 && a.y >= -1 && b.x <= e.canvas.width + 1 && b.y <= e.canvas.height + 1;
    });
    assert.equal(await worldFits(), true);
    // No icon/label overflow may steal a neighbouring menu's pointer target.
    await page.evaluate(()=>document.querySelectorAll('.topbar-rooms button').forEach(button=>
      button.addEventListener('click',()=>{window.menuPressed=button.id;})));
    for(const width of [1051,1280,1366,1700,1720,1920,2560]){
      await page.setViewportSize({width,height:1100});
      const menus=await page.evaluate(()=>[...document.querySelectorAll('.topbar-rooms button')].map(button=>{
        const r=button.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
        return {id:button.id,hit:hit?.closest('button')?.id};
      }));
      for(const menu of menus){
        assert.equal(menu.hit,menu.id,`${width}px: menu contents must stay within their own button`);
        await page.locator('#'+menu.id).click();
        assert.equal(await page.evaluate(()=>window.menuPressed),menu.id);
      }
    }
    await page.setViewportSize({width:1700,height:1100});
    await page.evaluate(() => window.engine.zoomTo(2));
    const before = await page.evaluate(() => window.engine.viewport.panY);
    await page.mouse.move(850, 450); await page.mouse.wheel(0, 180);
    await page.waitForTimeout(60);
    assert.ok(await page.evaluate(() => window.engine.viewport.panY) < before, 'wheel moves zoomed scene');
    const wheelPan = await page.evaluate(() => window.engine.viewport.panX);
    await page.mouse.move(850, 450); await page.mouse.down(); await page.mouse.move(940, 520, { steps: 5 }); await page.mouse.up();
    assert.ok(await page.evaluate(() => window.engine.viewport.panX) > wheelPan, 'drag moves zoomed scene');
    const beforeZoom = await page.evaluate(() => window.engine.zoom);
    await page.keyboard.down('Control'); await page.mouse.wheel(0, -100); await page.keyboard.up('Control');
    await page.waitForTimeout(60);
    assert.ok(await page.evaluate(() => window.engine.zoom) > beforeZoom);
    await page.evaluate(() => window.engine.fitView()); assert.equal(await worldFits(), true);
    const seat = await page.evaluate(() => {
      const e = window.engine, p = e.visiblePositions()[0], s = e.viewport.worldToScreen(p.x, p.y - 30), box = e.canvas.getBoundingClientRect();
      return { x: box.left + s.x / e.dpr, y: box.top + s.y / e.dpr };
    });
    await page.evaluate(() => {
      const e = window.engine;
      window.hoverPaint = { names: 0, boxes: 0 };
      const text = e.ctx.fillText.bind(e.ctx), box = e.ctx.strokeRect.bind(e.ctx);
      e.ctx.fillText = (value, ...args) => { if (String(value).includes('Pointer fixture')) window.hoverPaint.names++; return text(value, ...args); };
      e.ctx.strokeRect = (...args) => { window.hoverPaint.boxes++; return box(...args); };
    });
    await page.mouse.move(seat.x, seat.y);
    assert.deepEqual(await page.evaluate(() => window.hoverPaint), { names: 0, boxes: 0 }, 'no duplicate canvas name or character hover rectangle');
    assert.match(await page.locator('#office-canvas').getAttribute('title'), /Pointer fixture.*în așteptare/, 'one native tooltip retains real name/state');
    await page.mouse.click(seat.x, seat.y);
    assert.equal(await page.evaluate(() => window.selectedId), 'pointer-fixture', 'selection survives added navigation');
    await page.evaluate(() => { window.selectedId = null; window.engine.canvas.focus(); });
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => window.selectedId), 'pointer-fixture', 'keyboard agent selection retained');
    await page.setViewportSize({ width: 1366, height: 768 }); await page.waitForTimeout(80);
    assert.equal(await worldFits(), true, 'short desktop fits street and rooftop');
    await page.setViewportSize({ width: 390, height: 580 }); await page.waitForTimeout(80);
    await page.evaluate(() => window.scrollTo(0, 0)); await page.mouse.move(190, 320); await page.mouse.wheel(0, 350);
    await page.waitForTimeout(100);
    assert.ok(await page.evaluate(() => window.scrollY) > 0, 'native mobile page scroll remains available at fit');
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
