/**
 * The seeded provider must never present itself as verified, and the Owner must have a
 * working control to verify it. Checked through the running interface, not the source.
 */
import pw from '../frontend/node_modules/playwright/index.js';
import { readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';

const { chromium } = pw;
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const BASE = 'http://127.0.0.1:8000';
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
const page = await browser.newPage({ viewport: { width: 1440, height: 940 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.click('#login-form button[type="submit"]');
await page.waitForSelector('#studio-name');

await page.click('#open-settings');
await page.waitForSelector('#settings-dialog[open]');
await page.waitForFunction(() => !document.querySelector('.settings-content')?.textContent.includes('Se încarcă'));
await page.waitForTimeout(500);

const llm = await page.evaluate(() => document.querySelector('.settings-content').textContent);
check('The seeded endpoint is listed for the Owner', llm.includes('local-ollama'), 'in Furnizori AI');
check(
  'It states plainly that it was never contacted',
  llm.includes('Nu a fost contactat niciodată'),
);
check('It does not claim to be verified', !/Verificat:/.test(llm));

const buttons = await page.$$eval('.settings-content button', (els) => els.map((e) => e.textContent));
check('A verification control exists', buttons.includes('Verifică și încarcă modelele'));

// Agents tab: an unverified model must not be assignable.
await page.click('.settings-tabs button:nth-child(2)');
await page.waitForTimeout(400);
const options = await page.$$eval('.settings-content select option', (els) => els.map((e) => e.textContent));
check(
  'No unverified model is offered for assignment',
  !options.some((o) => o.includes(':cloud')),
  options.join(' | ').slice(0, 120),
);

// Press the control against an endpoint that is not running: it must say so, not "500".
await page.click('.settings-tabs button:nth-child(1)');
await page.waitForTimeout(400);
await page.click('.settings-content button:has-text("Verifică și încarcă modelele")');
await page.waitForFunction(
  () => (document.querySelector('.settings-message')?.textContent || '').trim().length > 0,
  { timeout: 50000 },
);
const message = await page.textContent('.settings-message');
check('A dead endpoint is reported honestly, not as an internal error', message.includes('nu a răspuns'), message.trim());
check('Nothing was recorded from the failed check', !message.includes('modele disponibile'));

await page.screenshot({ path: path.join(OUT, 'provider-honesty.png') });
check('No page errors', errors.length === 0, errors.join(' | ').slice(0, 160));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
