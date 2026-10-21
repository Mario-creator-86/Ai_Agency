/**
 * The handover from research to production, and what the studio says about a render before
 * the Owner asks for one.
 *
 * The chain used to break here: an approved script had no route into production, and the only
 * creation path in the Media panel produced test data. This drives the real route — approve a
 * script, see it queued, build the storyboard, render it — and checks that the studio states
 * up front that a render without a media provider is not publishable.
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

// A verified claim, a script that cites it, and approval — the state research hands over.
const fixture = await page.evaluate(async (t) => {
  const headers = { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' };
  const post = async (url, body) =>
    (await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) })).json();

  const topic = await post('/api/v1/factual/topics', {
    command_id: crypto.randomUUID(),
    title: `Handover ${Date.now()}`,
    topic: 'Hubble Space Telescope',
    angle: 'Discovery',
    target_audience: 'general',
  });
  const source = await post('/api/v1/factual/sources/ingest', {
    command_id: crypto.randomUUID(), topic_id: topic.id,
    url: 'https://example.org/hubble', title: 'Hubble facts', publisher: 'example.org',
    raw_content: 'The Hubble Space Telescope was launched in 1990.', credibility_score: 0,
  });
  const { claims } = await post('/api/v1/factual/claims/extract', {
    command_id: crypto.randomUUID(), source_id: source.id, topic_id: topic.id,
    claims: [{ claim_text: 'Hubble was launched in 1990.', importance: 'CRITICAL', confidence: 0.9 }],
  });
  await post(`/api/v1/factual/claims/${claims[0].id}/verify`, {
    command_id: crypto.randomUUID(), status: 'SUPPORTED', confidence: 0.95,
    verifier_notes: 'Sursa o afirmă.', evidence_text: 'launched in 1990',
  });
  const script = await post('/api/v1/factual/scripts/generate', {
    command_id: crypto.randomUUID(), topic_id: topic.id,
    title: 'Hubble, 1990', target_duration_seconds: 20,
    voiceover_full_text: 'Hubble a ajuns pe orbită în 1990 și observă universul de atunci.',
    scenes: [
      { scene_index: 1, visual_prompt: 'A telescope in orbit', duration_seconds: 10,
        voiceover_segment: 'Hubble a ajuns pe orbită în 1990.', shot_type: 'WIDE',
        transition_in: 'FADE', claim_ids: [claims[0].id] },
      { scene_index: 2, visual_prompt: 'Stars and galaxies', duration_seconds: 10,
        voiceover_segment: 'De atunci observă universul.', shot_type: 'WIDE',
        transition_in: 'FADE', claim_ids: [claims[0].id] },
    ],
    referenced_claim_ids: [claims[0].id],
  });
  return { scriptId: script.id, title: script.title };
}, token);

// 1. Approve it in Research, then it must appear in Production.
await page.click('#open-research-btn');
await page.waitForSelector('#research-modal[open]');
await page.waitForFunction(() => !document.querySelector('#scripts-list')?.textContent.includes('Se încarcă'));
await page.waitForSelector(`.script-card[data-script-id="${fixture.scriptId}"] .btn-approve-script`);
await page.click(`.script-card[data-script-id="${fixture.scriptId}"] .btn-approve-script`);
await page.waitForFunction(
  () => (document.querySelector('#script-status')?.textContent || '').includes('aprobat'),
  { timeout: 30000 },
);
check('An approved script is announced as ready for production', true,
  (await page.textContent('#script-status')).trim().slice(0, 90));
await page.click('#close-research-btn');

await page.click('#open-media-btn');
await page.waitForSelector('#media-modal[open]');
await page.waitForFunction(() => !document.querySelector('#media-provider-note')?.textContent.includes('Se verifică'));

// 2. The studio says what a render would be, before one is asked for.
const note = await page.textContent('#media-provider-note');
check('The panel states that renders are not publishable without a provider',
  note.includes('substitut') && note.includes('QC'), note.trim().slice(0, 110));
check('And says it as a warning', await page.evaluate(
  () => document.querySelector('#media-provider-note').className.includes('helper-warn')));

// 3. The approved script is queued for production.
await page.waitForSelector('#awaiting-storyboard:not([hidden])');
const queued = await page.textContent('#awaiting-list');
check('The approved script is queued for production', queued.includes(fixture.title), queued.replace(/\s+/g, ' ').slice(0, 130));
check('It shows how many verified claims it rests on', /\d+ afirmații verificate/.test(queued));
await page.screenshot({ path: path.join(OUT, 'production-handover.png') });

// 4. Build the storyboard from it, through the interface.
await page.click(`.btn-make-storyboard[data-script-id="${fixture.scriptId}"]`);
await page.waitForFunction(
  () => (document.querySelector('#media-status-msg')?.textContent || '').includes('Storyboard creat'),
  { timeout: 60000 },
);
check('The storyboard is built from the approved script', true,
  (await page.textContent('#media-status-msg')).trim().slice(0, 90));

// 5. It leaves the queue: a script in production is not offered again.
const stillQueued = await page.evaluate(async (args) => {
  const r = await fetch('/api/v1/media/scripts/awaiting-storyboard', { headers: { Authorization: `Bearer ${args.t}` } });
  return (await r.json()).scripts.some((s) => s.id === args.id);
}, { t: token, id: fixture.scriptId });
check('A script already in production is not offered again', stillQueued === false);

// 6. Render it and confirm the asset is labelled placeholder and blocked by QC.
const rendered = await page.evaluate(async (args) => {
  const headers = { Authorization: `Bearer ${args.t}`, 'Content-Type': 'application/json' };
  const sbs = await (await fetch('/api/v1/media/storyboards', { headers })).json();
  const sb = sbs.storyboards.find((s) => s.script_draft_id === args.id);
  if (!sb) return { error: 'storyboard not found' };
  const r = await fetch(`/api/v1/media/render/${sb.id}`, { method: 'POST', headers });
  return { status: r.status, body: await r.json() };
}, { t: token, id: fixture.scriptId });

check('The render completes', rendered.status === 200, `HTTP ${rendered.status}`);
check('The asset names the placeholder generator, not a provider',
  rendered.body?.visual_source === 'PLACEHOLDER_DETERMINISTIC_VISUALS', rendered.body?.visual_source);
check('QC blocks it from publication',
  rendered.body?.qc?.checks_json?.content_source_qc?.passed === false,
  JSON.stringify(rendered.body?.qc?.checks_json?.content_source_qc || {}).slice(0, 110));

check('No page errors', errors.length === 0, errors.join(' | ').slice(0, 160));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
