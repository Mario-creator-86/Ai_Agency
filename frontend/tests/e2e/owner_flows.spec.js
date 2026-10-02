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
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = fileURLToPath(new URL('../..', import.meta.url));
const ROOT = path.resolve(FRONTEND, '..');
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
async function signedIn() {
  const context = await /** @type {import('playwright').Browser} */ (browser).newContext({ viewport: { width: 1680, height: 1050 } });
  const page = await context.newPage();
  /** @type {{method: string, url: string}[]} */
  const sent = [];
  page.on('request', (request) => sent.push({ method: request.method(), url: request.url() }));
  await page.goto(server.url);
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
  await page.click('#open-treasury-btn');
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
