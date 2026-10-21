/**
 * The daily runbook, in the running page.
 *
 * Two honesty problems are tested here, both about a report rather than about the world.
 * First, the preflight must not round a missing capability up: a studio with no verified image
 * provider is DEGRADED and says so in words, not merely in a colour. Second, a run must not read
 * as more than it did — every stage of the runbook appears, including the ones that were skipped
 * and the ones that never got the chance, each with its reason. A page that listed only the
 * stages that ran would mislead by its shape without carrying a single false sentence.
 *
 * The run branch only exercises when the preflight is not BLOCKED, which needs a verified model.
 * This studio has none and must not pretend otherwise, so to cover that branch, run against a
 * throwaway copy of the database instead of flipping a verification flag on the real one:
 *
 *   cp data/studio.db data/verify_runbook.db
 *   python3 -c "import sqlite3;c=sqlite3.connect('data/verify_runbook.db');\
 *     c.execute('UPDATE model_record SET is_available=1 WHERE id=(SELECT id FROM model_record LIMIT 1)');\
 *     c.execute('UPDATE owner_policy SET autonomy_stopped=0 WHERE id=1');c.commit()"
 *   STUDIO_DATABASE_URL="sqlite:///data/verify_runbook.db" uv run python scripts/run.py
 *
 * That flag then means "verification fixture", never "a provider answered".
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

await page.click('#open-runbook-btn');
await page.waitForSelector('#runbook-modal[open]');
await page.waitForFunction(
  () => !document.querySelector('#runbook-preflight-summary')?.textContent.includes('Se încarcă'),
);

// 1. The preflight verdict is a word, not only a colour.
const verdict = (await page.textContent('.runbook-verdict')) || '';
check(
  'The preflight verdict names its status in words',
  /READY|DEGRADED|BLOCKED/.test(verdict),
  verdict.trim().slice(0, 90),
);

// 2. Every check is listed, the passing ones too: the Owner can see what was looked at.
const checkCount = await page.locator('.runbook-check').count();
check('Every preflight check is shown, not only the failures', checkCount >= 9, `${checkCount} checks`);
const allNamed = await page.evaluate(() =>
  [...document.querySelectorAll('.runbook-check')].every(
    (el) => (el.querySelector('.topic-card-meta')?.textContent || '').trim().length > 0,
  ),
);
check('Each check says what it found', allNamed);

// 3. The checks are named in Romanian, not left as internal identifiers.
const rawNames = await page.evaluate(() =>
  [...document.querySelectorAll('.runbook-check .topic-card-title')]
    .map((el) => (el.textContent || '').trim())
    .filter((t) => /^[a-z][a-z0-9_]*$/.test(t)),
);
check(
  'Preflight checks are named for the Owner, not by their identifiers',
  rawNames.length === 0,
  rawNames.join(', '),
);

// 4. A missing provider is reported as missing, in words the Owner can act on.
const missing = await page.evaluate(() =>
  [...document.querySelectorAll('.runbook-check.rb-fail')].map((el) => el.textContent).join(' '),
);
check(
  'A missing media provider is named rather than glossed over',
  /furnizor de imagine verificat|furnizor de voce/.test(missing),
  missing.replace(/\s+/g, ' ').trim().slice(0, 110),
);

// 4. The preflight is read-only: reading it twice must not create a run.
const runsBefore = await page.evaluate(async (t) => {
  await fetch('/api/v1/runbook/preflight', { headers: { Authorization: `Bearer ${t}` } });
  await fetch('/api/v1/runbook/preflight', { headers: { Authorization: `Bearer ${t}` } });
  const r = await fetch('/api/v1/runbook/runs', { headers: { Authorization: `Bearer ${t}` } });
  return (await r.json()).runs.length;
}, token);
await page.click('#refresh-preflight-btn');
await page.waitForTimeout(300);
const runsAfterPreflight = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/runbook/runs', { headers: { Authorization: `Bearer ${t}` } });
  return (await r.json()).runs.length;
}, token);
check(
  'Reading the preflight starts nothing',
  runsBefore === runsAfterPreflight,
  `${runsBefore} → ${runsAfterPreflight} runs`,
);

// 5. Whether the run button is offered follows the preflight, so a refusal is not a surprise.
const status = (await page.textContent('.runbook-verdict strong')) || '';
const disabled = await page.isDisabled('#start-run-btn');
check(
  'The run button matches the preflight verdict',
  disabled === status.trim().startsWith('BLOCKED'),
  `${status.trim()} / disabled=${disabled}`,
);

// 6. Run the day and read the record back.
if (!disabled) {
  await page.click('#start-run-btn');
  await page.waitForFunction(
    () => /etape încheiate/.test(document.querySelector('#runbook-status')?.textContent || ''),
    { timeout: 60000 },
  );
  const summary = (await page.textContent('#runbook-status')) || '';
  check('The run reports how many stages actually finished', /\d+\/\d+ etape încheiate/.test(summary), summary.trim().slice(0, 110));

  await page.waitForSelector('.runbook-run');
  const stageCount = await page.locator('.runbook-run').first().locator('.runbook-stage').count();
  check('Every stage of the runbook appears in the record', stageCount === 12, `${stageCount} stages`);

  const skipped = await page.evaluate(() =>
    [...document.querySelectorAll('.runbook-run .runbook-stage.rb-skipped')].map((el) =>
      (el.querySelector('.runbook-stage-reason')?.textContent || '').trim(),
    ),
  );
  check('Skipped stages are shown, not omitted', skipped.length > 0, `${skipped.length} skipped`);
  check('Every skipped stage carries a reason', skipped.every((r) => r.length > 0));

  const runStatus = await page.textContent('.runbook-run .topic-card-novelty');
  check(
    'A day with skipped stages is not reported as completed',
    skipped.length === 0 || runStatus.trim() !== 'COMPLETED',
    `status ${runStatus.trim()}`,
  );
}

if (disabled) {
  console.log(
    'SKIP  The run record — the preflight is BLOCKED, so no run started. See the header for how ' +
      'to cover this branch against a throwaway database.',
  );
}

// 7. Leaving safe mode without saying what was checked is refused by the server, not only the page.
const clearRefusal = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/runbook/safe-mode/clear', {
    method: 'POST',
    headers: { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ command_id: crypto.randomUUID(), notes: '  ' }),
  });
  return r.status;
}, token);
check(
  'Leaving safe mode without a note is refused by the server',
  clearRefusal === 422 || clearRefusal === 409,
  `HTTP ${clearRefusal}`,
);

// 8. The stored run keeps the preflight it ran under, so "the studio ran today" can be read in context.
const stored = await page.evaluate(async (t) => {
  const r = await fetch('/api/v1/runbook/runs', { headers: { Authorization: `Bearer ${t}` } });
  const runs = (await r.json()).runs;
  return runs.length ? { pf: runs[0].preflight_status, total: runs[0].stages_total } : null;
}, token);
check(
  'The run is stored with the preflight it ran under',
  !stored || (['READY', 'DEGRADED', 'BLOCKED'].includes(stored.pf) && stored.total === 12),
  stored ? `preflight ${stored.pf}, ${stored.total} stages` : 'no run recorded',
);

await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(400);
check('No horizontal overflow at 390px', !(await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)));

await page.screenshot({ path: path.join(OUT, 'runbook.png') });
check('No page errors', errors.length === 0, errors.join(' | ').slice(0, 160));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
