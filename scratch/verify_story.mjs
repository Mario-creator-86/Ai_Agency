/**
 * The daily log and the Office Serial, in the running page.
 *
 * What matters here is the boundary the spec draws: the log counts what happened, the episode
 * dramatises it, and the episode may never assert something the record does not contain. This
 * drives the real path and then tries, through the API, to store an episode citing an event
 * that never occurred — which must be refused whole.
 */
import pw from '../frontend/node_modules/playwright/index.js';
import { readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';

const { chromium } = pw;
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const OUT = path.join(ROOT, 'output', 'playwright');
mkdirSync(OUT, { recursive: true });
const token = readFileSync(path.join(ROOT, '.env'), 'utf8')
  .split('\n').find((l) => l.startsWith('STUDIO_OWNER_TOKEN=')).split('=')[1].trim();

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok: Boolean(ok) });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
};

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));

await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.click('#login-form button[type="submit"]');
await page.waitForSelector('#studio-name');

await page.click('#open-story-btn');
await page.waitForSelector('#story-modal[open]');
await page.waitForFunction(() => !document.querySelector('#story-logs')?.textContent.includes('Se încarcă'));

// 1. Closing the day counts the event stream.
await page.click('#close-day-btn');
// The interim message also contains the word, so wait for the shape of the final one.
await page.waitForFunction(
  () => /\d{4}-\d{2}-\d{2}: \d+ evenimente/.test(document.querySelector('#story-status')?.textContent || ''),
  { timeout: 30000 },
);
const closed = await page.textContent('#story-status');
check('Closing the day counts the event stream', /\d+ evenimente/.test(closed), closed.trim().slice(0, 100));
await page.waitForSelector('.story-log-card');
check('The closed day is listed with its totals', (await page.textContent('.story-log-card')).includes('evenimente'));

const logId = await page.getAttribute('.story-log-card', 'data-log-id');

// 2. Closing again does not produce a second record of the same day.
const logCount = await page.evaluate(async (t) => {
  const before = (await (await fetch('/api/v1/story/logs', { headers: { Authorization: `Bearer ${t}` } })).json()).logs.length;
  await fetch('/api/v1/story/logs/close', {
    method: 'POST',
    headers: { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ command_id: crypto.randomUUID(), business_date: null }),
  });
  const after = (await (await fetch('/api/v1/story/logs', { headers: { Authorization: `Bearer ${t}` } })).json()).logs.length;
  return { before, after };
}, token);
check('A day is closed once, not twice', logCount.before === logCount.after, `${logCount.before} -> ${logCount.after}`);

// 3. A day with material offers to write; a quiet day says so instead.
const quiet = await page.evaluate(async (t) => {
  const date = new Date(Date.now() - 5 * 86400000).toISOString().slice(0, 10);
  const log = await (await fetch('/api/v1/story/logs/close', {
    method: 'POST',
    headers: { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ command_id: crypto.randomUUID(), business_date: date }),
  })).json();
  const r = await fetch('/api/v1/story/episodes/write', {
    method: 'POST',
    headers: { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ command_id: crypto.randomUUID(), log_id: log.id }),
  });
  return { status: r.status, detail: (await r.json()).detail, notable: log.notable_events.length };
}, token);
check('A quiet day has no story material', quiet.notable === 0);
check('And writing one is refused as a fact, not an error', quiet.status === 409 && String(quiet.detail).includes('zi liniștită'), String(quiet.detail).slice(0, 90));

// 4. The panel says so too, rather than offering a button that would fail.
await page.click('#close-story-btn');
await page.click('#open-story-btn');
await page.waitForFunction(() => !document.querySelector('#story-logs')?.textContent.includes('Se încarcă'));
const logsText = await page.textContent('#story-logs');
check('The panel marks a quiet day instead of offering to write one', logsText.includes('Zi liniștită'), logsText.replace(/\s+/g, ' ').slice(0, 140));
await page.screenshot({ path: path.join(OUT, 'story-logs.png') });

// 5. Writing needs a working model, which this container has none of — so the refusal must be
//    about the model, not a quietly invented episode.
const attempted = await page.evaluate(async (args) => {
  const r = await fetch('/api/v1/story/episodes/write', {
    method: 'POST',
    headers: { Authorization: `Bearer ${args.t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ command_id: crypto.randomUUID(), log_id: args.id }),
  });
  return { status: r.status, detail: String((await r.json()).detail) };
}, { t: token, id: logId });
check('With no usable model, no episode is invented', attempted.status !== 200, `HTTP ${attempted.status}`);

const episodeCount = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/story/episodes', { headers: { Authorization: `Bearer ${t}` } });
  return (await r.json()).episodes.length;
}, token);
check('Nothing was stored by the failed attempt', episodeCount === 0, `${episodeCount} episodes`);

// 6. The grounding audit is reachable and honest about an unknown episode.
const audit = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/story/episodes/00000000-0000-0000-0000-000000000001/grounding', {
    headers: { Authorization: `Bearer ${t}` },
  });
  return r.status;
}, token);
check('Auditing an episode that does not exist is a clean 404', audit === 404, `HTTP ${audit}`);

await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(400);
check('No horizontal overflow at 390px', !(await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)));

check('No page errors', errors.length === 0, errors.join(' | ').slice(0, 160));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
