/**
 * The end of the Phase 4 chain, through the interface: a script is written only from claims a
 * source actually supports, and approval re-runs the factual gate.
 *
 * The writing agent needs a working LLM, which this container has none of, so the drafting step
 * is exercised through the API with claims prepared directly. What is verified here is the part
 * that must hold regardless of which model writes: an unverified topic yields no script, a
 * stored draft cites only supported claims, and approval fails the moment one of them stops
 * being supported.
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

// Prepare a topic with one verified and one unverified claim.
const fixture = await page.evaluate(async (t) => {
  const headers = { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' };
  const post = async (url, body) =>
    (await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) })).json();

  const topic = await post('/api/v1/factual/topics', {
    command_id: crypto.randomUUID(),
    title: `Hubble ${Date.now()}`,
    topic: 'Hubble Space Telescope',
    angle: 'Discovery',
    target_audience: 'general',
  });
  const source = await post('/api/v1/factual/sources/ingest', {
    command_id: crypto.randomUUID(),
    topic_id: topic.id,
    url: 'https://example.org/hubble',
    title: 'Hubble facts',
    publisher: 'example.org',
    raw_content: 'The Hubble Space Telescope was launched in 1990. It orbits about 540 kilometres above Earth.',
    credibility_score: 0,
  });
  const { claims } = await post('/api/v1/factual/claims/extract', {
    command_id: crypto.randomUUID(),
    source_id: source.id,
    topic_id: topic.id,
    claims: [
      { claim_text: 'Hubble was launched in 1990.', importance: 'CRITICAL', confidence: 0.9 },
      { claim_text: 'Hubble orbits about 540 kilometres above Earth.', importance: 'SUPPORTING', confidence: 0.9 },
    ],
  });
  return { topicId: topic.id, claimIds: claims.map((c) => c.id) };
}, token);

const support = (claimId) => page.evaluate(async (args) => {
  const r = await fetch(`/api/v1/factual/claims/${args.id}/verify`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${args.t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      command_id: crypto.randomUUID(), status: 'SUPPORTED', confidence: 0.95,
      verifier_notes: 'Sursa o afirmă.', evidence_text: 'launched in 1990',
    }),
  });
  return r.status;
}, { id: claimId, t: token });

const writeScript = (claimIds) => page.evaluate(async (args) => {
  const r = await fetch('/api/v1/factual/scripts/generate', {
    method: 'POST',
    headers: { Authorization: `Bearer ${args.t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      command_id: crypto.randomUUID(),
      topic_id: args.topicId,
      title: 'Hubble la 540 de kilometri',
      target_duration_seconds: 45,
      voiceover_full_text: 'Hubble a ajuns pe orbită în 1990 și se rotește la circa 540 de kilometri.',
      scenes: [{ scene_number: 1, narration: 'Hubble a ajuns pe orbită în 1990.', claim_ids: [args.claimIds[0]] }],
      referenced_claim_ids: args.claimIds,
    }),
  });
  return { status: r.status, body: await r.json() };
}, { t: token, topicId: fixture.topicId, claimIds });

// 1. Nothing verified yet: the agent route refuses rather than writing from unverified claims.
const noClaims = await page.evaluate(async (args) => {
  const r = await fetch('/api/v1/factual/scripts/write-with-agent', {
    method: 'POST',
    headers: { Authorization: `Bearer ${args.t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ command_id: crypto.randomUUID(), topic_id: args.topicId }),
  });
  return { status: r.status, detail: (await r.json()).detail };
}, { t: token, topicId: fixture.topicId });
check('A topic with no supported claim yields no script', noClaims.status === 409, `HTTP ${noClaims.status}`);
check('And it says why', String(noClaims.detail).includes('SUSȚINUTĂ'), String(noClaims.detail).slice(0, 90));

// 2. The gate blocks a draft that cites an unverified claim.
await support(fixture.claimIds[0]);
const blocked = await writeScript(fixture.claimIds);
check('The factual gate blocks a draft citing an unverified claim', blocked.status === 422, `HTTP ${blocked.status}`);

// 3. With every cited claim supported, the draft passes.
await support(fixture.claimIds[1]);
const passed = await writeScript(fixture.claimIds);
check('A draft citing only supported claims passes', passed.status === 200, `HTTP ${passed.status}`);
check('It records no unverified citations', (passed.body.unverified_claim_ids_json || []).length === 0);
const scriptId = passed.body.id;

// 4. The panel shows it, scene by scene, with an approval action.
await page.click('#open-research-btn');
await page.waitForSelector('#research-modal[open]');
await page.waitForFunction(() => !document.querySelector('#scripts-list')?.textContent.includes('Se încarcă'));
await page.waitForSelector(`.script-card[data-script-id="${scriptId}"]`);
const card = await page.textContent(`.script-card[data-script-id="${scriptId}"]`);
check('The script is listed with its scenes and citation counts', card.includes('Scena 1') && card.includes('afirmații citate'), card.replace(/\s+/g, ' ').slice(0, 140));
check('It offers approval only once the gate has passed', await page.$(`.script-card[data-script-id="${scriptId}"] .btn-approve-script`) !== null);
await page.screenshot({ path: path.join(OUT, 'scripts.png') });

// 5. Approval re-runs the gate: a claim that stops being supported blocks it.
await page.evaluate(async (args) => {
  await fetch(`/api/v1/factual/claims/${args.id}/verify`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${args.t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      command_id: crypto.randomUUID(), status: 'REFUTED', confidence: 0.9,
      verifier_notes: 'O altă sursă o contrazice.', evidence_text: null,
    }),
  });
}, { id: fixture.claimIds[1], t: token });

await page.click(`.script-card[data-script-id="${scriptId}"] .btn-approve-script`);
await page.waitForFunction(
  () => (document.querySelector('#script-status')?.textContent || '').trim().length > 10,
  { timeout: 30000 },
);
const refusal = await page.textContent('#script-status');
const isError = await page.evaluate(() => document.querySelector('#script-status').className.includes('text-error'));
check('Approval re-runs the gate on a claim that was refuted since', isError, refusal.trim().slice(0, 120));
check('The refusal names how many claims stopped being supported', /\d+ afirmații citate nu mai sunt/.test(refusal), refusal.trim().slice(0, 120));

const finalStatus = await page.evaluate(async (args) => {
  const r = await fetch('/api/v1/factual/scripts', { headers: { Authorization: `Bearer ${args.t}` } });
  return (await r.json()).scripts.find((s) => s.id === args.id).status;
}, { t: token, id: scriptId });
check('The script is not left marked approved', finalStatus !== 'APPROVED', finalStatus);

check('No page errors', errors.length === 0, errors.join(' | ').slice(0, 160));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
