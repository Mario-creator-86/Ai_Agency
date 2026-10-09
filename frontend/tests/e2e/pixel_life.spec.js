// Isolated real Canvas with explicit fixture staff; no backend/model/media calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { chromium } from 'playwright';
const FRONTEND = fileURLToPath(new URL('../..', import.meta.url));
const EVIDENCE = process.env.E2E_EVIDENCE;

test('all seated staff/street visibly animate and every lifecycle guard holds', async () => {
 const result = await build({ root: FRONTEND, configFile: false, publicDir: false, logLevel: 'warn',
  build: { write: false, minify: false, lib: { entry: path.join(FRONTEND, 'src/pixel_office.js'), name: 'PixelScene', formats: ['iife'] } } });
 const code = (Array.isArray(result) ? result[0] : result).output.find(o => o.type === 'chunk').code;
 const image = readFileSync(path.join(FRONTEND, 'public/assets/pixel/studio-detailed.png'));
 const characters = JSON.parse(readFileSync(path.join(FRONTEND, 'tests/fixtures/pixel_actors_bible.json'), 'utf8'));
 const manifest = JSON.parse(readFileSync(path.join(FRONTEND, '../config/pixel_actors.json'), 'utf8'));
 const atlasNames = new Set(Object.values(manifest.atlases).map(a=>path.basename(a.url)));
 const browser = await chromium.launch({ headless: true });
 const page = await browser.newPage({ viewport: { width: 1280, height: 950 } });
 const errors = []; page.on('pageerror', e => errors.push(e.message));
 try {
  await page.route('**/*', route => {
   const url = new URL(route.request().url());
   if (atlasNames.has(path.basename(url.pathname))) return route.fulfill({body: readFileSync(path.join(FRONTEND,'public/assets/pixel',path.basename(url.pathname))),contentType:'image/png'});
   if (url.pathname === '/assets/pixel/studio-detailed.png') return route.fulfill({ body: image, contentType: 'image/png' });
   if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: `<!doctype html><meta charset="utf-8"><title>Verificare animații în test</title>
    <style>body{margin:0;background:#222538;color:#f4dfb4;font:15px monospace}header{padding:14px 24px}canvas{display:block;width:100%;aspect-ratio:3/2;image-rendering:pixelated}</style>
    <header>AMN-AI · Verificare animații în test · <span id="scene-info"></span></header><canvas id="office-canvas" tabindex="0"></canvas>` });
   return route.abort();
  });
  await page.goto('http://pixel-life.invalid/'); await page.addScriptTag({ content: code });
  await page.clock.setFixedTime(new Date('2026-10-08T17:10:00Z'));
  await page.evaluate(async ({characters,manifest}) => {
   window.live = true; window.reduced = false;
   window.engine = new PixelScene.OfficeEngine(document.getElementById('office-canvas'), { parked: true,
    infoElement: document.getElementById('scene-info'), dataLive: () => window.live, reducedMotion: () => window.reduced,
    fetchWeather: async () => ({ available: true, condition: 'clear', observed_at_utc: '2026-10-08T17:10:00Z' }) });
   await window.engine.ready;
   if (PixelScene.actorAtlasStatus().loaded !== 5) throw new Error("All five detailed atlases must be loaded");
   window.engine.characters = new Map(characters.map(c=>[c.employee_id,c]));
   // A still-running backend serves its preceding visual config after a static page update.
   const preceding=structuredClone(window.engine.pixelLayout);
   preceding.stations.forEach(s=>{delete s.seating;delete s.foreground_polygons;});
   window.engine.setLayout({pixel_office:preceding});
   if(!window.engine.pixelLayout.stations.every(s=>s.seating&&s.foreground_polygons))throw Error('Current seating must survive preceding backend geometry');
   const roles = ['Director', 'LeadResearcher', 'FactChecker', 'Writer', 'VoiceArtist', 'VideoEditor', 'Publisher', 'Accountant'];
   window.engine.setAgents(roles.map((role_name, pixel_slot) => ({ id: manifest.staff[pixel_slot].employee_id, display_name: `Test ${role_name}`, role_name,
    pixel_slot, lifecycle: 'ACTIVE', runtime_state: ['IDLE', 'WORKING', 'THINKING', 'REVIEWING'][pixel_slot % 4] })));
   window.engine.unpark(); await window.engine.refreshWeather();
  }, {characters,manifest});
  await page.waitForFunction(() => window.engine.lifeElapsed > 100);
  const raster = await page.evaluate(() => {
   const e = window.engine, hash = r => {
    const a = e.viewport.worldToScreen(r.x, r.y);
    const bytes = e.ctx.getImageData(Math.round(a.x), Math.round(a.y), Math.round(r.w * e.viewport.zoom), Math.round(r.h * e.viewport.zoom)).data;
    let sum = 2166136261; for (const b of bytes) sum = Math.imul(sum ^ b, 16777619); return sum >>> 0;
   };
   e.stop(); const rows = [];
   for (const elapsed of [1000, 2400, 3700, 4600, 12000, 18000, 22000, 26000, 32000]) {
    e.lifeElapsed = elapsed; e.lifeFrameAt = null; e.draw();
    rows.push({ staff: e.visiblePositions().map(p => hash({ x: p.x - 32, y: p.y - 70, w: 64, h: 84 })),
     road: hash({ x: 200, y: 544, w: 650, h: 55 }), gestures: e.visiblePositions().map(p => e.motionFor(p.agent).gesture) });
   }
   return { rows, staff: e.agents.map(a => [a.id, a.runtime_state]), seats: e.positions.map(p => [p.id, p.slot, p.x, p.y]), ambient: e.environment.ambientAnimating };
  });
  for (let i = 0; i < 8; i++) assert.ok(new Set(raster.rows.map(r => r.staff[i])).size > 1, `staff ${i} has actual visible frame changes`);
  assert.ok(new Set(raster.rows.map(r => r.road)).size > 1, 'traffic actually moves in the canvas');
  assert.ok(raster.rows.some(r => r.gestures.includes('sip'))); assert.ok(raster.rows.some(r => r.gestures.includes('stretch')));
  assert.equal(raster.ambient, true);
  if (EVIDENCE) { mkdirSync(EVIDENCE, { recursive: true }); await page.screenshot({ path: path.join(EVIDENCE, 'life-test-gestures.png'), fullPage: true }); }
  await page.evaluate(() => { window.engine.startEnvironment(); window.engine.schedule(); }); await page.waitForTimeout(200);
  await page.evaluate(() => { window.live = false; window.engine.draw(); });
  const frozen = await page.evaluate(() => window.engine.lifeElapsed); await page.waitForTimeout(250);
  assert.equal(await page.evaluate(() => window.engine.lifeElapsed), frozen);
  assert.equal(await page.evaluate(() => window.engine.environment.ambientAnimating), false);
  await page.evaluate(() => { window.live = true; window.reduced = true; window.engine.draw(); window.engine.schedule(); });
  const quiet = await page.evaluate(() => window.engine.lifeElapsed); await page.waitForTimeout(250);
  assert.equal(await page.evaluate(() => window.engine.lifeElapsed), quiet);
  assert.equal(await page.evaluate(() => window.engine.tickTimer + window.engine.raf), 0);
  await page.evaluate(() => { window.reduced = false; window.engine.setReplay(true); });
  assert.equal(await page.evaluate(() => window.engine.environment.ambientAnimating), false);
  await page.evaluate(() => { window.engine.setReplay(false); Object.defineProperty(document, 'hidden', { configurable: true, value: true }); document.dispatchEvent(new Event('visibilitychange')); });
  assert.equal(await page.evaluate(() => window.engine.environmentTimer + window.engine.tickTimer + window.engine.raf), 0);
  const after = await page.evaluate(() => ({ staff: window.engine.agents.map(a => [a.id, a.runtime_state]), seats: window.engine.positions.map(p => [p.id, p.slot, p.x, p.y]) }));
  assert.deepEqual(after.staff, raster.staff); assert.deepEqual(after.seats, raster.seats);
  await page.evaluate(() => { delete document.hidden; window.engine.park(); });
  assert.equal(await page.evaluate(() => window.engine.environmentTimer + window.engine.tickTimer + window.engine.raf), 0);
  assert.deepEqual(errors, []);
 } finally { await browser.close(); }
});
