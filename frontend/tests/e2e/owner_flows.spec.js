// PAGE_SETTINGS_ERRORS (PAGE-15): main.js wires every money key of the page and had no behavioural
// test: the suite could only read it as text. These flows drive the real page in a headless
// Chromium against the real backend, on fakes: scripts/e2e_server.py starts the studio in TEST on
// a free port of 127.0.0.1 (never 8000), with a throwaway database and media folder, every paid
// vendor replaced and no socket allowed beyond this machine, serving the page built here into a
// temporary folder (never frontend/dist).
//
//   npm run test:e2e --prefix frontend
//
// It refuses to start while one of the Owner's games runs (the machine is shared). E2E_DIST may
// name a page already built into a scratch folder, to skip the build.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = fileURLToPath(new URL('../..', import.meta.url));
const ROOT = path.resolve(FRONTEND, '..');
const EVIDENCE = process.env.E2E_EVIDENCE || path.join(ROOT, 'data/pixel-details-backup');
const GAMES = /PathOfExile|League of Legends|LeagueClient/i;

/** Whether one of the Owner's games runs now: the flows wait for another time. */
function gameRunning() {
  try {
    const list = process.platform === 'win32'
      ? execFileSync('tasklist', ['/fo', 'csv', '/nh'], { encoding: 'utf8' })
      : execFileSync('ps', ['-eo', 'comm'], { encoding: 'utf8' });
    return GAMES.test(list);
  } catch {
    return false;
  }
}

const skip = gameRunning() ? 'un joc al Proprietarului rulează: fluxurile din browser așteaptă' : false;
/** @type {{url: string, token: string, storyboard_id: string}} */
let server;
/** @type {import('node:child_process').ChildProcess|null} */
let child = null;
/** @type {import('playwright').Browser|null} */
let browser = null;
let scratch = '';
/** The server's throwaway database and media folder, removed after the flows. */
let world = '';

before(async () => {
  if (skip) return;
  mkdirSync(EVIDENCE, { recursive: true });
  let dist = process.env.E2E_DIST || '';
  if (!dist) {
    scratch = mkdtempSync(path.join(os.tmpdir(), 'amn_e2e_page_'));
    dist = path.join(scratch, 'dist');
    const { build } = await import('vite');
    // into the scratch folder only: frontend/dist is what the Owner's studio serves
    await build({ root: FRONTEND, logLevel: 'warn', build: { outDir: dist, emptyOutDir: true } });
  }
  world = mkdtempSync(path.join(os.tmpdir(), 'amn_e2e_world_'));
  child = spawn('uv', ['run', 'python', 'scripts/e2e_server.py', '--dist', dist, '--folder', world], {
    cwd: ROOT,
    stdio: ['ignore', 'pipe', 'inherit'],
    shell: process.platform === 'win32',
  });
  server = await new Promise((resolve, reject) => {
    let seen = '';
    const timer = setTimeout(() => reject(new Error('the e2e server did not start in 120 s')), 120_000);
    child?.stdout?.on('data', (chunk) => {
      seen += String(chunk);
      const line = seen.split('\n').find((l) => l.trim().startsWith('{'));
      if (line) { clearTimeout(timer); resolve(JSON.parse(line)); }
    });
    child?.on('exit', (code) => { clearTimeout(timer); reject(new Error(`the e2e server ended (${code})`)); });
  });
  const { chromium } = await import('playwright');
  browser = await chromium.launch({ headless: true });
});

after(async () => {
  await browser?.close();
  if (child && child.exitCode === null) {
    if (process.platform === 'win32' && child.pid) {
      try { execFileSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore' }); } catch { /* already gone */ }
    } else {
      child.kill('SIGINT');
    }
  }
  for (const folder of [scratch, world]) {
    if (folder) rmSync(folder, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
  }
});

/** A signed-in page, with every request it sends recorded. */
async function signedIn(prepare = async (_page) => {}) {
  const context = await /** @type {import('playwright').Browser} */ (browser).newContext({ viewport: { width: 1680, height: 1050 } });
  const page = await context.newPage();
  page.on('pageerror', error => console.error('PAGE ERROR:', error.message));
  page.on('console', message => { if (message.type() === 'error') console.error('PAGE CONSOLE:', message.text()); });
  /** @type {{method: string, url: string}[]} */
  const sent = [];
  page.on('request', (request) => sent.push({ method: request.method(), url: request.url() }));
  await prepare(page);
  await page.goto(server.url);
  assert.ok(!sent.some(r => /\/office\/weather/.test(r.url)), 'weather is requested only after sign-in');
  await page.fill('#owner-token', server.token);
  await page.click('#login-form button[type="submit"]');
  await page.waitForSelector('#workspace:not([hidden])', { timeout: 60_000 });
  await page.waitForFunction(() => document.getElementById('studio-name')?.textContent?.trim(), null, { timeout: 60_000 });
  return { context, page, sent };
}

/** The studio's API, called as the page calls it (the flows' own setup, never a vendor). */
async function owner(page, pathName, options = {}) {
  return page.evaluate(async ([url, token, init]) => {
    const response = await fetch(`/api/v1${url}`, { ...init, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
    return { status: response.status, body: await response.json().catch(() => null) };
  }, [pathName, server.token, options]);
}

/** Opens the film's sheet from the media room's card. */
async function openSheet(page) {
  await page.click('#open-media-btn');
  const key = page.locator(`.btn-shooting-sheet[data-id="${server.storyboard_id}"]`);
  await key.waitFor({ state: 'visible', timeout: 30_000 });
  await key.click();
  await page.waitForSelector('#shooting-sheet-drawer[open] .sheet-step', { timeout: 60_000 });
}

test('signing in with the generated test key shows the studio', { skip }, async () => {
  const { context, page } = await signedIn();
  assert.ok(await page.isVisible('#workspace'));
  await context.close();
});

test('pixel studio: real staff, keyboard selection, autonomy settings and responsive scene', { skip }, async () => {
  const { context, page, sent } = await signedIn();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.screenshot({ path: path.join(EVIDENCE, 'pixel-before-check.png'), fullPage: true });
  await page.waitForSelector('#pixel-roster button', { timeout: 30_000 });
  const snapshot = await owner(page, '/snapshot');
  const staff = await page.locator('#pixel-roster button').count();
  assert.ok(staff > 0);
  assert.equal(await page.locator('#open-treasury-btn, #treasury-modal').count(), 0);
  assert.equal(Object.hasOwn(snapshot.body.modules, 'treasury'), false);
  assert.ok(!sent.some(r => /\/assets\/hq\/|\/office\/stream|\/economy\/treasury/.test(r.url)));
  await page.waitForFunction(() => window.__studio.engine.weatherReceivedAt > 0);
  assert.ok(sent.some(r => r.method === 'GET' && r.url === `${server.url}/api/v1/office/weather`));
  await page.locator('#office-canvas').focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Enter');
  await page.waitForSelector('#agent-inspector[open]');
  assert.ok(await page.locator('#inspector-name').textContent().catch(() => 'selected'));
  await page.keyboard.press('Escape');
  await page.waitForSelector('#agent-inspector[open]', { state: 'detached' });
  const person = await page.evaluate(() => {
    const engine = window.__studio.engine;
    const agent = engine.positions[0];
    const point = engine.viewport.worldToScreen(agent.x, agent.y - 28);
    const box = engine.canvas.getBoundingClientRect();
    return { name: agent.agent.display_name, x: box.left + point.x / engine.dpr, y: box.top + point.y / engine.dpr };
  });
  await page.mouse.click(person.x, person.y);
  await page.waitForSelector('#agent-inspector[open]');
  assert.equal((await page.locator('#inspector-name').textContent()).trim(), person.name);
  await page.keyboard.press('Escape');
  await page.waitForSelector('#agent-inspector[open]', { state: 'detached' });
  await page.click('#open-autonomy-btn');
  await page.waitForSelector('#autonomy-modal[open] .autonomy-summary');
  await page.click('[data-autonomy-go="providers"]');
  await page.waitForSelector('dialog.settings-dialog[open]');
  await page.keyboard.press('Escape');
  await page.waitForSelector('dialog.settings-dialog[open]', { state: 'detached' });
  await page.click('#open-autonomy-btn');
  await page.waitForSelector('#autonomy-modal[open] .autonomy-summary');
  await page.screenshot({ path: path.join(EVIDENCE, 'autonomy-desktop.png'), fullPage: true });
  await page.click('#autonomy-modal a[href="#autonomy-budget"]');
  await page.locator('#budget-form').scrollIntoViewIfNeeded();
  await page.waitForSelector('#budget-form');
  await page.click('#autonomy-modal a[href="#autonomy-overview"]');
  await page.click('[data-autonomy-go="policy"]');
  await page.waitForSelector('#autonomy-modal[open]', { state: 'detached' });
  await page.waitForSelector('#autonomy-mode-buttons', { state: 'visible' });
  assert.ok(await page.locator('#autonomy-mode-buttons').isVisible());
  await page.click('#open-autonomy-btn');
  await page.waitForSelector('#autonomy-modal[open] .autonomy-summary');
  await page.click('[data-autonomy-go="schedule"]');
  await page.waitForSelector('#runbook-modal[open]');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#runbook-modal[open]', { state: 'detached' });
  await page.click('#open-autonomy-btn');
  await page.waitForSelector('#autonomy-modal[open] .autonomy-summary');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#autonomy-modal[open]', { state: 'detached' });
  await page.waitForTimeout(400);
  await page.click('#side-close');
  await page.waitForSelector('html[data-side="closed"]');
  await page.waitForTimeout(500);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(EVIDENCE, 'pixel-studio-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.waitForTimeout(350);
  assert.ok((await page.locator('#open-autonomy-btn svg').boundingBox()).width <= 32);
  assert.ok(await page.evaluate(() => document.getElementById('office-canvas').getBoundingClientRect().width <= window.innerWidth));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
  await page.locator('#pixel-roster button').first().click();
  await page.waitForSelector('#agent-inspector[open]');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#agent-inspector[open]', { state: 'detached' });
  await page.waitForTimeout(400);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(EVIDENCE, 'pixel-studio-mobile.png'), fullPage: true });
  assert.deepEqual(errors, []);
  await context.close();
});

test('personal desks: committed backend states, seated gestures, annex selection and stale-data freeze', { skip }, async () => {
  const { context, page } = await signedIn();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.waitForSelector('#office-status[data-state="live"]', { timeout: 30_000 });
  await page.waitForFunction(() => window.__studio?.engine.characters.size >= 8);
  const seats = await page.evaluate(() => window.__studio.engine.positions.map(p => ({ id: p.id, deskId: p.deskId, slot: p.slot, page: p.page, x: p.x, y: p.y, role: p.agent.role_name })));
  assert.equal(seats.length, 10);
  assert.equal(new Set(seats.map(p => p.deskId)).size, 10);
  assert.equal(new Set(seats.map(p => `${p.page}:${p.x}:${p.y}`)).size, 10);
  const researcher = seats.find(p => p.role === 'LeadResearcher');
  assert.ok(researcher);
  assert.equal(await page.evaluate(id => window.__studio.engine.characters.has(id), researcher.id), true);
  for (const runtime_state of ['WORKING', 'THINKING', 'REVIEWING', 'BLOCKED', 'ERROR', 'IDLE']) {
    const changed = await owner(page, '/e2e/agent-state', { method: 'POST', body: JSON.stringify({ agent_id: researcher.id, runtime_state }) });
    assert.equal(changed.status, 200, JSON.stringify(changed.body));
    await page.waitForFunction(([id, mode]) => window.__studio.engine.agents.find(a => a.id === id)?.runtime_state === mode, [researcher.id, runtime_state]);
    const pose = await page.evaluate(id => { const e = window.__studio.engine; return e.motionFor(e.agents.find(a => a.id === id)); }, researcher.id);
    assert.equal(pose.mode, runtime_state);
    assert.equal(pose.animate, ['WORKING', 'THINKING', 'REVIEWING', 'IDLE'].includes(runtime_state));
    assert.equal(await page.locator(`#pixel-roster [data-agent="${researcher.id}"]`).getAttribute('data-state'), runtime_state);
  }
  const paused = await owner(page, `/agents/${researcher.id}/pause`, { method: 'POST' });
  assert.equal(paused.status, 200);
  await page.waitForFunction(id => window.__studio.engine.agents.find(a => a.id === id)?.lifecycle === 'PAUSED', researcher.id);
  assert.equal(await page.evaluate(id => { const e = window.__studio.engine; return e.motionFor(e.agents.find(a => a.id === id)).animate; }, researcher.id), false);
  assert.equal((await owner(page, `/agents/${researcher.id}/resume`, { method: 'POST' })).status, 200);
  await page.waitForFunction(id => window.__studio.engine.agents.find(a => a.id === id)?.lifecycle === 'ACTIVE', researcher.id);
  const extra = seats.find(p => p.page === 1);
  await page.locator(`#pixel-roster [data-agent="${extra.id}"]`).click();
  await page.waitForSelector('#agent-inspector[open]');
  assert.equal(await page.evaluate(() => window.__studio.engine.page), 1);
  assert.equal(await page.locator('#pixel-office-pages [aria-pressed="true"]').textContent(), 'Birouri suplimentare 1');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#agent-inspector[open]', { state: 'detached' });
  await page.locator('#pixel-office-pages button').first().click();
  assert.equal(await page.evaluate(() => window.__studio.engine.page), 0);
  // Set different actual test records, then observe their WebSocket projection together.
  const primary = seats.filter(p => p.page === 0);
  for (const [i, seat] of primary.entries()) {
    const runtime_state = ['THINKING', 'WORKING', 'REVIEWING', 'IDLE'][i % 4];
    assert.equal((await owner(page, '/e2e/agent-state', { method: 'POST', body: JSON.stringify({ agent_id: seat.id, runtime_state }) })).status, 200);
    await page.waitForFunction(([id, mode]) => window.__studio.engine.agents.find(a => a.id === id)?.runtime_state === mode, [seat.id, runtime_state]);
  }
  const same = await page.evaluate(() => window.__studio.engine.positions.map(p => ({ id: p.id, deskId: p.deskId, slot: p.slot, page: p.page, x: p.x, y: p.y, role: p.agent.role_name })));
  assert.deepEqual(same, seats);
  assert.equal(await page.evaluate(() => window.__studio.engine.pixelLayout.floor_count), 3);
  assert.equal(await page.evaluate(() => window.__studio.engine.visiblePositions().every(p => p.orientation === 'back')), true);
  // The library, lounge and original editing screens keep their actual illustrated pixels.
  const retained = await page.evaluate(() => {
    const e = window.__studio.engine;
    const expected = document.createElement('canvas');
    expected.width = e.canvas.width; expected.height = e.canvas.height;
    const c = expected.getContext('2d'); c.imageSmoothingEnabled = false;
    const v = e.viewport; c.setTransform(v.zoom, 0, 0, v.zoom, v.panX, v.panY);
    c.drawImage(e.background, 0, 0, e.worldW, e.worldH);
    return [{ x: 212, y: 254, w: 89, h: 74 }, { x: 630, y: 427, w: 173, h: 89 }, { x: 260, y: 442, w: 87, h: 18 }].map(r => {
      const x = Math.ceil(r.x * v.zoom + v.panX), y = Math.ceil(r.y * v.zoom + v.panY);
      const w = Math.floor(r.w * v.zoom), h = Math.floor(r.h * v.zoom);
      const before = c.getImageData(x, y, w, h).data;
      const after = e.ctx.getImageData(x, y, w, h).data;
      return before.every((value, index) => value === after[index]);
    });
  });
  assert.deepEqual(retained, [true, true, true], 'approved furniture is visible, without generic desk overlays');
  assert.equal(await page.evaluate(async () => {
    const canvas = document.getElementById('office-canvas');
    const first = canvas.toDataURL();
    await new Promise(resolve => setTimeout(resolve, 550));
    return first !== canvas.toDataURL();
  }), true, 'the live seated gestures actually paint changing frames');
  if (await page.isVisible('#side-close')) await page.click('#side-close');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(EVIDENCE, 'seated-agents-desktop.png'), fullPage: true });
  await page.locator(`#pixel-roster [data-agent="${researcher.id}"]`).click();
  await page.waitForSelector('#agent-inspector[open]');
  await page.waitForTimeout(750);
  assert.equal((await owner(page, '/e2e/agent-state', { method: 'POST', body: JSON.stringify({ agent_id: researcher.id, runtime_state: 'THINKING' }) })).status, 200);
  await page.waitForSelector('#inspector-state[data-state="THINKING"]');
  assert.equal(await page.locator('#inspector-head').getAttribute('data-state'), 'THINKING');
  await page.screenshot({ path: path.join(EVIDENCE, 'seated-agent-inspector.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await page.waitForSelector('#agent-inspector[open]', { state: 'detached' });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.equal(await page.evaluate(() => window.__studio.engine.agents.some(a => window.__studio.engine.motionFor(a).animate)), false);
  await page.waitForFunction(() => !window.__studio.engine.tickTimer && !window.__studio.engine.raf);
  assert.equal(await page.evaluate(async () => {
    const canvas = document.getElementById('office-canvas');
    const first = canvas.toDataURL();
    await new Promise(resolve => setTimeout(resolve, 250));
    return first === canvas.toDataURL();
  }), true, 'reduced motion paints a stable scene');
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.route('**/api/v1/snapshot', route => route.abort('failed'));
  await page.waitForSelector('#office-status[data-state="stale"]', { timeout: 20_000 });
  assert.equal(await page.evaluate(() => window.__studio.engine.agents.some(a => window.__studio.engine.motionFor(a).animate)), false);
  await page.unroute('**/api/v1/snapshot');
  await page.waitForSelector('#office-status[data-state="live"]', { timeout: 20_000 });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.waitForTimeout(400);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
  await page.screenshot({ path: path.join(EVIDENCE, 'seated-agents-mobile.png'), fullPage: true });
  assert.deepEqual(errors, []);
  await context.close();
});

test('outdoor clock and weather: real endpoint, day/night, rain/fog/snow, freshness and lifecycle', { skip }, async () => {
  let payload = { available: false, reason: 'not_configured' };
  let reads = 0;
  const { context, page } = await signedIn(async page => {
    await page.route('**/api/v1/office/weather', async route => {
      assert.ok(route.request().headers().authorization?.startsWith('Bearer '));
      reads++;
      await route.fulfill({ json: payload });
    });
  });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.waitForSelector('#office-status[data-state="live"]');
    await page.waitForFunction(() => window.__studio.engine.weatherReceivedAt > 0);
    assert.equal(await page.evaluate(() => window.__studio.engine.environment.available), false);
    if (await page.isVisible('#side-close')) await page.click('#side-close');
    await page.emulateMedia({ reducedMotion: 'reduce' });

    const stamp = new Date('2026-10-08T12:23:00Z');
    await page.clock.setFixedTime(stamp);
    for (const condition of ['clear', 'rain', 'fog', 'snow', 'storm']) {
      payload = { available: true, condition, intensity: 0.8, temperature_c: condition === 'snow' ? -2 : 14,
        observed_at: '2026-10-08T15:15', observed_at_utc: '2026-10-08T12:15:00Z', source: 'browser-test-fixture' };
      await page.evaluate(() => window.__studio.engine.refreshWeather());
      const state = await page.evaluate(() => window.__studio.engine.environment);
      assert.equal(state.clock, '15:23'); assert.equal(state.phase, 'day'); assert.equal(state.weather, condition);
      assert.equal(state.animating, false, 'reduced motion keeps weather still');
      const retained = await page.evaluate(() => {
        const e = window.__studio.engine, expected = document.createElement('canvas');
        expected.width = e.canvas.width; expected.height = e.canvas.height;
        const c = expected.getContext('2d'), v = e.viewport; c.imageSmoothingEnabled = false;
        c.setTransform(v.zoom, 0, 0, v.zoom, v.panX, v.panY); c.drawImage(e.background, 0, 0, e.worldW, e.worldH);
        return [{ x: 212, y: 254, w: 89, h: 74 }, { x: 630, y: 427, w: 173, h: 89 }].every(r => {
          const x = Math.ceil(r.x * v.zoom + v.panX), y = Math.ceil(r.y * v.zoom + v.panY);
          const w = Math.floor(r.w * v.zoom), h = Math.floor(r.h * v.zoom);
          const a = c.getImageData(x, y, w, h).data, b = e.ctx.getImageData(x, y, w, h).data;
          return a.every((value, i) => value === b[i]);
        });
      });
      assert.equal(retained, true, `${condition} preserves the furnished interior pixels`);
      await page.screenshot({ path: path.join(EVIDENCE, `weather-${condition}-test.png`), fullPage: true });
    }
    const outside = () => page.evaluate(() => {
      const e = window.__studio.engine, p = e.viewport.worldToScreen(20, 20);
      return Array.from(e.ctx.getImageData(Math.round(p.x), Math.round(p.y), 1, 1).data).slice(0, 3).reduce((a, b) => a + b, 0);
    });
    const dayLight = await outside();
    await page.clock.setFixedTime(new Date('2026-10-08T21:23:00Z'));
    payload = { ...payload, condition: 'clear', observed_at_utc: '2026-10-08T21:15:00Z' };
    await page.evaluate(() => window.__studio.engine.refreshWeather());
    assert.equal(await page.evaluate(() => window.__studio.engine.environment.clock), '00:23');
    assert.equal(await page.evaluate(() => window.__studio.engine.environment.phase), 'night');
    assert.ok(await outside() < dayLight, 'night actually darkens the exterior');
    await page.screenshot({ path: path.join(EVIDENCE, 'weather-night-test.png'), fullPage: true });

    payload = { ...payload, condition: 'rain' };
    await page.evaluate(() => window.__studio.engine.refreshWeather());
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.waitForFunction(() => window.__studio.engine.environment.animating);
    const first = await page.evaluate(() => window.__studio.engine.weatherElapsed);
    await page.waitForTimeout(250);
    assert.ok(await page.evaluate(() => window.__studio.engine.weatherElapsed) > first);
    // A hidden document pauses its timers and does not request weather, even when time advances.
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    assert.equal(await page.evaluate(() => window.__studio.engine.environmentTimer + window.__studio.engine.tickTimer + window.__studio.engine.raf), 0);
    const hiddenReads = reads;
    await page.clock.setFixedTime(new Date('2026-10-08T21:24:00Z'));
    await page.waitForTimeout(1100);
    assert.equal(reads, hiddenReads);
    await page.evaluate(() => {
      delete document.hidden; document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.waitForFunction(() => window.__studio.engine.environment.clock === '00:24');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    payload = { ...payload, observed_at_utc: '2026-10-08T20:00:00Z' };
    await page.evaluate(() => window.__studio.engine.refreshWeather());
    assert.equal(await page.evaluate(() => window.__studio.engine.environment.available), false, 'old observations never masquerade as current rain');
    payload = { available: false, reason: 'unreachable' };
    await page.evaluate(() => window.__studio.engine.refreshWeather());
    assert.match(await page.locator('#scene-info').textContent(), /indisponibil/);
    await page.evaluate(() => { window.__studio.engine.setReplay(true); window.__studio.engine.setReplayMoment('2026-10-08T12:23:00Z'); });
    assert.equal(await page.evaluate(() => window.__studio.engine.environment.phase), 'day');
    assert.match(await page.locator('#scene-info').textContent(), /atunci: necunoscută/);
    await page.evaluate(() => window.__studio.engine.setReplay(false));

    // This capture uses the actual configured provider observation saved by the read-only probe.
    if (process.env.E2E_REAL_WEATHER) {
      payload = JSON.parse(readFileSync(process.env.E2E_REAL_WEATHER, 'utf8')).observation;
      await page.clock.setFixedTime(new Date());
      await page.evaluate(() => window.__studio.engine.refreshWeather());
      assert.equal(await page.evaluate(() => window.__studio.engine.environment.weather), payload.condition);
      await page.screenshot({ path: path.join(EVIDENCE, 'weather-current-desktop.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(350);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
      await page.screenshot({ path: path.join(EVIDENCE, 'weather-current-mobile.png'), fullPage: true });
    }
    await page.click('#logout');
    assert.equal(await page.evaluate(() => window.__studio.engine.environmentTimer + window.__studio.engine.tickTimer + window.__studio.engine.raf), 0);
    const parkedReads = reads;
    await page.waitForTimeout(1100);
    assert.equal(reads, parkedReads);
    assert.deepEqual(errors, []);
  } finally { await context.close(); }
});

test('the sheet opens from the media room, and a step asks before anything is sent', { skip }, async () => {
  const { context, page, sent } = await signedIn();
  await openSheet(page);
  const before = sent.filter((r) => r.method === 'POST' && /\/steps\//.test(r.url)).length;
  await page.click('#shooting-sheet-drawer [data-sheet-action="step"][data-step="stills"]');
  await page.waitForSelector('#shooting-sheet-drawer [data-sheet-action="confirm-step"][data-step="stills"]');
  assert.equal(sent.filter((r) => r.method === 'POST' && /\/steps\//.test(r.url)).length, before, 'the first press only asks');
  // «Nu acum» sends nothing either
  await page.click('#shooting-sheet-drawer [data-sheet-action="cancel-step"]');
  assert.equal(sent.filter((r) => r.method === 'POST' && /\/steps\//.test(r.url)).length, before);
  await context.close();
});

test('an approval card names the film and opens its sheet instead of a bare «Aprobă»', { skip }, async () => {
  const { context, page } = await signedIn();
  // the studio asks him: a step pressed without his yes answers 202 with a pending question
  const sheet = await owner(page, `/media/storyboards/${server.storyboard_id}/shooting-sheet`);
  const asked = await owner(page, `/media/storyboards/${server.storyboard_id}/steps/stills`, {
    method: 'POST', body: JSON.stringify({ plan_hash: sheet.body.sheet_hash }),
  });
  assert.equal(asked.status, 202, JSON.stringify(asked.body).slice(0, 300));
  if (await page.isVisible('#side-rail')) await page.click('#side-rail');
  await page.click('#refresh-approvals-btn');
  const card = page.locator('#approvals-list [data-sheet-open]').first();
  await card.waitFor({ state: 'visible', timeout: 30_000 });
  assert.equal(await page.locator('#approvals-list button:has-text("Aprobă")').count(), 0, 'a paid step is answered on the sheet');
  await card.click();
  await page.waitForSelector('#shooting-sheet-drawer[open] .sheet-step', { timeout: 30_000 });
  await context.close();
});

test('Esc during a step does not hide the purchase in flight', { skip }, async () => {
  const { context, page } = await signedIn();
  // the step's answer is held back two seconds, so Esc lands while it is in flight
  await page.route('**/api/v1/media/storyboards/*/steps/stills', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    await route.continue();
  });
  await openSheet(page);
  await page.click('#shooting-sheet-drawer [data-sheet-action="step"][data-step="stills"]');
  await page.click('#shooting-sheet-drawer [data-sheet-action="confirm-step"][data-step="stills"]');
  await page.waitForSelector('#shooting-sheet-drawer [data-sheet-status]:not([hidden])');
  await page.keyboard.press('Escape');
  assert.ok(await page.isVisible('#shooting-sheet-drawer[open]'), 'the drawer stays open while buying');
  assert.match(await page.textContent('#shooting-sheet-drawer [data-sheet-status]') || '', /Se cumpără/);
  // the step buttons stay disabled while it buys
  assert.equal(await page.locator('#shooting-sheet-drawer .sheet-step:not([disabled])').count(), 0);
  // the answer arrives (the fakes bought it with his yes) and is said on the same status line
  await page.waitForFunction(() => !/Se cumpără/.test(document.querySelector('#shooting-sheet-drawer [data-sheet-status]')?.textContent || ''), null, { timeout: 60_000 });
  assert.ok(await page.isVisible('#shooting-sheet-drawer[open]'));
  await context.close();
});

test('his paid-step rule: a stale version is refused and reloaded, then saved', { skip }, async () => {
  const { context, page } = await signedIn();
  if (await page.isVisible('#side-rail')) await page.click('#side-rail');
  await page.click('.governance-rule-box summary');
  await page.waitForSelector('#paid-media-governance input[name="paid-media"][value="MODE"]');
  await page.check('#paid-media-governance input[name="paid-media"][value="MODE"]');
  // someone else changes the rule after the page read it: the page's version is now stale
  const snapshot = await owner(page, '/snapshot');
  const version = snapshot.body.policy.version;
  const moved = await owner(page, '/owner/paid-media-approval', {
    method: 'POST',
    body: JSON.stringify({ schema_version: 1, command_id: crypto.randomUUID(), expected_version: version, paid_media_approval: 'OVER_USD', over_usd: 5 }),
  });
  assert.equal(moved.status, 200, JSON.stringify(moved.body));
  await page.click('#paid-media-governance [data-sheet-action="paid-media-save"]');
  await page.waitForSelector('#autonomy-mode-note:not([hidden])');
  assert.match(await page.textContent('#autonomy-mode-note') || '', /s-a schimbat între timp/);
  // the page read the rule again: saving now goes through
  await page.waitForFunction(() => !document.querySelector('#paid-media-governance [data-sheet-action="paid-media-save"]')?.hasAttribute('disabled'));
  await page.check('#paid-media-governance input[name="paid-media"][value="MODE"]');
  await page.click('#paid-media-governance [data-sheet-action="paid-media-save"]');
  await page.waitForFunction(() => /Salvat/.test(document.getElementById('autonomy-mode-note')?.textContent || ''), null, { timeout: 30_000 });
  await context.close();
});

test('an empty budget is refused before anything is sent', { skip }, async () => {
  const { context, page, sent } = await signedIn();
  await page.click('#open-autonomy-btn');
  await page.click('#autonomy-modal a[href="#autonomy-budget"]');
  await page.waitForSelector('#budget-limit', { state: 'visible', timeout: 30_000 });
  await page.fill('#budget-limit', '');
  await page.click('#budget-form button[type="submit"]');
  await page.fill('#budget-limit', '0');
  await page.click('#budget-form button[type="submit"]');
  await page.waitForTimeout(500);
  assert.equal(sent.filter((r) => r.method !== 'GET' && /\/economy\/budget/.test(r.url)).length, 0, 'nothing was sent');
  assert.equal(await page.$eval('#budget-limit', (el) => /** @type {HTMLInputElement} */ (el).validity.valid), false);
  await context.close();
});

test('Setări → Canale: public in TEST is refused in the studio words; unlisted is asked, then saved', { skip }, async () => {
  const { context, page, sent } = await signedIn();
  await page.click('#open-settings');
  await page.click('#settings-dialog button:has-text("Canale")');
  const plate = page.locator('#settings-dialog .channel-plate', { hasText: 'Channel A' }).first();
  await plate.waitFor({ state: 'visible', timeout: 30_000 });
  const posts = () => sent.filter((r) => r.method === 'POST' && /\/publish-policy$/.test(r.url)).length;
  await plate.locator('select[id^="policy-privacy-"]').selectOption('public');
  await plate.locator('input[id^="policy-public-"]').check();
  await plate.locator('button:has-text("Schimbă politica")').click();
  // the question names the change; nothing is sent before «Da»
  await page.waitForSelector('#settings-dialog .owner-confirm-question');
  assert.match(await page.textContent('#settings-dialog .owner-confirm-question') || '', /privat → public/);
  assert.equal(posts(), 0);
  await page.click('#settings-dialog button:has-text("Da, schimbă politica")');
  const refused = page.locator('#settings-dialog .owner-answer.settings-error');
  await refused.waitFor({ state: 'visible', timeout: 30_000 });
  const words = await refused.textContent() || '';
  assert.match(words, /TEST|PRODUCTION/, words);
  assert.doesNotMatch(words, /Conexiunea nu a putut fi verificată/);
  assert.equal(posts(), 1);
  // unlisted is allowed in TEST
  const again = page.locator('#settings-dialog .channel-plate', { hasText: 'Channel A' }).first();
  await again.locator('select[id^="policy-privacy-"]').selectOption('unlisted');
  await again.locator('input[id^="policy-public-"]').uncheck();
  await again.locator('button:has-text("Schimbă politica")').click();
  await page.click('#settings-dialog button:has-text("Da, schimbă politica")');
  await page.waitForFunction(() => /Salvat\. .*nelistat/.test(document.querySelector('#settings-dialog .owner-answer')?.textContent || ''), null, { timeout: 30_000 });
  await context.close();
});

test('a card accepted in the window: «Decizii» opens his window, the card moves to «Istoric»', { skip }, async () => {
  const { context, page, sent } = await signedIn();
  // the studio seeded the audit's questions at startup; one whose recommended answer changes nothing
  const feed = await owner(page, '/owner/decision-cards');
  assert.equal(feed.status, 200, JSON.stringify(feed.body).slice(0, 300));
  const card = feed.body.cards.find((/** @type {any} */ c) => c.source_type === 'decision' && c.status === 'PENDING'
    && c.options.some((/** @type {any} */ o) => o.recommended && ['none', 'record'].includes(o.apply_type)));
  assert.ok(card, 'a seeded card whose recommended answer applies nothing');
  // the key in the top bar shows what waits for him
  await page.waitForSelector('#decisions-button:not([hidden])');
  await page.waitForFunction(() => document.getElementById('decisions-badge')?.textContent?.trim() !== '', null, { timeout: 30_000 });
  await page.click('#decisions-button');
  await page.waitForSelector('#decisions-window[open]');
  const article = page.locator(`#decisions-window article[data-card="${card.card_id}"]`);
  await article.waitFor({ state: 'visible', timeout: 30_000 });
  assert.match(await article.textContent() || '', /Recomandat/);
  await article.locator('[data-decision-action="accept"]').click();
  // his answer went to the card's own route, once
  await page.waitForFunction((id) => !document.querySelector(`#decisions-window article[data-card="${id}"]`), card.card_id, { timeout: 30_000 });
  assert.equal(sent.filter((r) => r.method === 'POST' && r.url.endsWith(`/owner/decisions/${card.id}/decide`)).length, 1);
  assert.match(await page.textContent('#decisions-window [data-decisions-status]') || '', /Ai ales/);
  // the history keeps it, with what it applied
  await page.click('#decisions-window [data-decisions-tab="history"]');
  const closed = page.locator(`#decisions-window article[data-card="${card.card_id}"]`);
  await closed.waitFor({ state: 'visible', timeout: 30_000 });
  assert.match(await closed.textContent() || '', /acceptat/);
  // Esc closes the window and gives the focus back to the key
  await page.keyboard.press('Escape');
  await page.waitForSelector('#decisions-window:not([open])', { state: 'attached' });
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'decisions-button');
  await context.close();
});
