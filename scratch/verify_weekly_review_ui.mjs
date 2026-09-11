/** The runbook panel carries the weekly-review button, and it answers in words. */
import pw from '../frontend/node_modules/playwright/index.js';
import { readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const { chromium } = pw;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'output', 'playwright');
mkdirSync(OUT, { recursive: true });
const token = readFileSync(path.join(ROOT, '.env'), 'utf8')
  .split('\n').find((l) => l.startsWith('STUDIO_OWNER_TOKEN=')).split('=')[1].trim();

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));

await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.evaluate(() => document.getElementById('login-form').requestSubmit());
await page.waitForSelector('#studio-name');
await page.waitForTimeout(2000);

await page.evaluate(() => document.getElementById('open-runbook-btn').click());
await page.waitForSelector('#runbook-modal[open]');
await page.waitForTimeout(800);

const button = await page.evaluate(() => {
  const btn = document.getElementById('start-weekly-review-btn');
  return btn ? { text: btn.textContent.trim(), visible: !btn.hidden } : null;
});
console.log(`${button && button.visible ? 'PASS' : 'FAIL'}  weekly-review button present — ${JSON.stringify(button)}`);

await page.evaluate(() => document.getElementById('start-weekly-review-btn').click());
await page.waitForFunction(
  () => {
    const el = document.getElementById('runbook-status');
    return el && el.hidden === false && /Revizia săptămânală a fost pusă|refu|409|deja/.test(el.textContent);
  },
  { timeout: 20000 },
);
const status = await page.evaluate(() => document.getElementById('runbook-status').textContent.trim());
console.log(`${/Revizia săptămânală/.test(status) ? 'PASS' : 'FAIL'}  button answers in words — "${status}"`);
await page.screenshot({ path: path.join(OUT, 'weekly-review-button.png') });

// The employee contract, seen by the Owner in the inspector, carries the new duties.
await page.keyboard.press('Escape');
await page.evaluate(() => {
  const engine = window.__studio.engine;
  const lyra = engine.agents.find((x) => String(x.display_name || '').includes('Lyra')) || engine.agents[0];
  engine.onSelectAgent(lyra);
});
await page.waitForSelector('#agent-inspector[open]');
await page.waitForTimeout(2000);
const contract = await page.evaluate(() => document.getElementById('inspector-contract').textContent);
console.log(
  `${/where the policy allows the choice, choose the voice/.test(contract) ? 'PASS' : 'FAIL'}  Lyra's contract shows the sound-steward duties`,
);
const sarahCheck = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/agents/', { headers: { Authorization: `Bearer ${t}` } });
  const data = await r.json();
  const sarah = (data.agents || []).find((a) => String(a.display_name || '').includes('Sarah'));
  const identity = await (
    await fetch(`/api/v1/agents/${sarah.id}/identity`, { headers: { Authorization: `Bearer ${t}` } })
  ).json();
  return (identity.contract?.work_contract_json?.deliverables || []).join(' | ');
}, token);
console.log(
  `${/weekly performance review/.test(sarahCheck) ? 'PASS' : 'FAIL'}  Sarah's contract carries the weekly review duty`,
);
await page.screenshot({ path: path.join(OUT, 'weekly-review-lyra-contract.png') });

console.log(`${errors.length === 0 ? 'PASS' : 'FAIL'}  no page errors ${errors.join(' | ').slice(0, 200)}`);
await browser.close();
