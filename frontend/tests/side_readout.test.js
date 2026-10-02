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
  assert.deepEqual(rows.map((r) => [r.label, r.value]), [['Rularea zilei', '—'], ['Trezorerie', '—'], ['Următoarea rulare', '—'], ['Filmul zilei', '—']]);
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
  assert.equal(studioReadout({ track: { empty: true, text: 'Nicio rulare a zilei în registru' }, reads: { runs: 'ok' } }).rows[0].value, 'nicio rulare în registru');
  // not read is not empty (W12)
  assert.equal(studioReadout({ track: { empty: true } }).rows[0].value, '—');
  assert.equal(studioReadout({ track: { empty: true }, reads: { runs: 'failed' } }).rows[0].value, 'registrul nu a putut fi citit');
  assert.equal(studioReadout({ reads: { figures: 'failed' } }).rows[1].note, 'trezoreria nu a putut fi citită');
});

test('the key changes only when a line does', () => {
  const a = studioReadout({ jobs: [DAILY], stopped: false, timeZone: 'Europe/Bucharest' }).key;
  assert.equal(a, studioReadout({ jobs: [DAILY], stopped: false, timeZone: 'Europe/Bucharest' }).key);
  assert.notEqual(a, studioReadout({ jobs: [DAILY], stopped: true }).key);
});

// PAGE_OWNER_DAY (PAGE-14): «Filmul zilei», from the newest run's own stages.
const FILM = '3ec1740c-0000-4000-8000-000000000001';
/** @param {Record<string, any>} artefacts by stage */
const runOf = (artefacts) => ({ business_date: '2026-10-02', stages: Object.entries(artefacts).map(([stage, a]) => ({ stage, status: 'COMPLETED', artefacts: a })) });

test('the film of the day waiting at a step says where, what it cost so far and opens its sheet', async () => {
  const { filmOfTheDay } = await import('../src/side_readout.js');
  const row = filmOfTheDay(runOf({ media: { awaiting_owner: [{ storyboard_id: FILM, step: 'stills', approval_id: 'a' }], films: [{ storyboard_id: FILM, status: 'ASKED', step: 'stills' }], bought_steps: [] } }));
  assert.equal(row.label, 'Filmul zilei');
  assert.equal(row.value, 'te așteaptă la imagini');
  assert.equal(row.tone, 'warn');
  assert.equal(row.sheet, FILM);
  const motion = filmOfTheDay(runOf({ media: { awaiting_owner: [{ storyboard_id: FILM, step: 'motion' }], bought_steps: [{ storyboard_id: FILM, step: 'stills', credits: 18 }, { storyboard_id: FILM, step: 'test_shot', credits: 340 }] } }));
  assert.equal(motion.value, 'te așteaptă la mișcare');
  assert.equal(motion.note, 'cumpărat până acum: 358 de credite');
});

test('in production, assembled with QC passed, QC failed and published private', async () => {
  const { filmOfTheDay } = await import('../src/side_readout.js');
  const making = filmOfTheDay(runOf({ media: { bought_steps: [{ storyboard_id: FILM, step: 'stills', credits: 18 }], films: [{ storyboard_id: FILM, status: 'READY' }] } }));
  assert.equal(making.value, 'în producție');
  assert.equal(making.note, 'cumpărat până acum: 18 credite');
  assert.equal(making.sheet, FILM);
  const passed = filmOfTheDay(runOf({ media: { assets: ['asset-1'], films: [{ storyboard_id: FILM, status: 'ASSEMBLED' }] }, edit_and_qc: { passed: 1, failed: 0 } }));
  assert.equal(passed.value, 'asamblat, QC trecut');
  assert.equal(passed.tone, 'ok');
  const failed = filmOfTheDay(runOf({ media: { assets: ['asset-1'] }, edit_and_qc: { passed: 0, failed: 1 } }));
  assert.equal(failed.value, 'QC picat');
  assert.equal(failed.tone, 'alert');
  const published = filmOfTheDay(runOf({ media: { assets: ['asset-1'] }, edit_and_qc: { passed: 1, failed: 0 }, publish: { published: [{ channel_name: 'Canalul faptelor', release_privacy: 'private', publication_status: 'PUBLISHED' }] } }));
  assert.equal(published.value, 'publicat privat');
  assert.equal(published.note, 'Canalul faptelor');
  assert.equal(published.tone, 'ok');
});

test('a day with no film says so, and nothing read is a dash', async () => {
  const { filmOfTheDay } = await import('../src/side_readout.js');
  assert.equal(filmOfTheDay(runOf({ selection: {} })).value, 'niciun film azi');
  assert.equal(filmOfTheDay(null).value, '—');
  assert.equal(filmOfTheDay(runOf({ media: { films: [{ storyboard_id: FILM, status: 'HELD' }] } })).value, 'oprit înainte de un pas plătit');
});

test('the readout carries the film of the day as its fourth line', () => {
  const { rows } = studioReadout({ run: runOf({ media: { awaiting_owner: [{ storyboard_id: FILM, step: 'test_shot' }] } }) });
  assert.deepEqual(rows.map((r) => r.label), ['Rularea zilei', 'Trezorerie', 'Următoarea rulare', 'Filmul zilei']);
  assert.equal(rows[3].value, 'te așteaptă la cadrul de probă');
});
