/**
 * The Phase 4 loop, as the Owner drives it: authorise a site, fetch a source, read claims out
 * of it, verify them. Checked through the running interface.
 *
 * The container this runs in has no direct egress, so the retrieval itself is exercised
 * against the API rather than the public internet; what is verified here is that the panel
 * shows the allowlist, refuses what it must, and never presents an unverified claim as
 * anything else.
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

await page.click('#open-research-btn');
await page.waitForSelector('#research-modal[open]');
await page.waitForFunction(
  () => !document.querySelector('#sources-allowlist')?.textContent.includes('Se verifică'),
);
await page.waitForTimeout(500);

// 1. The Owner can see which sites the studio may reach, and that it is a config-file setting.
const allowlist = await page.textContent('#sources-allowlist');
check('The authorised sites are stated in the panel', allowlist.includes('www.iana.org'), allowlist.trim().slice(0, 110));
check(
  'It says the list lives in the configuration file, not in the app',
  allowlist.includes('STUDIO_RESEARCH_ALLOWED_HOSTS') || allowlist.includes('.env'),
);

// 2. A site outside the list is refused, and the refusal explains itself.
const countSources = () => page.evaluate(async (t) => {
  const r = await fetch('/api/v1/factual/sources', { headers: { Authorization: `Bearer ${t}` } });
  return (await r.json()).sources.length;
}, token);
const sourcesBefore = await countSources();
await page.fill('#source-url', 'https://example.com/anything');
await page.click('#source-retrieve-form button[type="submit"]');
await page.waitForFunction(
  () => document.querySelector('#source-retrieve-status')?.textContent.trim().length > 20,
  { timeout: 30000 },
);
const refusal = await page.textContent('#source-retrieve-status');
check('An unauthorised site is refused with a reason', refusal.includes('nu este permisă'), refusal.trim().slice(0, 120));
check(
  'The refusal is shown as an error, not as a result',
  await page.evaluate(() => document.querySelector('#source-retrieve-status').className.includes('text-error')),
);

// 3. Nothing was stored by the refused attempt.
const sourcesAfter = await countSources();
check('A refused fetch stores nothing', sourcesAfter === sourcesBefore, `${sourcesBefore} -> ${sourcesAfter}`);

// 4. A stored source renders with its provenance, and its claims render as unverified.
const seeded = await page.evaluate(async (t) => {
  const headers = { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' };
  const src = await (await fetch('/api/v1/factual/sources/ingest', {
    method: 'POST', headers,
    body: JSON.stringify({
      command_id: crypto.randomUUID(),
      url: 'https://www.iana.org/help/example-domains',
      title: 'Example Domains',
      publisher: 'www.iana.org',
      raw_content: 'Example domains are reserved for use in documentation and may be used freely.',
      credibility_score: 0,
    }),
  })).json();
  await fetch('/api/v1/factual/claims/extract', {
    method: 'POST', headers,
    body: JSON.stringify({
      command_id: crypto.randomUUID(),
      source_id: src.id,
      claims: [{
        claim_text: 'Example domains are reserved for use in documentation.',
        claim_type: 'GENERAL', importance: 'CRITICAL', confidence: 0.9,
      }],
    }),
  });
  return src.id;
}, token);

await page.click('#refresh-sources-btn');
await page.waitForSelector('.source-card');
const card = await page.textContent('.source-card');
check('The source is listed with its publisher and provenance digest', card.includes('www.iana.org') && /amprentă [0-9a-f]{12}/.test(card));
check('The claim count is shown as unverified', card.includes('Neverificată'), card.replace(/\s+/g, ' ').slice(0, 160));

await page.click(`.btn-show-claims[data-source-id="${seeded}"]`);
await page.waitForSelector(`#claims-${seeded} .claim-row`);
const claimRow = await page.evaluate((id) => {
  const row = document.querySelector(`#claims-${id} .claim-row`);
  return { text: row.textContent, cls: row.className };
}, seeded);
check('An extracted claim is presented as unverified', claimRow.cls.includes('claim-unverified') && claimRow.text.includes('Neverificată'));

await page.screenshot({ path: path.join(OUT, 'research-sources.png') });

// 5. Verification offers the two honest routes and no one-click "mark true".
check('There is no button that just marks a claim verified', await page.$('.btn-verify-claim') === null);
check('A second agent can be asked to check it', await page.$('.btn-agent-verify') !== null);
check('The Owner can record their own verdict', await page.$('.btn-owner-verdict') !== null);

// The Owner's verdict is recorded with its reasoning, and the screen matches the backend.
await page.click(`#claims-${seeded} .btn-owner-verdict`);
await page.waitForSelector(`#claims-${seeded} .owner-verdict-form:not([hidden])`);
await page.selectOption(`#claims-${seeded} .owner-verdict-form select[name="status"]`, 'SUPPORTED');
await page.fill(`#claims-${seeded} .owner-verdict-form input[name="evidence"]`, 'Example domains are reserved for use in documentation.');
await page.fill(`#claims-${seeded} .owner-verdict-form input[name="notes"]`, 'Sursa afirmă exact acest lucru.');
await page.click(`#claims-${seeded} .owner-verdict-form button[type="submit"]`);
await page.waitForFunction(
  (id) => {
    const row = document.querySelector(`#claims-${id} .claim-row`);
    return row && !row.className.includes('claim-unverified');
  },
  seeded,
  { timeout: 30000 },
);
const verified = await page.evaluate((id) => {
  const row = document.querySelector(`#claims-${id} .claim-row`);
  return { text: row.textContent.replace(/\s+/g, ' ').trim(), cls: row.className };
}, seeded);
const apiStatus = await page.evaluate(async (args) => {
  const r = await fetch(`/api/v1/factual/claims?source_id=${args.id}`, { headers: { Authorization: `Bearer ${args.t}` } });
  const claims = (await r.json()).claims.filter((c) => c.source_id === args.id);
  const c = claims[0];
  return { status: c.status, notes: c.verifier_notes, by: c.verified_by_agent_id, n: claims.length };
}, { id: seeded, t: token });
check('The verdict is recorded', apiStatus.status === 'SUPPORTED', apiStatus.status);
check('The reasoning is stored with it', (apiStatus.notes || '').includes('Sursa afirmă'));
check('It is attributed to the Owner, not to an agent', apiStatus.by === null);
check('The status on screen is the status in the backend', verified.cls.includes(`claim-${apiStatus.status.toLowerCase()}`));
check('The evidence is shown under the claim', verified.text.includes('Example domains are reserved'), verified.text.slice(0, 120));

await page.screenshot({ path: path.join(OUT, 'research-verified.png') });

// 6. Layout holds at phone width.
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(500);
check('No horizontal overflow at 390px', !(await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)));

check('No page errors', errors.length === 0, errors.join(' | ').slice(0, 160));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
