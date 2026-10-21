// Bounded Canvas component checks, with no backend process, database writes, model or media calls.
// The full owner_flows suite retains its game/process guard. This graphical check opens one
// short-lived browser and intercepts all requests locally, without starting the film harness.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { chromium } from 'playwright';

const FRONTEND = fileURLToPath(new URL('../..', import.meta.url));
const ROOT = path.resolve(FRONTEND, '..');
const EVIDENCE = process.env.E2E_EVIDENCE;

test('pixel environment paints protected interiors, live clock/weather and bounded lifecycle', async () => {
  const result = await build({ root: FRONTEND, configFile: false, publicDir: false, logLevel: 'warn',
    build: { write: false, minify: false, lib: { entry: path.join(FRONTEND, 'tests/fixtures/pixel_environment_entry.js'), name: 'PixelScene', formats: ['iife'] } } });
  const code = (Array.isArray(result) ? result[0] : result).output.find(o => o.type === 'chunk').code;
  const image = readFileSync(path.join(FRONTEND, 'public/assets/pixel/studio-detailed.png'));
  const observation = process.env.E2E_REAL_WEATHER ? JSON.parse(readFileSync(process.env.E2E_REAL_WEATHER, 'utf8')).observation : { available: false };
  const staff = process.env.E2E_STAFF ? JSON.parse(readFileSync(process.env.E2E_STAFF, 'utf8')) : [];
  const characters = process.env.E2E_CHARACTER_BIBLE ? JSON.parse(readFileSync(process.env.E2E_CHARACTER_BIBLE, 'utf8')) : [];
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1536, height: 1130 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let reads = 0;
  try {
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/assets/pixel/studio-detailed.png') return route.fulfill({ body: image, contentType: 'image/png' });
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="ro"><meta charset="utf-8"><title>AMN-AI · verificare scenă</title><style>
        *{box-sizing:border-box}body{margin:0;background:#222538;color:#f4dfb4;font:15px monospace}header{padding:12px 24px;display:flex;justify-content:space-between}canvas{display:block;width:100%;aspect-ratio:3/2;image-rendering:pixelated}footer{padding:8px 24px;font-size:12px}#pixel-roster{display:flex;gap:6px;padding:8px 24px;flex-wrap:wrap}button{background:#353346;color:#f4dfb4;border:1px solid #696071;padding:6px}#pixel-office-pages{display:none}
        </style><header><b>AMN-AI · Studioul</b><span id="scene-info"></span></header><canvas id="office-canvas" aria-label="Ceas și mediu pixelat"></canvas><div id="pixel-office-pages"></div><div id="pixel-roster"></div><footer>Verificare izolată a scenei · fără pornirea producției</footer></html>` });
      return route.abort();
    });
    await page.goto('http://pixel-review.invalid/');
    await page.addScriptTag({ content: code });
    await page.exposeFunction('weatherRead', () => { reads++; });
    await page.evaluate(async ([data, staff, characters]) => {
      window.weatherPayload = data; window.live = true; window.reduced = true;
      window.engine = new PixelScene.OfficeEngine(document.getElementById('office-canvas'), { parked: true,
        infoElement: document.getElementById('scene-info'), dataLive: () => window.live, reducedMotion: () => window.reduced,
        fetchWeather: async () => { await window.weatherRead(); return window.weatherPayload; } });
      await window.engine.ready; window.engine.setCharacterBible(characters); window.engine.setAgents(staff); window.engine.unpark();
      await window.engine.refreshWeather();
    }, [observation, staff, characters]);
    await page.waitForFunction(() => window.engine.weatherReceivedAt > 0 && !window.engine.weather._pending);
    await page.evaluate(() => window.engine.draw());
    const capture = async name => { if (EVIDENCE) { mkdirSync(EVIDENCE, { recursive: true }); await page.screenshot({ path: path.join(EVIDENCE, `component-${name}.png`), fullPage: true }); } };
    if (observation.available) {
      assert.equal(await page.evaluate(() => window.engine.environment.weather), observation.condition);
      await capture('current-desktop');
    }
    const interior = () => page.evaluate(() => {
      const e = window.engine, c = document.createElement('canvas'); c.width = e.canvas.width; c.height = e.canvas.height;
      const ctx = c.getContext('2d'), v = e.viewport; ctx.imageSmoothingEnabled = false;
      ctx.setTransform(v.zoom, 0, 0, v.zoom, v.panX, v.panY); ctx.drawImage(e.background, 0, 0, e.worldW, e.worldH);
      // Match the intentional indoor life layer; compare exterior weather protection separately.
      PixelScene.drawRoomLife(ctx,e.background,e.lifeElapsed,e.currentWeather(),e.roomFrame);
      return [{ x: 320, y: 155, w: 65, h: 65 }, { x: 212, y: 254, w: 89, h: 74 }, { x: 630, y: 427, w: 173, h: 89 }].every(r => {
        const x = Math.ceil(r.x * v.zoom + v.panX), y = Math.ceil(r.y * v.zoom + v.panY), w = Math.floor(r.w * v.zoom), h = Math.floor(r.h * v.zoom);
        const a = ctx.getImageData(x, y, w, h).data, b = e.ctx.getImageData(x, y, w, h).data;
        return a.every((value, i) => value === b[i]);
      });
    });
    for (const condition of ['clear', 'rain', 'fog', 'snow', 'storm']) {
      await page.clock.setFixedTime(new Date('2026-10-08T12:23:00Z'));
      await page.evaluate(async condition => {
        window.weatherPayload = { available: true, condition, intensity: 0.8, temperature_c: condition === 'snow' ? -2 : 14, observed_at_utc: '2026-10-08T12:15:00Z' };
        await window.engine.refreshWeather();
      }, condition);
      const state = await page.evaluate(() => window.engine.environment);
      assert.equal(state.clock, '15:23'); assert.equal(state.phase, 'day'); assert.equal(state.weather, condition);
      assert.equal(state.animating, false); assert.equal(await interior(), true);
      await capture(`${condition}-test`);
    }
    await page.clock.setFixedTime(new Date('2026-10-08T15:35:00Z'));
    await page.evaluate(async () => { window.weatherPayload = { available: true, condition: 'clear', observed_at_utc: '2026-10-08T15:30:00Z' }; await window.engine.refreshWeather(); });
    assert.equal(await page.evaluate(() => window.engine.environment.phase), 'dusk');
    await capture('sunset-test');
    await page.clock.setFixedTime(new Date('2026-10-08T12:23:00Z'));
    await page.evaluate(async () => { window.weatherPayload.observed_at_utc = '2026-10-08T12:15:00Z'; await window.engine.refreshWeather(); });
    const outside = () => page.evaluate(() => { const e = window.engine, p = e.viewport.worldToScreen(20, 20); return Array.from(e.ctx.getImageData(p.x, p.y, 1, 1).data).slice(0, 3).reduce((a, b) => a + b, 0); });
    const daylight = await outside();
    await page.clock.setFixedTime(new Date('2026-10-08T21:23:00Z'));
    await page.evaluate(async () => { window.weatherPayload = { ...window.weatherPayload, condition: 'clear', observed_at_utc: '2026-10-08T21:15:00Z' }; await window.engine.refreshWeather(); });
    assert.equal(await page.evaluate(() => window.engine.environment.clock), '00:23');
    assert.equal(await page.evaluate(() => window.engine.environment.phase), 'night');
    assert.equal(await page.evaluate(() => window.engine.environment.sun), 0);
    assert.ok(await page.evaluate(() => window.engine.environment.moon) > 0.9);
    const moonVisible = await page.evaluate(() => {
      const e = window.engine, p = e.viewport.worldToScreen(867, 43);
      const rgb = Array.from(e.ctx.getImageData(p.x, p.y, 1, 1).data).slice(0, 3);
      return rgb[0] > 190 && rgb[1] > 180;
    });
    assert.equal(moonVisible, true, 'moon is painted in the actual canvas');
    assert.ok(await outside() < daylight); assert.equal(await interior(), true);
    await capture('night-test');
    await page.evaluate(async () => { window.weatherPayload.condition = 'rain'; window.reduced = false; await window.engine.refreshWeather(); });
    await page.waitForFunction(() => window.engine.weatherElapsed > 0);
    const elapsed = await page.evaluate(() => window.engine.weatherElapsed);
    await page.waitForTimeout(250);
    assert.ok(await page.evaluate(() => window.engine.weatherElapsed) > elapsed);
    await page.evaluate(() => { window.live = false; window.engine.draw(); });
    const frozen = await page.evaluate(() => window.engine.weatherElapsed);
    await page.waitForTimeout(250);
    assert.equal(await page.evaluate(() => window.engine.weatherElapsed), frozen);
    await page.evaluate(() => { window.reduced = true; window.engine.setReplay(true); window.engine.setReplayMoment('2026-10-08T12:23:00Z'); });
    assert.equal(await page.evaluate(() => window.engine.environment.available), false);
    assert.equal(await page.evaluate(() => window.engine.environment.phase), 'day');
    await page.evaluate(async () => { window.engine.setReplay(false); window.weatherPayload.observed_at_utc = '2026-10-08T20:00:00Z'; await window.engine.refreshWeather(); });
    assert.equal(await page.evaluate(() => window.engine.environment.available), false);
    await page.clock.setFixedTime(new Date('2026-10-08T21:24:00Z'));
    await page.waitForFunction(() => window.engine.environment.clock === '00:24');
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: true }); document.dispatchEvent(new Event('visibilitychange')); });
    assert.equal(await page.evaluate(() => window.engine.environmentTimer + window.engine.tickTimer + window.engine.raf), 0);
    const hiddenReads = reads; await page.waitForTimeout(1100); assert.equal(reads, hiddenReads);
    await page.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); });
    await page.evaluate(() => {
      window.originalFetch = window.engine.options.fetchWeather;
      window.engine.options.fetchWeather = () => new Promise(resolve => { window.finishReading = resolve; });
      window.pendingReading = window.engine.refreshWeather();
    });
    await page.evaluate(() => window.engine.park());
    await page.evaluate(async () => { window.finishReading(window.weatherPayload); await window.pendingReading; window.engine.options.fetchWeather = window.originalFetch; });
    assert.equal(await page.evaluate(() => window.engine.environmentTimer + window.engine.tickTimer + window.engine.raf), 0);
    assert.equal(await page.evaluate(() => window.engine.currentWeather().available), false, 'signed-out context clears cached weather');
    if (observation.available) {
      await page.clock.setFixedTime(new Date());
      await page.evaluate(async data => { window.weatherPayload = data; window.engine.unpark(); await window.engine.refreshWeather(); }, observation);
      await page.waitForFunction(() => window.engine.environment.available);
      await page.setViewportSize({ width: 390, height: 580 });
      await page.waitForTimeout(100);
      await capture('current-mobile');
    }
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
