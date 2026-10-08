import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { footerRows, stepButtons } from '../src/shooting_sheet.js';

const fixture = JSON.parse(fs.readFileSync(new URL('./fixtures/shooting_sheet.json', import.meta.url), 'utf8'));

test('RunPod pricing uses the Agency cap without requiring a fictional Runway balance', () => {
  const sheet = structuredClone(fixture);
  sheet.footer.balance = { applicable: false, billing_mode: 'gpu', credits: null };
  Object.assign(sheet.steps.stills, { to_buy: [1], cost_credits: 18, cost_usd: 0.18,
    cap_credits: 54, cap_usd: 0.54 });
  const stills = stepButtons(sheet).find(b => b.step === 'stills');
  assert.ok(stills);
  assert.ok(!stills.reasons.some(reason => reason.includes('Soldul Runway')));
  assert.match(stills.cap_ro, /54/);
  const balance = footerRows(sheet).find(r => r.key === 'balance');
  assert.equal(balance.label, 'RunPod GPU Cloud');
  assert.ok(!balance.value.includes('zero'));
});

test('RunPod costs show rejected attempts and keep unknown costs unknown', () => {
  const sheet = structuredClone(fixture);
  sheet.footer.runpod_metrics = { jobs: 3, provider: 'RUNPOD', estimated_gpu_cost_usd: '6.27',
    jobs_with_unknown_cost: 1, cost_per_accepted_scene_usd: null, cost_per_finished_short_usd: null,
    gpu_minutes_per_short: null, regenerations: 2,
    acceptance_by_model: { 'LTX-2.5': { accepted: 1, reviewed: 3 } } };
  const rows = footerRows(sheet);
  assert.match(rows.find(r => r.key === 'runpod_cost').value, /include încercările respinse/);
  assert.match(rows.find(r => r.key === 'runpod_cost').value, /cost necunoscut/);
  assert.equal(rows.find(r => r.key === 'runpod_scene').value, 'necunoscut');
  assert.equal(rows.find(r => r.key === 'runpod_minutes').value, 'necunoscute');
  assert.equal(rows.find(r => r.key === 'runpod_acceptance').value, 'LTX-2.5: 1/3');
  delete sheet.footer.runpod_metrics;
  assert.ok(!footerRows(sheet).some(r => r.key.startsWith('runpod_')));
});

test('A RunPod round names its GPU start inside the price; Runway steps say nothing of it', () => {
  const sheet = structuredClone(fixture);
  sheet.footer.balance = { applicable: false, billing_mode: 'gpu', credits: null };
  Object.assign(sheet.steps.stills, { to_buy: [1], cost_credits: 28, cost_usd: 0.28,
    cap_credits: 84, cap_usd: 0.84, gpu_start_credits: 14,
    gpu_start_ro: 'GPU: pornire și încărcarea modelelor: 14 credite pe rundă' });
  const stills = stepButtons(sheet).find(b => b.step === 'stills');
  assert.match(stills.price_ro, /GPU: pornire și încărcarea modelelor: 14 credite pe rundă/);
  const runway = structuredClone(fixture);
  for (const button of stepButtons(runway)) assert.doesNotMatch(button.price_ro, /pornire/);
});

test('A RunPod film never reads «Sold Runway»: no unknown-balance block on its steps or redos', async () => {
  const { sheetHtml } = await import('../src/shooting_sheet.js');
  const { escapeHtml } = await import('../src/html.js');
  const sheet = structuredClone(fixture);
  sheet.footer.balance = { applicable: false, billing_mode: 'gpu', credits: null };
  Object.assign(sheet.steps.stills, { to_buy: [1], cost_credits: 28, cost_usd: 0.28,
    cap_credits: 84, cap_usd: 0.84 });
  // A held hero with a paid redo, as in sheet_layout.test.js.
  sheet.steps.test_shot.to_buy = [];
  sheet.steps.test_shot.held = [1];
  sheet.scenes[0].motion.step_status = 'NEEDS_OWNER';
  const html = sheetHtml(sheet, { escape: escapeHtml });
  assert.doesNotMatch(html, /Sold(ul)? Runway/);
  assert.doesNotMatch(html, /data-sheet-action="redo"[^>]*data-kind="motion"[^>]*disabled/);
  assert.match(html, /RunPod GPU/);
});
