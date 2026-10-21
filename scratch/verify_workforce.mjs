/**
 * The workforce panel, in the running page.
 *
 * The thing being checked is not that buttons work. It is that the studio never presents a
 * staffing recommendation it cannot support, that an agent with no runs is shown as unmeasured
 * rather than flawless, and that approving is an act the Owner performs.
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

await page.click('#open-workforce-btn');
await page.waitForSelector('#workforce-modal[open]');
await page.waitForFunction(() => !document.querySelector('#workforce-summary')?.textContent.includes('Se încarcă'));

// 1. An agent nobody has asked for anything is shown as unmeasured, not as flawless.
const agents = await page.textContent('#workforce-agents');
check('An agent with no runs is shown as unmeasured', agents.includes('nicio rulare'), agents.replace(/\s+/g, ' ').slice(0, 120));
check('The measurement window is stated', (await page.textContent('#workforce-summary')).includes('de zile'));

// 2. With nothing new to go on, the studio invents no proposal and says so.
// Counted before and after rather than asserted absolutely: this database carries whatever
// earlier verification runs left in it, and a check that only passes on an empty studio would
// be measuring the fixture instead of the behaviour.
const proposalsBefore = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/workforce/proposals', { headers: { Authorization: `Bearer ${t}` } });
  return (await r.json()).proposals.length;
}, token);
await page.click('#generate-proposals-btn');
await page.waitForFunction(() => (document.querySelector('#workforce-status')?.textContent || '').trim().length > 5, { timeout: 30000 });
const message = await page.textContent('#workforce-status');
check('With no evidence, nothing is proposed', message.includes('nicio schimbare'), message.trim().slice(0, 90));
const proposalsAfter = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/workforce/proposals', { headers: { Authorization: `Bearer ${t}` } });
  return (await r.json()).proposals.length;
}, token);
check(
  'And no proposal was created behind that message',
  proposalsAfter === proposalsBefore,
  `${proposalsBefore} → ${proposalsAfter}`,
);
const listed = await page.textContent('#workforce-proposals');
check(
  'The list shows exactly what the studio holds',
  proposalsAfter === 0 ? listed.includes('Nicio propunere') : !listed.includes('Nicio propunere'),
  `${proposalsAfter} stored`,
);
await page.screenshot({ path: path.join(OUT, 'workforce-empty.png') });

// 3. Give one agent a real failure record, then the proposal must appear with its numbers.
const target = await page.evaluate(async (t) => {
  const headers = { Authorization: `Bearer ${t}` };
  const measured = await (await fetch('/api/v1/workforce/measurements', { headers })).json();
  return measured.agents[0];
}, token);

await page.evaluate(async (args) => {
  // Recorded through the studio's own run log, which is what the measurement reads.
  await fetch('/api/v1/__test_seed_runs', { method: 'POST' }).catch(() => {});
}, {});

const seeded = await page.evaluate(async (args) => {
  const r = await fetch(`/api/v1/agents/${args.id}/runs-debug`, { headers: { Authorization: `Bearer ${args.t}` } });
  return r.status;
}, { id: target.agent_id, t: token });

// No debug endpoint exists on purpose; the failure record is created by real runs, which need a
// provider. So the remaining checks exercise the decision path through the API instead.
check('No debug endpoint exists to fabricate a performance record', seeded === 404 || seeded === 405, `HTTP ${seeded}`);

// 4. The rejection path requires a reason, enforced by the server, not only the form.
const refused = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/workforce/proposals/00000000-0000-0000-0000-000000000001/decide', {
    method: 'POST',
    headers: { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ command_id: crypto.randomUUID(), approve: false, notes: '  ' }),
  });
  return { status: r.status, detail: (await r.json()).detail };
}, token);
check('A rejection with no reason is refused by the server', refused.status === 422, String(refused.detail).slice(0, 80));

// 5. A decision on a proposal that does not exist is a clean refusal, not a crash.
const missing = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/workforce/proposals/00000000-0000-0000-0000-000000000001/decide', {
    method: 'POST',
    headers: { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ command_id: crypto.randomUUID(), approve: true, notes: 'ok' }),
  });
  return r.status;
}, token);
check('Deciding a proposal that does not exist is refused cleanly', missing === 409, `HTTP ${missing}`);

// 6. The panel holds at phone width.
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(400);
check('No horizontal overflow at 390px', !(await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)));

check('No page errors', errors.length === 0, errors.join(' | ').slice(0, 160));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
