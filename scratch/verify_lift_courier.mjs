/**
 * The lift must be still when nothing moves, and must carry a visible courier when the
 * backend moves a workflow token between floors. Checked in the running page by pushing
 * real `workflow.running` domain events through the office state, exactly as the WebSocket
 * does, and reading the engine's own trip state back.
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
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));

await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.click('#login-form button[type="submit"]');
await page.waitForSelector('#studio-name');
await page.waitForTimeout(2500);

const engineReady = await page.evaluate(() => Boolean(window.__studio?.engine));
check('The office engine is reachable for inspection', engineReady);
if (!engineReady) {
  await browser.close();
  process.exit(1);
}

// 1. Nothing is happening: the cab must be standing still.
const still = await page.evaluate(async () => {
  const e = window.__studio.engine;
  const before = e.lift.y;
  await new Promise((r) => setTimeout(r, 2500));
  return { before, after: e.lift.y, trip: e.lift.trip, moving: e.lift.moving };
});
check('The cab is still while no token moves', still.before === still.after && !still.moving,
  `y ${still.before} -> ${still.after}`);
check('Nobody is riding an idle cab', still.trip === null);

// 2. A workflow token appears on one floor, then moves to another.
const dispatched = await page.evaluate(async () => {
  const { state, engine } = window.__studio;
  const push = (stage) =>
    state.handleDomainEvent({
      event_type: 'workflow.running',
      aggregate_id: 'wf_demo',
      payload: { current_stage: stage },
    });
  push('PUBLISHING');            // ground floor
  engine.setProjectTokens(state.projectTokens);
  await new Promise((r) => setTimeout(r, 400));
  const parked = { y: engine.lift.y, trip: engine.lift.trip };

  push('RESEARCH');              // floor 3
  engine.setProjectTokens(state.projectTokens);
  await new Promise((r) => setTimeout(r, 200));
  return { parked, trip: engine.lift.trip && { ...engine.lift.trip } };
});
check('Seeing a token for the first time does not start the lift', dispatched.parked.trip === null);
check('A token changing floor dispatches a courier', Boolean(dispatched.trip),
  dispatched.trip ? `phase ${dispatched.trip.phase}` : 'no trip');

// 3. Watch the delivery run through its stages, capturing a frame from each.
const phases = new Set();
for (let i = 0; i < 90; i += 1) {
  const phase = await page.evaluate(() => window.__studio.engine.lift.trip?.phase ?? null);
  if (phase && !phases.has(phase)) {
    phases.add(phase);
    await page.locator('#office-canvas').screenshot({ path: path.join(OUT, `lift-${phase}.png`) });
  }
  if (!phase && phases.size) break;
  await page.waitForTimeout(400);
}
check('The delivery passes through every stage', ['summon', 'board', 'travel', 'alight'].every((p) => phases.has(p)),
  [...phases].join(' -> '));

const done = await page.evaluate(() => ({
  trip: window.__studio.engine.lift.trip,
  tokens: window.__studio.engine.projectTokens.map((t) => ({ stage: t.stage, x: t.x, y: t.y })),
}));
check('The delivery finishes and the cab is free again', done.trip === null);
check('The token ends in the research lab, where the backend put it',
  done.tokens.some((t) => t.stage === 'RESEARCH' && t.y > 195 && t.y < 325),
  JSON.stringify(done.tokens));

check('No page errors', errors.length === 0, errors.join(' | ').slice(0, 160));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
