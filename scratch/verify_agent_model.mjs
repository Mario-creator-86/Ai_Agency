/**
 * The inspector must show the model the backend actually assigned to that agent.
 *
 * Regression: the "Model configurat" field was a fixed string written into index.html, so
 * every agent read "glm-5.2:cloud" whatever the Owner had chosen in Settings — and the office
 * layout was only fetched at login, so even a correct field would have shown the state from
 * before the change until the page was reloaded.
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
await page.waitForTimeout(2000);

// 0. No stale literal is baked into the page.
const markup = await page.evaluate(() => document.getElementById('inspector-model').textContent);
check('The model field starts empty rather than pre-filled', markup.trim() === '—', `"${markup.trim()}"`);

// 1. The backend's assignments, read directly.
const assignments = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/office/layout', { headers: { Authorization: `Bearer ${t}` } });
  return (await r.json()).assignments;
}, token);
check('The layout carries a model per agent', assignments.every((a) => 'model_name' in a));
const distinct = new Set(assignments.map((a) => a.model_name));
check('Agents do not all share one model', distinct.size > 1, [...distinct].join(', '));

// 2. Open each agent in turn and compare what is shown with what the backend said.
let mismatch = null;
for (const assignment of assignments) {
  const opened = await page.evaluate((a) => {
    const engine = window.__studio.engine;
    const agent = engine.agents.find((x) => (x.id || x.agent_id) === a.agent_id);
    if (!agent) return null;
    engine.onSelectAgent(agent);
    return true;
  }, assignment);
  if (!opened) { mismatch = `${assignment.display_name}: not on the canvas`; break; }
  await page.waitForSelector('#agent-inspector[open]');
  const shown = (await page.textContent('#inspector-model')).trim();
  const name = (await page.textContent('#inspector-name')).trim();
  const expected = assignment.model_name
    ? (assignment.model_is_available ? assignment.model_name : `${assignment.model_name} · neverificat`)
    : 'Niciun model alocat';
  if (name !== assignment.display_name || shown !== expected) {
    mismatch = `${assignment.display_name}: shown "${shown}" for "${name}", expected "${expected}"`;
    break;
  }
  await page.click('#inspector-close');
  await page.waitForTimeout(120);
}
check('Every agent shows its own assigned model', mismatch === null, mismatch || `${assignments.length} agents checked`);

// 3. An unverified model is labelled as such, and running is not offered.
const firstAgent = assignments[0];
await page.evaluate((a) => {
  const engine = window.__studio.engine;
  engine.onSelectAgent(engine.agents.find((x) => (x.id || x.agent_id) === a.agent_id));
}, firstAgent);
await page.waitForSelector('#agent-inspector[open]');
const state = await page.evaluate(() => ({
  text: document.getElementById('inspector-model').textContent.trim(),
  cls: document.getElementById('inspector-model').className,
  runDisabled: document.querySelector('#agent-run-form button[type="submit"]').disabled,
}));
if (!firstAgent.model_is_available) {
  check('An unverified model is labelled unverified', state.text.includes('neverificat'), state.text);
  check('Running is not offered on an unverified model', state.runDisabled === true);
} else {
  check('A verified model is shown plainly', !state.text.includes('neverificat'), state.text);
  check('Running is offered on a verified model', state.runDisabled === false);
}
await page.screenshot({ path: path.join(OUT, 'agent-model.png') });
await page.click('#inspector-close');

// 4. An unverified model cannot be assigned at all — the refusal is the honest outcome, and
//    it is what keeps an agent from being pointed at a model nothing has confirmed exists.
const assignAttempt = await page.evaluate(async (args) => {
  const headers = { Authorization: `Bearer ${args.t}`, 'Content-Type': 'application/json' };
  const settings = await (await fetch('/api/v1/settings', { headers })).json();
  const other = settings.models.find((m) => m.model_name !== args.current);
  if (!other) return { skipped: 'no other model' };
  const agent = settings.agents.find((a) => a.id === args.agentId);
  const response = await fetch(`/api/v1/settings/agents/${args.agentId}/model`, {
    method: 'PUT', headers,
    body: JSON.stringify({ model_id: other.id, expected_version: agent.version }),
  });
  return { status: response.status, available: other.is_available, name: other.model_name };
}, { t: token, agentId: firstAgent.agent_id, current: firstAgent.model_name });

if (assignAttempt.available === false) {
  check(
    'Assigning an unverified model is refused',
    assignAttempt.status === 422,
    `HTTP ${assignAttempt.status} for ${assignAttempt.name}`,
  );
} else {
  check('Assigning a verified model succeeds', assignAttempt.status === 200, `HTTP ${assignAttempt.status}`);
}

// 5. Closing Settings re-fetches the office layout, so a change made there reaches the
//    inspector without a page reload. Counted at the network, not inferred from the screen.
let layoutFetches = 0;
page.on('request', (r) => {
  if (r.url().includes('/api/v1/office/layout')) layoutFetches += 1;
});
await page.click('#open-settings');
await page.waitForSelector('#settings-dialog[open]');
const beforeClose = layoutFetches;
await page.click('#settings-dialog .dialog-header button');
await page.waitForTimeout(1500);
check(
  'Closing Settings refreshes the office, so a change there reaches the inspector',
  layoutFetches > beforeClose,
  `${layoutFetches - beforeClose} layout fetch(es) after closing`,
);

check('No page errors', errors.length === 0, errors.join(' | ').slice(0, 160));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
