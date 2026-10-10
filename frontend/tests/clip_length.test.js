// CLIP_LENGTH — «Pregătit» only when the render will accept the film (2026-10-09, film babcf272).
//
// The sheet bought every clip at its planned seconds before a word was voiced; scene 3's words
// then measured 6,06 s against its 5,0 s clip, the render refused the assembly four times, and the
// drawer said «Pregătit» each time. The backend now sends the render's own reading
// (`assembly_readiness`): a clip too short for its words is CLIP_SHORT with its seconds, a clip a
// little short is slowed down locally (a note, 0 USD), and the newest refused assembly is kept on
// the step. The drawer never offers an assembly the render refuses, and says why.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import { assembleButton, assembleWaitLine, sheetHtml } from '../src/shooting_sheet.js';
import { escapeHtml } from '../src/html.js';

const SHEET = JSON.parse(fs.readFileSync(new URL('./fixtures/shooting_sheet.json', import.meta.url), 'utf8'));
const e = escapeHtml;

/** The sheet once every paid step is bought: only the assembly is left. @returns {any} */
function afterMotion() {
  const s = structuredClone(SHEET);
  for (const name of ['stills', 'test_shot', 'motion']) s.steps[name].to_buy = [];
  s.steps.assemble.paid_steps_left = [];
  s.steps.assemble.ready = true;
  s.steps.assemble.blocked = [];
  s.steps.assemble.blocked_ro = '';
  s.steps.assemble.waiting_ro = '';
  return s;
}

const SHORT_RO = 'Scena 3: clipul are 5,0 s, iar cadrul lui cere 6,42 s: ar trebui '
  + 'încetinit cu 29%, peste cele 25% în care studioul îl încetinește local. Mișcarea scenei se reface '
  + 'la cel puțin 6,42 s. Sau alege „imagine fixă animată local” pentru ea pe foaia de filmare.';

/** babcf272 after its narration was bought: scene 3 refused, CLIP_SHORT. */
function sceneThreeRefused() {
  const s = afterMotion();
  s.steps.assemble.ready = false;
  s.steps.assemble.blocked = [{ scene_index: 3, code: 'CLIP_SHORT', why_ro: '', reason_ro: SHORT_RO, clip_seconds: 5, span: 6.417, needed_seconds: 5.133 }];
  s.steps.assemble.blocked_ro = SHORT_RO;
  s.steps.assemble.last_refusal = { at: '2026-10-09T18:22:41+00:00', stage: 'render', reason_ro: 'Scena 3: clipul are 5,0 s, iar cadrul lui cere 6,42 s.', scenes: [{ scene_index: 3, code: 'CLIP_SHORT' }] };
  return s;
}

test('a scene whose clip is too short for its words keeps the assembly from «Pregătit», and says why', () => {
  const s = sceneThreeRefused();
  const a = assembleButton(s);
  assert.equal(a.disabled, true);
  assert.deepEqual(a.reasons, [SHORT_RO]);
  assert.match(a.refusal_ro, /^Ultima asamblare a fost refuzată: Scena 3: clipul are 5,0 s/);

  const html = sheetHtml(s, { escape: e });
  const box = html.slice(html.indexOf('sheet-assemble'));
  assert.ok(!box.slice(0, box.indexOf('</h3>') + 200).includes('>Pregătit<'), 'the refused assembly is never «Pregătit»');
  assert.match(box, /data-step="assemble"[^>]*disabled/);
  assert.ok(box.includes('Clipul scenei 3 este prea scurt pentru narațiunea ei; mișcarea ei se reface la lungimea potrivită.'));
  assert.ok(box.includes('data-assemble-refusal'));
});

test('a clip a little short is slowed at 0 USD: the assembly is ready and the note says so', () => {
  const s = afterMotion();
  const note = 'Scena 1: clipul de 5,0 s se încetinește local la 5,92 s (+19%), 0 USD.';
  s.steps.assemble.notes_ro = [note];
  s.steps.assemble.last_refusal = { reason_ro: 'an older refusal, superseded', scenes: [] };
  const a = assembleButton(s);
  assert.equal(a.disabled, false);
  assert.deepEqual(a.notes, [note]);
  assert.equal(a.refusal_ro, '', 'a refusal is said only while the film still waits');
  const html = sheetHtml(s, { escape: e });
  assert.ok(html.includes(e(note)));
  assert.ok(!html.includes('data-assemble-refusal'));
  assert.ok(!/data-step="assemble"[^>]*disabled/.test(html));
});

test('the wait line keeps clips too short apart from scenes with no accepted clip', () => {
  assert.equal(
    assembleWaitLine([{ scene_index: 3, code: 'CLIP_SHORT' }, { scene_index: 5, code: 'CLIP_SHORT' }, { scene_index: 2, code: 'NO_SHOT' }]),
    'Clipurile scenelor 3, 5 sunt prea scurte pentru narațiunea lor; mișcarea lor se reface la lungimea potrivită. Așteaptă clipurile scenelor 2.',
  );
  assert.equal(assembleWaitLine([{ scene_index: 4, code: 'NO_STILL' }]), 'Așteaptă clipurile scenelor 4.');
  assert.equal(assembleWaitLine([]), '');
});

test('an older studio without the new fields still reads as before', () => {
  const s = afterMotion();
  delete s.steps.assemble.notes_ro;
  delete s.steps.assemble.last_refusal;
  const a = assembleButton(s);
  assert.equal(a.disabled, false);
  assert.deepEqual(a.notes, []);
  assert.equal(a.refusal_ro, '');
});
