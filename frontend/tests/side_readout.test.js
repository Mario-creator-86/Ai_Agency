// THE STUDIO AT A GLANCE: the side drawer's foot says only what its sources say.
import test from 'node:test';
import assert from 'node:assert/strict';
import { nextRunWords, studioReadout } from '../src/side_readout.js';

const DAILY = { workflow_type: 'DAILY_RUN', is_active: true, next_run_at: '2026-09-25T02:00:00+00:00' };

test('the next run is a time only while the job is active and autonomy is on', () => {
  const on = nextRunWords([DAILY], { stopped: false, timeZone: 'Europe/Bucharest' });
  assert.equal(on.tone, 'ok');
  assert.match(on.value, /25\.09/);
  assert.match(on.value, /05:00/);
  assert.deepEqual(nextRunWords([{ ...DAILY, is_active: false }], { stopped: false }), { value: 'programarea zilnică este oprită', tone: 'warn' });
  assert.deepEqual(nextRunWords([DAILY], { stopped: true }), { value: 'autonomia este oprită', tone: 'warn' });
  assert.deepEqual(nextRunWords([{ workflow_type: 'WEEKLY_REVIEW', is_active: true }]), { value: 'nicio treabă zilnică programată', tone: 'quiet' });
  assert.deepEqual(nextRunWords(null), { value: '—', tone: 'quiet' });
  assert.deepEqual(nextRunWords([{ ...DAILY, next_run_at: null }]), { value: '—', tone: 'quiet' });
});

test('with nothing read, every line is a dash', () => {
  const { rows } = studioReadout({});
  assert.deepEqual(rows.map((r) => [r.label, r.value]), [['Rularea zilei', '—'], ['Trezorerie', '—'], ['Următoarea rulare', '—']]);
});

test('the treasury line is the wall screen\'s own figures, cut to cents', () => {
  const treasury = { spendable: { amount: '50000.009' }, in_deficit: false };
  const budget = { budgets: [{ period: 'DAILY', active: true, spent_usd: '0.5', limit_usd: '15', ratio: 0.03, state: 'OK' }] };
  const row = studioReadout({ treasury, budget }).rows[1];
  assert.equal(row.value, '50.000 VR$ cheltuibili');
  assert.equal(row.note, 'azi 0,5 / 15 USD');
  assert.equal(row.tone, 'quiet');
  assert.equal(studioReadout({ treasury: { ...treasury, in_deficit: true }, budget }).rows[1].tone, 'alert');
});

test('the day\'s run is the slate\'s own words, and says a run is under way only while it is', () => {
  const track = { empty: false, date: '2026-09-12', closed: 12, total: 12, finished: true, status: 'COMPLETED', running: null, segments: [] };
  const row = studioReadout({ track, today: '2026-09-24' }).rows[0];
  assert.equal(row.note, 'Rularea din 12.09');
  assert.match(row.value, /^12\/12 · /);
  assert.equal(row.tone, 'quiet');
  assert.equal(studioReadout({ track: { empty: true, text: 'Nicio rulare a zilei în registru' } }).rows[0].value, 'nicio rulare în registru');
});

test('the key changes only when a line does', () => {
  const a = studioReadout({ jobs: [DAILY], stopped: false, timeZone: 'Europe/Bucharest' }).key;
  assert.equal(a, studioReadout({ jobs: [DAILY], stopped: false, timeZone: 'Europe/Bucharest' }).key);
  assert.notEqual(a, studioReadout({ jobs: [DAILY], stopped: true }).key);
});
