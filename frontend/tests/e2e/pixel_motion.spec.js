// Real Canvas/control with fixture staff: no backend, OS setting writes or provider calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { chromium } from 'playwright';

const FRONTEND = fileURLToPath(new URL('../..', import.meta.url));
const characters = JSON.parse(readFileSync(path.join(FRONTEND, 'tests/fixtures/pixel_actors_bible.json'), 'utf8'));

test('Windows reduced motion cannot silently freeze the requested scene; pause/resume persists', async () => {
  const built = await build({ root: FRONTEND, configFile: false, publicDir: false, logLevel: 'warn',
    build: { write: false, minify: false, lib: { entry: path.join(FRONTEND, 'tests/fixtures/pixel_motion_entry.js'), name: 'PixelMotionReview', formats: ['iife'] } } });
  const code = (Array.isArray(built) ? built[0] : built).output.find(o => o.type === 'chunk').code;
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ reducedMotion: 'reduce', viewport: { width: 1280, height: 950 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.pathname.startsWith('/assets/pixel/') && !url.pathname.includes('..')) {
        return route.fulfill({ contentType: 'image/png', body: readFileSync(path.join(FRONTEND, 'public', url.pathname)) });
      }
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: `<!doctype html><meta charset="utf-8">
        <style>body{margin:0}canvas{width:100%;aspect-ratio:3/2;image-rendering:pixelated}</style>
        <button id="scene-motion-toggle" aria-label="Animațiile studioului"><span class="switch-state"></span></button><canvas id="office-canvas"></canvas>` });
      return route.abort();
    });
    const mount = async () => {
      await page.addScriptTag({ content: code });
      await page.evaluate(async characters => {
        const { OfficeEngine, bindSceneMotion } = PixelMotionReview;
        window.live = true;
        const motion = bindSceneMotion(document.getElementById('scene-motion-toggle'), () => { window.engine.draw(); window.engine.schedule(); });
        window.engine = new OfficeEngine(document.getElementById('office-canvas'), {
          parked: true, reducedMotion: () => !motion.enabled(), dataLive: () => window.live,
          fetchWeather: async () => ({ available: false }),
        });
        await window.engine.ready;
        window.engine.setCharacterBible(characters);
        window.engine.setAgents(characters.map((c, pixel_slot) => ({ id: c.employee_id, display_name: c.canonical_name,
          role_name: c.role_name, pixel_slot, lifecycle: 'ACTIVE', runtime_state: 'IDLE' })));
        window.engine.unpark();
      }, characters);
    };
    const sample = () => page.evaluate(() => {
      const e = window.engine, frame = PixelMotionReview.streetFrame(e.lifeElapsed, { available: false }, false);
      return { elapsed: e.lifeElapsed, pedestrians: frame.people.map(p => p.x), bicycle: frame.bicycle.x,
        animate: e.agents.map(a => e.motionFor(a).animate) };
    });
    const button = page.getByRole('button', { name: 'Animațiile studioului' });
    await page.goto('http://pixel-motion.invalid/'); await mount();
    assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true);
    assert.equal(await button.getAttribute('aria-pressed'), 'true');
    await page.waitForFunction(() => window.engine.lifeElapsed > 200);
    const first = await sample(); await page.waitForTimeout(650); const moving = await sample();
    assert.ok(moving.elapsed > first.elapsed);
    assert.ok(moving.pedestrians.every((x, i) => x !== first.pedestrians[i]));
    assert.notEqual(moving.bicycle, first.bicycle);
    assert.ok(moving.animate.every(Boolean));
    await button.click();
    await page.waitForFunction(() => !window.engine.tickTimer && !window.engine.raf);
    const paused = await sample(); await page.waitForTimeout(650);
    assert.deepEqual(await sample(), paused);
    await page.reload(); await mount();
    assert.equal(await button.getAttribute('aria-pressed'), 'false');
    await page.waitForTimeout(250); assert.equal((await sample()).elapsed, 0);
    await button.click();
    await page.waitForFunction(() => window.engine.lifeElapsed > 200);
    // Cosmetic permission never overrides the authoritative-data or replay guard.
    await page.evaluate(() => { window.live = false; window.engine.draw(); });
    const stale = await sample(); await page.waitForTimeout(650); assert.deepEqual(await sample(), stale);
    await page.evaluate(() => { window.live = true; window.engine.setReplay(true); });
    const historical = await sample(); await page.waitForTimeout(250); assert.deepEqual(await sample(), historical);
    await page.evaluate(() => window.engine.setReplay(false));
    await page.waitForFunction(previous => window.engine.lifeElapsed > previous, historical.elapsed);
    await page.evaluate(() => window.engine.park());
    assert.equal(await page.evaluate(() => window.engine.environmentTimer + window.engine.tickTimer + window.engine.raf), 0);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
