/**
 * PAID WORK UNDER WAY (paid_work.js, 2026-10-12): the register's head line and the editor's name
 * tag follow the GPU sessions, the submitted takes, the redo bought and the continuation ended,
 * as the backend's events record them; nothing is claimed past the events.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { CONTINUATION_RECENT_MS, SESSION_MAX_MS, gpuWaitWord, paidWork, paidWorkKey } from '../src/paid_work.js';
import { productionStatus } from '../src/ledger.js';

const NOW = Date.parse('2026-10-12T12:00:00.000+00:00');
const MIN = 60 * 1000;
const iso = (/** @type {number} */ ms) => new Date(ms).toISOString();
const KAEL = { agent_id: 'a-kael', name: 'Kael (Video Editor)', role: 'VideoEditor', role_ro: 'Video Editor' };
const TITLE = 'The Zero Script Club';

let sequence = 100;
/** One event as the backend serves it to the page (events_feed.py enrich). */
function event(type, at, fields = {}) {
  sequence += 1;
  return { event_id: `e-${sequence}`, sequence, timestamp: iso(at), event_type: type, payload: {}, ...fields };
}

function opened(at, payload = {}, fields = {}) {
  return event('runpod.gpu_session_opened', at, {
    aggregate_id: 'sess-1',
    payload: { endpoint_id: 'ep-1', purpose: 'image', step: 'stills', storyboard_id: 'b-1', workers_max: 1, ...payload },
    film_title: TITLE,
    actor: KAEL,
    words_ro: `Kael (Video Editor) a pornit GPU-ul RunPod pentru imagini din «${TITLE}» (imagini); modelul se încarcă (~10 min).`,
    bubble_ro: 'GPU pornit: aștept imaginile.',
    ...fields,
  });
}

/** newest first, as the register holds them (the backend's sequence follows its clock) */
const newestFirst = (/** @type {any[]} */ events) => [...events].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));

test('an open GPU session is work: the head line says the film and the step, the editor waits for the images', () => {
  const work = paidWork(newestFirst([opened(NOW - 12 * MIN)]), NOW);
  assert.equal(work.busy, true);
  assert.equal(work.sessions.length, 1);
  assert.equal(work.text, `Se filmează «${TITLE}»: imaginile scenelor (GPU pornit de 12 min)`);
  assert.equal(work.since, NOW - 12 * MIN);
  assert.equal(gpuWaitWord(work, 'a-kael'), 'așteaptă imaginile de la RunPod');
  assert.equal(gpuWaitWord(work, 'a-kael', 'UNKNOWN'), 'așteaptă imaginile de la RunPod');
  // a state of his own is said as itself; another employee is not waiting for anything
  assert.equal(gpuWaitWord(work, 'a-kael', 'WORKING'), null);
  assert.equal(gpuWaitWord(work, 'a-sarah'), null);
  // the record's «Storyboard:» label is not the film's title (goal.py says the film the same way)
  const labelled = paidWork([opened(NOW - 12 * MIN, {}, { film_title: `Storyboard: ${TITLE}` })], NOW);
  assert.equal(labelled.text, `Se filmează «${TITLE}»: imaginile scenelor (GPU pornit de 12 min)`);
});

test('the matching off closes the session, by the session id or by the endpoint', () => {
  const open = opened(NOW - 20 * MIN);
  const bySession = event('runpod.gpu_off_verified', NOW - 2 * MIN, { aggregate_id: 'sess-1', payload: { endpoint_id: 'ep-1', off: true, reason: 'STEP_DONE' } });
  let work = paidWork(newestFirst([open, bySession]), NOW);
  assert.equal(work.busy, false);
  assert.equal(work.text, null);
  assert.equal(gpuWaitWord(work, 'a-kael'), null);
  const forced = event('runpod.gpu_forced_off', NOW - MIN, { aggregate_id: 'ep-1', payload: { endpoint_id: 'ep-1', off: true, reason: 'SHUTDOWN' } });
  work = paidWork(newestFirst([open, forced]), NOW);
  assert.equal(work.busy, false);
  // the studio asked for the off; whether it billed on is the GPU switch's question
  const unverified = event('runpod.gpu_off_unverified', NOW - MIN, { aggregate_id: 'sess-1', payload: { endpoint_id: 'ep-1', off: false } });
  assert.equal(paidWork(newestFirst([open, unverified]), NOW).busy, false);
  // an off of another endpoint closes nothing here
  const other = event('runpod.gpu_off_verified', NOW - MIN, { aggregate_id: 'sess-9', payload: { endpoint_id: 'ep-9', off: true } });
  assert.equal(paidWork(newestFirst([open, other]), NOW).busy, true);
});

test("a scene's redo at RunPod names the scene when its purchase is recorded during the session", () => {
  const video = opened(NOW - 3 * MIN, { purpose: 'video', step: 'scene_redo' }, { aggregate_id: 'sess-2' });
  let work = paidWork(newestFirst([video]), NOW);
  assert.equal(work.text, `Se reface o scenă a filmului «${TITLE}»: clipul e la RunPod (de 3 min)`);
  assert.equal(gpuWaitWord(work, 'a-kael'), 'așteaptă clipul de la RunPod');
  const redo = event('runbook.qc_paid_redo', NOW - 2 * MIN, {
    aggregate_id: 'b-1',
    aggregate_type: 'storyboard',
    payload: { scene_index: 5, kinds: ['still'], open_motion: true, continues: null },
    film_title: TITLE,
    words_ro: `Refacerea plătită a scenei 5 din «${TITLE}»: imaginea cumpărată; mișcarea poate urma.`,
  });
  work = paidWork(newestFirst([video, redo]), NOW);
  assert.equal(work.text, `Se reface scena 5 a filmului «${TITLE}»: clipul e la RunPod (de 3 min)`);
  // the redo of another film says nothing of this session
  const elsewhere = { ...redo, aggregate_id: 'b-7', event_id: 'e-x', sequence: 9000 };
  assert.equal(paidWork(newestFirst([video, elsewhere]), NOW).text, `Se reface o scenă a filmului «${TITLE}»: clipul e la RunPod (de 3 min)`);
});

test('a take submitted and not yet answered is a wait, in the backend\'s words; its result ends it', () => {
  const sent = event('media.scene_take_recorded', NOW - 4 * MIN, {
    aggregate_id: 'take-1',
    payload: { storyboard_id: 'b-1', scene_number: 3, kind: 'still', status: 'SUBMITTED' },
    film_title: TITLE,
    actor: KAEL,
    words_ro: `Kael (Video Editor) a trimis la RunPod imaginea scenei 3 din «${TITLE}».`,
  });
  let work = paidWork(newestFirst([sent]), NOW);
  assert.equal(work.busy, true);
  assert.equal(work.text, `Kael (Video Editor) a trimis la RunPod imaginea scenei 3 din «${TITLE}»; se așteaptă rezultatul (de 4 min)`);
  const paid = event('media.scene_take_recorded', NOW - MIN, { aggregate_id: 'take-1', payload: { storyboard_id: 'b-1', scene_number: 3, kind: 'still', status: 'PAID' }, film_title: TITLE, actor: KAEL });
  work = paidWork(newestFirst([sent, paid]), NOW);
  assert.equal(work.busy, false);
  assert.equal(work.submitted.length, 0);
  // without the backend's sentence the page says what it knows: the kind, the scene, the film
  const bare = { ...sent, words_ro: undefined };
  assert.equal(paidWork([bare], NOW).text, `Se așteaptă imaginea scenei 3 a filmului «${TITLE}» de la furnizor (de 4 min)`);
});

test('a continuation that just ended keeps the studio from resting for a few minutes, in its own words', () => {
  const ended = event('runbook.film_continued', NOW - 2 * MIN, {
    aggregate_id: 'b-1',
    aggregate_type: 'storyboard',
    payload: { status: 'COMPLETED', reason: 'Pasul zilei a fost cumpărat.' },
    film_title: TITLE,
    words_ro: `Filmul «${TITLE}» a mers până la capăt: Pasul zilei a fost cumpărat.`,
  });
  let work = paidWork([ended], NOW);
  assert.equal(work.busy, true);
  assert.equal(work.text, `Filmul «${TITLE}» a mers până la capăt: Pasul zilei a fost cumpărat.`);
  work = paidWork([ended], NOW + CONTINUATION_RECENT_MS + MIN);
  assert.equal(work.busy, false, 'past the few minutes the studio may rest');
  // a continuation that ended after a session opened for the same film ends that session's work
  const open = opened(NOW - 30 * MIN);
  assert.equal(paidWork(newestFirst([open, ended]), NOW + CONTINUATION_RECENT_MS + MIN).busy, false);
  // without words the walk is said from its status
  const bare = { ...ended, words_ro: undefined };
  assert.equal(paidWork([bare], NOW).text, `Filmul «${TITLE}» a mers până la capăt`);
});

test('a session the register kept past its cap, with no off, is not claimed as work', () => {
  const old = opened(NOW - SESSION_MAX_MS - MIN);
  assert.equal(paidWork([old], NOW).busy, false);
  // without a clock the words carry no minutes and no cap is applied
  const work = paidWork([opened(NOW - 50 * MIN)]);
  assert.equal(work.text, `Se filmează «${TITLE}»: imaginile scenelor (GPU pornit)`);
});

test("without the film's title the session's own sentence from the backend leads", () => {
  const untitled = opened(NOW - 5 * MIN, { storyboard_id: null }, { film_title: undefined });
  const work = paidWork([untitled], NOW);
  assert.equal(work.text, `Kael (Video Editor) a pornit GPU-ul RunPod pentru imagini din «${TITLE}» (imagini); modelul se încarcă (~10 min) (GPU pornit de 5 min)`);
  const wordless = { ...untitled, words_ro: undefined };
  assert.equal(paidWork([wordless], NOW).text, 'Se filmează «…»: imaginile scenelor (GPU pornit de 5 min)');
});

test('the key changes when the work does, so the name tags redraw only then', () => {
  const rest = paidWork([], NOW);
  const busy = paidWork([opened(NOW - MIN)], NOW);
  assert.notEqual(paidWorkKey(rest), paidWorkKey(busy));
  assert.equal(paidWorkKey(busy), paidWorkKey(paidWork([opened(NOW - MIN)], NOW)));
});

test('the register\'s head line leads with the paid work and keeps a running stage after it', () => {
  const open = opened(NOW - 8 * MIN);
  const finished = event('runbook.daily_run_finished', NOW - 3 * 60 * MIN, { payload: { status: 'COMPLETED', stages_productive: 3 } });
  let status = productionStatus(newestFirst([open, finished]), NOW, null);
  assert.equal(status.busy, true);
  assert.equal(status.live, false, 'no stage of the day is running');
  assert.equal(status.text, `Se filmează «${TITLE}»: imaginile scenelor (GPU pornit de 8 min)`);
  const stage = event('runbook.stage_started', NOW - 9 * MIN, { payload: { stage: 'media', index: 7, total: 12 } });
  status = productionStatus(newestFirst([open, stage]), NOW, null);
  assert.equal(status.text, `Se filmează «${TITLE}»: imaginile scenelor (GPU pornit de 8 min) · Acum: producție media`);
  assert.equal(status.live, true);
  // the off: the line is the day's again
  const off = event('runpod.gpu_off_verified', NOW - MIN, { aggregate_id: 'sess-1', payload: { endpoint_id: 'ep-1', off: true } });
  status = productionStatus(newestFirst([open, finished, off]), NOW, null);
  assert.equal(status.busy, false);
  assert.equal(status.text, 'Ultima rulare a zilei încheiată · 3 etape au produs ceva');
});
