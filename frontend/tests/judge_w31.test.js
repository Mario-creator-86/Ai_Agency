/**
 * W31, the release judge's small fixes, each measured on the page before it.
 *
 * The daily run's preflight printed «36 de site-uri autorizate, … disponibile. · 36 de site-uri
 * autorizate, … disponibile. Nu pot fi citite: …»: the check's detail repeats its message and
 * then adds to it, and the page printed both. The schedule said «Următoarea rulare: 18.09.2026,
 * 05:00:00» on 25.09 beside «Programarea este oprită»: a stopped job's stored next time is a
 * promise that cannot happen. Its title was the job's code, «daily_main».
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { checkLine, scheduleNextRun, SCHEDULE_TITLE } from '../src/readiness.js';

test('a detail that repeats the message is said once, and what it adds is kept', () => {
  const message = '36 de site-uri autorizate, 20 testate cu succes.';
  assert.equal(
    checkLine({ message, detail: `${message} Nu pot fi citite: www.loc.gov — a refuzat studioul (403).` }),
    `${message} · Nu pot fi citite: www.loc.gov — a refuzat studioul (403).`,
  );
  assert.equal(checkLine({ message, detail: message }), message);
  assert.equal(checkLine({ message, detail: `  ${message}  ` }), message);
});

test('a different detail is kept whole, and the sentences are never reworded', () => {
  assert.equal(checkLine({ message: 'FFmpeg disponibil.', detail: 'C:\\ffmpeg.exe' }), 'FFmpeg disponibil. · C:\\ffmpeg.exe');
  assert.equal(checkLine({ message: 'Autonomia este pornită.', detail: '' }), 'Autonomia este pornită.');
  assert.equal(checkLine({ message: '', detail: 'Doar detaliul.' }), 'Doar detaliul.');
  assert.equal(checkLine({}), '');
  // a detail that only begins like the message, mid-word, is not the message repeated
  assert.equal(checkLine({ message: '8 activi', detail: '8 activii' }), '8 activi · 8 activii');
});

test('a stopped schedule promises no next run; a running one says its time', () => {
  const at = '2026-09-18T02:00:00+00:00';
  assert.equal(scheduleNextRun({ is_active: false, next_run_at: at }), null);
  assert.equal(scheduleNextRun({ is_active: true, next_run_at: at }), at);
  assert.equal(scheduleNextRun({ is_active: true, next_run_at: null }), null);
});

test('the schedule is named in words, its code kept for the title', () => {
  assert.equal(SCHEDULE_TITLE, 'Ziua programată');
});

// The register's two publishing rows, reported by the W30 gates wave and measured on the page:
// a refused gate printed the English label «gate failed» and raw keys («channel_id: … · status:
// BLOCKED_GATE»), its Romanian reasons never shown; a failed upload printed nothing, because it
// read a field the event does not carry.
import { describeEvent } from '../src/ledger.js';
import fs from 'node:fs';

test('a refused gate says so, with the gate\'s own reasons', () => {
  const item = describeEvent({
    event_type: 'publishing.gate_failed',
    payload: {
      channel_id: 'c', media_asset_id: 'm', status: 'BLOCKED_GATE',
      gate_reasons: ['Publicare dublă oprită: materialul este deja pe acest canal', 'Controlul calității: lipsește'],
      gate_reason_codes: ['DUPLICATE_ASSET', 'QC_NOT_PASSED'],
    },
  });
  assert.equal(item.label, 'poarta de publicare a refuzat');
  assert.equal(item.text, 'Publicare dublă oprită: materialul este deja pe acest canal; Controlul calității: lipsește');
  assert.doesNotMatch(item.text, /BLOCKED_GATE|channel_id/);
});

test('a failed upload shows the detail the event carries', () => {
  const item = describeEvent({ event_type: 'publishing.failed', payload: { error_detail: 'Cota zilnică YouTube este epuizată.' } });
  assert.equal(item.label, 'publicare eșuată');
  assert.equal(item.text, 'Cota zilnică YouTube este epuizată.');
});

test('a site that answered with nothing usable is said with its negation, as the backend says it', () => {
  const main = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  assert.match(main, /OTHER: 'nu a răspuns cu nimic utilizabil'/);
});
